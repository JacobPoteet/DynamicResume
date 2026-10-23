"""The editor server's file route only serves previews and PDFs from build/ and the
applications folder."""
from types import SimpleNamespace

import pytest

from build import ROOT, BuildError
from studio.server import Handler


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
