#!/usr/bin/env python3
"""Build tailored resume and cover letter PDFs from data/master.yaml.

  python build.py build <app-folder>   one application (name or path)
  python build.py build master         full pool, multi-page, with tags
  python build.py build-all            every folder in applications/
  add --example to use examples/ (the public demo data) instead of your own
"""
import argparse
import calendar
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
BANNED = ["leverage", "passionate about", "drive innovation", "spearhead", "synergy", "cutting-edge"]
EM_DASH = "—"
EN_DASH = "–"


# ---------- helpers ----------

def find_typst():
    exe = shutil.which("typst")
    if exe:
        return exe
    pkgs = Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
    for p in pkgs.glob("Typst.Typst*/**/typst.exe"):
        return str(p)
    sys.exit("ERROR: typst not found. Install it (winget install Typst.Typst) and retry.")


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


def warn(msg):
    print(f"WARN: {msg}")


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
    games_by_id = {g["id"]: g for g in master.get("games", [])}
    if master_mode:
        game_ids = list(games_by_id)
        pos_sel = {p["id"]: None for p in master["positions"]}
        skill_groups = None
        skills_first = []
        overrides = {}
        project_sel = {p["id"]: None for p in master.get("projects", [])}
    else:
        game_ids = tailor.get("games") or list(games_by_id)
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
            sys.exit(f"ERROR: unknown position id '{pid}' in tailor.yaml")

    def pick(bullets, ids, owner):
        by_id = {b["id"]: b for b in bullets}
        chosen = bullets if ids is None else []
        if ids is not None:
            for i in ids:
                if i not in by_id:
                    sys.exit(f"ERROR: bullet '{i}' not found in {owner}")
                chosen.append(by_id[i])
        out = []
        for b in chosen:
            o = bullet_out(b)
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
            "id": p["id"], "heading": pos_heading(p), "title": p["title"],
            "company": p["company"], "engine": p.get("engine", ""),
            "game": games_by_id.get(p.get("game"), {}).get("name", p.get("product", "")),
            "location": p.get("location", ""), "dates": date_range(p["start"], p["end"]),
            "dates_short": short_range(p["start"], p["end"]),
            "start": str(p["start"]), "end": str(p["end"]),
            "bullets": pick(p.get("bullets", []), pos_sel[p["id"]], f"position {p['id']}"),
        })

    # Consecutive positions at one company become a single group with a shared span.
    groups = []
    for pos in positions:
        if groups and groups[-1]["company"] == pos["company"]:
            groups[-1]["roles"].append(pos)
        else:
            groups.append({"company": pos["company"], "location": pos["location"], "roles": [pos]})
    for g in groups:
        g["dates_short"] = short_range(g["roles"][-1]["start"], g["roles"][0]["end"])

    engine_by_game = {}
    for p in master["positions"]:
        if p.get("game") and p.get("engine"):
            engine_by_game.setdefault(p["game"], (p["engine"], p["company"]))

    games = []
    for gid in game_ids:
        if gid not in games_by_id:
            sys.exit(f"ERROR: unknown game id '{gid}' in tailor.yaml")
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
    for pr in master.get("projects", []):
        if pr["id"] not in project_sel:
            continue
        ids = project_sel[pr["id"]]
        projects.append({
            "name": pr["name"], "url": pr.get("url"), "summary": pr.get("summary"),
            "bullets": pick(pr.get("bullets", []), ids, f"project {pr['id']}"),
        })

    for k in overrides:
        if k not in used_overrides:
            warn(f"override '{k}' does not match any selected bullet")

    return {
        "basics": master["basics"], "games": games,
        "positions": positions, "groups": groups, "skills": skills, "education": education,
        "projects": projects, "meta": master_mode,
    }


# ---------- typst ----------

def typst_args(typst, template, data_path, extra):
    rel = "/" + data_path.relative_to(ROOT).as_posix()
    return [typst, *extra, "--root", str(ROOT), "--input", f"data={rel}", str(ROOT / "templates" / template)]


def compile_pdf(typst, template, data, out_pdf, work_dir, name):
    work_dir.mkdir(parents=True, exist_ok=True)
    data_path = work_dir / f"{name}.json"
    data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    cmd = typst_args(typst, template, data_path, ["compile"])
    cmd.append(str(out_pdf))
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        sys.exit(f"ERROR: typst failed for {template}:\n{r.stderr}")
    qcmd = typst_args(typst, template, data_path, ["query"]) + ["<pagecount>", "--field", "value", "--one"]
    q = subprocess.run(qcmd, capture_output=True, text=True, encoding="utf-8")
    try:
        return int(q.stdout.strip())
    except ValueError:
        warn(f"could not read page count for {out_pdf.name}: {q.stderr.strip()[:120]}")
        return None


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
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{slug(master['basics']['name'])}_Master.pdf"
    pages = compile_pdf(typst, "resume.typ", data, out, out_dir, "resume")
    print(f"OK: {out.relative_to(ROOT)} ({pages} pages)")


def pick_template(tailor, override):
    name = override or tailor.get("template") or "resume"
    if not (ROOT / "templates" / f"{name}.typ").exists():
        avail = sorted(p.stem for p in (ROOT / "templates").glob("resume*.typ"))
        sys.exit(f"ERROR: no template '{name}'. Available: {', '.join(avail)}")
    return name


def build_app(typst, app_arg, example, template=None):
    master_path, apps_dir = workspace(example)
    app = Path(app_arg)
    if not app.is_dir():
        app = apps_dir / app_arg
    if not app.is_dir():
        sys.exit(f"ERROR: application folder not found: {app_arg}")
    app = app.resolve()
    master = load_yaml(master_path)
    tailor = load_yaml(app / "tailor.yaml")
    target = tailor.get("target", {})
    studio = slug(target.get("studio", app.name))
    name = slug(master["basics"]["name"])
    work = ROOT / "build" / app.name
    print(f"Building {app.name}")

    data = resolve(master, tailor, False)
    for s in walk_strings(data):
        lint(s, "resume")
    tpl = pick_template(tailor, template)
    suffix = f"_{tpl}" if template else ""
    out = app / f"{name}_Resume_{studio}{suffix}.pdf"
    pages = compile_pdf(typst, f"{tpl}.typ", data, out, work, f"resume{suffix}")
    if pages and pages > 1:
        warn(f"RESUME IS {pages} PAGES. Trim bullets or skills in tailor.yaml.")
    print(f"  resume: {out.name} ({pages} page{'s' if pages != 1 else ''})")

    letter = app / "cover-letter.md"
    if not letter.exists():
        warn("no cover-letter.md, skipping cover letter")
        return
    cl = tailor.get("cover_letter") or {}
    text = letter.read_text(encoding="utf-8").strip()
    paragraphs = [" ".join(p.split()) for p in re.split(r"\n\s*\n", text) if p.strip()]
    letter_data = {
        "basics": master["basics"], "date": cl.get("date"),
        "greeting": cl.get("greeting", "Dear Hiring Team,"),
        "closing": cl.get("closing", "Sincerely,"), "paragraphs": paragraphs,
    }
    for s in walk_strings(letter_data):
        lint(s, "cover letter")
    out = app / f"{name}_Cover_Letter_{studio}.pdf"
    pages = compile_pdf(typst, "cover-letter.typ", letter_data, out, work, "cover-letter")
    if pages and pages > 1:
        warn(f"cover letter is {pages} pages")
    print(f"  letter: {out.name} ({pages} page{'s' if pages != 1 else ''})")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--example", action="store_true", help="use examples/ instead of data/ and applications/")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build one application folder, or 'master'")
    b.add_argument("target")
    b.add_argument("--template", help="resume template to use (e.g. resume-games); output gets the name as a suffix")
    sub.add_parser("build-all", help="build every application")
    args = ap.parse_args()
    typst = find_typst()

    if args.cmd == "build":
        if args.target == "master":
            build_master(typst, args.example)
        else:
            build_app(typst, args.target, args.example, args.template)
    else:
        _, apps_dir = workspace(args.example)
        folders = sorted(p for p in apps_dir.glob("*") if (p / "tailor.yaml").exists())
        if not folders:
            sys.exit(f"No applications with tailor.yaml in {apps_dir}")
        for f in folders:
            build_app(typst, str(f), args.example)


if __name__ == "__main__":
    main()
