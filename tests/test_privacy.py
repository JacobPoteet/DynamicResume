"""The privacy guard: PRIVATE_TERMS fail a file unless the match is a public-terms phrase."""
import importlib.util

from conftest import REPO

spec = importlib.util.spec_from_file_location("check_privacy", REPO / "scripts" / "check_privacy.py")
check_privacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_privacy)
scan = check_privacy.scan_text


def test_a_private_term_fails():
    assert scan("a.md", "Worked at Acme Games", ["acme games"])


def test_a_private_term_split_by_spaces_still_fails():
    assert scan("a.pdf", "Acme Ga mes", ["acme games"])


def test_a_public_phrase_passes():
    text = "Built by Jane Doe, github.com/JaneDoe/project"
    assert not scan("a.html", text, ["jane doe", "doe"], ["jane doe", "janedoe"])


def test_a_private_term_outside_the_public_phrase_still_fails():
    text = "Built by Jane Doe. Mr. Doe worked at Acme."
    assert scan("a.html", text, ["doe"], ["jane doe"])
    assert scan("a.html", "Jane Doe at Acme", ["acme"], ["jane doe"])


def test_the_committed_public_terms_load():
    assert all(t == t.lower() and t for t in check_privacy.public_terms())
