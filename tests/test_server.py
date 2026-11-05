"""The editor server's file route only serves previews and PDFs from build/ and the
applications folder, and a port already in use stops the server with a clear message."""
import json
import socket
import threading
from types import SimpleNamespace
from urllib.parse import quote
from urllib.request import urlopen

import pytest

import build
from build import ROOT, BuildError
from studio.server import Handler, Studio, init, open_server


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
