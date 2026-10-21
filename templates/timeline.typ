// Shared body for the resumes grouped by company. resume-games.typ lists the games in
// their own section; resume-inline.typ puts each game on its role line.
// There is deliberately no summary block in any template.
//
// Spacing rule: every block has zero built-in spacing, and gaps are set explicitly with
// the constants below. No negative offsets.
#let accent = rgb("#1f4e5f")
#let rule-soft = rgb("#b9ccd3")
#let ink = rgb("#1d1d1d")
#let muted = rgb("#5a666b")

#let margin-x = 0.65in
#let margin-y = 0.5in
#let gap-section = 11pt   // above a section heading
#let gap-heading = 5pt    // below a section heading's rule
#let gap-group = 9pt      // between companies, and between projects
#let gap-role = 6pt       // between roles inside one company
#let gap-line = 3.5pt     // between stacked heading lines (company/title, project name/summary)
#let gap-head = 4.5pt     // between a heading block and its first bullet
#let gap-bullet = 4.5pt   // between bullets; must stay larger than the line leading so wrapped lines read as one bullet

#let contact-line(b) = {
  let parts = (b.email, b.phone, b.location, b.linkedin).filter(x => x != none and x != "")
  parts.join(h(0.55em) + text(fill: rule-soft)[|] + h(0.55em))
}

#let section(title) = {
  v(gap-section)
  block(width: 100%, sticky: true, stroke: (bottom: 0.6pt + rule-soft), inset: (bottom: 2.5pt))[
    #text(size: 9.2pt, weight: "bold", fill: accent, tracking: 0.13em)[#upper(title)]
  ]
  v(gap-heading)
}

// Left text, right-aligned muted text.
#let row(lhs, rhs) = grid(
  columns: (1fr, auto), column-gutter: 1em, align: (left + top, right + top),
  lhs, text(fill: muted)[#rhs],
)

#let bullets(items) = list(spacing: gap-bullet, ..items.map(b => [#b.text]))

// "Judas (Unreal Engine)", dropping the parenthetical when the name already says the engine.
#let game-label(game, engine) = {
  if engine != "" and not game.contains(engine) [#game (#engine)] else [#game]
}

#let role(r, inline-game) = {
  let head = [#text(fill: accent, weight: "bold")[#r.title]#if inline-game and r.game != "" [ #text(fill: muted)[|] #emph[#game-label(r.game, r.engine)]]]
  block(breakable: false)[
    #row(head, r.dates_short)
    #v(gap-head)
    #bullets(r.bullets)
  ]
}

#let render(d, show-games) = {
  set page(paper: "us-letter", margin: (x: margin-x, y: margin-y))
  set text(font: ("Calibri", "Arial", "Libertinus Serif"), size: 10pt, fill: ink, lang: "en")
  set par(leading: 0.4em, spacing: 0pt, justify: false)
  set block(spacing: 0pt)
  set list(marker: text(fill: accent)[•], body-indent: 0.55em, indent: 0.15em)

  text(size: 25pt, weight: "bold", fill: accent)[#d.basics.name]
  v(6pt)
  text(size: 9.5pt, fill: muted)[#contact-line(d.basics)]

  if show-games and d.games.len() > 0 {
    section("Games")
    grid(
      columns: (3.1in, 1fr, auto), column-gutter: 1em, row-gutter: 4pt, align: (left + top, left + top, right + top),
      ..d.games.map(g => (
        [#strong[#g.name]#if g.engine != "" and not g.name.contains(g.engine) [ #text(fill: muted)[(#g.engine)]]],
        text(fill: muted)[#g.company],
        text(fill: muted)[#g.dates_short],
      )).flatten(),
    )
  }

  section("Experience")
  for (i, g) in d.groups.enumerate() {
    if i > 0 { v(gap-group) }
    let multi = g.roles.len() > 1
    block(sticky: true)[
      #row(text(size: 10.6pt)[#strong[#g.company]], [#g.location#if multi [ #h(0.8em) #g.dates_short]])
    ]
    v(gap-line)
    if multi {
      block(stroke: (left: 1.4pt + accent), inset: (left: 0.75em))[
        #stack(spacing: gap-role, ..g.roles.map(r => role(r, not show-games)))
      ]
    } else {
      role(g.roles.first(), not show-games)
    }
  }

  if d.projects.len() > 0 {
    section("Personal Projects")
    for (i, pr) in d.projects.enumerate() {
      if i > 0 { v(gap-group) }
      block(breakable: false)[
        #row(text(size: 10.6pt)[#strong[#pr.name]], if pr.url != none { pr.url } else { "" })
        #if pr.summary != none [
          #v(gap-line)
          #text(fill: muted)[#emph[#pr.summary]]
        ]
        #v(gap-head)
        #bullets(pr.bullets)
      ]
    }
  }

  if d.skills.len() > 0 {
    section("Skills")
    stack(spacing: 3.5pt, ..d.skills.map(s => [#text(fill: accent, weight: "bold")[#s.group:] #s.items.join(", ")]))
  }

  if d.education.len() > 0 {
    section("Education")
    stack(spacing: 6pt, ..d.education.map(e => [
      #row([#strong[#e.school]], e.years)
      #v(gap-line)
      #row([#e.credential], e.location)
    ]))
  }

  context [#metadata(counter(page).final().first()) <pagecount>]
}
