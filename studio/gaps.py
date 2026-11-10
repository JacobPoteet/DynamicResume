"""Closing out gaps, and writing a bullet for one from your own answers.

A gap is something a listing asked for that the master could not back up. `Workspace.gap_summary`
groups them by topic across applications. This module keeps what you decided about each group
in data/gaps.yaml (gitignored, kept in snapshots), keyed the way gap_summary groups them:

    - key: economy-design          # the topic, or the gap's text in lower case when it has none
      state: done                  # done (the master covers it now) or not-me (you have not done it)
      date: 2026-11-09
      bullet: gsg-economy          # optional: the bullet that closed it
      note: optional

Write a bullet runs headless Claude Code twice: once for questions about what you did, once to
turn your answers into a bullet. Claude gets read-only tools and the never-invent rule; nothing
reaches the master until you review the bullet and press Add to master.
"""
import json
import re
import subprocess
from datetime import date

import yaml

import build
from build import BuildError
from studio.draft import DENY, READ_ONLY, claude_path, parse_json

FILE = "gaps.yaml"
STATES = ("done", "not-me")
TIMEOUT_S = 300
PRIORITIES = (1, 2, 3)

QUESTIONS = """You are helping the person behind this DynamicResume repo write one honest resume bullet.
Follow CLAUDE.md, and CLAUDE.local.md if it exists: their writing and personal rules apply.

Job listings asked for this, and the master ({master}) has nothing that backs it up:
{gap}

Read the master to see their roles, games and projects. Then write 3 to 5 short questions that find
out what they did that relates to it: where (which role or project), what they did themselves,
the scale, the tools, and what came of it. Do not assume they did it: a question must let them say
they did not. Do not create or edit files. Reply with only one JSON object, no prose and no code fence:
{{"questions": ["...", "..."]}}
"""

BULLET = """You are helping the person behind this DynamicResume repo write one honest resume bullet.
Follow CLAUDE.md, and CLAUDE.local.md if it exists: their writing and personal rules apply.

Job listings asked for this, and the master ({master}) has nothing that backs it up:
{gap}

They answered these questions:
{answers}

Read the master for its tags, bullet style and position and project ids. Write one bullet from their
answers ONLY. Never add a number, tool, title, team size or result they did not give. If the answers
show they have not done this, say so instead of writing a bullet. Do not create or edit files.
Reply with only one JSON object, no prose and no code fence:
{{
  "text": "the bullet, in the master's style, past tense, no em dashes",
  "short": "a tighter version under about 90 characters, or empty",
  "tags": ["existing master tags first; a new lowercase tag only when none fits"],
  "owner": "the id of the master position or project it belongs under",
  "priority": 2,
  "unsupported": "what the listings ask for that the answers still do not show, or empty",
  "none": "only when the answers show no such experience: one sentence saying why; otherwise empty"
}}
"""


# ----- states -----

def path(ws):
    return ws.master_path.parent / FILE


def load(ws):
    """key -> {state, date, bullet?, note?}"""
    out = {}
    for e in ws._read_yaml(path(ws)) or []:
        if isinstance(e, dict) and e.get("key") and e.get("state") in STATES:
            out[str(e["key"])] = {k: e[k] for k in ("state", "date", "bullet", "note") if e.get(k) not in (None, "")}
    return out


def set_state(ws, key, state, bullet=None, note=None):
    """Mark a gap group done or not-me; state None reopens it."""
    key = str(key or "").strip().lower()
    if not key:
        raise BuildError("which gap? the key is missing")
    if state not in (*STATES, None):
        raise BuildError(f"a gap is done, not-me or open, not {state!r}")
    states = load(ws)
    states.pop(key, None)
    if state:
        e = {"state": state, "date": date.today().isoformat()}
        if bullet:
            e["bullet"] = str(bullet)
        if str(note or "").strip():
            e["note"] = str(note).strip()
        states[key] = e
    rows = [{"key": k, **v} for k, v in sorted(states.items())]
    p = path(ws)
    if rows:
        p.write_text(yaml.safe_dump(rows, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n")
    elif p.exists():
        p.unlink()
    return states.get(key)


def annotate(ws, groups):
    """Add each group's key, state and whether a listing raised it again after you closed it."""
    states = load(ws)
    for g in groups:
        g["key"] = group_key(g)
        s = states.get(g["key"])
        g["state"] = s
        g["raised_again"] = bool(s and any(str(i.get("drafted") or "")[:10] > str(s["date"]) for i in g["items"]))
    return groups


def group_key(g):
    return str(g["topic"] or g["items"][0]["text"]).strip().lower()


def find(ws, key):
    for g in annotate(ws, ws.gap_summary()):
        if g["key"] == str(key or "").strip().lower():
            return g
    raise BuildError("no gap with that key; it may have been removed from every listing")


# ----- writing a bullet with Claude -----

def describe(g):
    head = f"Topic: {g['topic']}\n" if g["topic"] else ""
    return head + "\n".join(f"- {i['studio']}: {i['text']}" for i in g["items"])


def ask(ws, prompt):
    """Run headless Claude Code in the data home with read-only tools and return its JSON reply."""
    exe = claude_path()
    if not exe:
        raise BuildError("the claude command was not found on PATH")
    cmd = [exe, "-p", "--output-format", "json", "--no-session-persistence", "--strict-mcp-config",
           "--allowedTools", *READ_ONLY, "--disallowedTools", *DENY]
    try:
        r = subprocess.run(cmd, cwd=ws.home, input=prompt, capture_output=True, text=True, encoding="utf-8",
                           timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise BuildError(f"Claude took longer than {TIMEOUT_S // 60} minutes")
    try:
        result = json.loads(r.stdout)
    except ValueError:
        raise BuildError(f"Claude did not finish: {(r.stderr or r.stdout).strip()[:400] or 'no output'}")
    if result.get("is_error") or result.get("subtype") != "success":
        raise BuildError(f"Claude did not finish: {str(result.get('result') or 'no result')[:400]}")
    return parse_json(result.get("result") or "")


def questions(ws, key):
    g = find(ws, key)
    out = ask(ws, QUESTIONS.format(master=rel(ws, ws.master_path), gap=describe(g)))
    qs = [str(q).strip() for q in out.get("questions") or [] if str(q).strip()][:6]
    if not qs:
        raise BuildError("Claude sent no questions; try again")
    return {"key": g["key"], "questions": qs}


def propose(ws, key, answers):
    """A bullet from the answers, checked against the master. Writes nothing."""
    g = find(ws, key)
    pairs = [(str(a.get("q") or "").strip(), str(a.get("a") or "").strip()) for a in answers or [] if isinstance(a, dict)]
    pairs = [(q, a) for q, a in pairs if a]
    if not pairs:
        raise BuildError("answer at least one question first")
    qa = "\n\n".join(f"Q: {q}\nA: {a}" for q, a in pairs)
    out = ask(ws, BULLET.format(master=rel(ws, ws.master_path), gap=describe(g), answers=qa))
    return check_proposal(ws.master(), out)


def check_proposal(master, out):
    """Keep the reply's fields in the shapes the master takes, with warnings for what was fixed."""
    owners = owner_list(master)
    warnings = []
    none = str(out.get("none") or "").strip()
    text = str(out.get("text") or "").strip()
    if none or not text:
        return {"none": none or "Claude could not write a bullet from those answers.", "owners": owners}
    owner = str(out.get("owner") or "")
    if owner not in {o["id"] for o in owners}:
        if owner:
            warnings.append(f"Claude picked '{owner}', which is not in the master; choose where it goes")
        owner = ""
    try:
        priority = int(out.get("priority"))
    except (TypeError, ValueError):
        priority = 2
    tags = []
    for t in out.get("tags") or []:
        t = re.sub(r"[^a-z0-9]+", "-", str(t).lower()).strip("-")
        if t and t not in tags:
            tags.append(t)
    known = {t for o in master["positions"] + master.get("projects", []) for b in o.get("bullets") or [] for t in b.get("tags") or []}
    new = [t for t in tags if t not in known]
    if new:
        warnings.append(f"new tag{'s' if len(new) > 1 else ''}: {', '.join(new)}")
    short = str(out.get("short") or "").strip()
    for s in (text, short):
        with build.collect_warnings() as w:
            build.lint(s, "bullet")
        warnings += w
    return {"text": text, "short": short, "tags": tags, "owner": owner,
            "priority": priority if priority in PRIORITIES else 2,
            "unsupported": str(out.get("unsupported") or "").strip(), "warnings": warnings, "owners": owners}


def owner_list(master):
    return ([{"id": p["id"], "kind": "position", "label": f"{p.get('title', '')}, {p.get('company', '')}".strip(", ")}
             for p in master["positions"]]
            + [{"id": p["id"], "kind": "project", "label": p.get("name", p["id"])} for p in master.get("projects") or []])


def add_bullet(ws, key, bullet):
    """Add a reviewed bullet to the end of its position or project, and mark the gap done."""
    g = find(ws, key)
    text = str(bullet.get("text") or "").strip()
    owner = str(bullet.get("owner") or "")
    if not text:
        raise BuildError("the bullet has no text")
    master = ws.master()
    target = next((o for o in master["positions"] + master.get("projects", []) if o["id"] == owner), None)
    if target is None:
        raise BuildError("choose the position or project it belongs under")
    ids = {b["id"] for o in master["positions"] + master.get("projects", []) for b in o.get("bullets") or []}
    base = new_id(target.get("game") or target["id"], text)
    bid, n = base, 1
    while bid in ids:
        n += 1
        bid = f"{base}-{n}"
    tags = [t for t in (re.sub(r"[^a-z0-9]+", "-", str(t).lower()).strip("-") for t in bullet.get("tags") or []) if t]
    try:
        priority = int(bullet.get("priority") or 2)
    except (TypeError, ValueError):
        priority = 2
    b = {"id": bid, "text": text}
    if str(bullet.get("short") or "").strip():
        b["short"] = str(bullet["short"]).strip()
    b["tags"] = tags
    b["priority"] = priority if priority in PRIORITIES else 2
    target.setdefault("bullets", []).append(b)
    ws.save_master(master)
    set_state(ws, g["key"], "done", bullet=bid)
    return {"id": bid, "owner": owner}


def new_id(owner, text):
    """'<initials of the game or owner>-<first two long words>', like the master's rr-tools ids."""
    prefix = "".join(w[0] for w in owner.split("-") if w)[:4] or "b"
    words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 3][:2]
    return "-".join([prefix, *words]) if words else f"{prefix}-bullet"


def rel(ws, p):
    return p.relative_to(ws.home).as_posix()
