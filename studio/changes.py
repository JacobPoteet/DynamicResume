"""What changed between two versions of an application: its selection, wording and letter.

The app shows this however the change was made, including an edit from outside it, as long as
an earlier version was kept (see build.remember_version).
"""
import difflib
import re


def _selection(tailor, kind, owners):
    """Owner id -> ordered bullet ids. A project with no list shows all its bullets."""
    raw = tailor.get(kind) or {}
    out = {}
    for oid in raw:
        ids = None if isinstance(raw, list) else (raw[oid] or {}).get("bullets")
        if ids is None:
            ids = [b["id"] for b in (owners.get(oid) or {}).get("bullets") or []] if kind == "projects" else []
        out[oid] = list(ids)
    return out


def _where(kind, owner, oid):
    if not owner:
        return oid
    return owner.get("name", oid) if kind == "projects" else f"{owner.get('company', '')}, {owner.get('title', '')}"


def _text(bullet, tailor):
    """The bullet's words as this version prints them."""
    if not bullet:
        return ""
    overrides = tailor.get("overrides") or {}
    if bullet["id"] in overrides:
        return str(overrides[bullet["id"]])
    if bullet["id"] in (tailor.get("short") or []) and bullet.get("short"):
        return bullet["short"]
    return bullet.get("text", "")


def _moved(old, new):
    """Ids in both lists whose order relative to the others changed."""
    common = set(old) & set(new)
    a, b = [i for i in old if i in common], [i for i in new if i in common]
    stayed = set()
    for m in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        stayed.update(a[m.a:m.a + m.size])
    return [i for i in b if i not in stayed]


def paragraphs(text):
    return [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]


def _letter(old, new):
    a, b = paragraphs(old), paragraphs(new)
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op != "equal":
            out += [{"change": "removed", "text": p} for p in a[i1:i2]]
            out += [{"change": "added", "text": p} for p in b[j1:j2]]
    return out


def compare(master, old, new, old_letter, new_letter):
    """The differences from `old` to `new`, with only the parts that changed."""
    added, removed, moved, reworded = [], [], [], []
    for kind, owners in (("positions", master.get("positions") or []), ("projects", master.get("projects") or [])):
        by_id = {o["id"]: o for o in owners}
        was, now = _selection(old, kind, by_id), _selection(new, kind, by_id)
        for oid in [*now, *(o for o in was if o not in now)]:
            owner = by_id.get(oid)
            bullets = {b["id"]: b for b in (owner or {}).get("bullets") or []}
            a, b = was.get(oid, []), now.get(oid, [])

            def row(i, tailor):
                return {"id": i, "where": _where(kind, owner, oid), "text": _text(bullets.get(i), tailor)}
            removed += [row(i, old) for i in a if i not in b]
            added += [row(i, new) for i in b if i not in a]
            moved += [row(i, new) for i in _moved(a, b)]
            for i in b:
                if i in a and _text(bullets.get(i), old) != _text(bullets.get(i), new):
                    reworded.append({**row(i, new), "before": _text(bullets.get(i), old)})
    out = {k: v for k, v in (("added", added), ("removed", removed), ("moved", moved), ("reworded", reworded)) if v}
    fields = []
    for key, label in (("headline", "Headline"), ("skills_first", "Skills moved to the front"),
                       ("skill_groups", "Skill groups"), ("template", "Template"), ("paper", "Paper")):
        a, b = old.get(key), new.get(key)
        if (a or None) != (b or None):
            show = lambda v: ", ".join(map(str, v)) if isinstance(v, list) else str(v or "(none)")
            fields.append({"label": label, "before": show(a), "after": show(b)})
    if fields:
        out["fields"] = fields
    letter = _letter(old_letter, new_letter)
    if letter:
        out["letter"] = letter
    return out
