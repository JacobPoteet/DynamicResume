// Shared look for resume and cover letter: page setup, fonts, header band.
#let band = rgb("#ececec")
#let ink = rgb("#222222")
#let muted = rgb("#666666")
#let margin-x = 0.65in
#let margin-y = 0.5in
#let fonts = ("Calibri", "Arial", "Libertinus Serif")

#let setup(size: 10pt, body) = {
  set page(paper: "us-letter", margin: (x: margin-x, top: margin-y, bottom: margin-y))
  set text(font: fonts, size: size, fill: ink, lang: "en")
  set par(justify: false)
  body
}

#let contact-line(b) = {
  let parts = (b.email, b.phone, b.location, b.linkedin).filter(x => x != none and x != "")
  parts.join("  |  ")
}

#let header(b) = pad(top: -margin-y, x: -margin-x, block(width: 100%, fill: band, inset: (x: margin-x, y: 11pt))[
  #text(size: 26pt, weight: "light")[#b.name]
  #v(1pt)
  #text(size: 9.5pt)[#contact-line(b)]
])
