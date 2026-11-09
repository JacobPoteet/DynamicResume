---
paths:
  - "build.py"
  - "studio/**"
  - "templates/**"
  - "scripts/**"
  - "docs/**"
  - "tests/**"
---

# Source files

- `build.py`: merge, lint, compile, page fill, the impact check, and the data home (`find_home`). Each template ends with a `<layout>` metadata label (page count, where the content ends, the usable area), and `timeline.typ` adds a `<bullet-fit>` label per bullet (lines, last-line fill) and a `<wrap>` label for a role line or headline that wraps; `build.py` queries all metadata. Each real build records its fill in `build/fit/<app>.json` under the data home, which `check` compares against, and a hash of the resolved resume and letter data (`pdf_hashes`). The app marks PDFs out of date when those hashes differ from what the current files would produce, so a master edit that does not reach an application's pages leaves it current. PDFs with no recorded hash compare file times. A change to a template's own code does not count as out of date. Errors raise `BuildError`; `collect_warnings()` gathers warnings for the app.
- `studio/`: the editor app. `server.py` (standard library HTTP server, JSON API, 127.0.0.1 only), `draft.py` (headless Claude Code drafts), `fit.py` (fitting a resume to the page), `changes.py` (the differences between two versions), `send.py` (plain text for application forms), `ics.py` (calendar files), `workspace.py` (application folders, round-trip YAML merge, master history, snapshots, gap summary, studio notes, tracking events), `tracking.py` (event checks, board column, quiet and ghosted rules, what needs attention, stats), `static/` (one HTML page, plain JS and CSS, no build step; `tracker.js` is the home page board, history, Timeline and Stats).
- `templates/timeline.typ` (shared), `resume-games.typ`, `resume-inline.typ`: resumes grouped by company, so several roles at one company sit under one heading, each with its own dates (no company-wide span). `resume-inline` (the default) puts each game on its role line, skipping it on a role that shares the game of the role above, and repeating the company on every role after the first so a parser never reads a team name as the employer; `resume-games` adds a Games section with one undated line per game. Pick one with `template:` in `tailor.yaml`, in the app, or try one with `python build.py build <app> --template resume-games` (that trial PDF goes to `build/<app>/`, not the application folder). No template has a summary; an optional one-line headline sits under the name.
- `templates/cover-letter.typ`: imports its colors, margins and header (name, headline, contact line) from `timeline.typ`, so the letter matches `resume-games` and `resume-inline`.
- `docs/`: the GitHub Pages project page, served from `main` /docs with no build step (`index.html`, `assets/`, `img/`), plus the README screenshots. Screenshots come from the demo (`python build.py --example serve`); never use real data. Phrases meant to be public, like the author credit, go in `scripts/public-terms.txt` so the privacy check's `PRIVATE_TERMS` skip them.
- `templates/common.typ`: gray header band, fonts and page setup for the older `resume.typ` only. All templates read `sys.inputs.data` (resolved JSON in `build/`) and take the page size from its `paper` field.
- Keep resumes ATS friendly: single column, real text, no icons, standard section names, no multi-column rows outside the right-aligned dates, and Skills before Projects (a standard heading closes Experience, so parsers do not fold projects into the last job), section-heading letter spacing at 0.08em or less (wider spacing extracts as "E X P E R I E N C E"). Check with `pypdf`'s `extract_text()` after a template change. PDFs carry a title and author, and contact and project URLs are links.
