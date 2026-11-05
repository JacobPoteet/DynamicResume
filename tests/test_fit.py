"""Fit to page: what gets shortened, cut and suggested, the report, and what changed between
versions. Rendering is faked except in the typst test, so the rules can be tested exactly."""
import copy
import json
import shutil
from types import SimpleNamespace

import pytest

import build
from build import ROOT, BuildError
from conftest import EXAMPLE_APP
from studio import fit, server
from studio.changes import compare
from studio.draft import Drafts
from studio.fit import Page, fit_app, fit_tailor
from test_workspace import fake_pdfs

WORK = ROOT / "build" / "pytest" / "fit"
MASTER = {
    "basics": {"name": "A"},
    "positions": [
        {"id": "new", "company": "New Co", "title": "Lead", "bullets": [
            {"id": "n1", "text": "new one", "tags": ["ai"], "priority": 1},
            {"id": "n2", "text": "new two", "tags": [], "priority": 2},
            {"id": "n3", "text": "new three", "short": "n3 short", "tags": [], "priority": 3},
            {"id": "n4", "text": "plain four", "tags": ["ui"], "priority": 1},
            {"id": "n4v", "text": "variant four", "variant_of": "n4", "tags": ["ui"], "priority": 1},
            {"id": "n5", "text": "open five", "tags": ["ui"], "priority": 2},
            {"id": "n6", "text": "open six", "tags": [], "priority": 3},
        ]},
        {"id": "old", "company": "Old Co", "title": "Designer", "bullets": [
            {"id": "o1", "text": "old one", "tags": ["ui"], "priority": 3},
            {"id": "o2", "text": "old two", "tags": [], "priority": 3},
        ]},
        {"id": "unused", "company": "Other Co", "title": "Tester", "bullets": [
            {"id": "u1", "text": "elsewhere", "tags": ["ui"], "priority": 1},
        ]},
    ],
    "projects": [{"id": "pr", "name": "Side", "bullets": [
        {"id": "p1", "text": "side one", "tags": [], "priority": 2},
        {"id": "p2", "text": "side two", "tags": [], "priority": 2},
    ]}],
}
UI = {"text": "Interfaces", "must": False, "tags": ["ui"]}


def selection(**over):
    return {"positions": {"new": {"bullets": ["n1", "n2", "n3"]}, "old": {"bullets": ["o1", "o2"]}},
            "projects": {"pr": {"bullets": ["p1", "p2"]}}, **over}


def ids(tailor):
    projects = tailor.get("projects") or {}
    if isinstance(projects, list):  # a plain list of projects shows all their bullets
        projects = {p["id"]: {"bullets": [b["id"] for b in p["bullets"]]} for p in MASTER["projects"] if p["id"] in projects}
    return [i for v in [*(tailor.get("positions") or {}).values(), *projects.values()] for i in v["bullets"]]


def fake_measure(room, heavy=None, short_saves=True):
    """A page holding `room` lines. A bullet takes two lines, or one with a short text that saves
    a line (the master's only short text is on n3); `heavy` gives some bullets more."""
    def measure(t):
        shorter = set(t.get("short") or []) if short_saves else set()
        bullets = {i: {"lines": 1 if i in shorter else (heavy or {}).get(i, 2), "last": 0.5} for i in ids(t)}
        used = sum(b["lines"] for b in bullets.values())
        return {"pages": 2 if used > room else 1, "fill": round(min(1, used / room), 3),
                "spill_lines": max(0, used - room), "bullets": bullets, "wraps": []}
    return measure


def test_a_full_page_changes_nothing():
    t = selection()
    new, r = fit_tailor(MASTER, t, None, "", fake_measure(14))
    assert new == t and not r["changed"] and not r["cut"] and not r["suggest"]


def test_short_texts_go_first_and_can_be_enough():
    new, r = fit_tailor(MASTER, selection(), None, "", fake_measure(13))
    assert new["short"] == ["n3"] and ids(new) == ids(selection())
    assert [(b["id"], b["text"]) for b in r["shortened"]] == [("n3", "n3 short")]
    assert r["cut"] == [] and r["changed"]


def test_a_short_text_that_saves_no_line_is_not_used():
    new, r = fit_tailor(MASTER, selection(), None, "", fake_measure(12, short_saves=False))
    assert "short" not in new and r["shortened"] == [] and r["cut"]


def test_an_override_keeps_its_wording_rather_than_a_short_text():
    new, r = fit_tailor(MASTER, selection(overrides={"n3": "reworded"}), None, "", fake_measure(13))
    assert "short" not in new and r["shortened"] == []
    assert new["overrides"] == {"n3": "reworded"}


def test_a_short_text_not_needed_after_a_big_cut_is_given_back():
    new, r = fit_tailor(MASTER, selection(), None, "", fake_measure(12, heavy={"o2": 4}))
    assert [b["id"] for b in r["cut"]] == ["o2"]
    assert "short" not in new and r["shortened"] == []


def test_relevance_decides_before_priority():
    # o1 is priority 3 but backs a requirement; n1 is priority 1 and backs none, so it goes first.
    spec = {"requirements": [UI]}
    new, r = fit_tailor(MASTER, selection(), spec, "", fake_measure(12))
    assert "o1" in ids(new)
    assert r["cut"][0]["reason"] == "Backs no listing requirement (priority 3)"
    page = Page(MASTER, selection(), spec, "")
    order = [s["bullet"]["id"] for s in sorted(page.slots, key=page.rank)]
    assert order.index("n1") < order.index("o1")


def test_ties_cut_low_priority_then_older_then_later_bullets():
    page = Page(MASTER, selection(), None, "")
    order = [s["bullet"]["id"] for s in sorted(page.slots, key=page.rank)]
    assert order == ["o2", "o1", "n3", "p2", "p1", "n2", "n1"]


def test_with_no_requirements_relevance_is_shared_words():
    listing = "We want someone who shipped a tremendous interface"
    master = copy.deepcopy(MASTER)
    master["positions"][1]["bullets"][1]["text"] = "Shipped a tremendous interface"
    page = Page(master, selection(), None, listing)
    order = [s["bullet"]["id"] for s in sorted(page.slots, key=page.rank)]
    assert order.index("o2") == len(order) - 1


def test_the_only_backer_of_a_must_have_goes_last():
    spec = {"requirements": [{"text": "Sole", "must": True, "bullets": ["o2"]},
                             *[{"text": "Common", "must": True, "bullets": ["n1", "n2", "n3", "p1", "p2", "o1"]}] * 2]}
    page = Page(MASTER, selection(), spec, "")
    # o2 scores lowest, but nothing else backs "Sole".
    assert page.next_cut(set())["bullet"]["id"] != "o2"
    assert page.next_cut({"n1", "n2", "p1", "p2"})["bullet"]["id"] != "o2"


def test_a_position_keeps_its_last_bullet_and_the_report_says_it_is_still_over():
    new, r = fit_tailor(MASTER, selection(), None, "", fake_measure(1))
    assert len(new["positions"]["old"]["bullets"]) == len(new["positions"]["new"]["bullets"]) == 1
    assert "projects" not in new  # a project can leave the page entirely
    assert r["over"] is True and r["after"]["pages"] == 2


def test_a_cut_that_turned_out_not_to_be_needed_is_given_back():
    # o2 goes first and is not enough; p2 is huge, so cutting it makes room for o2 again.
    t = selection(positions={"new": {"bullets": ["n1", "n2"]}, "old": {"bullets": ["o1", "o2"]}})
    new, r = fit_tailor(MASTER, t, None, "", fake_measure(12, heavy={"p2": 6}))
    assert [b["id"] for b in r["cut"]] == ["p2"]
    assert "o2" in ids(new)


def test_a_cut_bullet_loses_its_override_and_short_entry():
    t = selection(overrides={"o2": "x", "n1": "kept"}, short=["o2"])
    new, _ = fit_tailor(MASTER, t, None, "", fake_measure(11))
    assert "o2" not in ids(new)
    assert new["overrides"] == {"n1": "kept"} and "o2" not in new["short"]


def test_cutting_from_a_project_listed_without_ids():
    t = {"positions": {"new": {"bullets": ["n1"]}}, "projects": ["pr"]}
    new, _ = fit_tailor(MASTER, t, None, "", fake_measure(4))
    assert new["projects"] == {"pr": {"bullets": ["p1"]}}


def test_over_a_page_it_only_removes_and_never_rewords():
    t = selection(overrides={"n1": "my words"})
    new, _ = fit_tailor(MASTER, t, None, "", fake_measure(8))
    assert new["overrides"] == {"n1": "my words"}
    assert set(ids(new)) < set(ids(t))
    assert t == selection(overrides={"n1": "my words"})  # the input is left alone


def test_the_report_names_requirements_that_lost_coverage():
    spec = {"requirements": [{"text": "Backed by old", "must": False, "bullets": ["o2"]},
                             {"text": "Still fine", "must": True, "bullets": ["n1", "n2", "n3", "o1", "p1", "p2"]}]}
    _, r = fit_tailor(MASTER, selection(), spec, "", fake_measure(12))
    assert r["uncovered"] == [{"text": "Backed by old", "must": False}]


def test_room_left_suggests_the_best_fit_without_adding():
    t = {"positions": {"new": {"bullets": ["n1", "n2"]}, "old": {"bullets": ["o2"]}}}
    new, r = fit_tailor(MASTER, t, {"requirements": [UI]}, "", fake_measure(40))
    assert new == t and not r["changed"]
    assert [b["id"] for b in r["suggest"]] == ["n5", "o1", "n3"]
    assert r["suggest"][0]["fill"] == 0.2 and r["suggest"][0]["owner"] == "new"


def test_suggestions_never_include_either_side_of_a_variant_pair():
    t = {"positions": {"new": {"bullets": ["n1"]}}}
    _, r = fit_tailor(MASTER, t, {"requirements": [UI]}, "", fake_measure(100))
    assert r["suggest"] and not {"n4", "n4v"} & {b["id"] for b in r["suggest"]}


def test_suggestions_skip_what_would_overflow():
    t = {"positions": {"new": {"bullets": ["n1", "n2", "n3"]}}}
    _, r = fit_tailor(MASTER, t, {"requirements": [UI]}, "", fake_measure(8, heavy={"n5": 3}))
    assert [b["id"] for b in r["suggest"]] == ["n6"]


def test_suggestions_stay_on_positions_already_on_the_page():
    t = {"positions": {"new": {"bullets": ["n1"]}}}
    _, r = fit_tailor(MASTER, t, None, "", fake_measure(100))
    assert r["suggest"] and all(b["owner"] == "new" for b in r["suggest"])


def test_a_page_that_cannot_be_measured_is_left_alone():
    t = selection()
    new, r = fit_tailor(MASTER, t, None, "", lambda _: build.fill({}))
    assert new == t and r["measured"] is False and not r["changed"]


def test_the_editor_scores_with_the_same_stop_words(ws):
    assert server.init(SimpleNamespace(example=True, ws=ws), {}, {})["stop_words"] == sorted(fit.STOP)


# ----- files: the real workspace, with the page faked -----

@pytest.fixture
def small_page(monkeypatch):
    """Rendering reports a page that the demo application overflows."""
    def render(typst, template, data, out, work_dir, name):
        used = sum(len(o["bullets"]) * 2 for k in ("positions", "projects") for o in data[k])
        return {"pages": 2 if used > 10 else 1, "top": 0, "limit": 10, "end": min(used, 10)}
    monkeypatch.setattr(build, "render", render)
    monkeypatch.setattr(build, "find_typst", lambda: "typst")


def demo_bullets(ws):
    return ids(build.load_yaml(ws.apps_dir / EXAMPLE_APP / "tailor.yaml"))


def test_fit_app_writes_the_result_and_keeps_what_undo_needs(ws, small_page):
    before = demo_bullets(ws)
    fitted, r = fit_app(ws, "typst", EXAMPLE_APP, WORK)
    assert r["applied"] and r["cut"] and ids(fitted) == demo_bullets(ws)
    assert ids(r["previous"]) == before and len(demo_bullets(ws)) < len(before)


def test_report_mode_writes_nothing(ws, small_page):
    path = ws.apps_dir / EXAMPLE_APP / "tailor.yaml"
    was = path.read_bytes()
    _, r = fit_app(ws, "typst", EXAMPLE_APP, WORK, apply=False)
    assert r["cut"] and not r["applied"] and "previous" not in r
    assert path.read_bytes() == was


def test_a_submitted_application_cannot_be_fitted(ws, small_page):
    fake_pdfs(ws)
    ws.submit_app(EXAMPLE_APP, "2026-11-01")
    with pytest.raises(BuildError, match="submitted"):
        fit_app(ws, "typst", EXAMPLE_APP, WORK)


def test_a_draft_is_fitted_and_reports_it(ws, small_page):
    result = {"warnings": []}
    Drafts(ws, None, WORK).fit_draft(EXAMPLE_APP, result)
    assert result["fit"]["cut"] and result["fit"]["applied"] and result["warnings"] == []


def test_a_draft_that_cannot_render_stays_as_written(ws, monkeypatch):
    def missing():
        raise BuildError("typst not found")
    monkeypatch.setattr(build, "find_typst", missing)
    before = demo_bullets(ws)
    result = {"warnings": []}
    Drafts(ws, None, WORK).fit_draft(EXAMPLE_APP, result)
    assert "fit" not in result and "not fitted" in result["warnings"][0] and demo_bullets(ws) == before


def fit_studio(ws, state="idle"):
    return SimpleNamespace(ws=ws, typst="typst", build_dir=WORK, versions=lambda name=None: {},
                           preview=lambda *a, **k: {"ok": True}, drafts=SimpleNamespace(status=lambda n: {"state": state}))


def test_the_fit_route_will_not_overwrite_an_outside_edit(ws, small_page):
    s = fit_studio(ws)
    server.get_app(s, {}, {}, EXAMPLE_APP)
    path = ws.apps_dir / EXAMPLE_APP / "tailor.yaml"
    path.write_text(path.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
    assert server.fit_page(s, {}, {}, EXAMPLE_APP) == {"conflict": ["tailor.yaml"]}
    r = server.fit_page(s, {"keep": ["tailor.yaml"]}, {}, EXAMPLE_APP)
    assert r["report"]["cut"] and ids(r["tailor"]) == demo_bullets(ws)


def test_the_fit_route_refuses_while_a_draft_runs(ws):
    with pytest.raises(BuildError, match="draft is running"):
        server.fit_page(fit_studio(ws, "running"), {}, {}, EXAMPLE_APP)


# ----- what changed between versions -----

def test_compare_finds_each_kind_of_change():
    old = {"headline": "A", "skills_first": ["x"], "projects": ["pr"],
           "positions": {"new": {"bullets": ["n1", "n2", "n3"]}, "old": {"bullets": ["o1"]}}}
    new = {"headline": "B", "skills_first": ["y"], "overrides": {"n1": "reworded"},
           "positions": {"new": {"bullets": ["n3", "n1", "n2", "n5"]}}, "projects": {"pr": {"bullets": ["p1"]}}}
    c = compare(MASTER, old, new, "One.\n\nTwo.\n", "One.\n\nThree.\n")
    assert [b["id"] for b in c["added"]] == ["n5"]
    assert {b["id"] for b in c["removed"]} == {"o1", "p2"}
    assert [b["id"] for b in c["moved"]] == ["n3"]
    assert c["reworded"] == [{"id": "n1", "where": "New Co, Lead", "text": "reworded", "before": "new one"}]
    assert {f["label"] for f in c["fields"]} == {"Headline", "Skills moved to the front"}
    assert c["letter"] == [{"change": "removed", "text": "Two."}, {"change": "added", "text": "Three."}]


def test_compare_of_identical_versions_is_empty():
    t = selection(short=["n3"])
    assert compare(MASTER, t, copy.deepcopy(t), "x", "x") == {}


def test_changes_show_before_and_after_the_new_version_is_built(ws):
    app = ws.apps_dir / EXAMPLE_APP
    tailor = build.load_yaml(app / "tailor.yaml")
    letter = (app / "cover-letter.md").read_text(encoding="utf-8")
    assert ws.changes(EXAMPLE_APP) is None  # nothing kept yet
    build.remember_version(app, False, tailor, letter)
    assert ws.changes(EXAMPLE_APP) is None  # the first version has nothing before it

    edited = {**tailor, "headline": "Something else"}
    ws.save_tailor(EXAMPLE_APP, edited)  # a rewrite, say from a chat
    assert ws.changes(EXAMPLE_APP)["fields"][0]["after"] == "Something else"
    build.remember_version(app, False, edited, letter)  # as its build does
    assert ws.changes(EXAMPLE_APP)["fields"][0]["after"] == "Something else"


def test_two_different_versions_are_kept(ws):
    app = ws.apps_dir / EXAMPLE_APP
    for h in "abcc":
        build.remember_version(app, False, {"headline": h}, "")
    kept = json.loads(build.versions_path(app, False).read_text(encoding="utf-8"))
    assert [v["tailor"]["headline"] for v in kept] == ["b", "c"]


def test_deleting_an_application_forgets_its_versions(ws):
    app = ws.apps_dir / EXAMPLE_APP
    build.remember_version(app, False, {"headline": "a"}, "")
    ws.delete_app(EXAMPLE_APP)
    assert not build.versions_path(app, False).exists()


def test_a_submitted_application_shows_no_changes(ws):
    app = ws.apps_dir / EXAMPLE_APP
    build.remember_version(app, False, {"headline": "older"}, "")
    fake_pdfs(ws)
    ws.submit_app(EXAMPLE_APP, "2026-11-01")
    assert ws.load_app(EXAMPLE_APP)["changes"] is None


# ----- the real page -----

@pytest.mark.typst
def test_a_real_overflow_ends_on_one_page(ws):
    """The demo with every bullet selected and long wording runs over; the result fits and keeps
    every position."""
    try:
        typst = build.find_typst()
    except BuildError:
        pytest.skip("typst is not installed")
    work = ROOT / "build" / "pytest" / "fit-real"
    shutil.rmtree(work, ignore_errors=True)
    t = build.load_yaml(ws.apps_dir / EXAMPLE_APP / "tailor.yaml")
    t["positions"] = {p["id"]: {"bullets": [b["id"] for b in p["bullets"] if not b.get("variant_of")]}
                      for p in ws.master()["positions"]}
    t["projects"] = {p["id"]: {"bullets": [b["id"] for b in p.get("bullets") or []]} for p in ws.master()["projects"]}
    t["overrides"] = {i: "Long wording that takes up a good deal of room on the page. " * 6 for i in ids(t)}
    ws.save_tailor(EXAMPLE_APP, t)
    fitted, r = fit_app(ws, typst, EXAMPLE_APP, work)
    assert r["before"]["pages"] > 1
    assert r["after"]["pages"] == 1 and r["cut"]
    assert all(v["bullets"] for v in fitted["positions"].values())
    assert set(ids(fitted)) < set(ids(t))
