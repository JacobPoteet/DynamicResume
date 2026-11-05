"""Start from another application: what is copied, what never is, and what is dropped."""
import pytest
import yaml

import build
from conftest import EXAMPLE_APP

COPIED = ("template", "paper", "headline", "games", "positions", "skills_first", "skill_groups", "projects",
          "overrides", "short")


def rich_source(ws):
    """The example application with every copied key set, plus files that must not travel."""
    app = ws.app_dir(EXAMPLE_APP)
    t = build.load_yaml(app / "tailor.yaml")
    t.update({"paper": "a4", "template": "resume-games", "games": [g["id"] for g in ws.master()["games"]][:1],
              "skills_first": ["Unreal Engine"], "skill_groups": [g["group"] for g in ws.master()["skills"]][:1],
              "overrides": {"rr-lead": "Led a team of five."}, "short": ["rr-boosts"]})
    ws.save_tailor(EXAMPLE_APP, t)
    (app / "cover-letter.md").write_text("Old studio letter.\n", encoding="utf-8")
    (app / "job.yaml").write_text("pay: 1\n", encoding="utf-8")
    (app / "tracking.yaml").write_text("events: []\n", encoding="utf-8")
    (app / "listing.yaml").write_text("studio: Old\n", encoding="utf-8")
    (app / "Old_Resume.pdf").write_bytes(b"%PDF-1.7")
    return app


def write_master(ws, m):
    ws.master_path.write_text(yaml.safe_dump(m, sort_keys=False), encoding="utf-8")


def test_copies_the_selection_with_a_new_target_and_listing(ws):
    src = rich_source(ws)
    old = build.load_yaml(src / "tailor.yaml")
    name = ws.create_app("New Place", "Systems Designer", "New listing text.", start_from=EXAMPLE_APP)
    loaded = ws.load_app(name)
    new = loaded["tailor"]
    assert new["target"] == {"studio": "New Place", "role": "Systems Designer"}
    for k in COPIED:
        assert new[k] == old[k], k
    assert "cover_letter" not in new  # the greeting names the old studio
    assert "New listing text." in loaded["listing"] and "Harbor Light" not in loaded["listing"]
    build.resolve(ws.master(), new, False)  # it builds


def test_never_copies_the_letter_unless_asked_nor_tracking_or_job_details(ws):
    rich_source(ws)
    name = ws.create_app("New Place", "Systems Designer", "x", start_from=EXAMPLE_APP)
    assert sorted(p.name for p in ws.app_dir(name).iterdir()) == ["listing.md", "tailor.yaml"]
    name2 = ws.create_app("New Place", "Systems Designer", "x", start_from=EXAMPLE_APP, copy_letter=True)
    assert (ws.app_dir(name2) / "cover-letter.md").read_text(encoding="utf-8") == "Old studio letter.\n"
    assert sorted(p.name for p in ws.app_dir(name2).iterdir()) == ["cover-letter.md", "listing.md", "tailor.yaml"]


def test_a_submitted_source_is_read_from_what_was_sent(ws):
    src = rich_source(ws)
    resume, letter = build.output_names(ws.master(), build.load_yaml(src / "tailor.yaml"), src)
    for f in (resume, letter):
        (src / f).write_bytes(b"%PDF-1.7")
    ws.submit_app(EXAMPLE_APP, "2026-11-01")
    sent = build.load_yaml(src / "submitted" / "tailor.yaml")
    (src / "tailor.yaml").write_text("target: {studio: S, role: R}\nheadline: Changed live\n", encoding="utf-8")
    (src / "cover-letter.md").write_text("Changed live.\n", encoding="utf-8")
    name = ws.create_app("New Place", "Designer", "x", start_from=EXAMPLE_APP, copy_letter=True)
    assert ws.load_app(name)["tailor"]["headline"] == sent["headline"]
    assert ws.load_app(name)["letter"] == "Old studio letter.\n"
    folder = ws.app_dir(name)
    assert not (folder / "submitted").exists() and not list(folder.glob("*.pdf"))
    assert (src / "submitted" / "submitted.yaml").exists()  # the source is untouched


def test_ids_the_master_no_longer_has_are_dropped_and_reported(ws):
    rich_source(ws)
    m = ws.master()
    pos = next(p for p in m["positions"] if p["id"] == "pixel-forge-sr")
    pos["bullets"] = [b for b in pos["bullets"] if b["id"] != "rr-lead"]  # also overridden in the source
    m["projects"] = []
    write_master(ws, m)
    r = ws.create_app_from("New Place", "Designer", "x", EXAMPLE_APP)
    assert {"rr-lead", "sample-project"} <= set(r["dropped"]) and len(r["dropped"]) == len(set(r["dropped"]))
    t = ws.load_app(r["name"])["tailor"]
    assert "rr-lead" not in t["positions"]["pixel-forge-sr"]["bullets"] and "rr-lead" not in t.get("overrides", {})
    assert "sample-project" not in (t.get("projects") or {})
    build.resolve(ws.master(), t, False)


def test_a_bullet_that_became_a_variant_of_another_picked_one_is_dropped(ws):
    rich_source(ws)
    m = ws.master()
    pos = next(p for p in m["positions"] if p["id"] == "pixel-forge-sr")
    next(b for b in pos["bullets"] if b["id"] == "rr-playtests")["variant_of"] = "rr-boosts"
    write_master(ws, m)
    r = ws.create_app_from("New Place", "Designer", "x", EXAMPLE_APP)
    assert r["dropped"] == ["rr-playtests"]
    build.resolve(ws.master(), ws.load_app(r["name"])["tailor"], False)


def test_a_missing_source_is_an_error_and_leaves_nothing(ws):
    before = sorted(p.name for p in ws.apps_dir.iterdir())
    with pytest.raises(build.BuildError, match="no application named"):
        ws.create_app("New Place", "Designer", "x", start_from="nope")
    assert sorted(p.name for p in ws.apps_dir.iterdir()) == before


def test_the_route_starts_from_another_application(ws):
    from studio.server import create_app
    s = type("S", (), {"ws": ws})()
    r = create_app(s, {"studio": "Test Forge", "role": "Designer", "listing": "x", "start_from": EXAMPLE_APP}, {})
    assert r == {"name": "test-forge-designer", "dropped": []}
    again = create_app(s, {"studio": "Test Forge", "role": "Designer", "listing": "y"}, {})
    assert again["name"] == "test-forge-designer-2"
