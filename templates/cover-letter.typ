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

#context [#metadata(counter(page).final().first()) <pagecount>]
