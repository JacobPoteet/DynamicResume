"""Files the app reads and writes: master.yaml, application folders, and snapshots.

YAML goes through ruamel's round-trip mode, so comments, quoting and layout in the
hand-edited files survive edits made in the app.
"""
import copy
import io
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path

import yaml
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import YAMLError

import build
from build import ROOT, BuildError

HISTORY_KEEP = 50
APP_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SNAP_NAME = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{6}[A-Za-z0-9_-]*\.zip$")


# ---------- round-trip YAML ----------

def rt():
    y = YAML()
    y.width = 4096
    y.indent(mapping=2, sequence=4, offset=2)
    y.preserve_quotes = True
    return y


def rt_load(text):
    try:
        return rt().load(text)
    except YAMLError as e:
        raise BuildError(f"YAML error: {e}")


def rt_dump(node):
    out = io.StringIO()
    rt().dump(node, out)
    return out.getvalue()


def _scalar(v):
    return not isinstance(v, (dict, list))


def _key(v):
    if isinstance(v, dict):
        for k in ("id", "group", "school"):
            if v.get(k) is not None:
                return (k, v[k])
    return None


def _tail_slot(node):
    """(map, key) that holds the blank lines after `node`. ruamel stores them on the
    deepest last scalar key, e.g. the `priority` of a position's last bullet."""
    while True:
        if isinstance(node, CommentedSeq) and len(node) and not node.fa.flow_style():
            node = node[-1]
            continue
        if isinstance(node, CommentedMap) and node:
            k = list(node)[-1]
            v = node[k]
            if isinstance(v, (CommentedMap, CommentedSeq)) and len(v) and not (
                    isinstance(v, CommentedSeq) and v.fa.flow_style()):
                node = v
                continue
            return node, k
        return None, None


def _pop_tail(node):
    m, k = _tail_slot(node)
    slot = m.ca.items.get(k) if m is not None else None
    if not slot or slot[2] is None or slot[2].value.strip():
        return None  # nothing there, or a real comment that should stay put
    tok, slot[2] = slot[2], None
    return tok


def _set_tail(node, tok):
    m, k = _tail_slot(node)
    if m is not None and tok is not None:
        slot = m.ca.items.setdefault(k, [None, None, None, None])
        if slot[2] is None:
            slot[2] = copy.copy(tok)


def _fix_tails(olds, items):
    """Keep blank-line spacing right after items were added, removed or reordered: the
    list's trailing blank moves to the new last item, and lists whose items were all
    separated by blank lines stay that way."""
    if not olds or not items:
        return
    tails = [_pop_tail(o) for o in olds]
    end, between = tails[-1], [t for t in tails[:-1] if t is not None]
    separated = len(olds) > 1 and len(between) == len(olds) - 1
    for o, t in zip(olds[:-1], tails[:-1]):
        _set_tail(o, t)  # put the in-between ones back; fixed up below if they moved
    for item in items[:-1]:
        if separated:
            _set_tail(item, between[0])
    if not separated:
        _pop_tail(items[-1])
    _set_tail(items[-1], end)


def merge(old, new):
    """Return `old` (a ruamel node, or None) updated to equal `new` (plain data).

    Maps are updated in place and list items are matched by id (or group/school), so
    comments attached to anything that survives stay where they were."""
    if isinstance(new, dict):
        node = old if isinstance(old, CommentedMap) else CommentedMap()
        # When keys come or go, the blank line after the map moves to its new last key.
        end = _pop_tail(node) if node and set(node) != set(new) else None
        for k in [k for k in node if k not in new]:
            del node[k]
        for k, v in new.items():
            node[k] = merge(node[k] if k in node else None, v)
        _set_tail(node, end)
        return node
    if isinstance(new, list):
        olds = list(old) if isinstance(old, CommentedSeq) else []
        if all(_scalar(v) for v in new):
            if isinstance(old, CommentedSeq) and olds == new:
                return old
            items = list(new)
        else:
            keyed = {_key(o): o for o in olds if _key(o) is not None}
            items = []
            for i, v in enumerate(new):
                k = _key(v)
                prev = keyed.get(k) if k is not None else (olds[i] if i < len(olds) else None)
                items.append(merge(prev, v))
        if isinstance(old, CommentedSeq) and len(olds) == len(items) and all(a is b for a, b in zip(olds, items)):
            return old
        if not all(_scalar(v) for v in new):
            _fix_tails(olds, items)
        seq = CommentedSeq(items)
        if isinstance(old, CommentedSeq):
            if old.fa.flow_style():
                seq.fa.set_flow_style()
            seq.ca.comment = old.ca.comment
        elif all(_scalar(v) for v in new):
            seq.fa.set_flow_style()
        return seq
    if old is not None and _scalar(old) and old == new and type(new) is not bool:
        return old  # keeps quoting style
    return new


def plain(node):
    return json.loads(json.dumps(node, default=str))


# ---------- workspace ----------

class Workspace:
    def __init__(self, example=False):
        self.example = example
        self.master_path, self.apps_dir = build.workspace(example)
        self.base = self.master_path.parent.parent
        self.snap_dir = ROOT / "snapshots" / ("example" if example else "")
        self.history_dir = self.snap_dir / "master-history"

    # ----- master -----

    def master(self):
        return build.load_yaml(self.master_path)

    def master_text(self):
        return self.master_path.read_text(encoding="utf-8")

    def check_master(self, data):
        build.validate_master(data)
        with build.collect_warnings():
            build.resolve(data, {}, True)

    def save_master(self, data):
        """Write plain master data, merged into the existing file to keep its comments."""
        self.check_master(data)
        doc = rt_load(self.master_text())
        self._write_master(rt_dump(merge(doc, data)))

    def save_master_text(self, text):
        rt_load(text)
        try:
            data = yaml.safe_load(text) or {}
        except yaml.YAMLError as e:
            raise BuildError(f"YAML error: {e}")
        self.check_master(data)
        self._write_master(text)

    def _write_master(self, text):
        # Every master write keeps the previous version, so a bad save is one copy away.
        self.history_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")
        (self.history_dir / f"master_{stamp}.yaml").write_text(self.master_text(), encoding="utf-8")
        for old in sorted(self.history_dir.glob("master_*.yaml"))[:-HISTORY_KEEP]:
            old.unlink()
        self.master_path.write_text(text, encoding="utf-8", newline="\n")

    def bullet_usage(self):
        """Bullet id -> application names that select or override it."""
        usage = {}
        for app in self.app_dirs():
            t = self._read_yaml(app / "tailor.yaml") or {}
            ids = set((t.get("overrides") or {}).keys())
            for v in (t.get("positions") or {}).values():
                ids.update((v or {}).get("bullets") or [])
            projects = t.get("projects") or {}
            if isinstance(projects, dict):
                for v in projects.values():
                    ids.update((v or {}).get("bullets") or [])
            for i in ids:
                usage.setdefault(i, []).append(app.name)
        return usage

    # ----- applications -----

    def app_dirs(self):
        if not self.apps_dir.is_dir():
            return []
        return sorted(p for p in self.apps_dir.iterdir()
                      if p.is_dir() and ((p / "tailor.yaml").exists() or (p / "listing.md").exists()))

    def app_dir(self, name):
        if not APP_NAME.match(name or ""):
            raise BuildError(f"bad application name: {name!r}")
        p = self.apps_dir / name
        if not p.is_dir():
            raise BuildError(f"no application named {name}")
        return p

    @staticmethod
    def _read_yaml(path):
        return build.load_yaml(path) if path.exists() else None

    @staticmethod
    def _read_text(path):
        return path.read_text(encoding="utf-8") if path.exists() else None

    def pdf_status(self, app, tailor, master=None):
        master = master or self.master()
        resume, letter = build.output_names(master, tailor, app)
        inputs = [self.master_path, app / "tailor.yaml", app / "cover-letter.md"]
        newest = max((p.stat().st_mtime for p in inputs if p.exists()), default=0)
        out = {}
        for key, fname in (("resume", resume), ("letter", letter)):
            p = app / fname
            out[key] = {"file": fname, "exists": p.exists(),
                        "stale": p.exists() and p.stat().st_mtime < newest}
        return out

    def list_apps(self):
        master = self.master()
        apps = []
        for app in self.app_dirs():
            t = self._read_yaml(app / "tailor.yaml") or {}
            target = t.get("target") or {}
            mtimes = [p.stat().st_mtime for p in app.iterdir() if p.is_file() and p.suffix != ".pdf"]
            apps.append({
                "name": app.name, "studio": target.get("studio", ""), "role": target.get("role", ""),
                "template": t.get("template") or build.DEFAULT_TEMPLATE,
                "updated": max(mtimes, default=0), "pdfs": self.pdf_status(app, t, master),
                "drafted": (app / "listing.yaml").exists(),
            })
        apps.sort(key=lambda a: -a["updated"])
        return apps

    def create_app(self, studio, role, listing):
        studio, role = (studio or "").strip(), (role or "").strip()
        if not studio or not role:
            raise BuildError("studio and role are both required")
        name = re.sub(r"[^a-z0-9]+", "-", f"{studio} {role}".lower()).strip("-")
        app = self.apps_dir / name
        if app.exists():
            raise BuildError(f"applications/{name} already exists")
        app.mkdir(parents=True)
        (app / "listing.md").write_text(f"# {studio}: {role}\n\n{(listing or '').strip()}\n", encoding="utf-8")
        self.save_tailor(name, self.starter_tailor(studio, role))
        return name

    def starter_tailor(self, studio, role):
        """Every position with its priority 1 bullets: a starting point to edit from."""
        master = self.master()
        positions = {}
        for p in master["positions"]:
            ids = [b["id"] for b in p.get("bullets") or [] if b.get("priority", 3) == 1]
            positions[p["id"]] = {"bullets": ids}
        return {"target": {"studio": studio, "role": role}, "template": build.DEFAULT_TEMPLATE,
                "positions": positions}

    def load_app(self, name):
        app = self.app_dir(name)
        tailor = self._read_yaml(app / "tailor.yaml") or {}
        return {
            "name": name, "tailor": tailor,
            "listing": self._read_text(app / "listing.md") or "",
            "listing_spec": self._read_yaml(app / "listing.yaml"),
            "letter": self._read_text(app / "cover-letter.md"),
            "pdfs": self.pdf_status(app, tailor),
        }

    def save_tailor(self, name, tailor):
        path = self.apps_dir / name / "tailor.yaml"
        doc = rt_load(path.read_text(encoding="utf-8")) if path.exists() else None
        path.write_text(rt_dump(merge(doc, tailor)), encoding="utf-8", newline="\n")

    def save_listing_spec(self, name, spec):
        path = self.app_dir(name) / "listing.yaml"
        doc = rt_load(path.read_text(encoding="utf-8")) if path.exists() else None
        path.write_text(rt_dump(merge(doc, spec)), encoding="utf-8", newline="\n")

    def save_text(self, name, filename, text):
        if filename not in ("listing.md", "cover-letter.md"):
            raise BuildError(f"cannot write {filename}")
        (self.app_dir(name) / filename).write_text(text, encoding="utf-8", newline="\n")

    # ----- snapshots -----

    def _snapshot_files(self):
        roots = [self.master_path.parent, self.apps_dir, build.TEMPLATES]
        if not self.example:
            roots.append(ROOT / "Local")
        for r in roots:
            if r.is_dir():
                for p in sorted(r.rglob("*")):
                    if p.is_file() and p.suffix.lower() != ".pdf":
                        yield p
        if not self.example and (ROOT / "CLAUDE.local.md").exists():
            yield ROOT / "CLAUDE.local.md"

    def create_snapshot(self, label=""):
        self.snap_dir.mkdir(parents=True, exist_ok=True)
        tag = re.sub(r"[^A-Za-z0-9-]+", "-", label.strip()).strip("-")
        name = datetime.now().strftime("%Y-%m-%d_%H%M%S") + (f"_{tag}" if tag else "") + ".zip"
        path = self.snap_dir / name
        n = 0
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            for f in self._snapshot_files():
                z.write(f, f.relative_to(ROOT).as_posix())
                n += 1
        return {"name": name, "path": path.relative_to(ROOT).as_posix(), "files": n, "size": path.stat().st_size}

    def list_snapshots(self):
        if not self.snap_dir.is_dir():
            return []
        out = []
        for p in sorted(self.snap_dir.glob("*.zip"), reverse=True):
            with zipfile.ZipFile(p) as z:
                n = len(z.namelist())
            out.append({"name": p.name, "files": n, "size": p.stat().st_size, "created": p.stat().st_mtime})
        return out

    def restore_snapshot(self, name):
        """Write the snapshot's files back over the current ones. Takes a snapshot first.
        Files created after the snapshot are left alone."""
        if not SNAP_NAME.match(name or "") or not (self.snap_dir / name).exists():
            raise BuildError(f"no snapshot named {name}")
        backup = self.create_snapshot("before-restore")
        n = 0
        with zipfile.ZipFile(self.snap_dir / name) as z:
            for member in z.namelist():
                dest = (ROOT / member).resolve()
                if ROOT not in dest.parents:
                    raise BuildError(f"snapshot entry outside the repo: {member}")
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(z.read(member))
                n += 1
        return {"restored": n, "backup": backup["name"]}
