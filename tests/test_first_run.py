"""An empty data home: no master yet. The app offers the demo; the CLI gives a clear error."""
import os
import subprocess
import sys

import pytest

import build
from conftest import REPO


@pytest.fixture
def empty(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "HOME", tmp_path)
    return tmp_path


@pytest.fixture
def ws(empty):
    from studio.workspace import Workspace
    return Workspace(False)


@pytest.fixture
def studio(empty, monkeypatch):
    from studio.server import Studio
    monkeypatch.setattr(build, "find_typst", lambda: "typst")
    return Studio(False)


def call(fn, s, body=None):
    return fn(s, body or {}, {})


def test_the_init_route_reports_a_missing_master(studio):
    from studio.server import init
    r = call(init, studio)
    assert r["needs_master"] is True and r["master_file"] == "data/master.yaml"


def test_routes_explain_a_missing_master(studio):
    from studio.server import get_master, list_apps, versions
    for route in (list_apps, get_master):
        with pytest.raises(build.BuildError, match="no master file at data/master.yaml"):
            call(route, studio)
    assert call(versions, studio)["master"] == 0  # the page polls this while it waits


def test_start_from_demo_gives_a_working_board(studio, empty):
    from studio.server import create_app, get_master, init, list_apps, start_from_demo, stats
    call(start_from_demo, studio)
    assert (empty / "data" / "master.yaml").read_text(encoding="utf-8") == \
        (REPO / "examples" / "data" / "master.yaml").read_text(encoding="utf-8")
    assert call(init, studio)["needs_master"] is False
    assert call(list_apps, studio) == {"apps": []}
    assert call(stats, studio)
    assert call(get_master, studio)["master"]["positions"]
    name = call(create_app, studio, {"studio": "Test Forge", "role": "Designer"})["name"]
    assert [a["name"] for a in call(list_apps, studio)["apps"]] == [name]


def test_start_from_demo_never_overwrites_a_master(ws):
    ws.start_from_demo()
    ws.master_path.write_text("mine: true\n", encoding="utf-8")
    with pytest.raises(build.BuildError, match="already exists"):
        ws.start_from_demo()
    assert ws.master_path.read_text(encoding="utf-8") == "mine: true\n"


def test_creating_an_application_leaves_nothing_behind(ws, empty):
    with pytest.raises(build.BuildError, match="no master file"):
        ws.create_app("Test Forge", "Designer", "listing")
    assert not (empty / "applications").exists()


def test_build_and_check_raise_a_clear_error(empty):
    with pytest.raises(build.BuildError, match="no master file"):
        build.build_master(None, False)
    with pytest.raises(build.BuildError, match="no master file"):
        build.check_apps(None, False)
    app = empty / "applications" / "some-app"
    app.mkdir(parents=True)
    (app / "tailor.yaml").write_text("target: {studio: S, role: R}\n", encoding="utf-8")
    with pytest.raises(build.BuildError, match="no master file"):
        build.build_app(None, app, False)


@pytest.mark.parametrize("args", [["new", "Test Forge", "Designer"], ["build", "master"], ["check"]])
def test_the_cli_prints_an_error_line_not_a_traceback(tmp_path, monkeypatch, args):
    monkeypatch.setenv("DYNAMICRESUME_HOME", str(tmp_path))
    # A stand-in typst, so the build commands reach the master even where typst is not installed.
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "typst.cmd").write_text("@echo off\n", encoding="utf-8")
    (fake / "typst").write_text("#!/bin/sh\n", encoding="utf-8")
    (fake / "typst").chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}{os.pathsep}{os.environ['PATH']}")
    r = subprocess.run([sys.executable, str(REPO / "build.py"), *args], capture_output=True, text=True, encoding="utf-8")
    assert r.returncode != 0
    assert "ERROR: no master file at data/master.yaml" in r.stderr
    assert "Traceback" not in r.stderr
