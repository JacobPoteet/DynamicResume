# DynamicResume

Keep one master file of career data, then build a tailored one-page resume and matching cover letter for each job. A replacement for Resumake, using [Typst](https://typst.app) and a small Python script.

## Setup

```
winget install Typst.Typst      # or any other way to get the typst CLI
pip install -r requirements.txt
```

## Try the demo

```
python build.py --example serve
```

That opens the editor on the fictional data in `examples/`: tick bullets on and off, drag them into order, reword one for a single application, switch templates, and watch the page preview and fill meter update. `Build PDFs` writes the resume and cover letter into the application folder.

The same works from the command line:

```
python build.py --example build master
python build.py --example build-all
```

## Use it for real

1. Copy `examples/data/master.yaml` to `data/master.yaml` and replace it with your own career data. Include more bullets than fit on a page.
2. `python build.py serve`, paste a job listing under New application, and adjust the result until the page is full and says what you want.
3. Or by hand: make `applications/<studio>-<role>/` with `tailor.yaml`, `listing.md`, and `cover-letter.md` (copy from `examples/applications/`), then `python build.py build <studio>-<role>`.
4. `python build.py build master` renders the whole pool with bullet ids, priorities and tags so you can review it.
5. `python build.py snapshot` (or Take snapshot in the app) zips your data before a big change.

`data/`, `applications/`, `snapshots/` and PDFs are gitignored, so personal data stays local. The schema and tailoring workflow are documented in [CLAUDE.md](CLAUDE.md), which is written so an AI assistant can tailor applications for you.

Fonts: Calibri, then Arial, then Typst's built-in serif. Edit `templates/timeline.typ` to change them (`common.typ` for the older `resume.typ`).
