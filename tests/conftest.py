"""Shared fixtures. Tests never touch real data: `home` copies the fictional demo into a
temporary folder and points build.HOME (the data home) at it."""
import shutil
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import build  # noqa: E402

EXAMPLE_APP = "sample-studio-gameplay-designer"


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A data home holding a copy of examples/ (master, studios, one application)."""
    shutil.copytree(REPO / "examples" / "data", tmp_path / "data")
    shutil.copytree(REPO / "examples" / "applications", tmp_path / "applications")
    monkeypatch.setattr(build, "HOME", tmp_path)
    return tmp_path


@pytest.fixture
def ws(home):
    from studio.workspace import Workspace
    return Workspace(False)


@pytest.fixture
def master():
    return build.load_yaml(REPO / "examples" / "data" / "master.yaml")


@pytest.fixture
def tailor():
    return build.load_yaml(REPO / "examples" / "applications" / EXAMPLE_APP / "tailor.yaml")


def texts(data):
    """Bullet id -> resolved text, across positions and projects."""
    out = {}
    for p in data["positions"]:
        out.update({b["id"]: b["text"] for b in p["bullets"]})
    for p in data["projects"]:
        out.update({b["id"]: b["text"] for b in p["bullets"]})
    return out
