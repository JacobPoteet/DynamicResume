"""Closing out gaps (done, not me, reopen) and Write a bullet. Claude never runs here: `ask`
is replaced with canned replies, so the tests check what the app does with them."""
import pytest

import build
from build import BuildError
from studio import gaps, server

ANSWERS = [{"q": "Where did you do it?", "a": "Dungeon Delvers: I worked with the VFX artist on boss tells."}]


@pytest.fixture
def replies(monkeypatch):
    """The next replies ask() returns, in order, and the prompts it was given."""
    queue, prompts = [], []

    def fake(ws, prompt):
        prompts.append(prompt)
        return queue.pop(0)
    monkeypatch.setattr(gaps, "ask", fake)
    return queue, prompts


def summary(ws):
    return {g["key"]: g for g in gaps.annotate(ws, ws.gap_summary())}


def test_groups_carry_their_key_and_start_open(ws):
    g = summary(ws)
    assert set(g) == {"animation-vfx", "unreal-engine-5"}
    assert g["animation-vfx"]["state"] is None and not g["animation-vfx"]["raised_again"]
    assert g["animation-vfx"]["items"][0]["drafted"] == "2026-10-23 09:30"


def test_done_not_me_and_reopen_round_trip_through_gaps_yaml(ws, home):
    gaps.set_state(ws, "animation-vfx", "done", note="covered by dd-vfx")
    gaps.set_state(ws, "Unreal-Engine-5", "not-me")
    g = summary(ws)
    assert g["animation-vfx"]["state"]["state"] == "done" and g["animation-vfx"]["state"]["note"] == "covered by dd-vfx"
    assert g["unreal-engine-5"]["state"]["state"] == "not-me"
    assert (home / "data" / "gaps.yaml").exists()
    gaps.set_state(ws, "animation-vfx", None)
    gaps.set_state(ws, "unreal-engine-5", None)
    assert summary(ws)["animation-vfx"]["state"] is None
    assert not (home / "data" / "gaps.yaml").exists()  # nothing left to keep


def test_a_bad_state_or_missing_key_is_refused(ws):
    with pytest.raises(BuildError, match="done, not-me or open"):
        gaps.set_state(ws, "animation-vfx", "maybe")
    with pytest.raises(BuildError, match="key is missing"):
        gaps.set_state(ws, " ", "done")


def test_a_listing_drafted_after_closing_raises_it_again(ws, home):
    gaps.set_state(ws, "animation-vfx", "not-me")
    data = home / "data" / "gaps.yaml"
    data.write_text(data.read_text(encoding="utf-8").replace(str(gaps.date.today()), "2026-10-01"), encoding="utf-8")
    assert summary(ws)["animation-vfx"]["raised_again"]  # drafted 2026-10-23, closed 2026-10-01


def test_questions_describe_the_gap_and_never_reach_the_master(ws, replies):
    queue, prompts = replies
    queue.append({"questions": ["Which project?", " ", "What did you do yourself?"]})
    r = gaps.questions(ws, "animation-vfx")
    assert r == {"key": "animation-vfx", "questions": ["Which project?", "What did you do yourself?"]}
    assert "No bullet shows work with animation or VFX teams" in prompts[0]
    assert "let them say" in prompts[0] and "Do not create or edit files" in prompts[0]


def test_no_questions_is_an_error(ws, replies):
    replies[0].append({"questions": []})
    with pytest.raises(BuildError, match="no questions"):
        gaps.questions(ws, "animation-vfx")


def test_an_unknown_gap_is_an_error(ws):
    with pytest.raises(BuildError, match="no gap"):
        gaps.questions(ws, "nothing-like-this")


def test_propose_sends_only_answered_questions_and_checks_the_reply(ws, replies):
    queue, prompts = replies
    queue.append({"text": "Worked with VFX on boss tells — clearer attacks", "short": "", "tags": ["Game AI", "vfx", "game-ai"],
                  "owner": "dd-designer", "priority": 7, "unsupported": "animation", "none": ""})
    r = gaps.propose(ws, "animation-vfx", [*ANSWERS, {"q": "Scale?", "a": "  "}])
    assert "Q: Where did you do it?" in prompts[0] and "Scale?" not in prompts[0]
    assert "Never add a number" in prompts[0]
    assert r["owner"] == "dd-designer" and r["priority"] == 2  # out of range falls back
    assert r["tags"] == ["game-ai", "vfx"]
    assert any("new tag: vfx" in w for w in r["warnings"])
    assert any("em dash" in w for w in r["warnings"])
    assert r["unsupported"] == "animation"
    assert {"id": "dd-designer", "kind": "position"}.items() <= r["owners"][1].items()


def test_propose_needs_an_answer(ws, replies):
    with pytest.raises(BuildError, match="answer at least one"):
        gaps.propose(ws, "animation-vfx", [{"q": "Where?", "a": ""}])
    assert replies[1] == []  # Claude was never asked


def test_an_unknown_owner_is_left_for_the_user_to_choose(ws, replies):
    replies[0].append({"text": "Did a thing.", "tags": [], "owner": "made-up", "priority": 1})
    r = gaps.propose(ws, "animation-vfx", ANSWERS)
    assert r["owner"] == "" and any("made-up" in w for w in r["warnings"])


def test_answers_that_show_nothing_return_none_instead_of_a_bullet(ws, replies):
    replies[0].append({"text": "", "none": "You have not worked with VFX teams."})
    r = gaps.propose(ws, "animation-vfx", ANSWERS)
    assert r["none"] == "You have not worked with VFX teams." and "text" not in r


def test_add_bullet_appends_to_the_owner_and_closes_the_gap(ws, home):
    history = len(list(ws.history_dir.glob("master_*.yaml"))) if ws.history_dir.exists() else 0
    r = gaps.add_bullet(ws, "animation-vfx", {"text": "Worked with the VFX artist on boss attack tells.",
                                              "short": "Boss tells with VFX.", "owner": "dd-designer",
                                              "tags": ["Game AI", "collaboration"], "priority": "1"})
    assert r == {"id": "dd-worked-with", "owner": "dd-designer"}  # dungeon-delvers -> dd
    dd = next(p for p in ws.master()["positions"] if p["id"] == "dd-designer")
    b = dd["bullets"][-1]
    assert b == {"id": "dd-worked-with", "text": "Worked with the VFX artist on boss attack tells.",
                 "short": "Boss tells with VFX.", "tags": ["game-ai", "collaboration"], "priority": 1}
    assert summary(ws)["animation-vfx"]["state"]["bullet"] == "dd-worked-with"
    assert len(list(ws.history_dir.glob("master_*.yaml"))) == history + 1  # the old master is kept
    # The same words again get a numbered id, never a repeat.
    again = gaps.add_bullet(ws, "unreal-engine-5", {"text": "Worked with Unreal Engine 5.", "owner": "dd-designer"})
    assert again["id"] == "dd-worked-with-2"


def test_add_bullet_needs_text_and_a_real_owner(ws):
    with pytest.raises(BuildError, match="no text"):
        gaps.add_bullet(ws, "animation-vfx", {"text": " ", "owner": "dd-designer"})
    with pytest.raises(BuildError, match="choose"):
        gaps.add_bullet(ws, "animation-vfx", {"text": "Did it.", "owner": "nope"})


def test_a_project_bullet_uses_the_project_initials(ws):
    assert gaps.add_bullet(ws, "animation-vfx", {"text": "Built VFX hooks.", "owner": "jam-tools"})["id"] == "jt-built-hooks"


def test_routes(ws, replies, monkeypatch):
    monkeypatch.setattr(build, "find_typst", lambda: "typst")
    s = server.Studio(False)
    assert {g["key"] for g in server.gaps(s, {}, {})["gaps"]} == {"animation-vfx", "unreal-engine-5"}
    assert server.gap_state(s, {"key": "animation-vfx", "state": "not-me"}, {})["state"]["state"] == "not-me"
    assert server.gap_state(s, {"key": "animation-vfx", "state": None}, {})["state"] is None
    replies[0].append({"questions": ["Which project?"]})
    assert server.gap_questions(s, {"key": "animation-vfx"}, {})["questions"] == ["Which project?"]
    replies[0].append({"text": "Did it.", "tags": [], "owner": "dd-designer", "priority": 2})
    assert server.gap_propose(s, {"key": "animation-vfx", "answers": ANSWERS}, {})["text"] == "Did it."
    r = server.gap_bullet(s, {"key": "animation-vfx", "bullet": {"text": "Did it.", "owner": "dd-designer"}}, {})
    assert r["id"] == "dd-bullet" and isinstance(r["versions"], dict)  # no word over three letters: a plain id
