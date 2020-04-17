from collections import namedtuple
import html
from . import elements

""" tags which are empty in HTML """
_EMPTY_TAGS = ( 'area', 'base', 'br', 'col', 'command', 'embed', 'hr', 'img',
                'input', 'keygen', 'link', 'meta', 'param', 'source', 'track', 'wbr')

class _Frame:
    def __init__(self, el):
        """ element (private copy) """
        self.el = el
        """ tag of this element before translation """
        self.tag = el.tag
        """ content to emit after closing this element """
        self.suffix = ''

def escape_content(s):
    return html.escape(s, quote=False)

def escape_attribute(s):
    return html.escape(s, quote=True)
    
_NL_ENDTAG, _NL_STARTTAG, _NL_NONE = 3, 2, 1

class HtmlSink:
    def __init__(self, out):
    
        # settings
        """ Map to handle specific tags with your own functions """
        self.tag_hooks = {}
        """ Hook to handle URLs, may be used to give meaning to 'special' urls """
        self.url_hook = None
        """ function to generate notes markers in the running text, always gets an 1-based counter """
        self.make_note_link_text = lambda x : '*'+str(x)
        """ function to generate notes markers at the note paragraph itself
        
        Takes either a 1-based count, or None if a note doesn't have a link in the text. """
        self.make_note_marker = lambda x : '(*' + str(x) + ')' if x is not None else '✽'
        
        # internal stuff
        
        self.out = out
        self.stack = []
        self.newline_flag = _NL_NONE
        self.empty_tags = _EMPTY_TAGS
        # bookkeeping for notes
        self.notes = {}
        self.note_counter = 0
    
    def start_element(self, el, empty=False):
        """ Register the start of an element

        empty: declare there will be no content. In this case the next output
        MUST be the matching end_element() call."""

        if el.is_block:
            self.flush_nl(_NL_STARTTAG)
        
        # make our private copy so we can freely modify before output
        el = elements.FFElement(el)
        
        f = _Frame(el)
        made_up_content = self._translate_to_html(f)
        self.stack.append(f)
        
        # special case, fakeformat (root)
        if f.el.tag == 'fakeformat':
            pass
        elif f.el.tag:
            s = ['<', f.el.tag]
            # attributes
            for k, v in el.attr.items():
                if v is not None:
                    s += [' ', k, '="', escape_attribute(v) if v else '', '"']
                else:
                    s += [' ', k]
                    
            # id: string
            if f.el.id:
                s += [' id="', escape_attribute(f.el.id), '"']
            # class: list to string
            if f.el.classes:
                v = " ".join(f.el.classes)
                s += [' class="', escape_attribute(v), '"']
            s += ['>']
            self.out.write("".join(s))
            if el.is_block:
                self.newline_flag = _NL_STARTTAG
        
        if made_up_content:
            self.add_content(made_up_content)
            
            
    def end_element(self, el, empty=False):
        f = self.stack[-1]
        self.stack.pop()
        if f.el.tag == 'fakeformat':
            self.flush_nl(_NL_ENDTAG)
        elif f.el.tag:
            if el.is_block:
                self.flush_nl(_NL_ENDTAG)
            assert f.tag == el.tag, "mismatched start_element and end_element"
            if not f.el.tag in self.empty_tags:
                self.out.write('</' + f.el.tag + '>')
                if el.is_block:
                    self.newline_flag = _NL_ENDTAG
        if f.suffix:
            self.out.write(f.suffix)
            if el.is_block:
                self.newline_flag = _NL_ENDTAG
    
    def add_content(self, line):
        self.out.write(escape_content(line))

    def flush_nl(self, for_which):
        if self.newline_flag >= for_which:
            self.newline_flag = _NL_NONE
            self.out.write('\n')

    def _translate_to_html(self, f):
        """ translate some constructs to html
        
        This may change tags, wrap tags (using f.suffix) and make up extra content
        (by returning it)
        """
    
        attr = f.el.attr
        tag = f.el.tag
        classes = f.el.classes
        made_up_content = ''

        # void block tags are block quotes (which usually render as plain indented divs)
        if f.el.is_void() and f.el.is_block:
            tag = 'blockquote'
        
        # nameless tags: HTML has semantically 'empty' tags:
        if not tag:
            if 'src' in attr:
                tag = 'img'
            elif f.el.is_block:
                tag = 'div'
            else:
                tag = 'span'
            
        # a few things are not HTML tags, translate to HTML with the appropriate CSS classes
        elif tag == 'hbullet':
            tag = 'div'
            classes.append('hbullet')
        elif tag == 'quote':
            tag = 'blockquote'
            classes.append('quote')
        elif tag == 'infobox':
            tag = 'blockquote'
            del attr['type']    # ignoring that, sorry.
            classes.append('infobox')
        elif tag == 'infobox-title':
            tag = 'p'
            classes.append('infobox-title')
        elif tag == 'listhead':
            tag = 'p'
            classes.append('listhead')
        elif tag == 'sourcecode':
            tag = 'pre'
            classes.append('code')
        elif tag == 'caption-img':
            # split in image and the paragraph for the caption
            img_el = elements.FFElement(None)
            img_el.merge(f.el)
            img_el.tag = 'img'
            self.out.write('<table class="caption-image"><tr><td>')
            attr.clear()
            classes.clear()
            f.el.id = None
            tag = 'p'
            # recursive call (!) to create <img> with all the given attributes
            self.start_element(img_el, empty=True)
            self.end_element(img_el, empty=True)
            self.out.write('</td></tr>\n<tr><td>')
            f.suffix += '</td></tr></table>'
        elif tag == 'notelink':
            nid = attr['note-id']
            del attr['note-id']
            # get counter value, make a new one if needed
            if nid not in self.notes:
                self.note_counter += 1
                self.notes[nid] = self.note_counter
            # we will make an <a> element with made up content
            made_up_content = self.make_note_link_text(self.note_counter)
            tag = 'a'
            attr['href'] = '#note-' + str(self.note_counter)
            classes.append('notelink')
        elif tag == 'note':
            nid = attr['note-id']
            del attr['note-id']
            # retrieve the note counter value, and delete it
            counter = self.notes.get(nid)
            if counter:
                del self.notes[nid]
            # wrap in note box, and add marker
            prefix = '<div class="notebox" id="note-{}">\n<div class="notemarker">{}&nbsp;</div>'
            self.out.write(prefix.format(counter, self.make_note_marker(counter)))
            f.suffix = '</div>'
            # finally convert the note to plain html
            tag = 'div'
            classes.append('note')
        elif tag in ('ol', 'ul'):
            type = attr.get('-ff-type')
            if type:
                del attr['-ff-type']
                if type == 'conversation':
                    classes.append(type)
                else:
                    attr['style'] = attr.get('style', '') + 'list-style-type: ' + type + ';'
        
        if tag == 'img' and f.el.is_block:
            classes.append('blockimg')
        
        # set tag so hooks actually work
        f.el.tag = tag
        del tag
        
        if 'href' in attr and self.url_hook:
            new_url = self.url_hook(attr['href'], 'href', f.el)
            if new_url:
                attr['href'] = new_url
        
        if 'src' in attr and self.url_hook:
            attr['src'] = self.url_hook(attr['src'], 'src', f.el)
        
        h = self.tag_hooks.get(f.el.tag)
        if h:
            suffix = h(f.el)
            if suffix:
                f.suffix += suffix

        
        # end of translation. If href is set, generate a if necessary
        if 'href' in attr:
            if f.el.tag == 'span':
                f.el.tag = 'a'
            if f.el.tag != 'a':
                # wrap in <a>
                self.out.write('<a href="{}">'.format(escape_attribute(attr['href'])))
                f.suffix += '</a>'
                del attr['href']

        return made_up_content