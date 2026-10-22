#!/usr/bin/env python3
"""Build tailored resume and cover letter PDFs from data/master.yaml.

  python build.py serve                the editor app in your browser (http://127.0.0.1:8765)
  python build.py build <app-folder>   one application (name or path)
  python build.py build master         full pool, multi-page, with tags
  python build.py build-all            every folder in applications/
  python build.py snapshot [label]     zip master, applications and templates into snapshots/
  add --example to use examples/ (the public demo data) instead of your own
"""
import argparse
import calendar
import json
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
TEMPLATES = ROOT / "templates"
DEFAULT_TEMPLATE = "resume-inline"
TAILOR_KEYS = {"target", "template", "headline", "games", "positions", "skills_first", "skill_groups",
               "projects", "overrides", "cover_letter"}
BANNED = ["leverage", "passionate about", "drive innovation", "spearhead", "synergy", "cutting-edge", "excited to"]
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
        raw = tailor.get("projects") or []
        project_sel = {k: None for k in raw} if isinstance(raw, list) else {k: (v or {}).get("bullets") for k, v in raw.items()}

    used_overrides = set()
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
        out = []
        for b in chosen:
            o = bullet_out(b)
            if master_mode:
                o["meta"] = True
            if b["id"] in overrides:
                o["text"] = overrides[b["id"]]
                used_overrides.add(b["id"])
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

    Returns the template's <layout> metadata: page count and where the content ends."""
    work_dir.mkdir(parents=True, exist_ok=True)
    data_path = work_dir / f"{name}.json"
    data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    ccmd = typst_args(typst, template, data_path, ["compile"]) + [str(out)]
    qcmd = typst_args(typst, template, data_path, ["query"]) + ["<layout>", "--field", "value", "--one"]
    run = lambda cmd: subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    with ThreadPoolExecutor(2) as ex:
        c, q = ex.submit(run, ccmd), ex.submit(run, qcmd)
        c, q = c.result(), q.result()
    if c.returncode != 0:
        raise BuildError(f"typst failed for {template}:\n{c.stderr}")
    try:
        return json.loads(q.stdout)
    except ValueError:
        warn(f"could not read layout for {template}: {q.stderr.strip()[:120]}")
        return {}


LINE_PT = 10.5  # measured: a new one-line bullet adds ~10.8pt, a wrapped line ~10.3pt


def fill(layout):
    """Page count, how full the last page is, and roughly how many lines are free."""
    if not layout:
        return {"pages": None, "fill": None, "free_pt": None, "lines_free": None}
    used, room = layout["end"] - layout["top"], layout["limit"] - layout["top"]
    free = max(0.0, layout["limit"] - layout["end"])
    return {"pages": layout["pages"], "fill": round(min(1.0, used / room), 3),
            "free_pt": round(free, 1), "lines_free": int(free // LINE_PT)}


def describe(f):
    if f["pages"] is None:
        return "page count unknown"
    s = f"{f['pages']} page{'s' if f['pages'] != 1 else ''}"
    return s + f", last page {round(f['fill'] * 100)}% full"


# ---------- commands ----------

def workspace(example):
    base = ROOT / "examples" if example else ROOT
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
    print(f"OK: {out.relative_to(ROOT)} ({f['pages']} pages)")


def find_app(app_arg, example):
    _, apps_dir = workspace(example)
    app = Path(app_arg)
    if not app.is_dir():
        app = apps_dir / app_arg
    if not app.is_dir():
        raise BuildError(f"application folder not found: {app_arg}")
    return app.resolve()


def output_names(master, tailor, app):
    studio = slug((tailor.get("target") or {}).get("studio") or app.name)
    name = slug(master["basics"]["name"])
    return f"{name}_Resume_{studio}.pdf", f"{name}_Cover_Letter_{studio}.pdf"


def build_app(typst, app, example, template=None):
    """Build one application's PDFs. A --template trial build goes to build/<app>/ so the
    application folder only ever holds the real pair. Returns what was written."""
    master_path, _ = workspace(example)
    master = load_yaml(master_path)
    tailor = load_yaml(app / "tailor.yaml")
    work = ROOT / "build" / app.name
    resume_name, letter_name = output_names(master, tailor, app)

    data = resume_data(master, tailor)
    tpl = pick_template(tailor, template)
    out = (work / resume_name.replace(".pdf", f"_{tpl}.pdf")) if template else app / resume_name
    rf = fill(render(typst, f"{tpl}.typ", data, out, work, f"resume-{tpl}" if template else "resume"))
    if rf["pages"] and rf["pages"] > 1:
        warn(f"RESUME IS {rf['pages']} PAGES. Trim bullets or skills in tailor.yaml.")
    result = {"resume": out, "resume_fill": rf, "letter": None, "letter_fill": None}

    letter = app / "cover-letter.md"
    if template:
        return result
    if not letter.exists() or not letter.read_text(encoding="utf-8").strip():
        warn("no cover-letter.md, skipping cover letter")
        return result
    ldata = letter_data(master, tailor, letter.read_text(encoding="utf-8"))
    out = app / letter_name
    lf = fill(render(typst, "cover-letter.typ", ldata, out, work, "cover-letter"))
    if lf["pages"] and lf["pages"] > 1:
        warn(f"cover letter is {lf['pages']} pages")
    result.update(letter=out, letter_fill=lf)
    return result


def print_build(app, example, template=None):
    print(f"Building {app.name}")
    result = build_app(find_typst(), app, example, template)
    print(f"  resume: {result['resume'].relative_to(ROOT)} ({describe(result['resume_fill'])})")
    if result["letter"]:
        print(f"  letter: {result['letter'].relative_to(ROOT)} ({describe(result['letter_fill'])})")


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
    s = sub.add_parser("serve", parents=[common], help="open the editor app in your browser")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-browser", action="store_true", help="do not open a browser tab")
    n = sub.add_parser("snapshot", parents=[common], help="zip your data, applications and templates")
    n.add_argument("label", nargs="?", default="")
    args = ap.parse_args()
    example = getattr(args, "example", False)

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
        typst = find_typst()
        if args.cmd == "build":
            if args.target == "master":
                build_master(typst, example)
            else:
                print_build(find_app(args.target, example), example, args.template)
        else:
            _, apps_dir = workspace(example)
            folders = sorted(p for p in apps_dir.glob("*") if (p / "tailor.yaml").exists())
            if not folders:
                raise BuildError(f"No applications with tailor.yaml in {apps_dir}")
            for f in folders:
                print_build(f.resolve(), example)
    except BuildError as e:
        sys.exit(f"ERROR: {e}")


if __name__ == "__main__":
    main()
