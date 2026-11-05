"""Application folders: submitting, snapshots, round-trip YAML, gaps and studio notes."""
import os
import re
import subprocess
import sys

import pytest
import yaml

import build
from conftest import EXAMPLE_APP, REPO


def fake_pdfs(ws, name=EXAMPLE_APP, content=b"%PDF-1.7 sent"):
    """Stand-in PDFs, so these tests need no typst."""
    app = ws.apps_dir / name
    tailor = build.load_yaml(app / "tailor.yaml")
    resume, letter = build.output_names(ws.master(), tailor, app)
    for f in (resume, letter):
        (app / f).write_bytes(content)
    return app, resume, letter


# ----- submit -----

def test_submit_freezes_the_pdfs_and_inputs(ws):
    app, resume, letter = fake_pdfs(ws)
    r = ws.submit_app(EXAMPLE_APP, "2026-10-22")
    sent = app / "submitted"
    assert r["date"] == "2026-10-22" and r["resume"] == resume and r["letter"] == letter
    for f in (resume, letter, "tailor.yaml", "cover-letter.md", "listing.md", "listing.yaml", "master.yaml", "submitted.yaml"):
        assert (sent / f).exists(), f
    assert build.submission(app)["date"] == "2026-10-22"


def test_submit_needs_a_resume_pdf_and_a_real_date(ws):
    for pdf in (ws.apps_dir / EXAMPLE_APP).glob("*.pdf"):
        pdf.unlink()  # the demo folder ships with its PDFs
    with pytest.raises(build.BuildError, match="no resume PDF"):
        ws.submit_app(EXAMPLE_APP)
    fake_pdfs(ws)
    with pytest.raises(build.BuildError, match="should look like"):
        ws.submit_app(EXAMPLE_APP, "10/22")


def test_a_submitted_application_is_frozen(ws):
    fake_pdfs(ws)
    ws.submit_app(EXAMPLE_APP, "2026-10-22")
    with pytest.raises(build.BuildError, match="already marked"):
        ws.submit_app(EXAMPLE_APP)
    with pytest.raises(build.BuildError, match="Unsubmit it"):
        ws.require_editable(EXAMPLE_APP)
    with pytest.raises(build.BuildError, match="PDFs are frozen"):
        build.build_app(None, ws.apps_dir / EXAMPLE_APP, False)
    # Its bullets no longer pin the master: the frozen copy has its own.
    assert not any(EXAMPLE_APP in apps for apps in ws.bullet_usage().values())


def test_unsubmit_removes_an_unchanged_copy(ws):
    app, _, _ = fake_pdfs(ws)
    ws.submit_app(EXAMPLE_APP, "2026-10-22")
    assert ws.unsubmit_app(EXAMPLE_APP) == {"kept": None}
    assert not (app / "submitted").exists()
    ws.require_editable(EXAMPLE_APP)


def test_unsubmit_keeps_the_sent_pdfs_when_they_changed(ws):
    app, resume, _ = fake_pdfs(ws)
    ws.submit_app(EXAMPLE_APP, "2026-10-22")
    (app / resume).write_bytes(b"%PDF-1.7 rebuilt")
    r = ws.unsubmit_app(EXAMPLE_APP)
    kept = app / "submitted-2026-10-22"
    assert r["kept"].endswith("submitted-2026-10-22")
    assert (kept / resume).read_bytes() == b"%PDF-1.7 sent"


# ----- are the PDFs out of date? -----

def built(ws, name=EXAMPLE_APP):
    """Stand-in PDFs plus what a real build records about them."""
    app, _, _ = fake_pdfs(ws, name)
    tailor = build.load_yaml(app / "tailor.yaml")
    build.record_build(app, False, ws.master(), tailor, (app / "cover-letter.md").read_text(encoding="utf-8"), {}, None)
    return app


def stale(ws, app=None):
    app = app or ws.apps_dir / EXAMPLE_APP
    return {k: v["stale"] for k, v in ws.pdf_status(app, build.load_yaml(app / "tailor.yaml")).items()}


def edit_master(ws, change):
    m = ws.master()
    change(m)
    ws.save_master(m)


def bullet(master, bullet_id):
    return next(b for o in master["positions"] + master["projects"] for b in o["bullets"] if b["id"] == bullet_id)


def edit_tailor(ws, change):
    path = ws.apps_dir / EXAMPLE_APP / "tailor.yaml"
    t = build.load_yaml(path)
    change(t)
    ws.save_tailor(EXAMPLE_APP, t)


UNUSED = "rr-live-model"  # a demo bullet the sample application does not select
CURRENT = {"resume": False, "letter": False}
RESUME_ONLY = {"resume": True, "letter": False}
LETTER_ONLY = {"resume": False, "letter": True}
BOTH = {"resume": True, "letter": True}


def test_a_fresh_build_is_current(ws):
    built(ws)
    assert stale(ws) == CURRENT


@pytest.mark.parametrize("change", [
    lambda m: bullet(m, UNUSED).update(text="Reworded, but no application shows it"),
    lambda m: m["positions"][0]["bullets"].append({"id": "brand-new", "text": "A new bullet", "tags": [], "priority": 3}),
    lambda m: bullet(m, "rr-boosts").update(tags=["new-tag"], priority=3),  # neither is printed
    lambda m: m["basics"].update(headline="A default the tailor's own headline replaces"),
    lambda m: m["games"].append({"id": "new-game", "name": "New Game", "start": "2026-01", "end": "present"}),  # no Games section
], ids=["unselected-bullet", "new-bullet", "tags-and-priority", "default-headline", "new-game"])
def test_a_master_edit_that_does_not_reach_the_page_leaves_pdfs_current(ws, change):
    built(ws)
    edit_master(ws, change)
    assert stale(ws) == CURRENT


@pytest.mark.parametrize("change, expected", [
    (lambda m: bullet(m, "rr-boosts").update(text="Reworded on the page"), RESUME_ONLY),
    (lambda m: m["basics"].update(phone="555-0100"), BOTH),  # in both headers
    (lambda m: m["skills"][0]["items"].append("A new skill"), RESUME_ONLY),
], ids=["selected-bullet", "contact-line", "skills"])
def test_a_master_edit_that_reaches_the_page_marks_pdfs_out_of_date(ws, change, expected):
    built(ws)
    edit_master(ws, change)
    assert stale(ws) == expected


def test_a_new_game_counts_for_the_template_that_lists_games(ws):
    edit_tailor(ws, lambda t: t.update(template="resume-games"))
    built(ws)
    edit_master(ws, lambda m: m["games"].append({"id": "new-game", "name": "New Game", "start": "2026-01", "end": "present"}))
    assert stale(ws) == RESUME_ONLY


@pytest.mark.parametrize("change, expected", [
    (lambda t: t.update(headline="A new headline"), BOTH),
    (lambda t: t.update(template="resume-games"), RESUME_ONLY),
    (lambda t: t["positions"]["pixel-forge-sr"]["bullets"].pop(), RESUME_ONLY),
    (lambda t: t["cover_letter"].update(greeting="Hello,"), LETTER_ONLY),
    (lambda t: t["target"].update(role="A role name is not printed"), CURRENT),
], ids=["headline", "template", "bullet", "greeting", "role"])
def test_tailor_edits(ws, change, expected):
    built(ws)
    edit_tailor(ws, change)
    assert stale(ws) == expected


def test_a_letter_edit_marks_only_the_letter(ws):
    built(ws)
    ws.save_text(EXAMPLE_APP, "cover-letter.md", "A different letter.\n")
    assert stale(ws) == LETTER_ONLY


def test_undoing_an_edit_makes_pdfs_current_again(ws):
    built(ws)
    before = bullet(ws.master(), "rr-boosts")["text"]
    edit_master(ws, lambda m: bullet(m, "rr-boosts").update(text="Reworded"))
    assert stale(ws) == RESUME_ONLY
    edit_master(ws, lambda m: bullet(m, "rr-boosts").update(text=before))
    assert stale(ws) == CURRENT


def test_a_tailor_that_no_longer_builds_counts_as_out_of_date(ws):
    built(ws)
    edit_tailor(ws, lambda t: t["positions"]["pixel-forge-sr"]["bullets"].append("edited-in-by-hand"))
    assert stale(ws) == RESUME_ONLY


def test_pdfs_with_no_recorded_hash_fall_back_to_file_times(ws):
    app, resume, letter = fake_pdfs(ws)
    inputs = [ws.master_path, app / "tailor.yaml", app / "cover-letter.md"]
    for f in inputs:
        os.utime(f, (1_000_000, 1_000_000))
    for f in (resume, letter):
        os.utime(app / f, (2_000_000, 2_000_000))
    assert stale(ws) == CURRENT
    os.utime(ws.master_path, (3_000_000, 3_000_000))  # any newer input, as before
    assert stale(ws) == BOTH


def test_a_record_from_before_hashes_also_falls_back(ws):
    app, _, _ = fake_pdfs(ws)
    p = build.fit_path(app, False)
    p.parent.mkdir(parents=True)
    p.write_text('{"built": "2026-10-22 10:00", "resume": {}, "letter": null}', encoding="utf-8")
    os.utime(ws.master_path, (4_000_000_000, 4_000_000_000))  # newer than the PDFs just written
    assert stale(ws) == BOTH


# ----- snapshots -----

def test_snapshots_keep_sent_pdfs_but_not_built_ones(ws):
    app, resume, _ = fake_pdfs(ws)
    ws.submit_app(EXAMPLE_APP, "2026-10-22")
    names = [ws._member(f) for f in ws._snapshot_files()]
    assert f"applications/{EXAMPLE_APP}/submitted/{resume}" in names
    assert f"applications/{EXAMPLE_APP}/{resume}" not in names
    assert "data/master.yaml" in names and "templates/timeline.typ" in names


def test_restore_puts_files_back(ws):
    snap = ws.create_snapshot("test")
    before = ws.master_text()
    ws.master_path.write_text("broken: true\n", encoding="utf-8")
    r = ws.restore_snapshot(snap["name"])
    assert ws.master_text() == before
    assert r["backup"].endswith("before-restore.zip")


def submitted_with_events(ws):
    fake_pdfs(ws)
    ws.submit_app(EXAMPLE_APP, "2026-10-22")
    ws.add_event(EXAMPLE_APP, {"stage": "screen", "date": "2026-10-25"})
    return ws.apps_dir / EXAMPLE_APP / "tracking.yaml"


def test_restore_keeps_the_current_tracking_history(ws):
    tracking = submitted_with_events(ws)
    (ws.apps_dir / EXAMPLE_APP / "tailor.yaml").write_text("headline: From the snapshot\n", encoding="utf-8")
    snap = ws.create_snapshot("test")
    ws.add_event(EXAMPLE_APP, {"stage": "rejected", "date": "2026-11-01"})
    logged = tracking.read_text(encoding="utf-8")
    (ws.apps_dir / EXAMPLE_APP / "tailor.yaml").write_text("headline: Edited later\n", encoding="utf-8")
    r = ws.restore_snapshot(snap["name"])
    assert tracking.read_text(encoding="utf-8") == logged  # what really happened stays
    assert r["kept_tracking"] == len(list(ws.apps_dir.glob("*/tracking.yaml")))
    assert "From the snapshot" in (ws.apps_dir / EXAMPLE_APP / "tailor.yaml").read_text(encoding="utf-8")  # edits roll back


def test_restore_brings_back_tracking_for_a_deleted_application(ws):
    tracking = submitted_with_events(ws)
    logged = tracking.read_text(encoding="utf-8")
    snap = ws.create_snapshot("test")
    ws.delete_app(EXAMPLE_APP)
    r = ws.restore_snapshot(snap["name"])
    assert tracking.read_text(encoding="utf-8") == logged
    assert r["kept_tracking"] == len(list(ws.apps_dir.glob("*/tracking.yaml"))) - 1  # all but the one that came back
    assert ws.track(ws.apps_dir / EXAMPLE_APP)["column"] == "screen"


def test_restore_refuses_unknown_names(ws):
    with pytest.raises(build.BuildError):
        ws.restore_snapshot("../../etc.zip")


# ----- round-trip YAML -----

def test_saving_a_tailor_keeps_its_comments(ws):
    t = build.load_yaml(ws.apps_dir / EXAMPLE_APP / "tailor.yaml")
    t["headline"] = "Gameplay Designer | Combat"
    ws.save_tailor(EXAMPLE_APP, t)
    text = (ws.apps_dir / EXAMPLE_APP / "tailor.yaml").read_text(encoding="utf-8")
    assert "headline: Gameplay Designer | Combat" in text
    assert "# Reword a bullet for this listing without touching the master:" in text


def test_saving_a_tailor_keeps_a_new_project_order(ws):
    path = ws.apps_dir / EXAMPLE_APP / "tailor.yaml"
    before = path.read_text(encoding="utf-8")
    t = build.load_yaml(path)
    t["projects"] = dict(reversed(list(t["projects"].items())))
    ws.save_tailor(EXAMPLE_APP, t)
    assert list(build.load_yaml(path)["projects"]) == list(t["projects"])
    text = path.read_text(encoding="utf-8")
    assert "# printed in this order" in text and text.count("\n\n") == before.count("\n\n")


def test_saving_the_master_keeps_comments_and_history(ws):
    m = ws.master()
    m["positions"][0]["bullets"][0]["short"] = "Led ranked mode design"
    ws.save_master(m)
    text = ws.master_text()
    assert "short: Led ranked mode design" in text
    assert "# Optional tighter wording" in text and "variant_of makes" in text  # comments survive
    assert len(list(ws.history_dir.glob("master_*.yaml"))) == 1


def test_save_master_refuses_an_invalid_master(ws):
    m = ws.master()
    m["positions"][0]["bullets"][0]["variant_of"] = "missing"
    before = ws.master_text()
    with pytest.raises(build.BuildError):
        ws.save_master(m)
    assert ws.master_text() == before


# ----- removing a bullet an application uses -----

def without(master, bullet):
    """The master minus one bullet."""
    for o in master["positions"] + master.get("projects", []):
        o["bullets"] = [b for b in o.get("bullets") or [] if b["id"] != bullet]
    return master


def save_both_ways(ws):
    """The Bullets view's save and the Raw YAML save."""
    return [ws.save_master, lambda m: ws.save_master_text(yaml.safe_dump(m, sort_keys=False))]


@pytest.mark.parametrize("path", [0, 1], ids=["bullets", "raw"])
def test_saving_refuses_to_remove_a_selected_bullet(ws, path):
    before = ws.master_text()
    with pytest.raises(build.BuildError, match=rf"rr-boosts \(used by {EXAMPLE_APP}\)"):
        save_both_ways(ws)[path](without(ws.master(), "rr-boosts"))
    assert ws.master_text() == before


@pytest.mark.parametrize("path", [0, 1], ids=["bullets", "raw"])
def test_saving_refuses_to_remove_an_overridden_bullet(ws, path):
    t = ws.apps_dir / EXAMPLE_APP / "tailor.yaml"
    tailor = build.load_yaml(t)
    unused = next(b["id"] for b in ws.master()["positions"][0]["bullets"]
                  if b["id"] not in tailor["positions"]["pixel-forge-sr"]["bullets"])
    tailor["overrides"][unused] = "Reworded"
    ws.save_tailor(EXAMPLE_APP, tailor)
    with pytest.raises(build.BuildError, match=rf"{unused} \(used by {EXAMPLE_APP}\)"):
        save_both_ways(ws)[path](without(ws.master(), unused))


def test_saving_refuses_to_rename_or_move_a_selected_bullet(ws):
    m = ws.master()
    next(b for b in m["positions"][0]["bullets"] if b["id"] == "rr-boosts")["id"] = "rr-renamed"
    with pytest.raises(build.BuildError, match="rr-boosts"):
        ws.save_master(m)
    m = ws.master()
    b = next(b for b in m["positions"][0]["bullets"] if b["id"] == "rr-boosts")
    m["positions"][0]["bullets"].remove(b)
    m["positions"][1]["bullets"].append(b)
    with pytest.raises(build.BuildError, match="rr-boosts"):
        ws.save_master(m)


def test_saving_may_remove_a_bullet_nothing_uses(ws):
    tailor = build.load_yaml(ws.apps_dir / EXAMPLE_APP / "tailor.yaml")
    unused = next(b["id"] for b in ws.master()["positions"][0]["bullets"]
                  if b["id"] not in tailor["positions"]["pixel-forge-sr"]["bullets"])
    ws.save_master(without(ws.master(), unused))
    assert unused not in ws.master_text()


def test_a_submitted_application_does_not_block_a_removal(ws):
    fake_pdfs(ws)
    ws.submit_app(EXAMPLE_APP, "2026-10-22")
    ws.save_master(without(ws.master(), "rr-boosts"))
    assert "rr-boosts" not in ws.master_text()


def test_an_unknown_id_already_in_a_tailor_does_not_block_other_saves(ws):
    t = build.load_yaml(ws.apps_dir / EXAMPLE_APP / "tailor.yaml")
    t["positions"]["pixel-forge-sr"]["bullets"].append("edited-in-by-hand")
    ws.save_tailor(EXAMPLE_APP, t)
    m = ws.master()
    m["positions"][0]["bullets"][0]["text"] = "Reworded"
    ws.save_master(m)
    assert "edited-in-by-hand" in ws.bullet_usage()


# ----- gaps and studio notes -----

def test_gap_summary_groups_by_topic(ws):
    other = ws.apps_dir / "other-studio-designer"
    other.mkdir()
    (other / "listing.md").write_text("x", encoding="utf-8")
    (other / "listing.yaml").write_text(
        "studio: Other\ngaps:\n  - text: Nothing on VFX\n    topic: animation-vfx\n  - a plain gap\n", encoding="utf-8")
    gaps = ws.gap_summary()
    assert gaps[0]["topic"] == "animation-vfx" and len(gaps[0]["apps"]) == 2
    assert {"animation-vfx", "unreal-engine-5"} <= set(ws.gap_topics())
    assert any(g["items"][0]["text"] == "a plain gap" for g in gaps)


def test_studio_notes_round_trip(ws):
    assert "Lantern Hollow" in ws.studio_notes("sample studio")
    ws.save_studio_notes("New Place", "Met their team at a jam.")
    assert ws.studio_notes("New Place") == "Met their team at a jam."
    ws.save_studio_notes("New Place", "")
    assert ws.studio_notes("New Place") == ""
    assert "Lantern Hollow" in ws.studio_notes("Sample Studio")
    assert ws.load_app(EXAMPLE_APP)["studio_notes"].startswith("Played")


def test_create_app_starts_from_priority_one_bullets(ws):
    name = ws.create_app("Test Forge", "Combat Designer", "Design bosses.")
    assert name == "test-forge-combat-designer"
    t = build.load_yaml(ws.apps_dir / name / "tailor.yaml")
    assert "rr-lead" in t["positions"]["pixel-forge-sr"]["bullets"]
    assert "rr-mentor" not in t["positions"]["pixel-forge-sr"]["bullets"]
    with pytest.raises(build.BuildError, match="already exists"):
        ws.create_app("Test Forge", "Combat Designer", "")


def test_create_app_never_picks_a_variant_with_its_partner(ws):
    m = ws.master()
    variant = next(b for b in m["positions"][0]["bullets"] if b["id"] == "rr-live-model")
    variant["priority"] = 1  # rr-live, the plain version, is priority 1 too
    ws.save_master(m)
    name = ws.create_app("Test Forge", "Live Designer", "")
    t = build.load_yaml(ws.apps_dir / name / "tailor.yaml")
    ids = t["positions"]["pixel-forge-sr"]["bullets"]
    assert "rr-live" in ids and "rr-live-model" not in ids
    build.resolve(ws.master(), t, False)  # the starter builds


@pytest.mark.parametrize("name", ["../data", "a/b", "", ".hidden", "..", "a\\b", "東京/../x", "_x", "a:b"])
def test_app_names_cannot_escape_the_folder(ws, name):
    with pytest.raises(build.BuildError):
        ws.app_dir(name)


# ----- names in any script -----

def test_a_non_latin_application_gets_a_usable_folder_and_pdf_names(ws):
    name = ws.create_app("東京ゲームズ", "デザイナー", "ゲームをデザインする")
    assert name == "東京ゲームズ-デザイナー"
    app = ws.app_dir(name)
    loaded = ws.load_app(name)
    assert loaded["tailor"]["target"] == {"studio": "東京ゲームズ", "role": "デザイナー"}
    assert "ゲームをデザインする" in loaded["listing"]
    resume, letter = build.output_names(ws.master(), loaded["tailor"], app)
    assert resume.endswith("_Resume_東京ゲームズ.pdf") and letter.endswith("_Cover_Letter_東京ゲームズ.pdf")
    assert [a["name"] for a in ws.list_apps() if a["name"] == name] == [name]


def test_non_latin_names_stay_apart(ws):
    assert ws.create_app("東京", "Designer", "") != ws.create_app("大阪", "Designer", "")


def test_a_non_latin_application_survives_a_snapshot(ws):
    name = ws.create_app("東京ゲームズ", "デザイナー", "")
    snap = ws.create_snapshot("test")
    (ws.app_dir(name) / "listing.md").write_text("changed", encoding="utf-8")
    ws.restore_snapshot(snap["name"])
    assert "東京ゲームズ" in ws.load_app(name)["listing"]


def test_a_name_of_only_symbols_gets_a_generated_folder(ws):
    name = ws.create_app("!!!", "???", "")
    assert re.fullmatch(r"app-[0-9a-f]{8}", name)
    ws.app_dir(name)
    with pytest.raises(build.BuildError, match="already exists"):
        ws.create_app("!!!", "???", "")
    resume, _ = build.output_names(ws.master(), {"target": {"studio": "!!!"}}, ws.apps_dir / name)
    assert resume.endswith(f"_Resume_{name.replace('-', '_')}.pdf")


def test_slug_keeps_every_script_and_never_leaves_a_pdf_name_empty(tmp_path):
    assert build.slug("Alex Example!") == "Alex_Example"
    assert build.slug("José Núñez") == "José_Núñez"
    assert build.slug("東京 ゲームズ") == "東京_ゲームズ"
    assert build.slug("!!!") == ""
    master = {"basics": {"name": "???"}}
    assert build.output_names(master, {"target": {"studio": "!!!"}}, tmp_path / "---") == \
        ("Applicant_Resume_Application.pdf", "Applicant_Cover_Letter_Application.pdf")


def test_new_prints_a_non_latin_name_on_a_console_that_cannot(home, monkeypatch):
    monkeypatch.setenv("DYNAMICRESUME_HOME", str(home))
    monkeypatch.setenv("PYTHONIOENCODING", "cp1252")
    r = subprocess.run([sys.executable, str(REPO / "build.py"), "new", "東京ゲームズ", "デザイナー"],
                       capture_output=True, encoding="cp1252", errors="replace")
    assert r.returncode == 0, r.stderr
    assert (home / "applications" / "東京ゲームズ-デザイナー" / "tailor.yaml").exists()
