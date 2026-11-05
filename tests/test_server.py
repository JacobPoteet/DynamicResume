"""The editor server's file route only serves previews and PDFs from build/ and the
applications folder, and a port already in use stops the server with a clear message."""
import json
import re
import socket
import threading
from types import SimpleNamespace
from urllib.parse import quote
from urllib.request import urlopen

import pytest

import build
from build import ROOT, BuildError
from conftest import EXAMPLE_APP
from studio import server
from studio.server import Handler, Studio, init, open_server
from test_workspace import fake_pdfs


def test_a_busy_port_stops_the_server():
    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        held.listen()
        port = held.getsockname()[1]
        with pytest.raises(BuildError, match=rf"port {port}.*--port"):
            open_server(port)


def test_a_second_server_on_the_same_port_is_refused():
    first = open_server(0)
    try:
        with pytest.raises(BuildError, match="--port"):
            open_server(first.server_address[1])
    finally:
        first.server_close()


def test_a_free_port_can_be_reused_once_the_server_closes():
    first = open_server(0)
    port = first.server_address[1]
    first.server_close()
    open_server(port).server_close()


def test_a_non_latin_application_is_served_over_http(ws, monkeypatch):
    monkeypatch.setattr(build, "find_typst", lambda: "typst")
    studio = Studio(False)
    monkeypatch.setattr(Handler, "studio", studio)
    name = ws.create_app("東京ゲームズ", "デザイナー", "")
    pdf = ws.app_dir(name) / "Resume.pdf"
    pdf.write_bytes(b"%PDF-1.7 test")
    srv = open_server(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        with urlopen(f"{base}/api/apps/{quote(name)}") as r:
            assert json.load(r)["tailor"]["target"]["studio"] == "東京ゲームズ"
        url = studio.url(pdf)
        assert url.isascii()
        with urlopen(base + url) as r:
            assert r.read() == b"%PDF-1.7 test"
    finally:
        srv.shutdown()
        srv.server_close()


@pytest.fixture
def handler(ws):
    return SimpleNamespace(studio=SimpleNamespace(ws=ws), safe=Handler.safe)


def serve(handler, rel):
    return Handler.output_file(handler, rel)


def test_init_lists_the_paper_sizes(ws):
    out = init(SimpleNamespace(example=True, ws=ws), None, {})
    assert out["papers"] == ["letter", "a4"] and out["default_paper"] == "letter"


def test_serves_application_pdfs(handler, ws):
    p = serve(handler, "apps/sample-studio-gameplay-designer/submitted/Resume.pdf")
    assert p == (ws.apps_dir / "sample-studio-gameplay-designer" / "submitted" / "Resume.pdf").resolve()


def test_serves_build_previews(handler):
    assert serve(handler, "build/studio/app/resume/page-1.svg") == (ROOT / "build/studio/app/resume/page-1.svg").resolve()


@pytest.mark.parametrize("rel", [
    "apps/../data/master.yaml",                      # not a PDF or SVG
    "apps/../../build.py",
    "apps/../../../secret.pdf",                      # outside the applications folder
    "build/../applications/x/Resume.pdf",            # outside build/
    "apps/sample-studio-gameplay-designer/tailor.yaml",
    "data/master.yaml",                              # unknown prefix
    "Resume.pdf",
])
def test_refuses_everything_else(handler, rel):
    with pytest.raises(BuildError):
        serve(handler, rel)


# ----- saving over outside edits -----

@pytest.fixture
def studio(ws):
    return SimpleNamespace(ws=ws, versions=lambda name=None: {}, preview=lambda *a, **k: {"ok": True})


def tailor_of(ws):
    return build.load_yaml(ws.apps_dir / EXAMPLE_APP / "tailor.yaml")


def edit_outside(ws, filename, text="edited outside: true\n"):
    path = ws.studios_path if filename == "studios.yaml" else ws.apps_dir / EXAMPLE_APP / filename
    path.write_text(text, encoding="utf-8")
    return path


def test_autosave_does_not_overwrite_an_outside_edit(studio, ws):
    server.get_app(studio, {}, {}, EXAMPLE_APP)
    t = tailor_of(ws)
    path = edit_outside(ws, "tailor.yaml")
    r = server.put_tailor(studio, {"tailor": t}, {}, EXAMPLE_APP)
    assert r == {"conflict": ["tailor.yaml"]}
    assert path.read_text(encoding="utf-8") == "edited outside: true\n"


def test_keep_my_edit_replaces_the_outside_edit(studio, ws):
    server.get_app(studio, {}, {}, EXAMPLE_APP)
    t = tailor_of(ws)
    edit_outside(ws, "tailor.yaml")
    r = server.put_tailor(studio, {"tailor": t, "keep": ["tailor.yaml"]}, {}, EXAMPLE_APP)
    assert "conflict" not in r and tailor_of(ws)["target"] == t["target"]
    assert "conflict" not in server.put_tailor(studio, {"tailor": t}, {}, EXAMPLE_APP)  # settled


def test_loading_again_takes_in_the_outside_edit(studio, ws):
    server.get_app(studio, {}, {}, EXAMPLE_APP)
    t = tailor_of(ws)
    t["headline"] = "From outside"
    ws.save_tailor(EXAMPLE_APP, t)  # stands in for a text editor; a draft saves the same way
    assert server.put_tailor(studio, {"tailor": tailor_of(ws)}, {}, EXAMPLE_APP)["conflict"] == ["tailor.yaml"]
    assert server.get_app(studio, {}, {}, EXAMPLE_APP)["tailor"]["headline"] == "From outside"
    assert "conflict" not in server.put_tailor(studio, {"tailor": t}, {}, EXAMPLE_APP)


def test_the_pages_own_saves_never_conflict(studio, ws):
    """Autosaves overlap while typing: a second one goes out before the first has answered."""
    server.get_app(studio, {}, {}, EXAMPLE_APP)
    for headline in ("One", "Two", "Three"):
        t = tailor_of(ws)
        t["headline"] = headline
        assert "conflict" not in server.put_tailor(studio, {"tailor": t}, {}, EXAMPLE_APP)
    assert "conflict" not in server.put_letter(studio, {"text": "A"}, {}, EXAMPLE_APP)
    assert "conflict" not in server.put_letter(studio, {"text": "B"}, {}, EXAMPLE_APP)
    assert "conflict" not in server.put_studio_notes(studio, {"notes": "A"}, {}, EXAMPLE_APP)
    assert "conflict" not in server.put_studio_notes(studio, {"notes": "B"}, {}, EXAMPLE_APP)
    assert "conflict" not in server.put_listing(studio, {"text": "A", "spec": {"studio": "A"}}, {}, EXAMPLE_APP)
    assert "conflict" not in server.put_listing(studio, {"text": "B", "spec": {"studio": "B"}}, {}, EXAMPLE_APP)


@pytest.mark.parametrize(("filename", "call", "body"), [
    ("cover-letter.md", server.put_letter, {"text": "mine"}),
    ("listing.md", server.put_listing, {"text": "mine"}),
    ("listing.yaml", server.put_listing, {"spec": {"studio": "mine"}}),
    ("studios.yaml", server.put_studio_notes, {"notes": "mine"}),
])
def test_every_autosaved_file_is_guarded(studio, ws, filename, call, body):
    server.get_app(studio, {}, {}, EXAMPLE_APP)
    path = edit_outside(ws, filename, "- edited outside\n")
    assert call(studio, body, {}, EXAMPLE_APP) == {"conflict": [filename]}
    assert path.read_text(encoding="utf-8") == "- edited outside\n"
    assert "conflict" not in call(studio, {**body, "keep": [filename]}, {}, EXAMPLE_APP)


def test_saving_one_file_does_not_swallow_an_outside_edit_to_another(studio, ws):
    server.get_app(studio, {}, {}, EXAMPLE_APP)
    edit_outside(ws, "listing.md")
    assert "conflict" not in server.put_tailor(studio, {"tailor": tailor_of(ws)}, {}, EXAMPLE_APP)
    assert server.put_listing(studio, {"text": "mine"}, {}, EXAMPLE_APP) == {"conflict": ["listing.md"]}


def test_a_file_not_seen_since_the_server_started_passes(studio, ws):
    edit_outside(ws, "cover-letter.md")
    assert "conflict" not in server.put_letter(studio, {"text": "mine"}, {}, EXAMPLE_APP)


# ----- renaming the studio through the save route -----

def test_the_save_route_reports_renamed_pdfs_and_notes(studio, ws):
    fake_pdfs(ws)
    server.get_app(studio, {}, {}, EXAMPLE_APP)
    notes = ws.studio_notes("Sample Studio")
    t = tailor_of(ws)
    t["target"]["studio"] = "Lantern Works"
    r = server.put_tailor(studio, {"tailor": t}, {}, EXAMPLE_APP)
    assert r["pdfs"]["resume"]["exists"] and r["pdfs"]["resume"]["file"].endswith("_Lantern_Works.pdf")
    assert r["studio_notes"] == notes and r["warnings"] == []
    # The rename rewrote studios.yaml itself, so that is not an outside edit.
    assert "conflict" not in server.put_studio_notes(studio, {"notes": "More."}, {}, EXAMPLE_APP)


def test_the_save_route_refuses_to_rename_a_submitted_application(studio, ws):
    app, resume, letter = fake_pdfs(ws)
    ws.submit_app(EXAMPLE_APP, "2026-10-22")
    t = tailor_of(ws)
    t["target"]["studio"] = "Lantern Works"
    with pytest.raises(BuildError, match="Unsubmit it"):
        server.put_tailor(studio, {"tailor": t}, {}, EXAMPLE_APP)
    assert (app / resume).exists() and (app / "submitted" / resume).exists() and tailor_of(ws)["target"]["studio"] != "Lantern Works"


def test_init_gives_the_editor_the_build_lint_rules(ws):
    r = init(SimpleNamespace(example=True, ws=ws), {}, {})
    assert r["em_dash"] == build.EM_DASH and r["banned"] == build.BANNED


def test_the_master_route_reports_what_applications_name(ws):
    r = server.get_master(SimpleNamespace(ws=ws), {}, {})
    assert EXAMPLE_APP in r["used"]["position"]["pixel-forge-sr"]
    assert set(r["used"]) == {"position", "project", "game", "skill group"}


def test_the_app_scripts_share_one_scope_without_clashing():
    """The scripts load as plain globals, so a repeated function name silently replaces the first."""
    pattern = re.compile(r"^(?:async )?function (\w+)|^(?:const|let) (\w+)", re.M)
    names = []
    for script in ("app.js", "tracker.js"):
        text = (ROOT / "studio" / "static" / script).read_text(encoding="utf-8")
        names += [a or b for a, b in pattern.findall(text)]
    assert sorted(n for n in set(names) if names.count(n) > 1) == []
