// Cover letter. Reads resolved JSON from `--input data=/build/<name>/cover-letter.json`.
#import "common.typ": *

#let d = json(sys.inputs.data)

#show: setup.with(size: 11pt)
#set par(leading: 0.75em, spacing: 1.5em)

#header(d.basics)
#v(1.2em)

#if d.at("date", default: none) != none [
  #d.date
  #v(0.6em)
]

#d.greeting
#parbreak()

#d.paragraphs.join(parbreak())
#parbreak()

#d.closing \
#strong[#d.basics.name]

// Read by build.py: page count, and where the content ends so it can report free space.
#context [#metadata((
  pages: counter(page).final().first(), end: here().position().y / 1pt,
  top: margin-y / 1pt, limit: (page.height - margin-y) / 1pt,
)) <layout>]
