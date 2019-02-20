from collections import OrderedDict
from . import regexshim as _re

import sys


""" tags which we consider empty. This is largely the same as HTML but includes a few more. """
_EMPTY_TAGS = ( 'area', 'base', 'br', 'col', 'command', 'embed', 'hr', 'img',
                'input', 'keygen', 'link', 'meta', 'param', 'source', 'track', 'wbr',
                'notelink')


""" This matches a 'token' which may be delimited by spaces.

Exclude spaces, quotes and tag metacharacters. """
RE_TOKEN = r'[\w\p{Pd}\p{Pc}]+' if _re.has_regex else r'[\w\-]+'
PAT_TOKEN = _re.compile(RE_TOKEN)
""" matches 1 or more 'blank' characters """
PAT_SPACE = _re.compile(r'\p{Z}+')
""" matches 1 or more spaces """
PAT_WHITESPACE = _re.compile(r'\p{Zs}+')
""" matches 1 or more non-space characters """
PAT_NONSPACE = _re.compile(r'\P{Z}+')

# the pattern below has the convenient property that it always yields a valid match.
""" matches 0 or more spaces """
PAT_WHITESPACE_0 = _re.compile(r'\p{Zs}*')

""" matches exactly 1 non-space characters """
PAT_NONSPACE_1 = _re.compile(r'\P{Z}')

PAT_CMM_PUNCT = _re.compile(r'''[!"#$%&'()*+,\-./:;<=>?@[\]\^_`{|}~\p{Pc}\p{Pd}\p{Pe}\p{Pf}\p{Pi}\p{Po}\p{Ps}]''')

def match_length(content, pos, pat):
    m = pat.match(content, pos)
    return len(m.group()) if m else 0


class Sentinel:
    """ simple class to construct arbitrary named constants. Use the 'is' operator to check """
    def __init__(self, s):
        self.s = '['+s+']'
        
    def __str__(self):
        return self.s

def sentinels(*args):
    return map(Sentinel, args)

class FFElement:
    def __init__(self, arg):
        """ Make an element
        
        FFElement(tag_name): make a new element, with the given tag name and empty elements
        
        FFElement(element): make an independent copy of the given element.
        """
        # handle copy case
        el, tag = None, None
        if isinstance(arg, FFElement):  
            el = arg
            arg = None
        elif arg:
            tag = str(arg)
    
        """type of block"""
        self.tag = tag
        """ ID attribute """
        self.id = None
        """ class attribute (as list) """
        self.classes = []
        """ rest of attributes as map """
        self.attr = OrderedDict()
        """ content type """
        self.verbatim = False
        """ is this a block or not """
        self.is_block = False
        
        if el:
            self.merge(el)
            self.is_block = el.is_block
        
    def is_void(self):
        """ Return if this element has not tag name or attributes """
        return not self.tag and not self.id and not self.classes and not self.attr
    
    def clear(self):
        """ Clear this tag, i.e. make self.is_void() True. """
        self.tag = None;
        self.attr = OrderedDict()
        self.id = None
        self.classes = []
    
    def is_empty_tag(self):
        return self.tag in _EMPTY_TAGS or (self.tag is None and 'src' in self.attr)
    
    def merge(self, other):
        """ merge attributes from other.
      
        This will merge classes and attributes from other. If given the other tag
        name and ID will replace those of this element.

        other is normally an element derived from an explicit tag """
        if other.tag:
            self.tag = other.tag
        
        if other.id:
            self.id = other.id
        
        self.classes += other.classes
        self.attr.update(other.attr)
    
    def __str__(self):
        s = []
        if self.tag: s.append(self.tag)
        if self.id: s.append('#' + self.id)
        for c in self.classes: s.append('.' + c)
        return '{' + ' '.join(s) + '}'
        
    def __repr__(self):
        s = []
        if self.tag: s.append(self.tag)
        if self.id: s.append('#' + self.id)
        for c in self.classes: s.append('.' + c)
        for k, v in self.attr.items(): s.append(k + '="' + str(v) + '"')
        return type(self).__name__ + '(' + ' '.join(s) + ')'
        
        
class FFBlock(FFElement):
    def __init__(self, tag, indent=''):
        super().__init__(tag)
        """ indent """
        self.indent = indent
        """ indent, with spaces only """
        if indent is not None:
            self.space_indent = PAT_NONSPACE_1.sub(' ', indent)
        """ if True any text must be enclosed in a P """
        self.must_have_p = True
        """ is this a block or not """
        self.is_block = True
    
    def set_indent(self, indent, space_indent):
        """ Update indent. This always updates indent and space_indent in tandem """
        self.indent = indent
        self.space_indent = space_indent

    def match_blank(self, l):
        """ Check if this line is considered whitespace """
        assert self.indent is not None, 'Oops, indent is None (tag ' + self.tag + ' and line '+l+')'
        return self.indent.startswith(l) or self.space_indent.startswith(l)

    def match_indent(self, l):
        """Check if this line starts with our indent.
        
        If not this block is terminated"""
        return l.startswith(self.indent) or l.startswith(self.space_indent)

    def match_indent_prefix(self, l, prefix):
        """Check if this line starts with our indent, plus an extra prefix.
        
        If not this block is terminated"""
        return l.startswith(self.indent + prefix) or l.startswith(self.space_indent + prefix)
        
    def strip_indent(self, l):
        """Strip the indent off the given line. This happens blindly, so call match_indent first """
        return l[len(self.indent):]
    
    # def parse_hook(self, parser, line)
    #   if present, this will be called before the usual parsing of a line.
    #   l shall not have any whitespace stripped, so often you actually need self.strip_indent(line)
    #   returns: true if this line was consumed, false if normal parsing will happen
    #   If defined this is called for any line, including blanks, unless a block higher in the stack
    #   consumes the line in its own parse_hook routine.

        
class FF_Root(FFBlock):
    def __init__(self):
        super().__init__('fakeformat', '')

    def match_indent(self, l):
        return True
        
class FF_P(FFBlock):
    def __init__(self, indent):
        super().__init__('p', indent)
        self.must_have_p = False
