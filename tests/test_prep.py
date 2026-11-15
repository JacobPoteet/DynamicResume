"""Interview prep sheets. Claude never runs here: `ask` is replaced with canned replies, so the
tests check what the app sends Claude and what it keeps from the reply."""
from datetime import datetime

import pytest

import build
from build import BuildError
from studio import prep, server

from conftest import EXAMPLE_APP

HARBOR = "harbor-light-games-senior-combat-designer"
NORTHWIND = "northwind-interactive-systems-designer"
QUARRY = "quarry-lane-studio-technical-designer"
NOW = datetime(2026, 11, 14, 9, 30)
REPLY = {
    "questions": [
        {"q": "Walk us through a boss you designed.", "bullets": ["dd-bosses", "not-a-bullet"], "points": "Tells first."},
        {"q": "", "bullets": [], "points": "a question with no text is dropped"},
    ],
    "gaps": [{"text": "No co-op scaling work", "answer": "Point to the solo tuning."}],
    "ask_them": ["How do combat and level design share encounter work?"],
    "email": {"subject": "Thank you", "body": "Hi Sam,\n\nThanks for the time today."},
}


@pytest.fixture
def replies(monkeypatch):
    """The next replies ask() returns, in order, and the prompts it was given."""
    queue, prompts = [], []

    def fake(ws, prompt):
        prompts.append(prompt)
        return queue.pop(0)
    monkeypatch.setattr(prep, "ask", fake)
    return queue, prompts


def test_the_prompt_points_at_the_sent_files_and_the_latest_interview(ws, replies):
    replies[0].append(REPLY)
    prep.write(ws, HARBOR, now=NOW)
    prompt = replies[1][0]
    sent = f"applications/{HARBOR}/submitted/"
    for f in ("listing.md", "tailor.yaml", "cover-letter.md", "master.yaml"):
        assert sent + f in prompt
    assert "round: 2" in prompt and "take-home" in prompt  # the latest interview
    assert "They asked about scaling fights for co-op." in prompt  # round 1's debrief, as history
    assert "Never invent experience" in prompt


def test_the_sheet_keeps_only_known_bullets_and_is_saved(ws, replies):
    replies[0].append(REPLY)
    r = prep.write(ws, HARBOR, now=NOW)
    sheet = r["prep"]
    assert sheet["for"] == {"stage": "interview", "date": "2026-10-24", "round": 2}
    assert sheet["written"] == "2026-11-14 09:30"
    assert [q["q"] for q in sheet["questions"]] == ["Walk us through a boss you designed."]
    assert sheet["questions"][0]["bullets"] == ["dd-bosses"]
    assert any("not-a-bullet" in w for w in r["warnings"])
    assert prep.load(ws, HARBOR) == sheet
    assert (ws.app_dir(HARBOR) / "prep.yaml").exists()


def test_an_earlier_event_can_be_chosen(ws, replies):
    replies[0].append(REPLY)
    sheet = prep.write(ws, HARBOR, index=0, now=NOW)["prep"]
    assert sheet["for"] == {"stage": "screen", "date": "2026-10-09"}
    assert "Recruiter reached out by email" in replies[1][0]


def test_refusals(ws, replies):
    with pytest.raises(BuildError, match="not been sent"):
        prep.write(ws, EXAMPLE_APP)
    with pytest.raises(BuildError, match="log the screen or interview first"):
        prep.write(ws, QUARRY)
    with pytest.raises(BuildError, match="closed"):
        prep.write(ws, NORTHWIND)
    with pytest.raises(BuildError, match="no event 9"):
        prep.write(ws, HARBOR, index=9)
    assert replies[1] == []  # Claude was never asked
    replies[0].append({"questions": [], "email": {}})
    with pytest.raises(BuildError, match="no questions"):
        prep.write(ws, HARBOR)
    assert prep.load(ws, HARBOR) is None


def test_em_dashes_and_banned_phrases_are_flagged(ws, replies):
    replies[0].append({**REPLY, "email": {"subject": "Thanks", "body": f"I am excited to join {build.EM_DASH} truly."}})
    warnings = prep.write(ws, HARBOR, now=NOW)["warnings"]
    assert any("em dash" in w for w in warnings) and any("excited to" in w for w in warnings)


def test_as_text_reads_like_a_sheet(ws, replies):
    replies[0].append(REPLY)
    out = prep.as_text(prep.write(ws, HARBOR, now=NOW)["prep"])
    assert out.startswith("Prep for the interview round 2 (2026-10-24)")
    assert "bullets: dd-bosses" in out and "Thank-you email: Thank you" in out


def test_routes(ws, replies):
    s = server.Studio(False)
    assert server.get_prep(s, {}, {}, HARBOR) == {"prep": None}
    replies[0].append(REPLY)
    r = server.post_prep(s, {"index": 1}, {}, HARBOR)
    assert r["prep"]["for"]["round"] == 1
    assert server.get_prep(s, {}, {}, HARBOR)["prep"]["for"]["round"] == 1
