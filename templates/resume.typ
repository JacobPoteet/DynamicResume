// One-page resume. Reads resolved JSON from `--input data=/build/<name>/resume.json`.
#import "common.typ": *

#let d = json(sys.inputs.data)

#show: setup.with(size: 10pt)
#set par(leading: 0.5em)
#set list(marker: [•], body-indent: 0.5em, indent: 0.3em, spacing: 0.4em)

#let section(title) = {
  v(0.4em)
  block(sticky: true, below: 0.6em)[
    #text(size: 12pt, weight: "bold")[#title]
    #v(-0.45em)
    #line(length: 100%, stroke: 0.6pt + muted)
  ]
}

#let meta(b) = if d.at("meta", default: false) {
  text(size: 7.5pt, fill: muted)[ #b.id | p#b.priority | #b.tags.join(", ")]
}

#let bullets(items) = list(..items.map(b => [#b.text#meta(b)]))

#header(d.basics)
#v(0.2em)

#if d.at("summary", default: none) != none [
  #d.summary
]

#if d.games.len() > 0 [
  #section("Games")
  #for g in d.games [
    #strong[#g.name]#text(fill: muted)[, #g.dates] \
  ]
]

#section("Experience")
#for p in d.positions {
  block(breakable: false)[
    #strong[#p.heading] #h(1fr) #emph[#p.location] \
    #smallcaps[#p.title] #h(1fr) #text(fill: muted)[#emph[#p.dates]]
    #v(-0.2em)
    #bullets(p.bullets)
  ]
  v(0.2em)
}

#if d.skills.len() > 0 [
  #section("Skills")
  #for s in d.skills [
    #strong[#s.group:] #s.items.join(", ") \
  ]
]

#if d.education.len() > 0 [
  #section("Education")
  #for e in d.education [
    #strong[#e.school] #h(1fr) #emph[#e.location] \
    #smallcaps[#e.credential] #h(1fr) #text(fill: muted)[#emph[#e.dates]]
  ]
]

#if d.projects.len() > 0 [
  #section("Projects")
  #for pr in d.projects {
    block(breakable: false)[
      #strong[#pr.name]#if pr.url != none [ (#pr.url)]#if pr.summary != none [: #pr.summary]
      #if pr.bullets.len() > 0 [
        #v(-0.2em)
        #bullets(pr.bullets)
      ]
    ]
  }
]

#context [#metadata(counter(page).final().first()) <pagecount>]
