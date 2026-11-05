"""The Send dialog's plain text for application forms, and marking a draft sent from it."""
import json
from types import SimpleNamespace

import pytest

import build
from conftest import EXAMPLE_APP, texts
from studio import send, server
from test_workspace import fake_pdfs


@pytest.fixture
def studio(ws):
    return SimpleNamespace(ws=ws)


def first_position(tailor):
    return next(iter(tailor["positions"]))


def test_a_role_is_its_selected_bullets_in_tailor_order(master, tailor):
    pid = first_position(tailor)
    ids = list(reversed(tailor["positions"][pid]["bullets"]))
    tailor["positions"][pid]["bullets"] = ids
    data = build.resume_data(master, tailor)
    role = next(r for r in send.plain_text(master, tailor, "")["roles"] if r["id"] == pid)
    want = [f"- {texts(data)[i]}" for i in ids]
    assert role["text"].split("\n") == want
    assert role["title"] and role["company"] and role["dates"]


def test_overrides_and_short_texts_apply(master, tailor):
    pid = first_position(tailor)
    first, second = tailor["positions"][pid]["bullets"][:2]
    all_bullets = next(p for p in master["positions"] if p["id"] == pid)["bullets"]
    next(b for b in all_bullets if b["id"] == second)["short"] = "A short version."
    tailor.update(overrides={first: "An override."}, short=[second])
    role = next(r for r in send.plain_text(master, tailor, "")["roles"] if r["id"] == pid)
    assert role["text"].split("\n")[:2] == ["- An override.", "- A short version."]


def test_a_position_with_no_bullets_has_nothing_to_copy(master, tailor):
    pid = first_position(tailor)
    tailor["positions"][pid]["bullets"] = []
    assert pid not in [r["id"] for r in send.plain_text(master, tailor, "")["roles"]]


def test_the_letter_has_its_greeting_paragraphs_closing_and_name(master, tailor):
    tailor["cover_letter"] = {"greeting": "Dear Sam,", "closing": "Thanks,"}
    out = send.plain_text(master, tailor, "One\nline.\n\n\nTwo.\n")
    name = master["basics"]["name"]
    assert out["letter"] == f"Dear Sam,\n\nOne line.\n\nTwo.\n\nThanks,\n{name}"


def test_the_letter_starts_with_its_date_when_one_is_set(master, tailor):
    tailor["cover_letter"] = {"date": "November 5, 2026"}
    assert send.plain_text(master, tailor, "Text.")["letter"].startswith("November 5, 2026\n\nDear Hiring Team,")


def test_no_letter_text_means_no_letter(master, tailor):
    assert send.plain_text(master, tailor, "  \n")["letter"] is None


def test_contact_details_skip_what_is_empty(master):
    basics = {"name": "Sam Lee", "email": "sam@example.com", "phone": "", "location": None,
              "linkedin": "linkedin.com/in/sam", "headline": "Not a contact detail"}
    assert send.contact_text(basics) == "Sam Lee\nsam@example.com\nlinkedin.com/in/sam"


def test_a_resume_that_does_not_build_returns_the_error(master, tailor):
    tailor["positions"][first_position(tailor)]["bullets"] = ["no-such-bullet"]
    out = send.plain_text(master, tailor, "Text.")
    assert out["roles"] == [] and "no-such-bullet" in out["error"]
    assert out["contact"] and out["letter"]  # the rest can still be copied


def test_the_route_reports_a_draft_with_no_pdfs(studio, ws):
    (ws.app_dir(EXAMPLE_APP) / "job.yaml").write_text("url: https://example.com/jobs/1\n", encoding="utf-8")
    for pdf in ws.app_dir(EXAMPLE_APP).glob("*.pdf"):
        pdf.unlink()
    out = server.send_text(studio, {}, {}, EXAMPLE_APP)
    assert out["submitted"] is None and out["error"] is None
    assert out["studio"] and out["role"] and out["roles"] and out["letter"] and out["contact"]
    assert not out["pdfs"]["resume"]["exists"] and not out["pdfs"]["letter"]["exists"]
    assert out["job"]["url"] == "https://example.com/jobs/1"
    json.dumps(out, default=str)  # as the server sends it


def test_the_route_reads_the_saved_files(studio, ws):
    tailor = build.load_yaml(ws.app_dir(EXAMPLE_APP) / "tailor.yaml")
    bullet = tailor["positions"][first_position(tailor)]["bullets"][0]
    tailor["overrides"] = {bullet: "Saved override."}
    ws.save_tailor(EXAMPLE_APP, tailor)
    ws.save_text(EXAMPLE_APP, "cover-letter.md", "Saved letter.")
    out = server.send_text(studio, {}, {}, EXAMPLE_APP)
    assert "- Saved override." in out["roles"][0]["text"].split("\n")
    assert "Saved letter." in out["letter"]


def test_the_route_returns_the_last_build_fit_for_each_pdf(studio, ws):
    fake_pdfs(ws)
    fit = {"pages": 2, "fill": 0.2, "spill_lines": 7}
    letter = {"pages": 1, "fill": 0.6, "spill_lines": 0}
    path = build.fit_path(ws.app_dir(EXAMPLE_APP), False)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"resume": fit, "letter": letter}), encoding="utf-8")
    assert server.send_text(studio, {}, {}, EXAMPLE_APP)["fit"] == {"resume": fit, "letter": letter}


def test_the_route_does_not_swallow_an_outside_edit(studio, ws):
    """Only loading the application counts as having seen a file; opening the dialog does not."""
    server.get_app(studio, {}, {}, EXAMPLE_APP)
    (ws.app_dir(EXAMPLE_APP) / "cover-letter.md").write_text("Edited outside.", encoding="utf-8")
    server.send_text(studio, {}, {}, EXAMPLE_APP)
    assert server.put_letter(SimpleNamespace(ws=ws, versions=lambda name=None: {}, preview=lambda *a, **k: {}),
                             {"text": "Mine"}, {}, EXAMPLE_APP) == {"conflict": ["cover-letter.md"]}


def test_a_submitted_application_only_says_so(studio, ws):
    fake_pdfs(ws)
    ws.submit_app(EXAMPLE_APP, "2026-10-22")
    out = server.send_text(studio, {}, {}, EXAMPLE_APP)
    assert out["submitted"]["date"] == "2026-10-22" and "roles" not in out


def test_marking_sent_freezes_it_keeps_the_note_and_undoes(studio, ws):
    app, resume, _ = fake_pdfs(ws)
    r = server.add_event(studio, {"event": {"stage": "applied", "date": "2026-11-05", "note": "Via the careers page"}}, {}, EXAMPLE_APP)
    assert r["submitted"]["date"] == "2026-11-05" and (app / "submitted" / resume).exists()
    assert r["track"]["column"] == "applied"
    assert [e["note"] for e in r["track"]["events"]] == ["Via the careers page"]
    assert server.send_text(studio, {}, {}, EXAMPLE_APP)["submitted"]
    # What the Undo link in the toast does.
    server.delete_event(studio, {}, {}, EXAMPLE_APP, str(r["index"]))
    server.unsubmit(studio, {}, {}, EXAMPLE_APP)
    out = server.send_text(studio, {}, {}, EXAMPLE_APP)
    assert out["submitted"] is None and ws.track(app)["column"] == "drafting"


def test_marking_sent_needs_a_resume_pdf(studio, ws):
    for pdf in ws.app_dir(EXAMPLE_APP).glob("*.pdf"):
        pdf.unlink()
    with pytest.raises(build.BuildError, match="no resume PDF"):
        server.add_event(studio, {"event": {"stage": "applied", "date": "2026-11-05"}}, {}, EXAMPLE_APP)
    assert not build.submission(ws.app_dir(EXAMPLE_APP))


def test_the_dialog_is_in_the_page_on_every_view():
    """Not in a view's HTML: the editor and the board both open it."""
    from studio.server import STATIC
    assert '<dialog id="send-dlg"' in (STATIC / "index.html").read_text(encoding="utf-8")
