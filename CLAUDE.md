# DynamicResume: working notes for Claude

One master file of career data, a tailor file per job, Typst templates, and `build.py`. The goal is a one-page resume and matching cover letter for each application.

Follows the workflow standard in the user CLAUDE.md: squash merges, `/ship` to land a PR, `/release` to cut one, bugs fixed when found. Deviations are listed at the end.

**Privacy.** This is a public repo. `data/`, `applications/`, `Local/`, `build/`, `snapshots/` and all PDFs (outside `examples/`) are gitignored. Never commit personal data. Anything public goes in `examples/` with fictional data.

**Personal rules and notes.** Anything specific to the user's own career, background, or notes lives in the gitignored `CLAUDE.local.md` at the repo root. Read it before tailoring. Never copy its contents, or anything that reveals where private notes are kept, into a committed file, commit message, or PR.

## Area rules

This file holds what a tailoring session or a headless draft needs. Three files in `.claude/rules/` load when Claude touches what they cover: `app.md` (how the editor app behaves), `tracking.md` (the board and the tracking and job schemas) and `code.md` (what each source file does, ATS rules for templates). Read the matching one before changing an area its files did not load.

## Commands

```
python build.py serve                # editor app at http://127.0.0.1:8765 (the main way to work)
python build.py build <app-folder>   # name under applications/ or a path
python build.py build master         # full pool, multi-page, shows bullet id | priority | tags
python build.py build-all            # skips submitted applications
python build.py check                # rebuild every unsubmitted application into build/check/ and report what changed
python build.py new "<studio>" "<role>" [--listing file|-]   # start an application folder
python build.py new --url <link> ["<studio>" "<role>"]     # import a Greenhouse, Lever or Ashby posting instead
python build.py draft <app>          # headless Claude draft, as the app does, then build
python build.py fit <app> [--report] # fit the resume to one page, or suggest bullets when it has room; --report writes nothing
python build.py snapshot [label]     # zip master, applications, templates, Local/ into snapshots/
python build.py submit <app> [--date YYYY-MM-DD]   # freeze the PDFs as sent (no rebuild)
python build.py unsubmit <app>       # make it editable again
python build.py track <app> [stage] [--date --note --scheduled --format --length --with "Name, Role"]   # log what happened after sending; no stage prints the history
python build.py build-all --example  # --example (before or after the subcommand) uses examples/
```

Needs `typst` (`winget install Typst.Typst`) and `pip install -r requirements.txt`. Every build reports the page count and how full the last page is, and lints for em dashes and banned phrases. When a resume runs over it says about how many lines are on the extra page. It also lists bullets whose last line is nearly empty (trimming a few words there saves a whole line) and warns when a role line or the headline wraps.

**Data home.** In a linked git worktree, `build.py`, the app and drafts read and write the main checkout's `data/`, `applications/`, `Local/`, `snapshots/` and `CLAUDE.local.md` (it says "Using data in ..."). Code, templates, `examples/` and `build/` stay with the worktree. `DYNAMICRESUME_HOME` points them anywhere else. So in a worktree, edit the main checkout's data files directly; never copy data into the worktree. The Claude desktop app refuses Write and Edit on files outside the worktree, so write those data files with a shell command (or through `build.py` and the app).

**After editing the master,** run `python build.py check`. It rebuilds every unsubmitted application into `build/check/`, never the application folders, and compares each resume with its last real build. It exits nonzero when one goes past one page. The Master page and Save to master on the Resume tab run the same check after every save. Then fix what it reports (a `short` text, a different bullet) before building.

## Submitted applications

Never edit, rebuild, or unsubmit a submitted application unless the user asks. Tracking and job details are the exceptions: `tracking.yaml` and `job.yaml` stay editable after submitting (the app shows the live `job.yaml`, not the frozen copy), and restoring a snapshot keeps the current `tracking.yaml` (the snapshot's copy is written only when an application has none).

`.claude/rules/app.md` covers how Mark sent, the Send dialog and Unsubmit work.

## Application tracking

When the user says they heard back ("Scopely rejected me yesterday"), log it with `python build.py track <app> <stage> --date ...`. Use the day it happened, not today, and never invent events. After a master change, run `check`, then `build-all` (both skip submitted ones) rather than building each folder.

`.claude/rules/tracking.md` covers the board, Needs attention, calendar files, and the `tracking.yaml` and `job.yaml` schemas.

## Tailoring workflow (when the user pastes a job listing)

In the app, "Create and draft with Claude" (or Redraft on the Listing tab) runs this workflow headlessly; so does `python build.py draft <app>`. `studio/draft.py` starts `claude -p` in the data home with read-only tools, so this file and `CLAUDE.local.md` apply. The prompt includes the studio's notes from `data/studios.yaml` and the gap topics already in use. Claude answers with one JSON object (listing requirements, tailor, cover letter body, gaps with topics, notes); the app drops any id the master does not have and writes `listing.yaml`, `tailor.yaml` and `cover-letter.md`. Claude's raw reply is kept in `build/studio/<app>/draft-reply.txt`. Redrafting takes a snapshot first. A draft is then fitted to the page (see Fitting to the page) and the result reports what changed.

When tailoring from a chat instead, follow these steps and also write `listing.yaml` so the app can show requirement coverage:

1. Run `python build.py new "<studio>" "<role>" --listing -` with the listing on stdin. It creates `applications/<studio>-<role>/` with `listing.md` and a starter `tailor.yaml`. Folder and PDF names keep letters and digits in any script; a name of only symbols gets a generated folder (`app-1a2b3c4d`).
2. Check `data/studios.yaml` for notes on the studio (games played, people known) to use in the letter.
3. Read `data/master.yaml`. Pick bullets by tag match against the listing, then priority (1 = strongest). Order bullets within each position by relevance to the listing, not by priority alone.
4. Write `tailor.yaml`: a `headline`, ordered bullet ids per position, `skills_first`, optional `overrides` and `short`. Never select a bullet and its `variant_of` partner together.
5. Reword with `overrides` only where it helps match the listing's language. To save space, list a bullet under `short` (when the master has a `short` text) rather than pasting a shorter override. Never edit the master for one application.
6. Write `cover-letter.md`: plain paragraphs separated by blank lines. It is not rendered as Markdown: syntax prints as typed, and the build warns about it. Set greeting and closing in `tailor.yaml` under `cover_letter`.
7. Run `python build.py build <folder>`. Confirm the output says 1 page for both PDFs. If over, it says about how many lines to cut: run `python build.py fit <folder> --report` to see what the fit rule would cut, then use `short` texts, trim the bullets the build lists as having nearly empty last lines, or cut bullets, using your judgment about the listing; do not shrink fonts. Fix any role line or headline it says wraps. If the last page is well under 90% full, say so and give the bullets `fit --report` suggests: the user may want to add one.
8. Write `listing.yaml`, giving each gap a `topic` (reuse the topics other applications use), and tell the user which bullets were chosen and what the master cannot back up, so they can add bullets.

Never invent experience, metrics, tools, or titles. If a listing wants something the master lacks, say so and ask.

## Writing rules

- Never use em dashes in resume or cover letter text. Use commas, colons, periods, or parentheses. (En dashes in date ranges are fine and generated by the build.)
- The headline is "<title> | <two to four focus areas>". The title is one the master shows the person holding; the focus areas use the listing's words where selected bullets back them up.
- Write plain, specific, accurate copy that does not undersell the work. Avoid "leverage", "passionate about", "drive innovation", "spearhead", "synergy", "cutting-edge", "excited to", and similar filler. Cover letters should say concrete things the person did and why it fits the studio.

## Fitting to the page

`studio/fit.py` is one rule used three ways: the editor's Fit to page button (`POST /api/apps/<name>/fit`, with Undo and a report panel), `python build.py fit`, and after every headless draft. It renders the resume and measures it with the page data the templates report.

- Over one page: it applies `short` texts one at a time, skipping any that save no line, then cuts one bullet at a time until it fits, then gives back any cut or short text that turned out not to be needed. It never rewords, never changes fonts, and only removes bullets, so it cannot create a `variant_of` pair. A cut bullet's override and `short` entry go with it.
- Cut order, first to go: listing relevance (a must-have requirement scores 2 and a nice-to-have 1; with no requirements, words and tags shared with the listing, the same score the Resume tab ranks by), then priority, then older positions, projects before positions, and later bullets. The only bullet behind a must-have goes last. A position always keeps one bullet; a project with none left leaves the page. If that is still too long, the report says so.
- Under 90% full: it suggests up to three unselected bullets from positions and projects already on the page that a test render shows still fit, and never adds them itself. Either side of a `variant_of` pair is never suggested.

The report lists what was shortened and cut, and any requirement that lost its coverage. Because a cut may remove something the letter mentions, it says to check the letter.

## master.yaml schema

All dates are `YYYY-MM` or `present`. Positions are listed newest first; that order is the resume order.

```yaml
basics:
  name, email, phone, location, linkedin      # all strings
  headline                                    # optional default; tailor.yaml usually sets its own
  paper                                       # optional default page size: letter or a4; tailor.yaml can override it

games:                                        # "Games" section
  - id, name, start, end

positions:
  - id: unique-slug
    company, product, engine                  # heading: "company - product (engine)"
    game: <games id>                          # informational
    title, location, start, end
    team                                      # optional; printed after the title: "Technical Designer, UI Team"
    bullets:
      - id: unique-slug                       # stable; never rename once used in a tailor.yaml
        text: string
        short: string                         # optional tighter wording; a tailor uses it via `short`
        variant_of: <bullet id>               # optional: another version of a bullet in the same position;
                                              # selecting both is a build error
        tags: [..]
        priority: 1..3                        # 1 = strongest

skills:
  - group: Software                           # one line per group
    items: [..]

education:
  - school, credential, location, start, end

projects:
  - id, name, url, summary
    bullets: [ {id, text, tags, priority} ]
```

Tags in use: `leadership, mentorship, ui, game-ai, generative-ai, multiplayer, vr, unreal, unity, consoles, tools, shipped, systems, gameplay, performance, process, pipeline, product, mobile, narrative, web, live-service, collaboration, quests, dynamic-events, playtesting, analytics, balancing, research`. Add new ones freely, but reuse existing ones when they fit.

## tailor.yaml schema

```yaml
target: {studio: ..., role: ...}              # studio is used in output file names; see the note below
template: resume-inline | resume-games | resume   # optional, default resume-inline
paper: letter | a4                            # optional, resume and letter; default master basics.paper, else letter
headline: Senior Technical Designer | Quests, Encounters   # optional, one line under the name
games: [game ids]                             # optional; absent = all, [] = none
positions:                                    # only listed positions appear
  <position id>:
    bullets: [ordered bullet ids]
skills_first: [items moved to the front of their group]
skill_groups: [groups to show, in order]      # optional, default all
projects: [project ids]                       # or {id: {bullets: [ids]}}; printed in this order
overrides: {bullet id: replacement text}
short: [bullet ids]                           # use the master's `short` text for these; an override wins
cover_letter: {greeting, closing, date}       # all optional
```

Renaming the studio through the app (saved when you leave the field) renames the PDFs in the application folder and moves its `studios.yaml` notes if the new name has none. The notes stay under the old name too while another application uses it, and `submitted/` is never touched. A rename in a text editor does neither: build again, and move the notes by hand.

An unknown id or `paper` value, or a bullet selected with its `variant_of` partner, is a build error; the Resume tab shows an unknown bullet, position, project or game as a "Not in the master" row with Remove. A redraft keeps the application's `paper`. An override or `short` id that matches no selected bullet, or a top-level key the build does not use, is a warning.

## listing.yaml schema

Written by a Claude draft and editable on the Listing tab. The build ignores it; the app uses it for the requirement chips (covered or not by the selected bullets) and to rank unselected bullets.

```yaml
studio, role
requirements:
  - text: Design enemy behaviors and boss encounters   # under 8 words
    must: true                                         # false = nice to have
    tags: [game-ai]                                    # master tags it relates to
    bullets: [dd-enemies]                              # master bullet ids that back it up
gaps:                                                # what the listing asks for that the master cannot back up
  - text: No accessibility work in the master
    topic: accessibility                               # short, reused across applications; plain strings also work
notes: what the draft led with and why
drafted: YYYY-MM-DD HH:MM
```

A requirement with `bullets` counts as covered when one of them is selected; one without falls back to shared tags. Master, Gaps groups every application's gaps by topic and ranks them by how many applications raised them. What the user decided about each topic (`done` or `not-me`, the date, and the bullet that closed it) lives in `data/gaps.yaml`, which `studio/gaps.py` reads and writes.

## studios.yaml

Optional, in `data/` (gitignored), edited on the Listing tab. Your notes about a studio, matched on the tailor's studio name and given to drafts for the cover letter. Use only what it says; never invent a game the person played.

```yaml
- studio: Sample Studio
  notes: games of theirs you have played, people you know there, why you want to work with them
```

## Checks

CI (`.github/workflows/ci.yml`) runs ruff and `node --check`, the privacy check (`scripts/check_privacy.py`), `pytest -m "not typst"`, and on Windows the demo build, `check --example` and `pytest -m typst` (ATS text extraction). Before opening a PR, run `ruff check .`, `python scripts/check_privacy.py` (after staging, since it reads tracked files) and `python -m pytest`, with `pip install -r requirements-dev.txt` first. Add or update a test with every behavior change. After changing a template or the demo data, rebuild the demo with `python build.py --example build-all` and commit the PDFs; a test fails when they are stale. Tests use only the demo: the `home` fixture copies `examples/` into a temporary data home.

## Cutting a release

Run `/release`. There is no release workflow and no version file: the tag (`v1.0.0` so far) marks the release, and the notes go on a GitHub release made with `gh release create`. Pages deploys `docs/` from `main` on its own. Skip the wiki pass: this repo has no wiki.

## Deviations from the standard

| Deviation | Why |
| --- | --- |
| No wiki. This file and the code are the documentation | A personal tool with one user. The tailoring workflow and the master, tailor and listing schemas are rules a headless draft has to follow, so they stay here and the file runs past 150 lines for them |
| `CLAUDE.local.md` (gitignored) carries personal rules | The repo is public and the career data is private |
| `docs/` holds the GitHub Pages project page | A published page, not documentation |
