"""An interview prep sheet and a thank-you email, written by headless Claude from what was sent.

Claude reads the application as it was sent (submitted/: listing, tailor, letter, master), the
studio notes, and the interview's tracking entry with any earlier debriefs. It answers with likely
questions and the bullets to talk about for each, what the master cannot back up, questions to ask
them, and a thank-you email to copy. The app checks every bullet id against the frozen master and
keeps the result in the application's prep.yaml, one sheet at a time: writing one for another
interview replaces it. Nothing is ever sent.
"""
from datetime import datetime

import yaml

import build
from build import BuildError
from studio import gaps, tracking

FILE = "prep.yaml"
STAGES = ("screen", "interview")
LIMITS = {"questions": 10, "gaps": 6, "ask_them": 6}

PROMPT = """You are helping the person behind this DynamicResume repo get ready for an interview.
Follow CLAUDE.md, and CLAUDE.local.md if it exists: their writing and personal rules apply.

The application as they sent it:
- listing: {listing}
- resume choices: {tailor} (bullet ids per position, with any overrides of the master text)
- cover letter: {letter}
- master the resume was built from: {master}

Studio notes: {notes}

The interview to prepare for:
{event}

Earlier entries for this application, with any debriefs:
{history}

Read those files. Then write:
- questions: the 6 to 10 questions they are most likely to be asked, given the listing and this
  stage. For each, the ids of the master bullets that answer it (from the master above, preferring
  ones on the resume they sent) and short talking points drawn from those bullets ONLY.
- gaps: what the listing asks for that the master cannot back up, and an honest way to answer
  each (what related work they can point to, or saying plainly they have not done it).
- ask_them: 3 to 5 questions they could ask the interviewers, specific to this studio and role.
- email: a short thank-you email to send after the interview, addressed to the interviewers
  named above (or "Hi team" when none are), that mentions one concrete thing from the role.

Never invent experience, numbers, tools, titles or results. No em dashes. Do not create or edit
files. Reply with only one JSON object, no prose and no code fence:
{{
  "questions": [{{"q": "...", "bullets": ["bullet-id"], "points": "..."}}],
  "gaps": [{{"text": "...", "answer": "..."}}],
  "ask_them": ["..."],
  "email": {{"subject": "...", "body": "paragraphs separated by blank lines"}}
}}
"""


def ask(ws, prompt):
    return gaps.ask(ws, prompt)


def path(app):
    return app / FILE


def load(ws, name):
    """The saved prep sheet for an application, or None."""
    data = ws._read_yaml(path(ws.app_dir(name)))
    return data if isinstance(data, dict) else None


def pick_event(events, index):
    """The screen or interview to prepare for: the one at `index`, else the latest logged."""
    rows = tracking.ordered(events)
    if index is not None:
        hit = next((e for e in rows if e["i"] == int(index)), None)
        if not hit:
            raise BuildError(f"there is no event {index}")
        if hit["stage"] not in STAGES:
            raise BuildError("a prep sheet is for a screen or an interview")
        return hit
    found = [e for e in rows if e["stage"] in STAGES]
    if not found:
        raise BuildError("log the screen or interview first, then write a prep sheet for it")
    return found[-1]


def describe_event(e):
    keep = {k: e[k] for k in ("stage", "date", "scheduled", "round", "format", "length", "interviewers", "prep", "note")
            if e.get(k) not in (None, "", [])}
    return yaml.safe_dump(keep, sort_keys=False, allow_unicode=True).strip()


def describe_history(events, target):
    rows = [e for e in tracking.ordered(events) if e["i"] != target["i"]]
    lines = []
    for e in rows:
        bits = [str(e["date"]), e["stage"] + (f" round {e['round']}" if e.get("round") else "")]
        bits += [f"{k}: {e[k]}" for k in ("note", "debrief") if e.get(k)]
        lines.append("- " + "; ".join(bits))
    return "\n".join(lines) or "(none)"


def sources(ws, app):
    """The files Claude reads: the frozen copies in submitted/, or the live ones an older
    submitted/ lacks."""
    def pick(filename, live):
        frozen = app / build.SUBMITTED / filename
        return frozen if frozen.exists() else live
    return {"listing": pick("listing.md", app / "listing.md"), "tailor": pick("tailor.yaml", app / "tailor.yaml"),
            "letter": pick("cover-letter.md", app / "cover-letter.md"), "master": pick("master.yaml", ws.master_path)}


def text(v, limit=2000):
    return str(v or "").strip()[:limit]


def check_reply(out, master):
    """Keep what the sheet can use. Bullet ids the master lacks are dropped and reported."""
    known = {b["id"] for owner in [*(master.get("positions") or []), *(master.get("projects") or [])]
             for b in owner.get("bullets") or [] if isinstance(b, dict) and b.get("id")}
    warnings, unknown = [], set()
    questions = []
    for q in out.get("questions") or []:
        if not isinstance(q, dict) or not text(q.get("q")):
            continue
        ids = [str(i) for i in q.get("bullets") or [] if str(i)]
        unknown.update(i for i in ids if i not in known)
        questions.append({"q": text(q["q"], 400), "bullets": [i for i in ids if i in known],
                          "points": text(q.get("points"))})
    if unknown:
        warnings.append(f"dropped bullet ids the master does not have: {', '.join(sorted(unknown))}")
    sheet = {
        "questions": questions[:LIMITS["questions"]],
        "gaps": [{"text": text(g.get("text"), 400), "answer": text(g.get("answer"))}
                 for g in out.get("gaps") or [] if isinstance(g, dict) and text(g.get("text"))][:LIMITS["gaps"]],
        "ask_them": [text(a, 400) for a in out.get("ask_them") or [] if text(a)][:LIMITS["ask_them"]],
        "email": {"subject": text((out.get("email") or {}).get("subject"), 200),
                  "body": text((out.get("email") or {}).get("body"), 4000)},
    }
    if not sheet["questions"]:
        raise BuildError("Claude sent no questions; try again")
    words = " ".join([*(q["points"] for q in sheet["questions"]), *(g["answer"] for g in sheet["gaps"]),
                      sheet["email"]["subject"], sheet["email"]["body"]]).lower()
    if build.EM_DASH in words:
        warnings.append("the sheet has an em dash; edit it out before sending the email")
    banned = [p for p in build.BANNED if p.lower() in words]
    if banned:
        warnings.append(f"the sheet uses phrases the writing rules avoid: {', '.join(banned)}")
    return sheet, warnings


def write(ws, name, index=None, now=None):
    """Ask Claude for a prep sheet for one screen or interview and save it to prep.yaml.
    Runs Claude (minutes), so the server calls it outside its lock."""
    app = ws.app_dir(name)
    if not build.submission(app):
        raise BuildError(f"{name} has not been sent yet, so there is no interview to prepare for")
    column = ws.track(app)["column"]
    if column in tracking.CLOSED:
        raise BuildError(f"{name} is closed ({column}), so there is no interview to prepare for")
    events = ws.events(app)
    e = pick_event(events, index)
    files = sources(ws, app)
    tailor = ws._read_yaml(files["tailor"]) or {}
    notes = ws.studio_notes((tailor.get("target") or {}).get("studio")) or "(none)"
    prompt = PROMPT.format(**{k: gaps.rel(ws, p) for k, p in files.items()}, notes=notes,
                           event=describe_event(e), history=describe_history(events, e))
    master = ws._read_yaml(files["master"]) or {}
    sheet, warnings = check_reply(ask(ws, prompt), master)
    data = {"for": {k: e[k] for k in ("stage", "date", "round") if e.get(k) is not None},
            "written": (now or datetime.now()).strftime("%Y-%m-%d %H:%M"), **sheet}
    path(app).write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100),
                         encoding="utf-8", newline="\n")
    return {"prep": data, "warnings": warnings}


def as_text(data):
    """The sheet as plain text, for the terminal."""
    f = data.get("for") or {}
    head = f"Prep for the {f.get('stage', 'interview')}" + (f" round {f['round']}" if f.get("round") else "")
    out = [f"{head} ({f.get('date', '')}), written {data.get('written', '')}", "", "Likely questions"]
    for q in data.get("questions") or []:
        out.append(f"- {q['q']}")
        if q.get("bullets"):
            out.append(f"    bullets: {', '.join(q['bullets'])}")
        if q.get("points"):
            out.append(f"    {q['points']}")
    if data.get("gaps"):
        out += ["", "What the master cannot back up"]
        out += [f"- {g['text']}\n    {g['answer']}" for g in data["gaps"]]
    if data.get("ask_them"):
        out += ["", "Questions to ask them"] + [f"- {a}" for a in data["ask_them"]]
    email = data.get("email") or {}
    if email.get("body"):
        out += ["", f"Thank-you email: {email.get('subject', '')}", "", email["body"]]
    return "\n".join(out)
