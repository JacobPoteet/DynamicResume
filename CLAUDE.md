# DynamicResume: working notes for Claude

One master file of career data, a tailor file per job, Typst templates, and `build.py`. The goal is a one-page resume and matching cover letter for each application.

**Privacy.** This is a public repo. `data/`, `applications/`, `Local/`, `build/`, `snapshots/` and all PDFs (outside `examples/`) are gitignored. Never commit personal data. Anything public goes in `examples/` with fictional data.

**Personal rules and notes.** Anything specific to the user's own career, background, or notes lives in the gitignored `CLAUDE.local.md` at the repo root. Read it before tailoring. Never copy its contents, or anything that reveals where private notes are kept, into a committed file, commit message, or PR.

## Commands

```
python build.py serve                # editor app at http://127.0.0.1:8765 (the main way to work)
python build.py build <app-folder>   # name under applications/ or a path
python build.py build master         # full pool, multi-page, shows bullet id | priority | tags
python build.py build-all            # skips submitted applications
python build.py check                # rebuild every unsubmitted application into build/check/ and report what changed
python build.py new "<studio>" "<role>" [--listing file|-]   # start an application folder
python build.py draft <app>          # headless Claude draft, as the app does, then build
python build.py snapshot [label]     # zip master, applications, templates, Local/ into snapshots/
python build.py submit <app> [--date YYYY-MM-DD]   # freeze the PDFs as sent (no rebuild)
python build.py unsubmit <app>       # make it editable again
python build.py track <app> [stage] [--date --note --scheduled --format --length --with "Name, Role"]   # log what happened after sending; no stage prints the history
python build.py build-all --example  # --example (before or after the subcommand) uses examples/
```

Needs `typst` (`winget install Typst.Typst`) and `pip install -r requirements.txt`. Every build reports the page count and how full the last page is, and lints for em dashes and banned phrases. When a resume runs over it says about how many lines are on the extra page. It also lists bullets whose last line is nearly empty (trimming a few words there saves a whole line) and warns when a role line or the headline wraps.

**Data home.** In a linked git worktree, `build.py`, the app and drafts read and write the main checkout's `data/`, `applications/`, `Local/`, `snapshots/` and `CLAUDE.local.md` (it says "Using data in ..."). Code, templates, `examples/` and `build/` stay with the worktree. `DYNAMICRESUME_HOME` points them anywhere else. So in a worktree, edit the main checkout's data files directly; never copy data into the worktree. The Claude desktop app refuses Write and Edit on files outside the worktree, so write those data files with a shell command (or through `build.py` and the app).

**After editing the master,** run `python build.py check`. It rebuilds every unsubmitted application into `build/check/`, never the application folders, and compares each resume with its last real build. It exits nonzero when one goes past one page. The Master page and Save to master on the Resume tab run the same check after every save. Then fix what it reports (a `short` text, a different bullet) before building.

With no `data/master.yaml`, the app opens on a first-run screen that offers to copy the demo master there, and `build`, `check` and `new` print a clear `ERROR:` line.

The app has four areas: Applications (a board of every application by stage, with List, Timeline and Stats views and New application; see Application tracking below; deleting from List takes a snapshot first). A search box (every word must appear in studio or role) and a stage menu filter Board and List, and List sorts by studio, stage, applied date or last update from its column headers; the choices are remembered per browser (`T` in `tracker.js`). New application has an optional "Start from" menu: `Workspace.copy_tailor` copies `positions`, `overrides`, `short`, `headline`, `skills_first`, `skill_groups`, `projects`, `games`, `template` and `paper` (from the frozen `submitted/tailor.yaml` when the source was sent) plus, if asked, `cover-letter.md`, never `submitted/`, tracking, `listing.yaml`, job details or PDFs, and drops ids the master no longer has (the app lists them). Applying again to the same studio and role gets a `-2`, `-3` folder instead of an error, the editor (Resume, Cover letter and Listing tabs beside a live page preview, with Build PDFs and Send), Master (edit bullets, short texts, tags, priorities, position details and skills, or the raw YAML; Save validates before writing, and the server refuses a save (Bullets or Raw YAML) that removes, renames or moves a bullet an unsubmitted application selects or overrides, then shows which applications the change affects; a Gaps view ranks what listings asked for that the master lacks), and Snapshots. The app and the CLI read and write the same files, so either can be used at any time. The app saves `tailor.yaml` on every change and rebuilds the preview; it notices edits made to the files outside the app (by Claude or a text editor) within a couple of seconds and reloads. While you are mid-edit the reload waits until you finish, and the server refuses an autosave that would overwrite a file changed outside (`Workspace.outside_edits`): the editor keeps your edit and asks whether to use the file on disk or keep your edit. It writes YAML with ruamel round-trip, so comments and layout in `master.yaml` and `tailor.yaml` survive, and every master save keeps the previous file in `snapshots/master-history/`.

## Submitted applications

Mark sent in the Send dialog (or `build.py submit`) copies the application's PDFs as they are, plus `tailor.yaml`, `cover-letter.md`, `listing.md`, `listing.yaml`, `job.yaml` and the current `master.yaml`, into `applications/<app>/submitted/` with a `submitted.yaml` (date, file names, whether the PDFs were older than the inputs). From then on `build <app>` refuses (a `--template` trial build to `build/` still works), `build-all` skips it, the app opens it read-only and shows the sent PDFs beside the frozen `tailor.yaml`, letter, listing and `master.yaml` (the live file if an older `submitted/` lacks one), the server refuses edits and drafts, and its bullets no longer block master deletes. Snapshots include the sent PDFs. Unsubmit removes `submitted/` when the folder's PDFs still match it, and otherwise keeps it as `submitted-<date>/`.

The Send dialog (`openSend` in `tracker.js`; the element is in `index.html`, so the editor and the board both have it) opens from the editor's Send button, from dropping a draft on Applied, and from Move to Applied in the history dialog. It saves pending edits first and refuses while an outside edit awaits a choice. It shows each PDF as missing, out of date or current with its page count and fill, offers Rebuild (the finalize route) when one is missing or out of date, warns when the resume is over a page, copies the letter, each role's bullets and the contact details as plain text (falling back to selected text in a readonly box), opens the posting when `job.yaml` has a valid link, and takes the sent date and an optional note. Mark sent needs a resume PDF but allows out-of-date ones, with a warning, and goes through the applied path of `add_event`, so the toast's Undo works. `GET /api/apps/<name>/send-text` supplies the text, built by `studio/send.py` from `build.resume_data` and `build.letter_data` so it matches the PDFs; a tailor that does not build returns `error` instead of roles. The app never sends anything itself.

Never edit, rebuild, or unsubmit a submitted application unless the user asks. Tracking and job details are the exceptions: `tracking.yaml` and `job.yaml` stay editable after submitting (the app shows the live `job.yaml`, not the frozen copy), and restoring a snapshot keeps the current `tracking.yaml` (the snapshot's copy is written only when an application has none).

## Application tracking

The home page is a board: Saved (leads not started), Drafting (not submitted), Applied, Screen, Interviewing, Offer, and Rejected, Ghosted and Withdrew trays. Each column lists the most recently updated first. Dragging a card opens a dialog for the date it happened, an optional scheduled date and time, and a note; interviews also take round (numbered automatically), format, length, interviewers, prep notes and a debrief. Moving a draft to Applied opens the Send dialog instead. Clicking a card opens its history, where every event can be edited or deleted. A card in Applied, Screen or Interviewing with nothing logged or scheduled for 30 days shows Quiet and offers Ghosted, which counts as a rejection but is left out of time-to-rejection. Saved comes from `saved: true` in the application's `job.yaml`: New application has Save for later, which needs only a studio, a role and optionally a link; a card's Start drafting (or dragging it onto Drafting) clears the flag. Cards show the link and deadline, and the history dialog lists every job detail. Saved leads are not counted in Stats. Timeline and Stats (reply rate, days to reply and to rejection by stage, funnel, applications per week, interviews by format, upcoming) are computed by `studio/tracking.py`.

When the user says they heard back ("Scopely rejected me yesterday"), log it with `python build.py track <app> <stage> --date ...`. Use the day it happened, not today, and never invent events. After a master change, run `check`, then `build-all` (both skip submitted ones) rather than building each folder.

## Tailoring workflow (when the user pastes a job listing)

In the app, "Create and draft with Claude" (or Redraft on the Listing tab) runs this workflow headlessly; so does `python build.py draft <app>`. `studio/draft.py` starts `claude -p` in the data home with read-only tools, so this file and `CLAUDE.local.md` apply. The prompt includes the studio's notes from `data/studios.yaml` and the gap topics already in use. Claude answers with one JSON object (listing requirements, tailor, cover letter body, gaps with topics, notes); the app drops any id the master does not have and writes `listing.yaml`, `tailor.yaml` and `cover-letter.md`. Claude's raw reply is kept in `build/studio/<app>/draft-reply.txt`. Redrafting takes a snapshot first.

When tailoring from a chat instead, follow these steps and also write `listing.yaml` so the app can show requirement coverage:

1. Run `python build.py new "<studio>" "<role>" --listing -` with the listing on stdin. It creates `applications/<studio>-<role>/` with `listing.md` and a starter `tailor.yaml`. Folder and PDF names keep letters and digits in any script; a name of only symbols gets a generated folder (`app-1a2b3c4d`).
2. Check `data/studios.yaml` for notes on the studio (games played, people known) to use in the letter.
3. Read `data/master.yaml`. Pick bullets by tag match against the listing, then priority (1 = strongest). Order bullets within each position by relevance to the listing, not by priority alone.
4. Write `tailor.yaml`: a `headline`, ordered bullet ids per position, `skills_first`, optional `overrides` and `short`. Never select a bullet and its `variant_of` partner together.
5. Reword with `overrides` only where it helps match the listing's language. To save space, list a bullet under `short` (when the master has a `short` text) rather than pasting a shorter override. Never edit the master for one application.
6. Write `cover-letter.md`: plain paragraphs separated by blank lines. It is not rendered as Markdown: syntax prints as typed, and the build warns about it. Set greeting and closing in `tailor.yaml` under `cover_letter`.
7. Run `python build.py build <folder>`. Confirm the output says 1 page for both PDFs. If over, it says about how many lines to cut: use `short` texts, trim the bullets it lists as having nearly empty last lines, or cut lowest-priority bullets or skill groups; do not shrink fonts. Fix any role line or headline it says wraps. If the last page is well under 90% full, say so: the user may want to add a bullet.
8. Write `listing.yaml`, giving each gap a `topic` (reuse the topics other applications use), and tell the user which bullets were chosen and what the master cannot back up, so they can add bullets.

Never invent experience, metrics, tools, or titles. If a listing wants something the master lacks, say so and ask.

## Writing rules

- Never use em dashes in resume or cover letter text. Use commas, colons, periods, or parentheses. (En dashes in date ranges are fine and generated by the build.)
- The headline is "<title> | <two to four focus areas>". The title is one the master shows the person holding; the focus areas use the listing's words where selected bullets back them up.
- Write plain, specific, accurate copy that does not undersell the work. Avoid "leverage", "passionate about", "drive innovation", "spearhead", "synergy", "cutting-edge", "excited to", and similar filler. Cover letters should say concrete things the person did and why it fits the studio.

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

## tracking.yaml schema

In each application folder. The Applied date is `submitted/submitted.yaml`'s date, never stored here. Events are kept in the order logged; the board orders them by date.

```yaml
events:
  - date: 2026-11-03               # the day it happened
    stage: interview               # screen, interview, offer, rejected, ghosted, withdrew, note (applied only to move back)
    scheduled: 2026-11-06 14:00    # optional: YYYY-MM-DD or YYYY-MM-DD HH:MM
    round: 2                       # interview only, from here down
    format: video                  # phone, video, onsite, take-home
    length: 60                     # minutes
    interviewers: [{name: Sam Lee, role: Lead Designer}]
    prep: what to review
    debrief: how it went
    note: anything else            # any stage
```

## job.yaml schema

In each application folder, edited on the Listing tab (it stays open on submitted applications). Every field is optional and empty ones are dropped; the file is deleted when nothing is left. `studio/job.py` checks it. The `url` must be http or https, and the app only shows it as a link then. The `deadline` is `YYYY-MM-DD`.

```yaml
saved: true                        # a lead you have not started drafting (Saved column); removed by Start drafting
url: https://example.com/jobs/123
location: Remote (US)
salary: 120k to 140k
source: Studio careers page
referral: Sam Lee
deadline: 2026-11-20
contact: Pat Kim, recruiter, pat@example.com
```

A redraft never touches `job.yaml`, and `Workspace.outside_edits` guards it like the other autosaved files. `GET /api/apps` and `GET /api/apps/<name>` carry it as `job`; `PUT /api/apps/<name>/job` saves it.

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

A requirement with `bullets` counts as covered when one of them is selected; one without falls back to shared tags. Master, Gaps groups every application's gaps by topic and ranks them by how many applications raised them.

## studios.yaml

Optional, in `data/` (gitignored), edited on the Listing tab. Your notes about a studio, matched on the tailor's studio name and given to drafts for the cover letter. Use only what it says; never invent a game the person played.

```yaml
- studio: Sample Studio
  notes: games of theirs you have played, people you know there, why you want to work with them
```

## Checks

CI (`.github/workflows/ci.yml`) runs ruff and `node --check`, the privacy check (`scripts/check_privacy.py`), `pytest -m "not typst"`, and on Windows the demo build, `check --example` and `pytest -m typst` (ATS text extraction). Before opening a PR, run `ruff check .`, `python scripts/check_privacy.py` (after staging, since it reads tracked files) and `python -m pytest`, with `pip install -r requirements-dev.txt` first. Add or update a test with every behavior change. After changing a template or the demo data, rebuild the demo with `python build.py --example build-all` and commit the PDFs; a test fails when they are stale. Tests use only the demo: the `home` fixture copies `examples/` into a temporary data home.

## Files

- `build.py`: merge, lint, compile, page fill, the impact check, and the data home (`find_home`). Each template ends with a `<layout>` metadata label (page count, where the content ends, the usable area), and `timeline.typ` adds a `<bullet-fit>` label per bullet (lines, last-line fill) and a `<wrap>` label for a role line or headline that wraps; `build.py` queries all metadata. Each real build records its fill in `build/fit/<app>.json` under the data home, which `check` compares against, and a hash of the resolved resume and letter data (`pdf_hashes`). The app marks PDFs out of date when those hashes differ from what the current files would produce, so a master edit that does not reach an application's pages leaves it current. PDFs with no recorded hash compare file times. A change to a template's own code does not count as out of date. Errors raise `BuildError`; `collect_warnings()` gathers warnings for the app.
- `studio/`: the editor app. `server.py` (standard library HTTP server, JSON API, 127.0.0.1 only), `draft.py` (headless Claude Code drafts), `send.py` (plain text for application forms), `workspace.py` (application folders, round-trip YAML merge, master history, snapshots, gap summary, studio notes, tracking events), `tracking.py` (event checks, board column, quiet and ghosted rules, stats), `static/` (one HTML page, plain JS and CSS, no build step; `tracker.js` is the home page board, history, Timeline and Stats).
- `templates/timeline.typ` (shared), `resume-games.typ`, `resume-inline.typ`: resumes grouped by company, so several roles at one company sit under one heading, each with its own dates (no company-wide span). `resume-inline` (the default) puts each game on its role line, skipping it on a role that shares the game of the role above, and repeating the company on every role after the first so a parser never reads a team name as the employer; `resume-games` adds a Games section with one undated line per game. Pick one with `template:` in `tailor.yaml`, in the app, or try one with `python build.py build <app> --template resume-games` (that trial PDF goes to `build/<app>/`, not the application folder). No template has a summary; an optional one-line headline sits under the name.
- `templates/cover-letter.typ`: imports its colors, margins and header (name, headline, contact line) from `timeline.typ`, so the letter matches `resume-games` and `resume-inline`.
- `docs/`: the GitHub Pages project page, served from `main` /docs with no build step (`index.html`, `assets/`, `img/`), plus the README screenshots. Screenshots come from the demo (`python build.py --example serve`); never use real data. Phrases meant to be public, like the author credit, go in `scripts/public-terms.txt` so the privacy check's `PRIVATE_TERMS` skip them.
- `templates/common.typ`: gray header band, fonts and page setup for the older `resume.typ` only. All templates read `sys.inputs.data` (resolved JSON in `build/`) and take the page size from its `paper` field.
- Keep resumes ATS friendly: single column, real text, no icons, standard section names, no multi-column rows outside the right-aligned dates, and Skills before Projects (a standard heading closes Experience, so parsers do not fold projects into the last job), section-heading letter spacing at 0.08em or less (wider spacing extracts as "E X P E R I E N C E"). Check with `pypdf`'s `extract_text()` after a template change. PDFs carry a title and author, and contact and project URLs are links.
