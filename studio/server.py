"""Local web server for the editor. Binds to 127.0.0.1 only; standard library HTTP.

The browser UI (studio/static) talks to the JSON API below. Every write goes to the
same files the CLI uses (master.yaml, tailor.yaml, ...), so the app, a text editor and
Claude Code can all work on one application.
"""
import json
import re
import shutil
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import build
from build import HOME, ROOT, BuildError
from studio.draft import Drafts, claude_path
from studio.workspace import Workspace

STATIC = Path(__file__).parent / "static"
TYPES = {".html": "text/html", ".js": "text/javascript", ".css": "text/css",
         ".svg": "image/svg+xml", ".pdf": "application/pdf"}
LOCK = threading.Lock()  # one typst build or file write at a time


class Studio:
    def __init__(self, example):
        self.example = example
        self.ws = Workspace(example)
        self.typst = build.find_typst()
        self.build_dir = ROOT / "build" / ("studio-example" if example else "studio")
        self.drafts = Drafts(self.ws, LOCK, self.build_dir)

    def url(self, p):
        """The /files/ URL for a preview page or PDF: build output, or a file in an application
        folder (which may sit outside this checkout, see build.find_home)."""
        p = Path(p).resolve()
        for prefix, base in (("build", ROOT / "build"), ("apps", self.ws.apps_dir)):
            try:
                return f"/files/{prefix}/{p.relative_to(base.resolve()).as_posix()}?v={int(time.time() * 1000)}"
            except ValueError:
                pass
        raise BuildError(f"cannot serve {p}")

    def versions(self, name=None):
        """Newest modification time of what a preview depends on, so the page can notice
        edits made outside the app (a text editor, Claude Code) and refresh."""
        def newest(paths):
            return max((p.stat().st_mtime for p in paths if p.exists()), default=0)
        v = {"master": newest([self.ws.master_path]), "templates": newest(build.TEMPLATES.glob("*.typ"))}
        if name:
            app = self.ws.apps_dir / name
            v["app"] = newest([*(app / f for f in ("tailor.yaml", "listing.md", "listing.yaml", "cover-letter.md")),
                               self.ws.studios_path])
        return v

    def preview(self, name, kind, tailor=None, letter=None):
        """Render the resume or cover letter to SVG pages and report how full they are."""
        app = self.ws.app_dir(name)
        with LOCK, build.collect_warnings() as warnings:
            try:
                master = self.ws.master()
                if tailor is None:
                    tailor = self.ws._read_yaml(app / "tailor.yaml") or {}
                out_dir = self.build_dir / name / kind
                out_dir.mkdir(parents=True, exist_ok=True)
                for old in out_dir.glob("page-*.svg"):
                    old.unlink()
                if kind == "resume":
                    data = build.resume_data(master, tailor)
                    template = build.pick_template(tailor) + ".typ"
                else:
                    if letter is None:
                        letter = self.ws._read_text(app / "cover-letter.md") or ""
                    data = build.letter_data(master, tailor, letter)
                    template = "cover-letter.typ"
                fill = build.fill(build.render(self.typst, template, data, out_dir / "page-{p}.svg", out_dir, kind))
                for w in build.fit_warnings(fill):
                    build.warn(w)
                pages = sorted(out_dir.glob("page-*.svg"), key=lambda p: int(re.sub(r"\D", "", p.stem)))
                urls = [self.url(p) for p in pages]
                return {"ok": True, "pages": urls, "fill": fill, "warnings": list(warnings)}
            except BuildError as e:
                return {"ok": False, "error": str(e), "warnings": list(warnings)}

    def finalize(self, name):
        app = self.ws.app_dir(name).resolve()
        with LOCK, build.collect_warnings() as warnings:
            r = build.build_app(self.typst, app, self.example)
        return {"resume": self.url(r["resume"]), "resume_fill": r["resume_fill"],
                "letter": r["letter"] and self.url(r["letter"]), "letter_fill": r["letter_fill"], "warnings": warnings,
                "pdfs": self.ws.pdf_status(app, self.ws._read_yaml(app / "tailor.yaml") or {})}


# ---------- routes ----------

ROUTES = []


def route(method, pattern):
    def deco(fn):
        ROUTES.append((method, re.compile(f"^{pattern}$"), fn))
        return fn
    return deco


@route("GET", "/api/init")
def init(s, body, q):
    return {"example": s.example, "templates": build.templates(), "default_template": build.DEFAULT_TEMPLATE,
            "claude": bool(claude_path()), "data_home": None if s.example or HOME == ROOT else str(HOME)}


@route("GET", "/api/versions")
def versions(s, body, q):
    return s.versions(q.get("app", [None])[0])


@route("GET", "/api/apps")
def list_apps(s, body, q):
    return {"apps": s.ws.list_apps()}


@route("POST", "/api/apps")
def create_app(s, body, q):
    with LOCK:
        name = s.ws.create_app(body.get("studio"), body.get("role"), body.get("listing"))
    return {"name": name}


@route("GET", "/api/apps/([^/]+)")
def get_app(s, body, q, name):
    return s.ws.load_app(name)


@route("DELETE", "/api/apps/([^/]+)")
def delete_app(s, body, q, name):
    if s.drafts.status(name).get("state") == "running":
        raise BuildError("a Claude draft is running for this application; cancel it first")
    with LOCK:
        r = s.ws.delete_app(name)
        shutil.rmtree(s.build_dir / name, ignore_errors=True)
    return r


@route("PUT", "/api/apps/([^/]+)/tailor")
def put_tailor(s, body, q, name):
    s.ws.require_editable(name)
    with LOCK:
        s.ws.save_tailor(name, body["tailor"])
    return {"preview": s.preview(name, "resume", body["tailor"]), "versions": s.versions(name)}


@route("POST", "/api/apps/([^/]+)/preview/(resume|letter)")
def get_preview(s, body, q, name, kind):
    return s.preview(name, kind)


@route("PUT", "/api/apps/([^/]+)/letter")
def put_letter(s, body, q, name):
    s.ws.require_editable(name)
    with LOCK:
        s.ws.save_text(name, "cover-letter.md", body["text"])
    return {"preview": s.preview(name, "letter", letter=body["text"]), "versions": s.versions(name)}


@route("POST", "/api/apps/([^/]+)/finalize")
def finalize(s, body, q, name):
    return s.finalize(name)


@route("POST", "/api/apps/([^/]+)/submit")
def submit(s, body, q, name):
    with LOCK:
        return s.ws.submit_app(name, body.get("date"))


@route("POST", "/api/apps/([^/]+)/unsubmit")
def unsubmit(s, body, q, name):
    with LOCK:
        return s.ws.unsubmit_app(name)


@route("PUT", "/api/apps/([^/]+)/studio-notes")
def put_studio_notes(s, body, q, name):
    tailor = s.ws._read_yaml(s.ws.app_dir(name) / "tailor.yaml") or {}
    with LOCK:
        s.ws.save_studio_notes((tailor.get("target") or {}).get("studio"), body.get("notes"))
    return {"versions": s.versions(name)}


@route("PUT", "/api/apps/([^/]+)/listing")
def put_listing(s, body, q, name):
    s.ws.require_editable(name)
    with LOCK:
        if "text" in body:
            s.ws.save_text(name, "listing.md", body["text"])
        if "spec" in body:
            s.ws.save_listing_spec(name, body["spec"])
    return {"versions": s.versions(name)}


@route("GET", "/api/apps/([^/]+)/draft")
def draft_status(s, body, q, name):
    return s.drafts.status(name)


@route("POST", "/api/apps/([^/]+)/draft")
def draft_start(s, body, q, name):
    s.ws.require_editable(name)
    return s.drafts.start(name)


@route("POST", "/api/apps/([^/]+)/draft/cancel")
def draft_cancel(s, body, q, name):
    return s.drafts.cancel(name)


@route("GET", "/api/master")
def get_master(s, body, q):
    return {"master": s.ws.master(), "text": s.ws.master_text(), "usage": s.ws.bullet_usage()}


@route("PUT", "/api/master")
def put_master(s, body, q):
    with LOCK:
        if "text" in body:
            s.ws.save_master_text(body["text"])
        else:
            s.ws.save_master(body["master"])
        master = s.ws.master()
        with build.collect_warnings() as warnings:
            for text in build.walk_strings(master):
                build.lint(text, "master")
    return {"master": master, "text": s.ws.master_text(), "usage": s.ws.bullet_usage(),
            "versions": s.versions(), "warnings": warnings}


@route("POST", "/api/check")
def check(s, body, q):
    """What the master's current state does to every unsubmitted application's resume."""
    with LOCK:
        return {"rows": build.check_apps(s.typst, s.example)}


@route("GET", "/api/gaps")
def gaps(s, body, q):
    return {"gaps": s.ws.gap_summary()}


@route("GET", "/api/snapshots")
def list_snapshots(s, body, q):
    return {"snapshots": s.ws.list_snapshots()}


@route("POST", "/api/snapshots")
def create_snapshot(s, body, q):
    with LOCK:
        return s.ws.create_snapshot(body.get("label", ""))


@route("POST", "/api/snapshots/([^/]+)/restore")
def restore_snapshot(s, body, q, name):
    with LOCK:
        return s.ws.restore_snapshot(name)


# ---------- HTTP ----------

class Handler(BaseHTTPRequestHandler):
    studio = None

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        self.handle_request("GET")

    def do_POST(self):
        self.handle_request("POST")

    def do_PUT(self):
        self.handle_request("PUT")

    def do_DELETE(self):
        self.handle_request("DELETE")

    def send(self, code, data, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, obj, code=200):
        self.send(code, json.dumps(obj, default=str).encode("utf-8"), "application/json")

    def send_file(self, path):
        if not path.is_file():
            return self.send_json({"error": "not found"}, 404)
        self.send(200, path.read_bytes(), TYPES.get(path.suffix.lower(), "application/octet-stream"))

    def handle_request(self, method):
        url = urlparse(self.path)
        path = unquote(url.path)
        # Only answer pages served from this machine (guards against DNS rebinding), and
        # require a custom header on writes so other sites cannot post to the API.
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            return self.send_json({"error": "bad host"}, 403)
        if method != "GET" and self.headers.get("X-Studio") != "1":
            return self.send_json({"error": "missing X-Studio header"}, 403)
        try:
            if method == "GET" and path in ("/", "/index.html"):
                return self.send_file(STATIC / "index.html")
            if method == "GET" and path.startswith("/static/"):
                return self.send_file(self.safe(STATIC, path[len("/static/"):]))
            if method == "GET" and path.startswith("/files/"):
                return self.send_file(self.output_file(path[len("/files/"):]))
            body = {}
            if method in ("POST", "PUT"):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
            for m, rx, fn in ROUTES:
                match = rx.match(path)
                if m == method and match:
                    return self.send_json(fn(self.studio, body, parse_qs(url.query), *match.groups()))
            self.send_json({"error": f"no route {method} {path}"}, 404)
        except BuildError as e:
            self.send_json({"error": str(e)}, 400)
        except Exception as e:  # keep the server up; show the error in the page
            traceback.print_exc()
            self.send_json({"error": f"{type(e).__name__}: {e}"}, 500)

    @staticmethod
    def safe(base, rel):
        p = (base / rel).resolve()
        if base.resolve() not in p.parents:
            raise BuildError("path outside the allowed folder")
        return p

    def output_file(self, rel):
        """Previews and PDFs only: SVG/PDF files under build/ (files/build/...) or the
        applications folder (files/apps/...)."""
        prefix, _, rest = rel.partition("/")
        base = {"build": ROOT / "build", "apps": self.studio.ws.apps_dir}.get(prefix)
        if base is None:
            raise BuildError("not a preview or PDF")
        p = self.safe(base, rest)
        if p.suffix.lower() not in (".svg", ".pdf"):
            raise BuildError("not a preview or PDF")
        return p


def serve(example, port, open_browser=True):
    Handler.studio = Studio(example)
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"DynamicResume editor{' (example data)' if example else ''}: {url}   Ctrl+C to stop")
    if not example and HOME != ROOT:
        print(f"Data and applications: {HOME}")
    if open_browser:
        threading.Timer(0.6, webbrowser.open, [url]).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("stopped")
