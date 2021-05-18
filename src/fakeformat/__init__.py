# tagging those table rows in new-north-shore-network.md still doesn't work

# warn for single space indent in a few places (generic block and tag)

from . import regexshim as _re
from . import errors
from .blocks import FakeFormatStdBlocks
from .elements import *
from .lineparser import *


_IN_PARAGRAPH = Sentinel("In paragraph")

class FakeFormatBase:
    """ fakeformat block parser base class

    This is the base class for our fakeformat parser. It handles the basic structure of
    indented blocks and paragraphs. It also handles block tags. Other patterns (lists,
    notes, etc.) are added via mix-ins. """

    def __init__(self, sink, error_sink):
        # output object
        self.sink = sink
        # errors and warnings output
        self.error_sink = error_sink
        # FFBlock[]
        self.stack = [FF_Root()]
        # Flag set on encountering a blank line, cleared after the first non blank
        self.blank_flag = False
        # pending content, is buffered until we identify the next block
        self.pending_content = None
        # pending paragraph tag to go with pending_content
        self.pending_p_tag = None
        # List of 'pending' block tags. FFElement elements, where every next element
        # has more indent than the previous
        self.pending_block_tags = []
        # FFBlock[] -- elements of self.stack with a parse_hook function
        self.parse_hook_bl = []
        # Lines in the paragraph. These are buffered until the next paragraph break
        self.lines = []
        # line parser
        self.lineparser = Lineparser(self.sink, self.error_sink)

        """ list of single line matchers, called for single line paragraphs

        All the matchers below may safely assume preceding paragraphs are properly
        terminated.
        If the pattern matches, then the matcher should ‘consume’ both lines. It may call
        parse_in_block() or parse_with_blocks() to put content in newly pushed blocks (depending
        on if nested blocks are expected).
        """
        self.first_matchers = []
        """ list of dual line matchers, called for the first 2 lines of each paragraph """
        self.first_2_matchers = []
        """ list of matchers called for single lines with whitespace both before and after """
        self.single_matchers = []

        
    def start(self):
        """ Start must be called in the beginning.
        
        You may manipulate some variables in the parser (or the line parser) before
        calling start(). """
        # tell line parser to start
        self.lineparser.start()
        
        # tell our sink to start
        self.sink.start_element(self.stack[0])

    def add_line(self, l):
        l = l.rstrip()

        for bl in reversed(self.parse_hook_bl):
            if bl.parse_hook(self, l):
                return

        if self.top().match_blank(l):
            # blank line.
            self.blank_flag = True
            self.break_p()
            self.handle_empty_blocktag()
                
        else:

            if not self.lines:
                # first line after a blank.

                # first of all, pop blocks if the indent does not match
                while not self.top().match_indent(l):
                    self.end_block()

                # the current block must have paragraphs if we encountered a blank and didn't pop
                if self.blank_flag:
                    self.blank_flag = False
                    self.top().must_have_p = True
                
                # flush previous block
                if self.pending_content:
                    self.flush_pending_block(True)
                
                # strip indent of this block
                l = self.top().strip_indent(l)

                
                # and parse for patterns
                self.parse_with_blocks(l)

            else:

                if self.top().match_indent(l):
                    # matches indent, strip and parse for patterns
                    l = self.top().strip_indent(l)
                    self.parse_with_blocks(l)
                else:
                    # no match, just add to current block
                    self.parse_in_block(l)

    def top(self):
        """ top of the stack, which is the block where any content is going right now """
        return self.stack[-1]


    def in_p(self):
        """ True if we are in the middle of a paragraph """
        return bool(self.lines)

        
    def get_block_tag(self, line):
        """ Get a block tag on the given line """
        return self.lineparser.probe_block_tag(line)
    
    
    def save_block_tag(self, tag_el, extra_indent):
        """ Indicate there was a block tag.
        
        The indent given is the extra indent on top of the
        current top of the stack. """
        # drop tags without the matching indent
        tag_indent = self.top().indent + extra_indent
        pbt = self.pending_block_tags
        while pbt and not tag_indent.startswith(pbt[-1].indent):
            self.error_sink.warn('Dropping block tag with more indent: ' + str(pbt[-1]))
            pbt.pop()
        # same indent: merge
        if pbt and pbt[-1].indent == tag_indent:
            pbt[-1].merge(tag_el)
            tag_el = None
        # else append
        else:
            tag_el.set_indent(tag_indent, tag_indent)
            pbt.append(tag_el)
    
    
    def probe_block_tag(self, line):
        """ Match a block tag, and if it matches process it.
        
        The line must have the current block indent stripped."""
        tag_el, extra_indent = self.lineparser.probe_block_tag(line)
        if tag_el:
            self.save_block_tag(tag_el, extra_indent)
            return True
        return False
        

    def parse_with_blocks(self, line):
        """ Parse one or two lines for block structures.

        The given line must have the indent of the current block already stripped.

        This function is recursive, for any new block will also call parse_with_blocks
        for the content in the new block"""

        if not self.lines:
            # look for block tag
            if self.probe_block_tag(line):
                return
        
            # Call first set of matchers
            for m in self.first_matchers:
                done = m(self, line)
                if done:
                    return

            # detect extra whitespace, make generic block if any
            # this implies:
            #  - two line block matching patterns cannot start with spaces
            #  - we never need to strip extra indentation from self.lines
            m_white = PAT_WHITESPACE.match(line, 0)
            if m_white:
                indent = m_white.group()
                line = line[len(m_white.group()):]
                blq = FFBlock(None, indent)
                self.begin_block(blq)
                self.parse_with_blocks(line)
                return

            # no match. Keep line, try to match later
            self.lines.append(line)

        elif len(self.lines) == 1:
            # second line after a blank.
            # clear our lines field, if the matchers pick something up they
            # start from a clean line buffer
            lines = self.lines
            self.lines = []

            # Call second set of matchers
            for m in self.first_2_matchers:
                done = m(self, lines[0], line)
                if done:
                    return

            # no matches, restore line buffer and make paragraph
            self.lines = lines
            self.lines.append(line)

        else:
            # middle of paragraph, do not match for patterns
            self.lines.append(line)


    def parse_in_block(self, l):
        """ Parse a line, without trying to match any block structures """
        self.lines.append(l)


    def break_p(self):
        """ Break the current paragraph.

        Usually called in response of encountering an empty line."""

        if not self.in_p(): return
        
        lines = self.lines
        self.lines = []

        if len(lines) == 1:
            # single line, call relevant matchers
            for m in self.single_matchers:
                done = m(self, lines[0])
                if done:
                    return

        # no match, if single line declare it a plain paragraph
        pbt = self.pending_block_tags
        if pbt and pbt[0].indent == self.top().indent:
            self.pending_p_tag = pbt[0]
            pbt[0] = None
        
        for p in pbt:
            if p:
                self.error_sink.warn("Tag " + str(p) + " was not matched with a subsequent block.")
        self.pending_block_tags = []
        
        assert (not self.pending_content), "oops, dropping pending content"
        self.pending_content = lines
        

    def handle_empty_blocktag(self):
        """ Handle empty block tags before a blank line or EOF """
        # emit any pending block tags as nested tags
        # first strip void tags
        pbt = self.pending_block_tags
        while pbt and pbt[-1].is_void():
            pbt.pop()
        
        if pbt:
            for t in pbt[:-1]:
                self.sink.start_element(t)
            self.do_block(pbt[-1])
            for t in reversed(pbt[:-1]):
                self.sink.start_element(t)
            
        self.pending_block_tags = []
    
    def flush_pending_block(self, for_child_block):
        """ Feed the pending block to the line parser and send to output """
#        # any block with child blocks must have paragraphs
#        if for_child_block:
#            self.top().must_have_p = True

        if not self.pending_content:
            return

        content = self.pending_content
        p_tag = self.pending_p_tag
        self.pending_content = None
        self.pending_p_tag = None
        
        if p_tag:
            # create block images: no tag name, and src attribute
            if (not p_tag.tag or p_tag.tag == 'img') and 'src' in p_tag.attr:
                p_tag.tag = 'caption-img'

        # create a paragraph if necessary

        use_p = p_tag or self.top().must_have_p
        verbatim = self.top().verbatim
        if use_p:
            bl = FF_P('')
            if p_tag:
                bl.merge(p_tag)
            self.sink.start_element(bl)

        # parse content of this paragraph with inline parser
        content = '\n'.join(content)
        if verbatim:
            self.sink.add_content(content)
        else:
            self.lineparser.parse(content)

        # End current paragraph
        if use_p:
            self.sink.end_element(bl)


    def unwind(self, bl):
        """ unwind until the given block is the top of the stack.

        This assumes the current paragraph is terminated properly. Call
        break_p() if necessary. """
        while self.top() != bl:
            self.end_block()


    def parse_eof(self):
        """ end of file, output outstanding line buffer and close all blocks """
        self.break_p()
        self.handle_empty_blocktag()

        while len(self.stack) > 1:
            self.end_block()
            
        self.flush_pending_block(False)
        self.sink.end_element(self.stack[0])


    def begin_block(self, bl, empty=False):
        """ A new block begins

        the parser will prepend the indent of the topmost block to the indent of
        this block. This implies that a block cannot contain another block with
        less indentation.
        
        Setting the indent of the given block to None suppresses scanning for tags.
        This is unusual, any matching construct should always one way or another consume
        pending block tags.

        you must ensure any preceding paragraph is properly terminated with break_p(). """
        self.flush_pending_block(True)
        
        if bl.indent is not None:
            # does this block have its own extra indent:
            extra_tag_indent_limit = 1 if len(bl.indent) == 0 else 0
            
            bl.set_indent(self.top().indent + bl.indent, self.top().space_indent + bl.space_indent)
            top_indent = self.top().indent
            
            # investigate pending tags
            pbt = self.pending_block_tags
            tag_indent_limit = len(bl.indent) + extra_tag_indent_limit

            # detect generic block, started by additional indentation of the first pending tag
            pb0_indent_len = len(pbt[0].indent) if pbt else 0
            if pbt and len(top_indent) < pb0_indent_len < tag_indent_limit:
                div = FFBlock(None, pbt[0].indent)
                self.sink.start_element(div)
                self.stack.append(div)
            
            # use blocks whith strictly less indent. The same indent will be consumed by
            # paragraphs (the exception are other blocks which don't declare extra indentation)
            bl_ix = 0
            while bl_ix < len(pbt) and len(pbt[bl_ix].indent) < tag_indent_limit: 
                bl_ix += 1
            
            # generate nested blocks for nested tag. Each block for a tag gets the
            # indent for the next tag. The last one gets merged with the given block
            # and thus gets that indent
            for i in range(bl_ix - 1):
                pbt[i].set_indent(pbt[i + 1].indent, pbt[i + 1].space_indent)
                self.sink.start_element(pbt[i])
                self.stack.append(pbt[i])
                
            if bl_ix != 0:
                bl.merge(pbt[bl_ix - 1])
                
            self.pending_block_tags = pbt[bl_ix:]
        
        self.sink.start_element(bl, empty=empty)
        self.stack.append(bl)
        if hasattr(bl, 'parse_hook'):
            self.parse_hook_bl.append(bl)


    def end_block(self, empty=False):
        """ A block ends

        you must ensure the current paragraph is properly terminated with break_p(). """
        assert not self.in_p()
        
        self.flush_pending_block(False)
        bl = self.top()
        self.sink.end_element(bl, empty=False)
        self.stack.pop()
        if self.parse_hook_bl and self.parse_hook_bl[-1] == bl:
            self.parse_hook_bl.pop()
        assert self.stack, "Root block was popped"


    def do_block(self, bl, content=None, end_mark=None):
        """ Add a child block, with an optional line of content

        if content is None, the block will be 'empty', this bit of
        info is available to the sink.

        If not, content is added and parsed as in line content, without wrapping p.
        
        if not verbatim, you can use end_mark to specify where the line parser will stop.

        This assumes the line buffer is empty. This is guaranteed when a
        matcher is called. """
        self.begin_block(bl, empty=(content is None))
        end_pos = None
        if content:
            if bl.verbatim:
                # verbatim (no line elements)
                self.sink.add_content(content)
            else:
                # parse content of this paragraph with inline parser
                end_pos = self.lineparser.parse(content, end_mark=end_mark)
        self.end_block(empty=(content is None))
        return end_pos



class FakeFormat(FakeFormatStdBlocks, FakeFormatBase):
    pass


class Out:
    """ basic implementation of the output sink expected by our html sink """
    def write(self, l):
        print(end=l)

class WarningOut:
    """ basic implementation of the warning sink expected by fakeformat """
    def error(self, l):
        print("Error:", l, file=sys.stderr)

    def warn(self, l):
        print("Warning:", l, file=sys.stderr)

_HEAD = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link rel="stylesheet" type="text/css" href="skin.css"/>
</head>
<body>
"""


def main(args):
    import sys
    from . import htmlsink

    try:
        # test if stdout encoding has reasonable coverage
        test_what = 'output'
        "→•—❦".encode(sys.stdout.encoding)
        test_what = 'input'
        "→•—❦".encode(sys.stdin.encoding)
    except UnicodeEncodeError:
        msg = 'Warning, {} encoding is set to "{}". An universal encoding like UTF-8 should be used. You may set PYTHONIOENCODING to override.'
        print(msg.format(test_what, sys.stdout.encoding),
                    file=sys.stderr)

    print(end=_HEAD)
    h = htmlsink.HtmlSink(Out())
    ff = FakeFormat(h, WarningOut())
    ff.start()
    try:
        while True:
            l = sys.stdin.readline()
            if not l: break
            ff.add_line(l)
        ff.parse_eof()
    except errors.ParseException as e:
        print(e.message, file=sys.stderr)
        return 1
    print('</body>\n</html>\n')
    return 0
