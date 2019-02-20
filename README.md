# fake-format-ml
_Markdown dialect tailored towards prose, and occasional custom markup_

## Why?

Basically because I spotted Markdown on Stack Overflow too late (i.e. after creating the crappy PHP
version of this thing). I decided to keep it.

<!-- there is some irony in the fact that this is actually a Markdown document. -->

<!-- And if anyone is ever interested enough, I'll figure out how to properly
make a Python module. -->

## Basic principles

  - It will have (now so familiar) human-readable markup, somewhat based on old school plain text messaging conventions
  - It can mostly represent arbitrary HTML markup. (the main limitation is that it usually generates `<p>` tags around text).
  - One single markup language: doesn’t rely on inline HTML.
  - No implicit URLs, URLs are usually enclosed in angle brackets (moderately old school types remember this from e-mail headers).
  - Allow user hooks, for the occasional application-specific markup.

## Abstract

A basic example will look very familiar:

```
List:
 - item
 - item with **bold text**
     
> Quote
```

To handle the random markup (and images) there are 3 extra constructs:

**Span**: Text can be grouped into a _span_ with square brackets

```
This is [text in a span].
```

**Tag**: uses curly brackets and XML syntax with a few extensions borrowed from CSS. A
tag can decorate a line level or block level construct, or can occur by itself. A few
examples:

```
Boring XML: {class="emoticon" src="http://www.example.org/smile.png"}

Alternative syntax: {.emoticon <http://www.example.org/smile.png>}

{.fancy-p}
On a block element.

{.fancy-em} _On a line level element_.
```

If the element type cannot be inferred from the construct it is attached to, it will
be a semantically empty tag. Unless it has a `src` property, then it will become
an image.

**URL**: is inside angle brackets. Can exist by itself, or turn a
preceding element into a link. That order was borrowed from e-mail conventions.

```
This is [text in a link] <http://www.example.org>.

This is a link with the URL itself as text: <http://www.example.org>. The fact that the
period is not part of the URL is easy to understand.
```