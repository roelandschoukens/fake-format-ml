from collections import namedtuple

from . import regexshim as _re
from .elements import *

# == a few simple blocks ==

def match_hr(parser, line1):
    if _re.match(r'\-\-\-\-+$', line1):
        parser.do_block(FFBlock('hr', ''))
        return True
    return False

# this one matches whitespace in line1, so it MUST be a first_matcher
def match_dingbat(parser, line1):
    m = _re.match(r'\s+(.)$', line1)
    if m and m.group(1) in ('❖', '❦', '*'):
        b = m.group(1)
        parser.do_block(FFBlock('hbullet', ''), b if b != '*' else parser.dingbat)
        return True
    return False

_PAT_SMALLHEAD = _re.compile(r'==+\s*(.*)==+$')

def match_small_head(parser, line1):
    m = _PAT_SMALLHEAD.match(line1)
    if m:
        parser.do_block(FFBlock('h4', ''), m.group(1).strip())
        return True
    return False

_PAT_H2 = _re.compile(r'====+$')
_PAT_H3 = _re.compile(r'\-\-\-\-+$')

def match_head(parser, line1, line2):
    if _PAT_H2.match(line2):
        parser.do_block(FFBlock('h2', ''), line1)
        return True
    if _PAT_H3.match(line2):
        parser.do_block(FFBlock('h3', ''), line1)
        return True
    return False


def match_note(parser, line1):
    # our old note syntax: (*1) blah
    m = _re.match(r'\((\*\d*)\)\p{Zs}+', line1)
    # pandoc syntax [^1]: blah
    m = m or _re.match(r'\[(\^\P{Z}+)\]:\p{Zs}+', line1)
    if m:
        ind = PAT_NONSPACE_1.sub(' ', m.group()) # indent will be a space for each character in the prefix
        bl = FFBlock('note', ind)
        bl.attr['note-id'] = m.group(1)
        parser.begin_block(bl)
        parser.parse_with_blocks(line1[len(ind):])
        return True
    return False


pat_info_box = _re.compile(r'!!!\s+([\w-]+)(\s+[\'"](.*)[\'"])?$')

def match_info_box(parser, line1, line2):
    # admonition style note box. This is rendered as a somewhat more subdued version of a quote.
    # match !!! prefix on line 1
    m = pat_info_box.match(line1)
    if not m: return False
    
    # line 2 must be indented (as with other constructs here, we don't require exactly 4 spaces)
    m_indent = PAT_WHITESPACE.match(line2)
    if not m_indent: return False
    
    title = m.group(3) or parser.default_info_box_title
    ind = m_indent.group()
    
    bl = FFBlock('infobox', ind)
    bl.attr['type'] = m.group(1)
    parser.begin_block(bl)
    parser.do_block(FFBlock('infobox-title', None), title)
    parser.parse_with_blocks(line2[len(ind):])
    return True


def match_quote(parser, line1):
    if line1[0] == '>':
        # any extra whitespace becomes part of the indentation
        ind = _re.match(r'>\s*', line1).group()
        qb = FFBlock('quote', ind)
        qb.must_have_p = False
        parser.begin_block(qb)
        parser.parse_with_blocks(line1[len(ind):])
        return True
    return False


def match_code(parser, line1, line2):

    class FF_Code(FFBlock):

        def __init__(self, *args, fence=None, **kwargs):
            super().__init__(*args, **kwargs)
            self.fence = fence

        def match_blank(self, line):
            """ blanks are not parsed inside verbatim blocks.

            we rely on parse_hook() to terminate this block. """
            return False

        def parse_hook(self, parser, line):
            if self.match_indent(line):
                line = self.strip_indent(line)
            if line.startswith(self.fence) and len(set(line)) == 1:
                # end fence: at least as long as the start fence, and all that same char
                parser.end_block()
            else:
                self.add_line(line)
            return True

        def add_line(self, line):
            sp = FFBlock('span', None)
            sp.verbatim = True
            parser.do_block(sp, line)

    # valid code block: fenced with '```' plus optionally a valid CSS class name
    m = _re.match('```+|~~~+', line1)
    if not m: return False

    fence = m.group()

    cl = line1[len(fence):].strip()
    if cl and not _re.match(RE_TOKEN+'$', cl): return False

    # valid. This block has a parse hook
    bl = FF_Code('sourcecode', '', fence=fence)
    bl.must_have_p = False
    if cl: bl.classes.append('lang-'+cl)
    parser.begin_block(bl)
    bl.add_line(line2)
    return True


# == list blocks ==

class FF_List(FFBlock):
    def __init__(self, tag, indent, bullet_pattern):
        """ A list block has an indent, which may or may not be 0. The
        indent determines where the left edge of bullets is.

        The bullet pattern will be used to match subsequent bullets."""
        super().__init__(tag, indent)
        self.bullet_pattern = bullet_pattern
        self.had_tag = False
        
        
    def choose_li_tag(self, bullet):
        if self.tag == 'tr':
            return ('th' if bullet == '#' else 'td')
        else:
            return 'li'
            
        self.current_li = None

    def match_indent(self, line):
        # list is unusual in that it terminates not by decreasing indent, but by
        # not matching the bullet
        # note that list items always 'consume' lines which don't start with a bullet
        if not super().match_indent(line):
            return False
        
        # let's inspect what comes after the indent:
        x = len(self.indent)
        
        if line[x:x + 1] == '{':
            return True
        
        return bool(self.bullet_pattern.match(line, x))

    def parse_hook(self, parser, line):
        if parser.top().match_blank(line) or not self.match_indent(line):
            # blank, or not our indent: delegate to normal parsing, 
            return False
            
        line = self.strip_indent(line)

        # look for block tag at exactly our indentation
        if line[0] == '{':
            tag_el, _ = parser.get_block_tag(line)
            if tag_el:
                parser.break_p()
                parser.unwind(self)
                parser.save_block_tag(tag_el, '')
                self.had_tag = True
                return True
        
        
        # match with our bullet indent
        m = self.bullet_pattern.match(line)
        if m:
            # our indent: this is a new list item
            if parser.in_p():
                # 'compact' list: we will see our bullet while in a paragraph
                parser.break_p()
            elif not self.had_tag:
                # with blank space: require p
                self.current_li.must_have_p = True
            
            bullet = m.group(1)
            
            parser.unwind(self)
            lbl = FFBlock(self.choose_li_tag(bullet), ' ' * len(bullet) + m.group(2))
            parser.begin_block(lbl)
            # by default we must have a paragraph if the previous item had a paragraph
            # meaning once a list had a paragraph break, it has paragraphs in all subsequent
            # items
            lbl.must_have_p = self.current_li.must_have_p
            self.current_li = lbl
            self.had_tag = False
            parser.parse_with_blocks(line[len(m.group()):])
            return True
        return False


def match_h_li(parser, line1, line2):
    """ match a single line followed by a list item

    The single line will be used as a kind of header. This is also
    responsible for generating the 'nested' single line list items
    in densely packed lists. """

    for om in parser._ord_list_pat:
        m = om.first.match(line2)
        if m:
            tag = 'ol'
            next_pat = om.next
            type = om.type
            break
    if not m:
        m = parser._list_pat.match(line2)
        if m:
            tag = 'ul'
            next_pat = _re.compile('('+_re.escape(m.group(2)) + r')(\s+)')
            type = 'conversation' if m.group(2) in ('—', '―', '--') else None

    if not m:
        return False
        
    if line1:
        # match_li() sets line1 to None
        parser.do_block(FFBlock('listhead', None), line1)

    ulbl = FF_List(tag, m.group(1), next_pat)
    if type:
        ulbl.attr['-ff-type'] = type
    parser.begin_block(ulbl)
    more_indent = ' ' * len(m.group(2)) + m.group(3)
    lbl = FFBlock(ulbl.choose_li_tag(m.group(2)), more_indent)
    lbl.must_have_p = False
    parser.begin_block(lbl)
    ulbl.current_li = lbl
    parser.parse_with_blocks(line2[len(m.group(0)):])
    return True

def match_li(parser, line1):
    """ match the first item in a list"""
    # simply defer to match_h_li, with no first line
    return match_h_li(parser, '', line1)


OrdListPattern = namedtuple('OrdListPattern', 'first next type')


class FakeFormatStdBlocks:
    """ This adds the standard blocks to an otherwise 'empty' parser """
    
    def __init__(self, *args):
        # user settings
        
        """ matches the various kinds of unordered list dashes.

        The last ones (— and ―, em dash and horizontal bar)
        add the 'conversation' class to the enclosing list.
        The hash mark triggers headings in table rows. """
        self.list_re = ['\*', '#', '·', '•', '-', '–', '—', '―', '--']

        """ Ordered lists. These are more complicated, with an initial matching, and a subsequent
        bullet matching pattern. All patterns shall occur before a dot and some spacing. """
        self.ord_list_re = [
            OrdListPattern(r'[\d#]+',    r'[\d+#]+',   None),
            OrdListPattern(r'0[\d#]+',   r'[\d+#]+',   'decimal-leading-zero'),
            OrdListPattern(r'[ivx]',    r'[a-z]',    'lower-roman'),
            OrdListPattern(r'[IVX]',    r'[A-Z]',    'upper-roman'),
            OrdListPattern(r'[a-z]',    r'[a-z]',    'lower-alpha'),
            OrdListPattern(r'[A-Z]',    r'[A-Z]',    'upper-alpha'),
        ]
        
        """ The dingbat to emit if a * is used in a dingbat block. """
        self.dingbat = '❦'
        """ The default title for an info box """
        self.default_info_box_title = "Note"
        
        
        # internal
        
        super().__init__(*args)
        self.first_matchers += [match_dingbat, match_li, match_note, match_quote]
        self.first_2_matchers += [match_head, match_h_li, match_code, match_info_box]
        self.single_matchers += [match_hr, match_small_head]
        
        self._ord_list_pat = None
        self._list_pat = None


    def start(self):
        super().start()
        self._ord_list_pat = [OrdListPattern(_re.compile('(\s*)('+a+r'\.)(\s+)'), _re.compile('('+b+r'\.)(\s+)'), c) for a, b, c in self.ord_list_re]
        self._list_pat = _re.compile(r'(\s*)(' + '|'.join(self.list_re) + r')(\s+)')
