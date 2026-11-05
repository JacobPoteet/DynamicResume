"""Fit a resume to one page by measuring it, not by guessing.

Over one page: apply `short` texts, then cut the lowest-ranked selected bullets, rendering after
each step. Under 90% full: suggest bullets to add, and leave adding them to the person. It never
rewords anything or changes fonts, and it only removes bullets, so it cannot create a
`variant_of` pair. app.js's bulletScore gives the same scores for its ranking of unselected bullets.
"""
import copy
import re

import build

FULL = 0.9  # a resume at least this full counts as a full page
SUGGESTIONS = 3
SUGGEST_TRIES = 8  # candidates to test-render, so a page with little room stays quick

STOP = frozenset((
    "about above after again along also among based being below between build built could "
    "design designed designer during each every first from have having into large like made make making more most "
    "other over same should since some such than that their them then there these they this those through under "
    "using very well were what when where which while will with within work worked working would years your"
).split())


def words(text):
    return {w for w in re.findall(r"[a-z][a-z0-9+#/-]{4,}", str(text).lower()) if w not in STOP}


def req_matches(req, bullet):
    """Claude names the bullets that back a requirement; without names, fall back to shared tags."""
    if req.get("bullets"):
        return bullet["id"] in req["bullets"]
    return bool(set(bullet.get("tags") or []) & set(req.get("tags") or []))


def score(bullet, text, reqs, listing):
    """How well a bullet fits the listing: requirements it backs, else words it shares."""
    if reqs:
        return sum((2 if r.get("must") else 1) for r in reqs if req_matches(r, bullet))
    low = listing.lower()
    hits = len(words(text) & words(listing))
    return hits + sum(1 for t in bullet.get("tags") or [] if t.replace("-", " ", 1) in low)


def _owners(master):
    """Every position, then every project, as (kind, owner), oldest last."""
    return [("positions", p) for p in master["positions"]] + [("projects", p) for p in master.get("projects") or []]


def _selected_ids(tailor, kind, owner):
    """The bullet ids an owner has selected, or None when it is not on the resume."""
    raw = tailor.get(kind) or {}
    if owner["id"] not in raw:
        return None
    ids = None if isinstance(raw, list) else (raw[owner["id"]] or {}).get("bullets")
    if ids is None:  # a project with no list shows all its bullets; a position with none shows none
        return [b["id"] for b in owner.get("bullets") or []] if kind == "projects" else []
    return list(ids)


def _where(kind, owner):
    return owner.get("name", "") if kind == "projects" else f"{owner.get('company', '')}, {owner.get('title', '')}"


class Page:
    """One application's selection, and how to rank and change it."""

    def __init__(self, master, tailor, spec, listing):
        self.master, self.tailor, self.listing = master, tailor, listing or ""
        self.reqs = [r for r in (spec or {}).get("requirements") or [] if isinstance(r, dict)]
        self.slots = []  # every selected bullet
        self.open = []  # every unselected bullet of an owner on the resume
        for oi, (kind, owner) in enumerate(_owners(master)):
            ids = _selected_ids(tailor, kind, owner)
            if ids is None:
                continue
            by_id = {b["id"]: b for b in owner.get("bullets") or []}
            base = {"kind": kind, "owner": owner["id"], "where": _where(kind, owner), "owner_index": oi}
            self.slots += [{**base, "bullet": by_id[i], "index": n} for n, i in enumerate(ids) if i in by_id]
            self.open += [{**base, "bullet": b, "index": n} for n, b in enumerate(owner.get("bullets") or [])
                          if b["id"] not in ids]

    def text(self, bullet):
        return (self.tailor.get("overrides") or {}).get(bullet["id"], bullet.get("text", ""))

    def score(self, slot):
        return score(slot["bullet"], self.text(slot["bullet"]), self.reqs, self.listing)

    def rank(self, slot):
        """Sorts lowest first: listing relevance, then priority, then older owners and later bullets."""
        return (self.score(slot), -slot["bullet"].get("priority", 3), -slot["owner_index"], -slot["index"])

    def only_backer(self, slot, removed):
        """Whether cutting this would leave a must-have requirement with no bullet behind it."""
        for r in self.reqs:
            if r.get("must") and req_matches(r, slot["bullet"]):
                left = [s for s in self.slots if req_matches(r, s["bullet"]) and s["bullet"]["id"] not in removed]
                if len(left) == 1:
                    return True
        return False

    def next_cut(self, removed):
        """The next bullet to cut, or None. A position always keeps one bullet, so a job in the
        work history never ends up as a bare heading, and the only bullet behind a must-have
        goes last."""
        left = [s for s in self.slots if s["bullet"]["id"] not in removed]
        count = {}
        for s in left:
            count[s["owner"]] = count.get(s["owner"], 0) + 1
        cuttable = [s for s in left if s["kind"] == "projects" or count[s["owner"]] > 1]
        return min(cuttable, key=lambda s: (self.only_backer(s, removed), self.rank(s)), default=None)

    def changed(self, removed=(), shorts=()):
        """A copy of the tailor without the removed bullets, with these added to `short`."""
        t = copy.deepcopy(self.tailor)
        removed = set(removed)
        for slot in self.slots:
            if slot["bullet"]["id"] not in removed or slot["kind"] != "positions":
                continue
            sel = t["positions"][slot["owner"]]
            sel["bullets"] = [i for i in sel["bullets"] if i != slot["bullet"]["id"]]
        hit = {s["owner"] for s in self.slots if s["kind"] == "projects" and s["bullet"]["id"] in removed}
        if hit:
            raw = t["projects"]
            sel = {k: None for k in raw} if isinstance(raw, list) else raw
            projects = {}
            owners = {o["id"]: o for kind, o in _owners(self.master) if kind == "projects"}
            for pid, v in sel.items():
                if pid not in hit:
                    projects[pid] = v
                    continue
                keep = [i for i in _selected_ids(self.tailor, "projects", owners[pid]) if i not in removed]
                if keep:  # a project with nothing left to say leaves the page altogether
                    projects[pid] = {**(v or {}), "bullets": keep}
            t["projects"] = projects
            if not projects:
                del t["projects"]
        overrides = {k: v for k, v in (t.get("overrides") or {}).items() if k not in removed}
        short = [i for i in t.get("short") or [] if i not in removed] + [i for i in shorts if i not in removed]
        for key, value in (("overrides", overrides), ("short", short)):
            if value:
                t[key] = value
            else:
                t.pop(key, None)
        return t

    def with_added(self, slot):
        t = copy.deepcopy(self.tailor)
        sel = t[slot["kind"]][slot["owner"]] = t[slot["kind"]][slot["owner"]] or {}
        sel["bullets"] = [*(sel.get("bullets") or []), slot["bullet"]["id"]]
        return t

    def reason(self, slot):
        fits = [r for r in self.reqs if req_matches(r, slot["bullet"])]
        priority = f"priority {slot['bullet'].get('priority', 3)}"
        if fits:
            return f"Fits: {'; '.join(r.get('text', '') for r in fits[:2])}{f' +{len(fits) - 2}' if len(fits) > 2 else ''} ({priority})"
        if self.reqs:
            return f"Backs no listing requirement ({priority})"
        n = self.score(slot)
        return f"Shares {n} word{'' if n == 1 else 's'} with the listing ({priority})"

    def item(self, slot):
        b = slot["bullet"]
        return {"id": b["id"], "kind": slot["kind"], "owner": slot["owner"], "where": slot["where"],
                "text": self.text(b), "reason": self.reason(slot)}

    def covered(self, removed=()):
        left = [s["bullet"] for s in self.slots if s["bullet"]["id"] not in removed]
        return {i for i, r in enumerate(self.reqs) if any(req_matches(r, b) for b in left)}


def _over(f):
    return (f["pages"] or 0) > 1


def _shrink(page, measure, first):
    """Apply short texts, then cut, until it fits. Then give back whatever turned out not to be
    needed, since a large late cut can make room for an earlier one. Returns (removed, shorts, fill)."""
    current, shorts, removed = first, [], []
    overrides, already = page.tailor.get("overrides") or {}, set(page.tailor.get("short") or [])
    for slot in sorted(page.slots, key=page.rank):
        b = slot["bullet"]
        if not _over(current):
            break
        if not b.get("short") or b["id"] in overrides or b["id"] in already:
            continue  # an override beats a short text, so listing it here would change nothing
        trial = measure(page.changed(shorts=[*shorts, b["id"]]))
        was, now = (f["bullets"].get(b["id"], {}).get("lines") for f in (current, trial))
        if was and now and now >= was:
            continue  # shorter words that save no line are not worth the changed wording
        shorts.append(b["id"])
        current = trial
    while _over(current):
        slot = page.next_cut(set(removed))
        if not slot:
            break
        removed.append(slot["bullet"]["id"])
        current = measure(page.changed(removed, shorts))
    if not _over(current):
        for i in reversed(removed[:-1]):
            keep = [r for r in removed if r != i]
            trial = measure(page.changed(keep, shorts))
            if not _over(trial):
                removed, current = keep, trial
        for i in list(shorts):
            keep = [s for s in shorts if s != i]
            trial = measure(page.changed(removed, keep))
            if not _over(trial):
                shorts, current = keep, trial
    return removed, shorts, current


def _suggest(master, tailor, spec, listing, measure):
    """The best unselected bullets that a test render shows still fit. A bullet with a `variant_of`
    partner is left out, whichever side of the pair it is: variants are chosen on purpose."""
    page = Page(master, tailor, spec, listing)
    paired = {b.get("variant_of") for _, o in _owners(master) for b in o.get("bullets") or []} - {None}
    open_slots = [s for s in page.open if not s["bullet"].get("variant_of") and s["bullet"]["id"] not in paired]
    open_slots.sort(key=lambda s: (-page.score(s), s["bullet"].get("priority", 3), s["owner_index"], s["index"]))
    out = []
    for slot in open_slots[:SUGGEST_TRIES]:
        trial = measure(page.with_added(slot))
        if not _over(trial):
            out.append({**page.item(slot), "fill": trial["fill"]})
            if len(out) == SUGGESTIONS:
                break
    return out


def fit_tailor(master, tailor, spec, listing, measure):
    """Returns (the fitted tailor, a report of what changed). `measure(tailor)` gives build.fill's dict."""
    first = measure(tailor)
    report = {"before": build.brief(first), "after": build.brief(first), "measured": first["pages"] is not None,
              "shortened": [], "cut": [], "uncovered": [], "suggest": [], "changed": False, "over": False}
    if not report["measured"]:
        return tailor, report
    page = Page(master, tailor, spec, listing)
    result, final = tailor, first
    if _over(first):
        removed, shorts, final = _shrink(page, measure, first)
        result = page.changed(removed, shorts)
        by_id = {s["bullet"]["id"]: s for s in page.slots}
        lost = page.covered() - page.covered(removed)
        report.update(after=build.brief(final), over=_over(final), changed=bool(removed or shorts),
                      shortened=[{**page.item(by_id[i]), "text": by_id[i]["bullet"]["short"]} for i in shorts],
                      cut=[page.item(by_id[i]) for i in removed],
                      uncovered=[{"text": page.reqs[i].get("text", ""), "must": bool(page.reqs[i].get("must"))} for i in sorted(lost)])
    elif (final["fill"] or 0) < FULL:
        report["suggest"] = _suggest(master, result, spec, listing, measure)
    return result, report


def fit_app(ws, typst, name, work_dir, apply=True):
    """Fit an application's tailor.yaml, measuring in `work_dir` (under the repo's build/, since
    typst only reads data from inside the repo). With apply=False nothing is written."""
    ws.require_editable(name)
    app = ws.app_dir(name)
    master = ws.master()
    tailor = ws._read_yaml(app / "tailor.yaml") or {}
    spec = ws._read_yaml(app / "listing.yaml")
    listing = ws._read_text(app / "listing.md") or ""

    def measure(t):
        with build.collect_warnings():  # the same warnings reach the person from the preview and the build
            data = build.resume_data(master, t)
            return build.fill(build.render(typst, build.pick_template(t) + ".typ", data, work_dir / "fit.pdf", work_dir, "fit"))

    fitted, report = fit_tailor(master, tailor, spec, listing, measure)
    report["applied"] = bool(apply and report["changed"])
    if report["applied"]:
        ws.save_tailor(name, fitted)
        report["previous"] = tailor  # for Undo
    return fitted if report["applied"] else tailor, report
