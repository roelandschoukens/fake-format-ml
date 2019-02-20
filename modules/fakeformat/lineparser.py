from . import regexshim as _re
from .elements import *

""" backslash escape sequences for quoted strings """
_map_quoted_backsl = {
    'a': '\a',
    'b': '\b',
    'f': '\f',
    'n': '\n',
    'r': '\r',
    't': '\t',
    'v': '\v',
}
    

def _flank_test(left, right):   
    """ left flanking test. For right, invert the order of arguments.
    
    returns if we are left-flanking and if we are _followed by_ punctuation """
    
    # we will follow CommonMark specification for flank tests:
    # A left-flanking delimiter run is a delimiter run that is
    # (a): not followed by Unicode whitespace, and 
    if PAT_WHITESPACE.match(right): return False, False
    
    # (b):
    #  - either not followed by a punctuation character,
    #  - or preceded by Unicode whitespace
    #  - or [preceded by] a punctuation character.
    r_punct = bool(PAT_CMM_PUNCT.match(right))
    if not r_punct: return True, False
    if PAT_WHITESPACE.match(left): return True, r_punct
    if PAT_CMM_PUNCT.match(left): return True, r_punct
    return False, False

class _Line_match:
    def __init__(self, match_re, match_function):
        """ a line match item.
        
        - match_re: regular expression which indicates where a possible match will occur.
        - match_function: function with arguments (parser, content, pos, group_index, match).
            - parser: line parser
            - content: content being parsed (read only)
            - pos: current position (equivalent to match.start())
            - match: match object coming from the Big Combined Regular Expression. In this
              expression our own expression is enclosed in a capture group, so
              match.group(group_index + i) will contain the matched text for our own subgroup i.
              
            - return: None if the position doesn't match, or the new
                      position if there is a match.
        """
        self.re = match_re
        """ amount of capturing groups in our regular expression """
        self.group_count = _re.compile(self.re).groups
        """ match function """
        self.match_function = match_function

""" enum value for token types.

_ELEMENT
_ROOT : root element, similar to _ELEMENT
_TEXT: text
_WHITESPACE: whitespace token, generated when it preceeds 
"""
_TEXT, _ELEMENT, _WHITESPACE, _ROOT = sentinels("Text", "Element", "Whitespace", "root")


class LineToken:
    def __init__(self, type, what):
        """ type, see above """
        self.type = type
        """ Hints at which kind of construct will close this frame. Must be valid, but can be empty.
        
        normally a string containing the expected closing sequence, eg. '_', '``' or ']' """
        self.close_hint = ''
        """ string or FFElement """
        self.what = what
        """ Child content for elements """
        self.content = [] if type in (_ELEMENT, _ROOT) else None

    def el(self):
        """ Return our element. Return None if self is not an Element. """
        return self.what if self.type == _ELEMENT else None

    def text(self):
        """ Return our text. Return None if self is an Element. """
        return self.what if self.type != _ELEMENT else None

    def eat_whitespace(self):
        """ Trim a trailing whitespace element. """
        assert self.content is not None
        if self.content and self.content[-1].type == _WHITESPACE:
            self.content.pop()

    def trailing_ignore_whitespace(self):
        """ If the last piece of content is an Element, return it

        Return None otherwise. Ignores one trailing whitespace element. """
        assert self.type in (_ELEMENT, _ROOT)
        if not self.content:
            return None
        if self.content[-1].type != _WHITESPACE:
            return self.content[-1]
        if len(self.content) > 1:
            return self.content[-2]
        return None

    def dump(self):
        if self.type == _ROOT:
            return ' '.join(c.dump() for c in self.content)
        elif self.type == _ELEMENT:
            return '{'+str(self.el().tag)+'}[ ' + ' '.join(c.dump() for c in self.content) + ' ]'
        else:
            return '«'+self.text()+'»'
        
_PAT_M_QUOTE = _re.compile(r'\'|"|\\.|\n')
""" Unicode tag: {U+1234} in text represents an Unicode character. """
_PAT_UCHAR_TAG = _re.compile(r'[uU]+[a-fA-F0-9]{2,6}\}')
""" Unicode char after backslash: x12, u1234, U123456 """
_PAT_UCHAR_QUOTE = _re.compile(r'U[a-fA-F0-9]{6}|u[a-fA-F0-9]{4}|[xX][a-fA-F0-9]{2}')
""" note (*1) """
_PAT_NOTE = _re.compile(r'\(\*[0-9]*\)')
""" Pandoc style note: [^foo]. """
_PAT_PANDOC_NOTE = _re.compile(r'\[\^\P{Zs}+\]')

class Lineparser:
    def __init__(self, sink, error_sink):
        """ Sink object to write content and tags """
        self.sink = sink
        """ Sink object to write errors and warnings """
        self.error_sink = error_sink
        """ List of patterns to match """
        self.match_list = [
            _Line_match(r'\\.', Lineparser.do_escape),
            _Line_match(r'\s*\\\n', Lineparser.do_newline),
            _Line_match(r'_+|\*+', Lineparser.do_italic_bold),
            _Line_match(r'~~', Lineparser.do_strike),
            _Line_match(r'`+', Lineparser.do_codespan),
            _Line_match(r'\.\.\.(?!\.)', Lineparser.do_ellip),
            _Line_match(r'\-\-\-?(?!\-)', Lineparser.do_dashes),
            _Line_match(r'<\S', Lineparser.do_url),
            _Line_match(r'\{', Lineparser.do_tag_or_U),
            _Line_match(r'\(\*|\[\^', Lineparser.do_note),
            _Line_match(r'\[', Lineparser.do_span),
            _Line_match(r'\]', Lineparser.do_span_end),
        ]
        """ maps a group index to one of our _Line_match items (actually a list) """
        self.match_map = None
        
        """ Stack of open elements, this one starts out with one root.
        
        All items MUST be Elements. """
        self.stack = None
        """ Big regular expression to match, this allows us to test for all our patterns at once. """
        self.token_pat = None
        """ 'draft' element, present if we had tag constructs but not matching element yet """
        self.draft_el_token = None
        
    # start
    def start(self):
        """ Start the parser. Must happen exactly once
        
        This gives you a chance to modify settings after constructing this parser. """
        # build the Big Regex to match all tokens at once
        self.token_pat = _re.compile('(' + ')|('.join(lm.re for lm in self.match_list) + ')')
            
        # build index to _Line_match map
        self.match_map = []
        for lm in self.match_list:
            self.match_map.append(lm)
            # leave empty slots for subgroups contained within lm.re
            self.match_map += [None] * lm.group_count         

    def top(self):
        """ top of the stack """
        return self.stack[-1]
    
    
    def _reset(self):
        self.stack = [LineToken(_ROOT, None)]
        self.draft_el_token = None

            
    def probe_block_tag(self, line):
        """ check if the given line is a block tag
        
        trailing whitespace must be stripped before calling.
        
        Returns (FFElement, indent) if a block tag is found, else (None, 0)
        """
        self._reset()
        indent = PAT_WHITESPACE_0.match(line, 0).group()
        ilen = len(indent)
        if not (line[ilen] == '{' and line[-1] == '}'):
            return None, ''
        
        if line[ilen+1:ilen+3].upper() == 'U+':
            # that is probably an Unicode char
            return None, ''
        
        pos, el = self._consume_tag(line, ilen, tag_class=FFBlock)
        if pos == len(line):
            return el, indent
        return None, ''
        
            
    def parse(self, content):

        self._reset()
    
        pos = 0
        
        while True:
        
            whitespace = PAT_WHITESPACE_0.match(content, pos).group()
            pos += len(whitespace)
                
            m = self.token_pat.search(content, pos)
            if m:
                # add intermediate text
                new_pos = m.start()
                txt = content[pos:new_pos]
                if txt:
                    self._append_text(whitespace)
                    self._append_text(txt)
                else:
                    # found only whitespace (or nothing). Mark it as whitespace
                    self.top().content.append(LineToken(_WHITESPACE, whitespace))
                    
                pos = new_pos
                
                # Figure out which token we recognised
                group_index, match_str = next((i, x) for i, x in enumerate(m.groups()) if x is not None)
                lm = self.match_map[group_index]
                
                # lm.match_function counts must be 'unbound'
                new_pos = lm.match_function(self, content, pos, group_index, m)
                if new_pos:
                    pos = new_pos
                else:
                    self._append_text(content[pos:pos+1])
                    pos += 1
            else:
                # add final text
                self._append_text(whitespace)
                self._append_text(content[pos:])
                break
              
        while len(self.stack) > 1:
            self._close_tag()
        
        self._emit_all(self.stack[0].content)
        
        
    # bookkeeping
    
    def _set_draft_tag(self, el):
        """ Set draft element. If one is already there it will remain empty
        
        if el has a tag which indicates it should be empty it will be immediately flushed.
        
        This element is added to the current top element, and may be assigned content later
        by any kind of inline span. """
        self._flush_draft_el()
        if not el.is_void():
            tk = LineToken(_ELEMENT, el)
            self.top().content.append(tk)
            if not tk.el().is_empty_tag():
                self.draft_el_token = tk
        

    def _flush_draft_el(self):
        """ Called when we know the current draft element will not get further content. """
        self.draft_el_token = None
        
        
    def _no_break_space(self):
        """ Turns any trailing whitespace, if present, into no break space

        You may have to strip _WHITESPACE first if it came after a tag construct. """
        c = self.top().content
        if not c: return
        
        c = c[-1]
        if c.type is _TEXT or c.type is _WHITESPACE:
            if PAT_WHITESPACE.match(c.text()[-1:]):
                c.what = c.what.rstrip() + '\u00A0'
        
    def _append_text(self, text):
        """ Append content to the topmost open element.
        
        type may be set to _WHITESPACE for spaces. Create any draft tag first """
        self._flush_draft_el()
        self.top().content.append(LineToken(_TEXT, text))
        
        
    def _append_el(self, element):
        """ Append an element, taking into account the draft element
        
        This strips intervening whitespace, merges the elements and assigns
        to the existing token generated for the draft element. The tag of the
        draft element will override the tag name of the given element
        
        returns the LineToken instance """
        
        if self.draft_el_token:
            # merge into existing element
            self.top().eat_whitespace()
            tk = self.draft_el_token
            element.merge(tk.what)
            tk.what = element
            self.draft_el_token = None
        else:
            # no draft element, create now
            tk = LineToken(_ELEMENT, element)
            self.top().content.append(tk)            
        return tk
        
        
    def _begin_tag(self, element, close_hint=None):
        """ Append an element, taking into account the draft element. Push that element on the stack
        
        Returns the added element """
        tk = self._append_el(element)
        tk.close_hint=close_hint
        self.stack.append(tk)
        return element
    
    def _close_tag(self):
        """ ends the current tag. Create any draft tag first """
        self._flush_draft_el()
        
        top_el = self.top().el()
        
        # split composite tag
        if top_el.tag and '+' in top_el.tag:
            parts = self.top().el().tag.split('+')
            self._wrap_tag(FFElement(parts[1]), parts[0])
            
        self.stack.pop()
        assert self.stack, "popped off root element"
        
    
    def _wrap_tag(self, el, top_tag):
        """ Wrap the current content of the top tag in a new element

        el: new parent element for content
        top_tag: new tag name for current top element"""
        e = LineToken(_ELEMENT, el)
        e.content = self.top().content
        # hard-coded: we can only have em and strong here:
        self.top().el().tag = top_tag
        self.top().content = [e]
                    
    
    def _emit_all(self, content):
        """ end of paragraph, emit all content """
        for tk in content:
            if tk.type == _ELEMENT:
                empty = not tk.content
                self.sink.start_element(tk.el(), empty=empty)
                self._emit_all(tk.content)
                self.sink.end_element(tk.el(), empty=empty)
            else:
                self.sink.add_content(tk.text())

        
    # parsing tokens
    
    def _consume_quoted(self, content, pos, quote_char):
        """ consume quoted string. pos shall indicate the first character _after_ the quote """
        tk = ''
        while pos < len(content):
            m = _PAT_M_QUOTE.search(content, pos)
            if not m:
                self.error_sink.warn('quoted string not terminated')
                return pos + len(content), tk + content[pos:]
                
            new_pos = m.start()
            tk += content[pos:new_pos]
            pos = new_pos
            
            if m.group() == quote_char:
                return pos + 1, tk
            if m.group()[0] == '\\':
                ch = m.group[1]
                if ch in 'uUxX':
                    # unicode escape
                    mu = PAT_UCHAR_QUOTE.match(content, pos + 1)
                    if mu:
                        tk += chr(int(mu.group()[1:], 16))
                        pos += 1 + len(mu.group())
                    else:
                        self.error_sink.warn('Ill-formed unicode escape sequence ({})'.format(content[pos:pos+8]))
                        pos += 2
                elif ch == '\n':
                    self._append_el(FFElement('br'))
                else:
                    # single character escape
                    tk += _map_quoted_backsl.get(ch, ch)
                    pos += 2
            elif m.group()[0] == '\n':
                # eat newline and all whitespace after 
                pos += 1
                pos += match_length(content, pos, PAT_SPACE)
            else:
                # that other quote
                tk += m.group()
                pos += 1
            
    def _consume_val(self, content, pos):
        chr = content[pos:pos+1]
        if chr == '':
            return pos, ''
        if chr == '"':
            return self._consume_quoted(content, pos + 1, '"')
        if chr == "'":
            return self._consume_quoted(content, pos + 1, "'")
        if chr == "<":
            return self._consume_url(content, pos + 1)
        
        m = PAT_TOKEN.match(content, pos)
        if not m:
            # oops, got some other stuff: consume non space
            self.error_sink.warn('bad value after "=" ({}...), suggest using quotes'.format(content[pos:pos+10]))
            return pos + match_length(content, pos, _re.compile('[^\s}]+')), ''
        tk = m.group()
        pos += len(tk)
        return pos, tk
            
    def _consume_url(self, content, pos):
        """ consume URL. pos shall be the character _after_ the opening '<'

        The URL is expected to be percent encoded, specifically '%' and '>' MUST be encoded
        
        We may pass through:
         - spaces
         - unicode above U+00FF
        
        Note that you cannot express values containing a '>' with this construct. The value
        should not contain '<' either.
        
        special URLs are reported as being prepended with '<' (but without trailing '>').
        
        Whitespace after a line break is swallowed. """
        
        special_url = content[pos:pos+1] == '<'
        # capture second '<' at content[pos] in the url below
        
        pos_end = content.find('>', pos)
        if pos_end != -1:
            url = content[pos:pos_end] 
            pos_end += 1
            # double ending bracket for special url
            if special_url and content[pos_end:pos_end+1] == '>':
                pos_end += 1
        else:
            url = content[pos:]
            pos_end = len(content)
            self.error_sink.warn('URL not terminated')
        
        # remove newlines and any spaces after
        url = _re.sub('\n\s*', '', url)
        return pos_end, url
    
    def _consume_tag(self, content, pos, tag_class=FFElement):
        """ consume a tag. This already assumes it is not an Unicode char """
        pos += 1
        first = True
        
        el = tag_class(None)
        
        while True:
            pos += match_length(content, pos, PAT_SPACE)
            chr = content[pos:pos+1] # slicing avoids errors if we unexpectedly reach the end
            if (chr == ''):
                self.error_sink.warn("Tag construct was truncated")
                break
            elif (chr == '}'):
                pos += 1
                break
            elif (chr == '#'):
                # #id
                pos, v = self._consume_val(content, pos + 1)
                if v: el.id = v
            elif (chr == '.'):
                # .class
                pos, v = self._consume_val(content, pos + 1)
                if v: el.classes.append(v)
            elif (chr == '"' or chr == "'"):
                # "title"
                pos, v = self._consume_quoted(content, pos + 1, chr)
                if v: el.attr['title'] = v
            elif (chr == '<'):
                # src attribute
                pos, v = self._consume_url(content, pos + 1)
                el.attr['src'] = v
            else:
                # either attr=value or tagname
                # tagname is an error if it does not come first
                m = PAT_TOKEN.match(content, pos)
                if m:
                    k = m.group()
                    pos += len(k)
                    if content[pos:pos+1] == '=':
                        # key='value'
                        pos += 1
                        pos, v = self._consume_val(content, pos)
                        if k == 'id':
                            el.id = v
                        elif k == 'class':
                            el.classes += v.split(' ')
                        else:
                            el.attr[k] = v
                    else:
                        # tag name
                        if first:
                            el.tag = k
                        else:
                            self.error_sink.warn("ignoring token {}, tag names must come first".format(k))
                else:
                    # something unknown, go to next space and hope for the best
                    self.error_sink.warn("Unknown construct in tag ({}...), result may be incorrect".format(content[pos:pos+10]))
                    pos, _ = self._consume_val(content, pos)
            first = False
        return pos, el
    
    # parsing
    
    def do_newline(self, content, pos, group_index, m):
        self._append_el(FFElement('br'))
        return pos + 1
        
    def do_escape(self, content, pos, group_index, m):
        chr = content[m.start() + 1]
        self._append_text(chr if chr != ' ' else '\u00a0')  # U+00A0 no-break space
        return pos + 2
        
    def do_minitag(self, content, pos, tag, delim, use_flank_test):
        """ handle either the start or end of a mini tag

        use_flank_test specifies which flanking test we want. 1 for weak, 2 for strong.

        deciding if _ and * can start a tag is decidedly hairy, we're following a subset of CommonMark
        Specifically we do the left-flanking and right-flanking test, but we parse strictly left
        to right. '*' and '**' always open <em> and <bold> """

        can_open = True
        close_hint = self.top().close_hint
        can_close = close_hint == delim
        can_partial_close, can_double_close = False, False
        if not can_close:
            # parse ***foo* bar**
            can_partial_close = len(close_hint) == 3 and close_hint.startswith(delim)
            # parse **foo *bar***
            can_double_close = len(delim) == 3 and len(self.stack) >= 2 and (close_hint + self.stack[-2].close_hint) == delim
        
        # left flanking and right flanking test:
        if use_flank_test:
            lch = content[pos-1:pos] or ' '
            pos2 = pos + len(delim)
            rch = content[pos2:pos2+1] or ' '
            
            l_fl, r_punct = _flank_test(lch, rch)
            r_fl, l_punct = _flank_test(rch, lch)
            
            if can_close or can_partial_close or can_double_close:
                # let's see if we may close:
                if use_flank_test == 2:
                    # strong flanking test (_)
                    can_close = r_fl and (not l_fl or r_punct)
                else:
                    # weak flanking test (* and ~~)
                    can_close = r_fl
                
            if not can_close:
                # we will not close, let's see if we may open:
                # strong flanking test (_)
                if use_flank_test == 2:
                    can_open = l_fl and (not r_fl or l_punct)
                # weak flanking test (* and ~~)
                else:
                    can_open = l_fl
                    
        if can_close:
            if can_double_close:
                # end both tags
                self._close_tag()
                self._close_tag()
            elif can_partial_close:
                # complicated case, must wrap current top in a new element.
                self._wrap_tag(FFElement(tag), 'em' if len(delim) == 2 else 'strong')
                # crop off the 'innermost' delimiter part from close_hint
                self.top().close_hint = close_hint[len(delim):]
            else:
                # end tag
                self._close_tag()
            
        elif can_open:
            # start tag
            self._begin_tag(FFElement(tag), close_hint=delim)
            
        else:
            # literally append that delimiter
            self._append_text(delim)
            
        return pos + len(delim)
        
    def do_italic_bold(self, content, pos, group_index, m):
        match_string = m.group()
        # a sequence of 4 or more _ or * is not a valid opening sequence.
        if len(match_string) > 3:
            self._append_text(match_string)
            return pos + len(match_string)

        tag = ('em', 'strong', 'strong+em')[len(match_string) - 1]
            
        return self.do_minitag(content, pos, tag, match_string, True)
    
    def do_strike(self, content, pos, group_index, m):
        match_string = m.group()
        # ~~ for strike through
        return self.do_minitag(content, pos, 'del', match_string, True)
    
    def do_codespan(self, content, pos, group_index, m):
        ticks = m.group()
        pos += len(ticks)
        tk = self._append_el(FFElement('code'))
        # consume everything until we find the end
        pos_end = content.find(ticks, pos)
        span = content[pos:pos_end] if pos_end > 0 else content[pos:]
        # note that whitespace is stripped off
        tk.content = [LineToken(_TEXT, span.strip())]
        if pos_end < 0:
            pos_end = len(content)
        else:
            pos_end += len(ticks)
        return pos_end
        
    
    def do_ellip(self, content, pos, group_index, m):
        self._append_text('…')
        return pos + 3
    
    def do_dashes(self, content, pos, group_index, m):
        str = m.group()
        self._append_text('–' if str == '--' else '—') # en dash, em dash
        return pos + len(str)
        
    def do_url(self, content, pos, group_index, m):
        pos, url = self._consume_url(content, pos + 1)
        # Check if we just closed an element
        # this may return the draft token. Instantiate that one.
        tk = self.top().trailing_ignore_whitespace()
        draft_tk = self.draft_el_token
        self._flush_draft_el()

        # only merge if it doesn't already have an href attribute
        if tk and (tk.type != _ELEMENT or 'href' in tk.el().attr):
            tk = None
        
        # found one. Eat whitespace in between
        if tk:
            self.top().eat_whitespace()
        else:
            # if none found create one
            tk = self._append_el(FFElement('a'))
        # if this was a draft token or none found, add url text as content
        if not tk or tk == draft_tk:
            tk.content.append(LineToken(_TEXT, url))
        el = tk.el()
        el.attr['href'] = url
        return pos
    
    def do_tag_or_U(self, content, pos, group_index, m):
        um = _PAT_UCHAR_TAG.match(content, pos + 1)
        if um:
            self._append_text(chr(int(um.group()[2:-1], 16)))
            return pos + 1 + len(um)
        
        pos, el = self._consume_tag(content, pos)
        self._set_draft_tag(el)

        return pos

    
    def do_note(self, content, pos, group_index, m):
        p = _PAT_NOTE if m.group() == '(*' else _PAT_PANDOC_NOTE
        m = p.match(content, pos)
        if m:
            el = FFElement('notelink')
            el.attr['note-id'] = m.group()[1:-1]
            if self.draft_el_token:
                self.top().eat_whitespace()
            self._no_break_space()
            self._append_el(el)
            return pos + len(m.group())
        return None
    
    def do_span(self, content, pos, group_index, m):
        self._begin_tag(FFElement(None), close_hint=']')
        return pos + 1
    
    def do_span_end(self, content, pos, group_index, m):
        if self.top().close_hint == ']':
            self._close_tag()
            return pos + 1
        return None
