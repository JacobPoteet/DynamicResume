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

#let filled(x) = x != none and x != ""

// Shows the address as written and links it, adding https:// when it has no scheme.
#let web-link(url) = link(if url.starts-with("http") { url } else { "https://" + url }, url)

// Read by build.py: flags a line meant to fit on one line (a role line, the headline) that
// wraps. `rhs` is the right-aligned text beside it, if any. Invisible; takes no space.
#let wrap-probe(body, rhs, what, label) = layout(size => {
  // `row` keeps a 1em gutter before the right-hand text.
  let room = size.width - if rhs == "" { 0pt } else { measure(text(fill: muted)[#rhs]).width + 1em.to-absolute() }
  if measure(body).width > room [#metadata((what: what, text: label)) <wrap>]
})

// Email and LinkedIn are real links, so a recruiter reading the PDF can click them.
#let contact-line(b) = {
  let parts = (
    if filled(b.email) { link("mailto:" + b.email, b.email) },
    b.phone, b.location,
    if filled(b.linkedin) { web-link(b.linkedin) },
  ).filter(filled)
  parts.join(h(0.55em) + text(fill: rule-soft)[|] + h(0.55em))
}

// Name, optional headline, contact line. The cover letter uses the same header.
#let header(b, headline) = {
  text(size: 25pt, weight: "bold", fill: accent)[#b.name]
  if filled(headline) {
    v(5pt)
    text(size: 11.5pt)[#headline]
    wrap-probe(text(size: 11.5pt)[#headline], "", "Headline", headline)
  }
  v(6pt)
  text(size: 9.5pt, fill: muted)[#contact-line(b)]
}

// Keep tracking at 0.08em or less: wider letter spacing makes some PDF text extractors
// (and the ATS parsers built on them) read the heading as "E X P E R I E N C E".
#let section(title) = {
  v(gap-section)
  block(width: 100%, sticky: true, stroke: (bottom: 0.6pt + rule-soft), inset: (bottom: 2.5pt))[
    #text(size: 9.2pt, weight: "bold", fill: accent, tracking: 0.06em)[#upper(title)]
  ]
  v(gap-heading)
}

// Left text, right-aligned muted text.
#let row(lhs, rhs) = grid(
  columns: (1fr, auto), column-gutter: 1em, align: (left + top, right + top),
  lhs, text(fill: muted)[#rhs],
)

// The master build marks each bullet with its id, priority and tags.
#let meta(b) = if b.at("meta", default: false) {
  text(size: 7.5pt, fill: muted)[ #b.id | p#b.priority | #b.tags.join(", ")]
}

// Fit probes, read by build.py: how many lines each bullet takes and how full its last line
// is, so the build can point at the bullet to trim, and any line that should fit on one line
// but wraps. They are invisible metadata and take no space.
#let line-counter(width) = {
  let one = measure(block(width: width, [X])).height
  let step = measure(block(width: width, [X #linebreak() X])).height - one
  body => calc.round((measure(block(width: width, body)).height - one) / step) + 1
}

#let bullet-fit(b, width, lines) = {
  let n = lines(b.text)
  let words = b.text.split(" ")
  // The last line holds the fewest trailing words whose removal drops a line.
  let k = 1
  while n > 1 and k < words.len() and lines(words.slice(0, words.len() - k).join(" ")) == n { k += 1 }
  let tail = if n == 1 { b.text } else { words.slice(words.len() - k).join(" ") }
  [#metadata((id: b.id, lines: n, last: measure(tail).width / width)) <bullet-fit>]
}


#let bullets(items) = layout(size => {
  list(spacing: gap-bullet, ..items.map(b => [#b.text#meta(b)]))
  if items.len() > 0 and not items.first().at("meta", default: false) {
    // The width a list item's text wraps at: the column minus indent, marker and gap.
    let width = size.width - (0.15em + 0.55em).to-absolute() - measure(text(fill: accent)[•]).width
    let lines = line-counter(width)
    for b in items { bullet-fit(b, width, lines) }
  }
})

// "Judas (Unreal Engine)", dropping the parenthetical when the name already says the engine.
#let game-label(game, engine) = {
  if engine != "" and not game.contains(engine) [#game (#engine)] else [#game]
}

// `company` repeats the employer on a later role under one company heading, so a parser
// that reads each role as its own job does not take the team name for the company. That line
// is the longest on the page, so its engine shortens to "UE4".
#let role(r, inline-game, company: none) = {
  let head = [#text(fill: accent, weight: "bold")[#r.title]#if filled(r.team) [#text(fill: muted)[, #r.team]]#if company != none [ #text(fill: muted)[| #company]]#if inline-game and r.game != "" [ #text(fill: muted)[|] #emph[#game-label(r.game, if company != none { r.engine.replace("Unreal Engine ", "UE") } else { r.engine })]]]
  block(breakable: false)[
    #row(head, r.dates_short)
    #wrap-probe(head, r.dates_short, "Role line", r.title + if r.game != "" { " | " + r.game } else { "" })
    #v(gap-head)
    #bullets(r.bullets)
  ]
}

#let render(d, show-games) = {
  set document(title: d.basics.name + " Resume", author: d.basics.name)
  set page(paper: "us-letter", margin: (x: margin-x, y: margin-y))
  set text(font: ("Calibri", "Arial", "Libertinus Serif"), size: 10pt, fill: ink, lang: "en")
  set par(leading: 0.4em, spacing: 0pt, justify: false)
  set block(spacing: 0pt)
  set list(marker: text(fill: accent)[•], body-indent: 0.55em, indent: 0.15em)

  header(d.basics, d.headline)

  // One plain line per game, without dates. A company and date range on each row would read
  // to an ATS as extra jobs, and columns lose their order when the text is extracted.
  if show-games and d.games.len() > 0 {
    section("Games")
    stack(spacing: 4pt, ..d.games.map(g => [
      #strong[#g.name]#if g.engine != "" and not g.name.contains(g.engine) [ #text(fill: muted)[(#g.engine)]]#if filled(g.company) [ #text(fill: muted)[|] #g.company]
    ]))
  }

  section("Experience")
  for (i, g) in d.groups.enumerate() {
    if i > 0 { v(gap-group) }
    // Each role carries its own dates, so promotions show no company-wide span on top.
    let multi = g.roles.len() > 1
    block(sticky: true)[
      #row(text(size: 10.6pt)[#strong[#g.company]], g.location)
    ]
    v(gap-line)
    if multi {
      // A role on the same game as the role above it skips the repeated game label.
      block(stroke: (left: 1.4pt + accent), inset: (left: 0.75em))[
        #stack(spacing: gap-role, ..g.roles.enumerate().map(((j, r)) => {
          let same = j > 0 and g.roles.at(j - 1).game == r.game
          role(r, not show-games and not same, company: if j > 0 { g.company })
        }))
      ]
    } else {
      role(g.roles.first(), not show-games)
    }
  }

  if d.skills.len() > 0 {
    section("Skills")
    stack(spacing: 3.5pt, ..d.skills.map(s => [#text(fill: accent, weight: "bold")[#s.group:] #s.items.join(", ")]))
  }


  if d.projects.len() > 0 {
    section("Projects")
    for (i, pr) in d.projects.enumerate() {
      if i > 0 { v(gap-group) }
      block(breakable: false)[
        #row(text(size: 10.6pt)[#strong[#pr.name]], if filled(pr.url) { web-link(pr.url) } else { "" })
        #if pr.summary != none [
          #v(gap-line)
          #text(fill: muted)[#emph[#pr.summary]]
        ]
        #v(gap-head)
        #bullets(pr.bullets)
      ]
    }
  }

  if d.education.len() > 0 {
    section("Education")
    stack(spacing: 6pt, ..d.education.map(e => [
      #row([#strong[#e.school]], e.years)
      #v(gap-line)
      #row([#e.credential], e.location)
    ]))
  }

  // Read by build.py: page count, and where the content ends so it can report free space.
  context [#metadata((
    pages: counter(page).final().first(), end: here().position().y / 1pt,
    top: margin-y / 1pt, limit: (page.height - margin-y) / 1pt,
  )) <layout>]
}
