#!/usr/bin/env python3
"""Build tailored resume and cover letter PDFs from data/master.yaml.

  python build.py serve                the editor app in your browser (http://127.0.0.1:8765)
  python build.py build <app-folder>   one application (name or path)
  python build.py build master         full pool, multi-page, with tags
  python build.py build-all            every folder in applications/
  python build.py snapshot [label]     zip master, applications and templates into snapshots/
  python build.py check                rebuild every application into build/check/ and report page changes
  python build.py submit <app> [--date YYYY-MM-DD]   freeze the PDFs you sent; builds then skip it
  python build.py unsubmit <app>       undo submit so the application can be edited and rebuilt
  python build.py new "<studio>" "<role>" [--listing file|-]   start an application folder
  python build.py draft <app>          draft it with headless Claude Code, as the app does
  add --example to use examples/ (the public demo data) instead of your own

In a linked git worktree, your data (data/, applications/, Local/, snapshots/) is read from
the main checkout. Set DYNAMICRESUME_HOME to use another folder.
"""
import argparse
import calendar
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent


def find_home():
    """Where your own data lives: data/, applications/, Local/, snapshots/, CLAUDE.local.md.

    Usually this checkout. In a linked git worktree it is the main checkout, because those
    folders are gitignored and a worktree has none of its own (or a stale copy).
    DYNAMICRESUME_HOME overrides both."""
    env = os.environ.get("DYNAMICRESUME_HOME")
    if env:
        return Path(env).expanduser().resolve()
    dotgit = ROOT / ".git"
    if dotgit.is_file():  # a worktree's .git file reads "gitdir: <main>/.git/worktrees/<name>"
        m = re.match(r"gitdir:\s*(.+)", dotgit.read_text(encoding="utf-8").strip())
        if m:
            gitdir = Path(m.group(1).strip())
            gitdir = gitdir if gitdir.is_absolute() else (ROOT / gitdir).resolve()
            if gitdir.parent.name == "worktrees" and gitdir.parent.parent.name == ".git":
                return gitdir.parent.parent.parent.resolve()
    return ROOT


HOME = find_home()
TEMPLATES = ROOT / "templates"
DEFAULT_TEMPLATE = "resume-inline"
TAILOR_KEYS = {"target", "template", "headline", "games", "positions", "skills_first", "skill_groups",
               "projects", "overrides", "short", "cover_letter"}
BANNED = ["leverage", "passionate about", "drive innovation", "spearhead", "synergy", "cutting-edge", "excited to"]
SUBMITTED = "submitted"  # folder in an application that holds the PDFs as they were sent
EM_DASH = "—"
EN_DASH = "–"


class BuildError(Exception):
    pass


# ---------- helpers ----------

_sink = None


def warn(msg):
    if _sink is not None:
        _sink.append(msg)
    else:
        print(f"WARN: {msg}")


@contextmanager
def collect_warnings():
    """Collect warn() messages into a list instead of printing them."""
    global _sink
    prev, _sink = _sink, []
    try:
        yield _sink
    finally:
        _sink = prev


def find_typst():
    exe = shutil.which("typst")
    if exe:
        return exe
    pkgs = Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
    for p in pkgs.glob("Typst.Typst*/**/typst.exe"):
        return str(p)
    raise BuildError("typst not found. Install it (winget install Typst.Typst) and retry.")


def load_yaml(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def fmt_date(d):
    s = str(d)
    if s.lower() == "present":
        return "Present"
    m = re.match(r"^(\d{4})-(\d{1,2})", s)
    if not m:
        return s
    return f"{calendar.month_name[int(m.group(2))]} {m.group(1)}"


def date_range(start, end):
    return f"{fmt_date(start)} {EN_DASH} {fmt_date(end)}"


def short_date(d):
    s = str(d)
    if s.lower() == "present":
        return "Present"
    m = re.match(r"^(\d{4})-(\d{1,2})", s)
    if not m:
        return s
    return f"{calendar.month_abbr[int(m.group(2))]} {m.group(1)}"


def short_range(start, end):
    return f"{short_date(start)} {EN_DASH} {short_date(end)}"


def year_range(start, end):
    return f"{str(start)[:4]} {EN_DASH} {'Present' if str(end).lower() == 'present' else str(end)[:4]}"


def rel(p):
    """A path for messages: relative to this checkout or the data home, else absolute."""
    p = Path(p).resolve()
    for base in (ROOT, HOME):
        try:
            return p.relative_to(base).as_posix()
        except ValueError:
            pass
    return p.as_posix()


def slug(s):
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")


def lint(text, where):
    if EM_DASH in text:
        warn(f"em dash in {where}: {text[:70]!r}")
    low = text.lower()
    for phrase in BANNED:
        if phrase in low:
            warn(f"banned phrase '{phrase}' in {where}")


def walk_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from walk_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk_strings(v)


# ---------- resolve ----------

def validate_master(master):
    """Structural checks that resolve() does not catch on its own."""
    for key in ("basics", "positions"):
        if key not in master:
            raise BuildError(f"master is missing '{key}'")
    seen = {}
    for owner in master["positions"] + master.get("projects", []):
        if "id" not in owner:
            raise BuildError(f"a position or project has no id: {owner.get('company') or owner.get('name')}")
        for b in owner.get("bullets") or []:
            if not b.get("id") or not b.get("text"):
                raise BuildError(f"a bullet in {owner['id']} is missing its id or text")
            if b["id"] in seen:
                raise BuildError(f"bullet id '{b['id']}' is used in both {seen[b['id']]} and {owner['id']}")
            seen[b["id"]] = owner["id"]
        ids = {b["id"] for b in owner.get("bullets") or []}
        for b in owner.get("bullets") or []:
            v = b.get("variant_of")
            if v is not None and (v == b["id"] or v not in ids):
                raise BuildError(f"bullet '{b['id']}' has variant_of '{v}', which is not another bullet in {owner['id']}")
    for p in master["positions"]:
        for key in ("company", "title", "start", "end"):
            if key not in p:
                raise BuildError(f"position {p['id']} is missing '{key}'")


def pos_heading(p):
    h = p["company"]
    if p.get("product"):
        h += f" - {p['product']}"
    if p.get("engine"):
        h += f" ({p['engine']})"
    return h


def bullet_out(b):
    return {"id": b["id"], "text": b["text"], "tags": b.get("tags", []), "priority": b.get("priority", 3)}


def resolve(master, tailor, master_mode):
    """Merge master + tailor into the dict the Typst resume template reads."""
    validate_master(master)
    games_by_id = {g["id"]: g for g in master.get("games", [])}
    if master_mode:
        game_ids = list(games_by_id)
        pos_sel = {p["id"]: None for p in master["positions"]}
        skill_groups = None
        skills_first = []
        overrides = {}
        short_ids = set()
        project_sel = {p["id"]: None for p in master.get("projects", [])}
    else:
        for k in tailor:
            if k not in TAILOR_KEYS:
                warn(f"tailor.yaml key '{k}' is not used by the build")
        # An absent games list means all games; an empty one means none.
        game_ids = list(games_by_id) if tailor.get("games") is None else tailor["games"]
        pos_sel = {k: (v or {}).get("bullets", []) for k, v in (tailor.get("positions") or {}).items()}
        skill_groups = tailor.get("skill_groups")
        skills_first = tailor.get("skills_first") or []
        overrides = tailor.get("overrides") or {}
        short_ids = set(tailor.get("short") or [])
        raw = tailor.get("projects") or []
        project_sel = {k: None for k in raw} if isinstance(raw, list) else {k: (v or {}).get("bullets") for k, v in raw.items()}

    used_overrides, used_short = set(), set()
    all_pos = {p["id"]: p for p in master["positions"]}
    for pid in pos_sel:
        if pid not in all_pos:
            raise BuildError(f"unknown position id '{pid}' in tailor.yaml")

    def pick(bullets, ids, owner):
        by_id = {b["id"]: b for b in bullets}
        chosen = bullets if ids is None else []
        if ids is not None:
            for i in ids:
                if i not in by_id:
                    raise BuildError(f"bullet '{i}' not found in {owner}")
                chosen.append(by_id[i])
        if not master_mode:
            on = {b["id"] for b in chosen}
            for b in chosen:
                if b.get("variant_of") in on:
                    raise BuildError(f"'{b['id']}' is another version of '{b['variant_of']}' in {owner}; "
                                     "select one of them, not both")
        out = []
        for b in chosen:
            o = bullet_out(b)
            if master_mode:
                o["meta"] = True
            short = b["id"] in short_ids and b.get("short")
            if short:
                used_short.add(b["id"])
            if b["id"] in overrides:  # an override beats the short text
                o["text"] = overrides[b["id"]]
                used_overrides.add(b["id"])
            elif short:
                o["text"] = b["short"]
            out.append(o)
        return out

    positions = []
    for p in master["positions"]:  # master order = reverse chronological
        if p["id"] not in pos_sel:
            continue
        positions.append({
            "id": p["id"], "heading": pos_heading(p), "title": p["title"], "team": p.get("team", ""),
            "company": p["company"], "engine": p.get("engine", ""),
            "game": games_by_id.get(p.get("game"), {}).get("name", p.get("product", "")),
            "location": p.get("location", ""), "dates": date_range(p["start"], p["end"]),
            "dates_short": short_range(p["start"], p["end"]),
            "start": str(p["start"]), "end": str(p["end"]),
            "bullets": pick(p.get("bullets") or [], pos_sel[p["id"]], f"position {p['id']}"),
        })

    # Consecutive positions at one company become a single group; each role keeps its own dates.
    groups = []
    for pos in positions:
        if groups and groups[-1]["company"] == pos["company"]:
            groups[-1]["roles"].append(pos)
        else:
            groups.append({"company": pos["company"], "location": pos["location"], "roles": [pos]})

    engine_by_game = {}
    for p in master["positions"]:
        if p.get("game") and p.get("engine"):
            engine_by_game.setdefault(p["game"], (p["engine"], p["company"]))

    games = []
    for gid in game_ids:
        if gid not in games_by_id:
            raise BuildError(f"unknown game id '{gid}' in tailor.yaml")
        g = games_by_id[gid]
        engine, company = engine_by_game.get(gid, ("", ""))
        games.append({
            "name": g["name"], "dates": date_range(g["start"], g["end"]),
            "dates_short": short_range(g["start"], g["end"]), "engine": engine, "company": company,
        })

    skills = []
    for g in master.get("skills", []):
        if skill_groups is not None and g["group"] not in skill_groups:
            continue
        items = list(g["items"])
        front = [i for i in skills_first if i in items]
        skills.append({"group": g["group"], "items": front + [i for i in items if i not in front]})
    if skill_groups:
        skills.sort(key=lambda s: skill_groups.index(s["group"]))
    for s in skills_first:
        if not any(s in g["items"] for g in master.get("skills", [])):
            warn(f"skills_first item '{s}' is not in master skills")

    education = [{
        "school": e["school"], "credential": e.get("credential", ""),
        "location": e.get("location", ""), "dates": date_range(e["start"], e["end"]),
        "years": year_range(e["start"], e["end"]),
    } for e in master.get("education", [])]

    projects = []
    all_projects = {pr["id"]: pr for pr in master.get("projects", [])}
    for pid in project_sel:
        if pid not in all_projects:
            raise BuildError(f"unknown project id '{pid}' in tailor.yaml")
    for pr in master.get("projects", []):
        if pr["id"] not in project_sel:
            continue
        ids = project_sel[pr["id"]]
        projects.append({
            "name": pr["name"], "url": pr.get("url"), "summary": pr.get("summary"),
            "bullets": pick(pr.get("bullets") or [], ids, f"project {pr['id']}"),
        })

    for k in overrides:
        if k not in used_overrides:
            warn(f"override '{k}' does not match any selected bullet")
    for k in sorted(short_ids - used_short):
        warn(f"short '{k}' does not match a selected bullet that has short text")

    return {
        "basics": master["basics"], "headline": headline(master, tailor), "games": games,
        "positions": positions, "groups": groups, "skills": skills, "education": education,
        "projects": projects, "meta": master_mode,
    }


def headline(master, tailor):
    """The line under the name: the application's own, else the master's default, else none."""
    return (tailor.get("headline") or master["basics"].get("headline") or "").strip()


def resume_data(master, tailor):
    data = resolve(master, tailor, False)
    for s in walk_strings(data):
        lint(s, "resume")
    return data


def letter_data(master, tailor, text):
    cl = tailor.get("cover_letter") or {}
    paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    data = {
        "basics": master["basics"], "headline": headline(master, tailor), "date": cl.get("date"),
        "greeting": cl.get("greeting") or "Dear Hiring Team,",
        "closing": cl.get("closing") or "Sincerely,", "paragraphs": paragraphs,
    }
    for s in walk_strings(data):
        lint(s, "cover letter")
    return data


# ---------- typst ----------

def templates():
    return sorted(p.stem for p in TEMPLATES.glob("resume*.typ"))


def pick_template(tailor, override=None):
    name = override or tailor.get("template") or DEFAULT_TEMPLATE
    if not (TEMPLATES / f"{name}.typ").exists():
        raise BuildError(f"no template '{name}'. Available: {', '.join(templates())}")
    return name


def typst_args(typst, template, data_path, extra):
    rel = "/" + data_path.relative_to(ROOT).as_posix()
    return [typst, *extra, "--root", str(ROOT), "--input", f"data={rel}", str(TEMPLATES / template)]


def render(typst, template, data, out, work_dir, name):
    """Compile `template` with `data` to `out` (PDF, or SVG with a {p} page pattern).

    Returns the template's <layout> metadata (page count and where the content ends) plus
    what it measured: "bullets" (id -> lines and last-line fill) and "wraps" (lines that
    should fit on one line but do not)."""
    work_dir.mkdir(parents=True, exist_ok=True)
    data_path = work_dir / f"{name}.json"
    data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    ccmd = typst_args(typst, template, data_path, ["compile"]) + [str(out)]
    qcmd = typst_args(typst, template, data_path, ["query"]) + ["metadata"]
    run = lambda cmd: subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    with ThreadPoolExecutor(2) as ex:
        c, q = ex.submit(run, ccmd), ex.submit(run, qcmd)
        c, q = c.result(), q.result()
    if c.returncode != 0:
        raise BuildError(f"typst failed for {template}:\n{c.stderr}")
    try:
        items = json.loads(q.stdout)
    except ValueError:
        warn(f"could not read layout for {template}: {q.stderr.strip()[:120]}")
        return {}
    layout, bullets, wraps = {}, {}, []
    for it in items:
        label, v = it.get("label"), it.get("value")
        if label == "<layout>":
            layout = dict(v)
        elif label == "<bullet-fit>":
            bullets[v["id"]] = {"lines": int(v["lines"]), "last": round(v["last"], 2)}
        elif label == "<wrap>":
            wraps.append(v)
    return {**layout, "bullets": bullets, "wraps": wraps}


LINE_PT = 10.5  # measured: a new one-line bullet adds ~10.8pt, a wrapped line ~10.3pt
SHORT_LAST = 0.3  # a wrapped bullet whose last line fills less than this share of the width


def fill(layout):
    """Page count, how full the last page is, roughly how many lines are free (or sit on the
    extra page), and the template's per-bullet measurements."""
    if "pages" not in (layout or {}):
        return {"pages": None, "fill": None, "free_pt": None, "lines_free": None, "spill_lines": None,
                "bullets": {}, "wraps": []}
    used, room = layout["end"] - layout["top"], layout["limit"] - layout["top"]
    free = max(0.0, layout["limit"] - layout["end"])
    return {"pages": layout["pages"], "fill": round(min(1.0, used / room), 3),
            "free_pt": round(free, 1), "lines_free": int(free // LINE_PT),
            "spill_lines": math.ceil(used / LINE_PT) if layout["pages"] > 1 else 0,
            "bullets": layout.get("bullets", {}), "wraps": layout.get("wraps", [])}


def describe(f):
    if f["pages"] is None:
        return "page count unknown"
    if f["pages"] > 1:
        return f"{f['pages']} pages, about {f['spill_lines']} lines on page {f['pages']}"
    return f"1 page, last page {round(f['fill'] * 100)}% full"


def fit_warnings(f):
    """Lines the template found wrapping that should fit on one line."""
    return [f"{w['what']} wraps to a second line: {w['text']}" for w in f.get("wraps") or []]


def short_last_lines(f, limit=6):
    """Wrapped bullets whose last line is nearly empty, emptiest first: trimming a few
    words from one of these saves a whole line."""
    tight = [(i, b) for i, b in (f.get("bullets") or {}).items() if b["lines"] > 1 and b["last"] < SHORT_LAST]
    return sorted(tight, key=lambda x: x[1]["last"])[:limit]


# ---------- commands ----------

def workspace(example):
    base = ROOT / "examples" if example else HOME
    return base / "data" / "master.yaml", base / "applications"


def build_master(typst, example):
    master_path, _ = workspace(example)
    master = load_yaml(master_path)
    data = resolve(master, {}, True)
    for s in walk_strings(data):
        lint(s, "master")
    out_dir = ROOT / "build" / "master"
    out = out_dir / f"{slug(master['basics']['name'])}_Master.pdf"
    f = fill(render(typst, f"{DEFAULT_TEMPLATE}.typ", data, out, out_dir, "resume"))
    print(f"OK: {rel(out)} ({f['pages']} page{'s' if f['pages'] != 1 else ''})")


def find_app(app_arg, example):
    _, apps_dir = workspace(example)
    app = Path(app_arg)
    if not app.is_dir():
        app = apps_dir / app_arg
    if not app.is_dir():
        raise BuildError(f"application folder not found: {app_arg}")
    return app.resolve()


def app_folders(example):
    _, apps_dir = workspace(example)
    return sorted(p.resolve() for p in apps_dir.glob("*") if (p / "tailor.yaml").exists())


def submission(app):
    """The application's submitted/submitted.yaml (date, files), or None if it was not submitted."""
    p = app / SUBMITTED / "submitted.yaml"
    return load_yaml(p) if p.exists() else None


def output_names(master, tailor, app):
    studio = slug((tailor.get("target") or {}).get("studio") or app.name)
    name = slug(master["basics"]["name"])
    return f"{name}_Resume_{studio}.pdf", f"{name}_Cover_Letter_{studio}.pdf"


def fit_path(app, example):
    """Where the last real build of an application recorded its page fill. It sits with the
    data, not the checkout, so the impact check compares against the PDFs you actually have."""
    base = ROOT / "build" / "fit-example" if example else HOME / "build" / "fit"
    return base / f"{app.name}.json"


def brief(f):
    return None if not f else {"pages": f["pages"], "fill": f["fill"], "spill_lines": f.get("spill_lines")}


def last_fit(app, example):
    p = fit_path(app, example)
    try:
        return brief(json.loads(p.read_text(encoding="utf-8")).get("resume"))
    except (OSError, ValueError):
        return None


def build_app(typst, app, example, template=None, out_dir=None):
    """Build one application's PDFs into its folder. A --template trial build goes to
    build/<app>/, and `out_dir` (the impact check) takes both PDFs instead, so the
    application folder only ever holds the real pair. Returns what was written."""
    sub = submission(app)
    if sub and not (template or out_dir):
        raise BuildError(f"{app.name} was submitted on {sub.get('date')}, so its PDFs are frozen. "
                         f"Run 'python build.py unsubmit {app.name}' to edit and rebuild it.")
    master_path, _ = workspace(example)
    master = load_yaml(master_path)
    tailor = load_yaml(app / "tailor.yaml")
    work = out_dir or ROOT / "build" / app.name
    dest = out_dir or app
    resume_name, letter_name = output_names(master, tailor, app)

    data = resume_data(master, tailor)
    tpl = pick_template(tailor, template)
    out = (work / resume_name.replace(".pdf", f"_{tpl}.pdf")) if template else dest / resume_name
    rf = fill(render(typst, f"{tpl}.typ", data, out, work, f"resume-{tpl}" if template else "resume"))
    if rf["pages"] and rf["pages"] > 1:
        warn(f"RESUME IS {rf['pages']} PAGES. Cut about {rf['spill_lines']} lines in tailor.yaml.")
    for w in fit_warnings(rf):
        warn(w)
    result = {"resume": out, "resume_fill": rf, "letter": None, "letter_fill": None}
    if template:
        return result

    letter = app / "cover-letter.md"
    if not letter.exists() or not letter.read_text(encoding="utf-8").strip():
        warn("no cover-letter.md, skipping cover letter")
    else:
        ldata = letter_data(master, tailor, letter.read_text(encoding="utf-8"))
        out = dest / letter_name
        lf = fill(render(typst, "cover-letter.typ", ldata, out, work, "cover-letter"))
        if lf["pages"] and lf["pages"] > 1:
            warn(f"cover letter is {lf['pages']} pages")
        for w in fit_warnings(lf):
            warn(w)
        result.update(letter=out, letter_fill=lf)
    if not out_dir:
        p = fit_path(app, example)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"built": time.strftime("%Y-%m-%d %H:%M"), "resume": rf,
                                 "letter": result["letter_fill"]}, indent=2), encoding="utf-8")
    return result


def print_build(app, example, template=None):
    print(f"Building {app.name}")
    result = build_app(find_typst(), app, example, template)
    rf = result["resume_fill"]
    print(f"  resume: {rel(result['resume'])} ({describe(rf)})")
    tight = short_last_lines(rf)
    if tight and (rf["pages"] or 0) >= 1 and ((rf["pages"] or 0) > 1 or (rf["fill"] or 0) >= 0.9):
        print("  short last lines (trim a few words to save a line): "
              + ", ".join(f"{i} {round(b['last'] * 100)}%" for i, b in tight))
    if result["letter"]:
        print(f"  letter: {rel(result['letter'])} ({describe(result['letter_fill'])})")


def check_apps(typst, example):
    """Rebuild every unsubmitted application into build/check/ (never its own folder) and
    compare each resume with its last real build. One row per application."""
    rows = []
    for app in app_folders(example):
        if submission(app):
            continue
        row = {"name": app.name, "before": last_fit(app, example), "after": None, "error": None}
        with collect_warnings() as w:
            try:
                r = build_app(typst, app, example, out_dir=ROOT / "build" / "check" / app.name)
                row["after"] = brief(r["resume_fill"])
            except BuildError as e:
                row["error"] = str(e)
        row["warnings"] = [x for x in w if not x.startswith("RESUME IS")]
        a, b = row["after"], row["before"]
        row["over"] = bool(a and (a["pages"] or 0) > 1)
        row["changed"] = bool(row["error"] or not b or not a or a["pages"] != b["pages"]
                              or abs((a["fill"] or 0) - (b["fill"] or 0)) >= 0.005)
        rows.append(row)
    return rows


def fit_label(f):
    if not f:
        return "no earlier build"
    if f["pages"] is None:
        return "unknown"
    if f["pages"] > 1:
        return f"{f['pages']} pages (~{f['spill_lines']} lines over)"
    return f"1 page, {round(f['fill'] * 100)}%"


def print_check(rows):
    print(f"Checking {len(rows)} application{'s' if len(rows) != 1 else ''} against their last build "
          "(output in build/check/; submitted ones are skipped)")
    for r in rows:
        after = f"ERROR: {r['error']}" if r["error"] else fit_label(r["after"])
        flag = "  OVER ONE PAGE" if r["over"] else "" if r["changed"] else "  (unchanged)"
        print(f"  {r['name']}: {fit_label(r['before'])} -> {after}{flag}")
        for w in r["warnings"]:
            print(f"      {w}")
    return not any(r["over"] or r["error"] for r in rows)


def run_draft(example, name):
    """Run the app's headless Claude draft from the command line, printing its progress."""
    import threading
    from studio.draft import Drafts
    from studio.workspace import Workspace
    drafts = Drafts(Workspace(example), threading.Lock(), ROOT / "build" / ("studio-example" if example else "studio"))
    drafts.start(name)
    seen = 0
    while True:
        st = drafts.status(name)
        for line in st["log"][seen:]:
            print(f"  {line}")
        seen = len(st["log"])
        if st["state"] != "running":
            break
        time.sleep(1)
    if st["state"] != "done":
        raise BuildError(st.get("error") or "the draft did not finish")
    res = st["result"]
    print(f"Notes: {res['notes']}")
    for g in res["gaps"]:
        print(f"  gap: {g['text'] if isinstance(g, dict) else g}")
    for w in res["warnings"]:
        print(f"WARN: {w}")


def main():
    # --example works before or after the subcommand.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--example", action="store_true", default=argparse.SUPPRESS,
                        help="use examples/ instead of data/ and applications/")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                 parents=[common])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", parents=[common], help="build one application folder, or 'master'")
    b.add_argument("target")
    b.add_argument("--template", help="try another resume template; output goes to build/<app>/")
    sub.add_parser("build-all", parents=[common], help="build every application")
    sub.add_parser("check", parents=[common], help="report how the master's current state changes each application")
    s = sub.add_parser("serve", parents=[common], help="open the editor app in your browser")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-browser", action="store_true", help="do not open a browser tab")
    n = sub.add_parser("snapshot", parents=[common], help="zip your data, applications and templates")
    n.add_argument("label", nargs="?", default="")
    u = sub.add_parser("submit", parents=[common], help="freeze an application's PDFs as sent")
    u.add_argument("target")
    u.add_argument("--date", help="the day you sent it, YYYY-MM-DD (default today)")
    x = sub.add_parser("unsubmit", parents=[common], help="make a submitted application editable again")
    x.add_argument("target")
    w = sub.add_parser("new", parents=[common], help="start an application folder")
    w.add_argument("studio")
    w.add_argument("role")
    w.add_argument("--listing", help="a file with the job listing, or - to read it from stdin")
    d = sub.add_parser("draft", parents=[common], help="draft an application with headless Claude Code")
    d.add_argument("target")
    d.add_argument("--no-build", action="store_true", help="do not build the PDFs after drafting")
    args = ap.parse_args()
    example = getattr(args, "example", False)
    if HOME != ROOT and not example:
        print(f"Using data in {HOME}")

    try:
        if args.cmd == "serve":
            from studio.server import serve
            serve(example, args.port, open_browser=not args.no_browser)
            return
        if args.cmd == "snapshot":
            from studio.workspace import Workspace
            snap = Workspace(example).create_snapshot(args.label)
            print(f"OK: {snap['path']} ({snap['files']} files)")
            return
        if args.cmd in ("submit", "unsubmit"):
            from studio.workspace import Workspace
            ws, name = Workspace(example), find_app(args.target, example).name
            if args.cmd == "submit":
                r = ws.submit_app(name, args.date)
                print(f"OK: {name} submitted on {r['date']}. Frozen copies are in {r['path']}")
                if r["stale"]:
                    print("WARN: the PDFs were older than your latest edits; they were frozen as they are.")
            else:
                r = ws.unsubmit_app(name)
                print(f"OK: {name} can be edited again." + (f" The sent PDFs are kept in {r['kept']}" if r["kept"] else ""))
            return
        if args.cmd == "new":
            from studio.workspace import Workspace
            listing = ""
            if args.listing == "-":
                listing = sys.stdin.read()
            elif args.listing:
                listing = Path(args.listing).read_text(encoding="utf-8")
            name = Workspace(example).create_app(args.studio, args.role, listing)
            _, apps_dir = workspace(example)
            print(f"OK: {rel(apps_dir / name)}" + ("" if listing.strip() else " (paste the listing into listing.md)"))
            print(f"Next: python build.py{' --example' if example else ''} draft {name}")
            return
        if args.cmd == "draft":
            app = find_app(args.target, example)
            print(f"Drafting {app.name} with Claude Code (usually one to three minutes)")
            run_draft(example, app.name)
            if not args.no_build:
                print_build(app, example)
            return
        typst = find_typst()
        if args.cmd == "build":
            if args.target == "master":
                build_master(typst, example)
            else:
                print_build(find_app(args.target, example), example, args.template)
        elif args.cmd == "check":
            if not print_check(check_apps(typst, example)):
                sys.exit(1)
        else:
            folders = app_folders(example)
            if not folders:
                raise BuildError(f"No applications with tailor.yaml in {rel(workspace(example)[1])}")
            for f in folders:
                sub = submission(f)
                if sub:
                    print(f"Skipping {f.name} (submitted {sub.get('date')})")
                    continue
                print_build(f, example)
    except BuildError as e:
        sys.exit(f"ERROR: {e}")


if __name__ == "__main__":
    sys.modules.setdefault("build", sys.modules[__name__])  # studio/ imports build: share one BuildError
    main()
