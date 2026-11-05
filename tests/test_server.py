"""The editor server's file route only serves previews and PDFs from build/ and the
applications folder."""
from types import SimpleNamespace

import pytest

import build
from build import ROOT, BuildError
from conftest import EXAMPLE_APP
from studio import server
from studio.server import Handler
from test_workspace import fake_pdfs


@pytest.fixture
def handler(ws):
    return SimpleNamespace(studio=SimpleNamespace(ws=ws), safe=Handler.safe)


def serve(handler, rel):
    return Handler.output_file(handler, rel)


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


@pytest.fixture
def studio(ws):
    return SimpleNamespace(ws=ws, versions=lambda name=None: {}, preview=lambda *a, **k: {"ok": True})


def tailor_of(ws):
    return build.load_yaml(ws.apps_dir / EXAMPLE_APP / "tailor.yaml")


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
