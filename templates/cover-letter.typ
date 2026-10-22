// Cover letter. Reads resolved JSON from `--input data=/build/<name>/cover-letter.json`.
// Shares the header, colors, fonts and margins of the timeline resumes so the pair matches.
#import "timeline.typ": accent, ink, muted, rule-soft, margin-x, margin-y, contact-line

#let d = json(sys.inputs.data)

#set page(paper: "us-letter", margin: (x: margin-x, y: margin-y))
#set text(font: ("Calibri", "Arial", "Libertinus Serif"), size: 11pt, fill: ink, lang: "en")
#set par(leading: 0.7em, spacing: 1.35em, justify: false)

// Same header as the resume: bold accent name, muted contact line, then a soft rule.
#block(width: 100%, stroke: (bottom: 0.6pt + rule-soft), inset: (bottom: 9pt))[
  #set par(spacing: 0pt, leading: 0.4em)
  #text(size: 25pt, weight: "bold", fill: accent)[#d.basics.name]
  #v(6pt)
  #text(size: 9.5pt, fill: muted)[#contact-line(d.basics)]
]
#v(1.6em)

#if d.at("date", default: none) != none [
  #text(fill: muted)[#d.date]
  #v(0.4em)
]

#d.greeting
#parbreak()

#d.paragraphs.join(parbreak())
#parbreak()

#d.closing \
#text(weight: "bold", fill: accent)[#d.basics.name]

// Read by build.py: page count, and where the content ends so it can report free space.
#context [#metadata((
  pages: counter(page).final().first(), end: here().position().y / 1pt,
  top: margin-y / 1pt, limit: (page.height - margin-y) / 1pt,
)) <layout>]
