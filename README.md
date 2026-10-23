# DynamicResume

Keep all of your career history in one master file, then build a tailored one-page resume and a matching cover letter for each job in a few minutes. Paste a job listing, let Claude Code pick and order the bullets that match it, fine-tune the result in a local editor with a live page preview, and export PDFs that read cleanly in applicant tracking systems.

Built with [Typst](https://typst.app) and a small Python app. No server, no account: everything runs on your machine, and your data stays in gitignored files.

![The editor: listing requirements as chips above the bullet list, with a live one-page preview and fill meter on the right](docs/editor.png)

## Why

A strong resume for one job is a weak resume for another. Reordering bullets, rewording a line to match a listing's language, and trimming to one page by hand takes an hour per application and tends to drift: the wording you improved for one job never makes it back to the others.

DynamicResume splits the work in two:

- **One master file** (`data/master.yaml`) holds every position, bullet, skill and project you could ever show, more than fits on a page. Each bullet has an id, tags and a priority.
- **One small tailor file per job** (`applications/<studio>-<role>/tailor.yaml`) only says which bullets to show, in what order, plus any rewording for that listing. The master is never edited for one application.

Improving a bullet in the master improves it everywhere, and every application stays a few lines of YAML you can rebuild at any time.

## Features

**Drafting with Claude.** Paste a listing under New application and choose Create and draft with Claude. The app runs Claude Code headlessly in the repo with read-only tools. It reads the master and the listing, picks and orders bullets, writes a headline and a cover letter, breaks the listing into requirements, and lists anything the master cannot back up. Every bullet id it returns is checked against the master before anything is written.

**Requirement coverage.** Each requirement from the listing becomes a chip on the Resume tab, green when a selected bullet backs it up. Unselected bullets are ranked by how well they match the listing, so filling a gap is one click.

![The Listing tab: Claude's notes, the gaps the master cannot back up, and the editable requirement list](docs/listing.png)

**A live editor.** Tick bullets on and off, drag them into order, double-click to reword one for this application only, switch templates, and edit the cover letter, with the PDF preview rebuilding as you go. A fill meter shows how full the page is and how many lines are free.

**One page, enforced.** Every build reports the page count and how full the last page is, and warns when a resume runs past one page. The fix is always to cut or reword, never to shrink the font.

**Writing lint.** Builds flag em dashes and filler phrases ("leverage", "passionate about", "spearhead" and others) in resume and letter text.

**ATS-friendly output.** Single column, real text, standard section names, no icons, and each role's company repeated so autofill parsers never mistake a team name for an employer. Template changes are checked with `pypdf` text extraction. PDFs carry a title and author, and contact and project URLs are links.

**Matching cover letters.** Write paragraphs in Markdown. The letter shares the resume's header, colors and margins.

**Safe editing.** The app writes YAML with round-trip formatting, so comments and layout in your files survive. Every master save keeps the previous version, the app refuses to delete a bullet an application still uses, and snapshots zip everything before a redraft or delete. Edit the files in a text editor or with Claude at any time; the app notices within a couple of seconds and reloads.

## Quick start

You need Python 3 and the Typst CLI.

```
winget install Typst.Typst
pip install -r requirements.txt
```

Try it on the fictional demo data in `examples/`:

```
python build.py --example serve
```

That opens the editor at http://127.0.0.1:8765 with a sample application already drafted. Build PDFs writes the resume and cover letter into the application folder.

Drafting needs [Claude Code](https://claude.com/claude-code) installed and signed in (`claude` on your PATH). It uses your Claude Code login, so there is no API key to set up. Without it, the app still works; you pick the bullets yourself.

## Using it for real

1. Copy `examples/data/master.yaml` to `data/master.yaml` and replace it with your own history. Write more bullets than fit on a page, tag them, and give the strongest ones priority 1.
2. Run `python build.py serve`. Paste a job listing under New application and choose Create and draft with Claude.
3. Review the draft: check the requirement chips, swap bullets, reword where it helps, and fill the page.
4. Build PDFs, then check the build output says one page for both files.

Run `python build.py build master` to render the whole pool on several pages with each bullet's id, priority and tags, which makes the master easy to review.

You can also tailor without the app: make `applications/<studio>-<role>/` with `tailor.yaml`, `listing.md` and `cover-letter.md` (copy them from `examples/applications/`), then run `python build.py build <studio>-<role>`.

Personal rules for Claude, such as how to describe a project you can't name or which jobs to leave off, go in a gitignored `CLAUDE.local.md` at the repo root. Drafts follow it alongside `CLAUDE.md`.

## Commands

```
python build.py serve                 # editor app at http://127.0.0.1:8765
python build.py build <app-folder>    # one application, by name under applications/ or a path
python build.py build master          # the full pool, with ids, priorities and tags
python build.py build-all             # every application
python build.py snapshot [label]      # zip the master, applications and templates into snapshots/
```

Add `--example` to any command to use `examples/` instead of your own data. `build <app> --template <name>` tries another template without changing the application (the trial PDF goes to `build/<app>/`).

## How it works

```
data/master.yaml ─┐
                  ├─ build.py ─ resolved JSON ─ Typst template ─ PDF
tailor.yaml ──────┘   (merge, override, lint, measure the page)
```

`build.py` merges the master with an application's tailor file, applies overrides, lints the text and writes resolved JSON into `build/`. The Typst template reads that JSON and lays out the page, then ends with a metadata label (page count, where the content ends, the usable area) that `build.py` queries to report the fill.

The editor in `studio/` is a standard-library Python HTTP server bound to 127.0.0.1, with one HTML page of plain JavaScript and CSS and no build step. The app and the command line read and write the same files, so either works at any time.

## Templates

| Template | Layout |
|---|---|
| `resume-inline` (default) | Roles grouped by company, each game named on its role line |
| `resume-games` | Roles grouped by company, plus a Games section with one line per title |
| `resume` | The original layout with a gray header band |

Pick one with `template:` in `tailor.yaml` or the Template menu in the app. Fonts fall back from Calibri to Arial to Typst's built-in serif; change them in `templates/timeline.typ` (`common.typ` for `resume`).

## Project layout

```
build.py               merge, lint, compile, page fill
studio/                the editor app (server, Claude drafts, workspace and snapshots)
templates/             Typst resume and cover letter templates
examples/              fictional demo master and application
CLAUDE.md              schemas and the tailoring workflow, written for Claude and for you
data/, applications/   your master and applications (gitignored)
snapshots/, build/     backups and build output (gitignored)
```

The full `master.yaml`, `tailor.yaml` and `listing.yaml` schemas are in [CLAUDE.md](CLAUDE.md).

## Privacy

This is a public repository. `data/`, `applications/`, `Local/`, `snapshots/`, `build/`, `CLAUDE.local.md` and every PDF outside `examples/` are gitignored, so your career data, applications and personal rules never leave your machine. Anything in `examples/` is fictional.
