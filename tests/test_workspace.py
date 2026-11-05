"""Application folders: submitting, snapshots, round-trip YAML, gaps and studio notes."""
import pytest

import build
from conftest import EXAMPLE_APP


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


@pytest.mark.parametrize("name", ["../data", "a/b", "", ".hidden"])
def test_app_names_cannot_escape_the_folder(ws, name):
    with pytest.raises(build.BuildError):
        ws.app_dir(name)


# ----- renaming the studio -----

def rename_studio(ws, new, name=EXAMPLE_APP):
    t = build.load_yaml(ws.apps_dir / name / "tailor.yaml")
    t["target"]["studio"] = new
    ws.save_tailor(name, t)
    return t


def test_renaming_the_studio_keeps_the_pdfs_and_notes(ws):
    app, resume, letter = fake_pdfs(ws)
    notes = ws.studio_notes("Sample Studio")
    rename_studio(ws, "Lantern Works")
    loaded = ws.load_app(EXAMPLE_APP)
    assert loaded["pdfs"]["resume"]["exists"] and loaded["pdfs"]["letter"]["exists"]
    assert loaded["pdfs"]["resume"]["file"].endswith("_Resume_Lantern_Works.pdf")
    assert not (app / resume).exists() and not (app / letter).exists()
    assert loaded["studio_notes"] == notes
    assert ws.studio_notes("Sample Studio") == ""  # moved, not copied


def test_a_rename_leaves_notes_another_application_still_uses(ws):
    notes = ws.studio_notes("Sample Studio")
    other = rename_studio(ws, "Sample Studio", "harbor-light-games-senior-combat-designer")
    assert other["target"]["studio"] == "Sample Studio"
    rename_studio(ws, "Lantern Works")
    assert ws.studio_notes("Lantern Works") == notes
    assert ws.studio_notes("Sample Studio") == notes


def test_a_rename_never_replaces_the_new_names_notes(ws):
    old = ws.studio_notes("Sample Studio")
    ws.save_studio_notes("Lantern Works", "Met their team at a jam.")
    rename_studio(ws, "Lantern Works")
    assert ws.studio_notes("Lantern Works") == "Met their team at a jam."
    assert ws.studio_notes("Sample Studio") == old


def test_a_rename_that_only_changes_case_still_finds_the_pdfs(ws):
    app, _, _ = fake_pdfs(ws)
    notes = ws.studio_notes("Sample Studio")
    rename_studio(ws, "SAMPLE STUDIO")
    assert ws.load_app(EXAMPLE_APP)["studio_notes"] == notes
    resume = ws.load_app(EXAMPLE_APP)["pdfs"]["resume"]["file"]
    assert resume in [p.name for p in app.glob("*.pdf")]


def test_a_rename_does_not_overwrite_a_pdf_already_there(ws):
    app, resume, _ = fake_pdfs(ws)
    t = build.load_yaml(app / "tailor.yaml")
    t["target"]["studio"] = "Lantern Works"
    target = build.output_names(ws.master(), t, app)[0]
    (app / target).write_bytes(b"%PDF-1.7 older")
    with build.collect_warnings() as warnings:
        ws.save_tailor(EXAMPLE_APP, t)
    assert (app / target).read_bytes() == b"%PDF-1.7 older" and (app / resume).exists()
    assert any("already exists" in w for w in warnings)


def test_a_rename_leaves_a_submitted_application_alone(ws):
    app, resume, letter = fake_pdfs(ws)
    ws.submit_app(EXAMPLE_APP, "2026-10-22")
    frozen = {p.name: p.read_bytes() for p in (app / "submitted").iterdir()}
    notes = ws.studio_notes("Sample Studio")
    rename_studio(ws, "Lantern Works")
    assert {p.name: p.read_bytes() for p in (app / "submitted").iterdir()} == frozen
    assert (app / resume).exists() and (app / letter).exists()
    assert ws.studio_notes("Sample Studio") == notes and ws.studio_notes("Lantern Works") == ""


def test_saving_without_a_rename_touches_neither_pdfs_nor_notes(ws):
    app, resume, _ = fake_pdfs(ws)
    before = ws.studios_path.read_bytes()
    t = build.load_yaml(app / "tailor.yaml")
    t["headline"] = "Gameplay Designer | Combat"
    ws.save_tailor(EXAMPLE_APP, t)
    assert (app / resume).exists() and ws.studios_path.read_bytes() == before


# ----- a submitted application opens as it was sent -----

def edit_after_sending(ws, app):
    m = ws.master()
    first = m["positions"][0]["bullets"][0]
    sent = first["text"]
    first["text"] = "Edited after sending."
    ws.save_master(m)
    t = build.load_yaml(app / "tailor.yaml")
    t["headline"] = "Edited after sending"
    ws.save_tailor(EXAMPLE_APP, t)
    ws.save_text(EXAMPLE_APP, "cover-letter.md", "Edited after sending.")
    ws.save_text(EXAMPLE_APP, "listing.md", "Edited after sending.")
    (app / "listing.yaml").write_text("studio: Edited after sending\n", encoding="utf-8")
    return sent


def test_a_submitted_application_loads_what_was_sent(ws):
    app, _, _ = fake_pdfs(ws)
    before = ws.load_app(EXAMPLE_APP)
    ws.submit_app(EXAMPLE_APP, "2026-10-22")
    sent = edit_after_sending(ws, app)
    loaded = ws.load_app(EXAMPLE_APP)
    assert loaded["master"]["positions"][0]["bullets"][0]["text"] == sent
    assert ws.master()["positions"][0]["bullets"][0]["text"] == "Edited after sending."
    for key in ("tailor", "letter", "listing", "listing_spec"):
        assert loaded[key] == before[key], key
        assert "Edited after sending" not in str(loaded[key]), key


def test_a_submitted_application_falls_back_to_live_files_it_lacks(ws):
    app, _, _ = fake_pdfs(ws)
    ws.submit_app(EXAMPLE_APP, "2026-10-22")
    edit_after_sending(ws, app)
    for f in ("master.yaml", "tailor.yaml", "cover-letter.md", "listing.md", "listing.yaml"):
        (app / "submitted" / f).unlink()
    loaded = ws.load_app(EXAMPLE_APP)
    assert loaded["master"] is None  # the editor then uses the live master
    assert loaded["tailor"]["headline"] == "Edited after sending"
    assert loaded["letter"] == "Edited after sending."
    assert loaded["listing"] == "Edited after sending."
    assert loaded["listing_spec"]["studio"] == "Edited after sending"


def test_an_unsubmitted_application_loads_the_live_files(ws):
    app, _, _ = fake_pdfs(ws)
    ws.save_text(EXAMPLE_APP, "cover-letter.md", "Live letter.")
    loaded = ws.load_app(EXAMPLE_APP)
    assert loaded["master"] is None and loaded["letter"] == "Live letter."
