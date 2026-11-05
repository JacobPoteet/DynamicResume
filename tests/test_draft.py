"""Turning Claude's draft reply into files: the JSON parser, gaps, and the tailor clean-up."""
import threading

import pytest

from build import ROOT, BuildError
from conftest import EXAMPLE_APP
from studio.draft import Drafts, clean_gap, clean_tailor, parse_json


@pytest.mark.parametrize("reply, expected", [
    ('{"a": 1}', {"a": 1}),
    ('```json\n{"a": 1}\n```', {"a": 1}),
    ('Here is the draft:\n{"a": {"b": [1, 2]}}\nLet me know!', {"a": {"b": [1, 2]}}),
    ('{"a": 1} and a closing remark with {braces}', {"a": 1}),
    # Closed one brace early, then more keys: seen from a real draft.
    ('{"listing": {"x": 1}, "gaps": [{"text": "t"}]}, "notes": "n"}', {"listing": {"x": 1}, "gaps": [{"text": "t"}], "notes": "n"}),
])
def test_parse_json_recovers_the_object(reply, expected):
    assert parse_json(reply) == expected


@pytest.mark.parametrize("reply", ["no json here", '{"a": }'])
def test_parse_json_reports_bad_replies(reply):
    with pytest.raises(BuildError):
        parse_json(reply)


def test_clean_gap():
    assert clean_gap("plain gap") == "plain gap"
    assert clean_gap({"text": " No UE5 work ", "topic": "Unreal Engine 5"}) == {"text": "No UE5 work", "topic": "unreal-engine-5"}
    assert clean_gap({"text": "no topic"}) == "no topic"


def test_clean_tailor_keeps_only_known_ids(master):
    warnings = []
    out = clean_tailor(master, {
        "target": {"studio": "S", "role": "R", "extra": "x"},
        "template": "not-a-template",
        "positions": {"pixel-forge-sr": {"bullets": ["rr-lead", "made-up"]}, "nope": {"bullets": []}},
        "projects": ["sample-project"],
        "games": ["robo-racers", "nope"],
        "skills_first": ["C#", "Juggling"],
        "overrides": {"rr-lead": "New text", "dd-ui": "not selected"},
        "short": ["rr-lead", "dd-ui"],
    }, warnings)
    assert out["target"] == {"studio": "S", "role": "R"}
    assert out["template"] == "resume-inline"
    assert out["positions"] == {"pixel-forge-sr": {"bullets": ["rr-lead"]}}
    assert out["projects"]["sample-project"]["bullets"] == ["sp-shipped", "sp-rewind"]
    assert out["games"] == ["robo-racers"]
    assert out["skills_first"] == ["C#"]
    assert out["overrides"] == {"rr-lead": "New text"}
    assert out["short"] == ["rr-lead"]
    assert "dropped unknown bullet 'made-up' from pixel-forge-sr" in warnings
    assert "dropped unknown position 'nope'" in warnings


def test_clean_tailor_keeps_a_known_paper_and_drops_the_rest(master):
    assert clean_tailor(master, {"paper": "a4"}, [])["paper"] == "a4"
    assert "paper" not in clean_tailor(master, {}, [])
    warnings = []
    assert "paper" not in clean_tailor(master, {"paper": "legal"}, warnings)
    assert warnings == ["dropped unknown paper 'legal'"]


@pytest.mark.parametrize("current, reply, expected", [
    ("a4", None, "a4"),      # the reply leaves it out
    ("a4", "letter", "a4"),  # the application's own choice wins
    (None, "a4", "a4"),
    (None, None, None),
])
def test_a_redraft_keeps_the_paper(ws, current, reply, expected):
    tailor = ws.load_app(EXAMPLE_APP)["tailor"]
    tailor.pop("paper", None)
    ws.save_tailor(EXAMPLE_APP, {**tailor, **({"paper": current} if current else {})})
    draft = {"target": {"studio": "S", "role": "R"}, "positions": {}, **({"paper": reply} if reply else {})}
    Drafts(ws, threading.Lock(), ROOT / "build" / "pytest").apply(EXAMPLE_APP, {"tailor": draft})
    assert ws.load_app(EXAMPLE_APP)["tailor"].get("paper") == expected
