# DynamicResume

Keep one master file of career data, then build a tailored one-page resume and matching cover letter for each job. A replacement for Resumake, using [Typst](https://typst.app) and a small Python script.

## Setup

```
winget install Typst.Typst      # or any other way to get the typst CLI
pip install -r requirements.txt
```

## Try the demo

```
python build.py --example build master
python build.py --example build-all
```

The demo uses fictional data in `examples/`. Output PDFs land in the application folder, and the full-pool render goes to `build/master/`.

## Use it for real

1. Copy `examples/data/master.yaml` to `data/master.yaml` and replace it with your own career data. Include more bullets than fit on a page.
2. For each job, make `applications/<studio>-<role>/` with `tailor.yaml`, `listing.md`, and `cover-letter.md` (copy from `examples/applications/`).
3. `python build.py build <studio>-<role>`. The build warns if the resume runs past one page.
4. `python build.py build master` renders the whole pool with bullet ids, priorities and tags so you can review it.

`data/`, `applications/`, and PDFs are gitignored, so personal data stays local. The schema and tailoring workflow are documented in [CLAUDE.md](CLAUDE.md), which is written so an AI assistant can tailor applications for you.

Fonts: Calibri, then Arial, then Typst's built-in serif. Edit `templates/common.typ` to change them.
