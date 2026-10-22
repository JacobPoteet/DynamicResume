"""Draft an application with headless Claude Code (`claude -p`).

Claude runs in the repo, so it picks up CLAUDE.md and CLAUDE.local.md (the tailoring
workflow and writing rules) on its own. It gets read-only tools and answers with one
JSON object; the app checks every id against the master and writes listing.yaml,
tailor.yaml and cover-letter.md. Uses the Claude Code login, so no API key.
"""
import json
import shutil
import subprocess
import threading
import time

import build
from build import ROOT, BuildError

TIMEOUT_S = 600
READ_ONLY = ["Read", "Glob", "Grep"]
DENY = ["Bash", "Edit", "Write", "NotebookEdit", "WebFetch", "WebSearch", "Agent", "Task"]

PROMPT = """You are drafting a job application in this DynamicResume repo. Follow CLAUDE.md, and
CLAUDE.local.md if it exists: its tailoring workflow, writing rules and personal rules all apply.

Read {master} (the master career data) and {listing} (the job listing).{existing}

Do not create or edit any files. Reply with only one JSON object, no prose and no code fence:
{{
  "listing": {{
    "studio": "studio name",
    "role": "role title",
    "requirements": [
      {{"text": "short phrase", "must": true, "tags": ["master tags it relates to"], "bullets": ["master bullet ids that back it up"]}}
    ]
  }},
  "tailor": {{ "the tailor.yaml content as JSON, per the schema in CLAUDE.md" }},
  "cover_letter": "the letter body, paragraphs separated by a blank line, no greeting or closing",
  "gaps": ["each thing the listing asks for that the master cannot back up"],
  "notes": "two or three sentences: which bullets you led with and why"
}}

- requirements: the listing's 6 to 12 real asks, each under 8 words. must is true for required
  qualifications and false for nice-to-haves.
- tailor: target {{studio, role}}, template "{template}", headline, positions with ordered bullet ids,
  skills_first, skill_groups, projects as {{id: {{bullets: [ids]}}}}, overrides only where rewording
  helps match the listing, and cover_letter {{greeting, closing}}. Use only ids that exist in the master.
- headline: one line under the name, "<title> | <two to four focus areas>". The title must be one the
  master shows the person holding (usually the most recent); the focus areas use the listing's words
  where the selected bullets back them up. Never a title they have not held.
- Size: a full page is usually 17 to 21 bullets across positions and projects. Aim to fill the page
  without going over; the user fine-tunes it in the editor afterwards.
- Never invent experience, metrics, tools or titles. Put anything the master cannot support in gaps.
"""


def claude_path():
    return shutil.which("claude")


class Drafts:
    """Background draft jobs, one per application."""

    def __init__(self, ws, lock, build_dir):
        self.ws = ws
        self.build_dir = build_dir
        self.lock = lock
        self.jobs = {}

    def status(self, name):
        job = self.jobs.get(name)
        if not job:
            return {"state": "idle"}
        return {k: v for k, v in job.items() if k != "proc"}

    def start(self, name):
        app = self.ws.app_dir(name)
        exe = claude_path()
        if not exe:
            raise BuildError("the claude command was not found on PATH")
        if self.jobs.get(name, {}).get("state") == "running":
            raise BuildError("a draft is already running for this application")
        if not (app / "listing.md").read_text(encoding="utf-8").strip():
            raise BuildError("listing.md is empty; paste the listing first")
        job = {"state": "running", "started": time.time(), "log": ["Starting Claude Code"], "result": None}
        self.jobs[name] = job
        threading.Thread(target=self._run, args=(name, exe, job), daemon=True).start()
        return self.status(name)

    def cancel(self, name):
        job = self.jobs.get(name)
        if job and job.get("state") == "running" and job.get("proc"):
            job["cancelled"] = True
            job["proc"].kill()
        return self.status(name)

    def _prompt(self, app):
        rel = lambda p: p.relative_to(ROOT).as_posix()
        existing = ""
        if (app / "tailor.yaml").exists():
            existing = (f"\n\n{rel(app / 'tailor.yaml')} is the current selection. Replace it with your best "
                        "draft, but keep any wording in its overrides that still fits.")
        return PROMPT.format(master=rel(self.ws.master_path), listing=rel(app / "listing.md"),
                             existing=existing, template=build.DEFAULT_TEMPLATE)

    def _run(self, name, exe, job):
        app = self.ws.apps_dir / name
        cmd = [exe, "-p", "--output-format", "stream-json", "--verbose", "--no-session-persistence",
               "--strict-mcp-config", "--allowedTools", *READ_ONLY, "--disallowedTools", *DENY]
        log = job["log"]
        try:
            proc = subprocess.Popen(cmd, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, encoding="utf-8")
            job["proc"] = proc
            killer = threading.Timer(TIMEOUT_S, proc.kill)
            killer.start()
            proc.stdin.write(self._prompt(app))
            proc.stdin.close()
            result, other = None, []
            for line in proc.stdout:
                try:
                    msg = json.loads(line)
                except ValueError:
                    other.append(line.strip())  # stderr is merged in; keep it for error messages
                    continue
                if msg.get("type") == "assistant":
                    for part in msg.get("message", {}).get("content", []):
                        if part.get("type") == "tool_use":
                            inp = part.get("input", {})
                            target = inp.get("file_path") or inp.get("pattern") or inp.get("path") or ""
                            target = str(target).replace(str(ROOT), "").replace("\\", "/").lstrip("/")
                            log.append(f"{part.get('name')} {target}")
                elif msg.get("type") == "result":
                    result = msg
            proc.wait()
            killer.cancel()
            if job.get("cancelled"):
                raise BuildError("cancelled")
            if not result or result.get("is_error") or result.get("subtype") != "success":
                err = (result or {}).get("result") or " ".join(other).strip()[:400] or "no result"
                raise BuildError(f"Claude did not finish: {err}")
            log.append(f"Claude finished in {round(result.get('duration_ms', 0) / 1000)} s; checking the draft")
            # Keep Claude's raw reply next to the previews, for when a draft looks wrong.
            raw = self.build_dir / name / "draft-reply.txt"
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_text(result.get("result", ""), encoding="utf-8")
            out = parse_json(result.get("result", ""))
            with self.lock:
                job["result"] = self.apply(name, out)
            job["state"] = "done"
            log.append("Draft written")
        except BuildError as e:
            job.update(state="error", error=str(e))
        except Exception as e:  # report anything else in the page rather than losing the thread
            job.update(state="error", error=f"{type(e).__name__}: {e}")
        finally:
            job["finished"] = time.time()
            job.pop("proc", None)

    def apply(self, name, out):
        """Check the draft against the master, drop anything unknown, and write the files."""
        master = self.ws.master()
        warnings = []
        tailor = out.get("tailor") or {}
        if not isinstance(tailor, dict):
            raise BuildError("the draft has no tailor object")
        tailor = clean_tailor(master, tailor, warnings)
        spec = out.get("listing") or {}
        known = {b["id"] for o in master["positions"] + master.get("projects", []) for b in o.get("bullets") or []}
        reqs = []
        for r in spec.get("requirements") or []:
            if not isinstance(r, dict) or not r.get("text"):
                continue
            reqs.append({"text": str(r["text"]), "must": bool(r.get("must", True)),
                         "tags": [str(t) for t in r.get("tags") or []],
                         "bullets": [b for b in r.get("bullets") or [] if b in known]})
        listing = {"studio": spec.get("studio") or tailor["target"].get("studio", ""),
                   "role": spec.get("role") or tailor["target"].get("role", ""),
                   "requirements": reqs, "gaps": [str(g) for g in out.get("gaps") or []],
                   "notes": str(out.get("notes") or ""), "drafted": time.strftime("%Y-%m-%d %H:%M")}
        app = self.ws.app_dir(name)
        if (app / "listing.yaml").exists():
            self.ws.create_snapshot(f"before-redraft-{name}")
        self.ws.save_tailor(name, tailor)
        self.ws.save_listing_spec(name, listing)
        letter = str(out.get("cover_letter") or "").strip()
        if letter:
            self.ws.save_text(name, "cover-letter.md", letter + "\n")
        for s in build.walk_strings({"t": tailor.get("overrides"), "l": letter}):
            with build.collect_warnings() as w:
                build.lint(s, "draft")
            warnings += w
        return {"warnings": warnings, "notes": listing["notes"], "gaps": listing["gaps"]}


def parse_json(text):
    """The JSON object in Claude's reply, tolerating a code fence or a stray sentence."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise BuildError(f"Claude's reply had no JSON object: {text[:200]!r}")
    try:
        return json.loads(text[start:end + 1])
    except ValueError as e:
        raise BuildError(f"Claude's reply was not valid JSON ({e}): {text[:200]!r}")


def clean_tailor(master, t, warnings):
    """Keep only ids the master has, in the shapes the build expects."""
    out = {"target": {k: str(v) for k, v in (t.get("target") or {}).items() if k in ("studio", "role")}}
    tpl = t.get("template") or build.DEFAULT_TEMPLATE
    out["template"] = tpl if tpl in build.templates() else build.DEFAULT_TEMPLATE
    if str(t.get("headline") or "").strip():
        out["headline"] = str(t["headline"]).strip()

    def ids_for(owners, sel, kind):
        by_owner = {o["id"]: [b["id"] for b in o.get("bullets") or []] for o in owners}
        res = {}
        for oid, v in (sel or {}).items():
            if oid not in by_owner:
                warnings.append(f"dropped unknown {kind} '{oid}'")
                continue
            ids = v.get("bullets") if isinstance(v, dict) else v
            ids = list(ids) if isinstance(ids, list) else by_owner[oid]
            keep = [i for i in ids if i in by_owner[oid]]
            warnings.extend(f"dropped unknown bullet '{i}' from {oid}" for i in ids if i not in by_owner[oid])
            res[oid] = {"bullets": keep}
        return res

    out["positions"] = ids_for(master["positions"], t.get("positions"), "position")
    projects = t.get("projects")
    if isinstance(projects, list):
        projects = {p: None for p in projects}
    if projects:
        out["projects"] = ids_for(master.get("projects", []), projects, "project")
    games = {g["id"] for g in master.get("games", [])}
    if isinstance(t.get("games"), list):
        out["games"] = [g for g in t["games"] if g in games]
    items = {i for g in master.get("skills", []) for i in g.get("items", [])}
    groups = [g["group"] for g in master.get("skills", [])]
    if t.get("skills_first"):
        out["skills_first"] = [i for i in t["skills_first"] if i in items]
    if t.get("skill_groups"):
        out["skill_groups"] = [g for g in t["skill_groups"] if g in groups]
    chosen = {i for v in list(out["positions"].values()) + list(out.get("projects", {}).values()) for i in v["bullets"]}
    overrides = {k: str(v) for k, v in (t.get("overrides") or {}).items() if k in chosen}
    if overrides:
        out["overrides"] = overrides
    cl = {k: str(v) for k, v in (t.get("cover_letter") or {}).items() if k in ("greeting", "closing", "date") and v}
    if cl:
        out["cover_letter"] = cl
    return out
