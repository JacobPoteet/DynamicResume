"""How master + tailor merge: overrides, short text, variants, unknown ids, warnings."""
import copy

import pytest

import build
from conftest import texts


def by_id(master):
    return {b["id"]: b for o in master["positions"] + master.get("projects", []) for b in o.get("bullets") or []}


def test_demo_resolves_cleanly(master, tailor):
    with build.collect_warnings() as w:
        data = build.resume_data(master, tailor)
    assert w == []
    assert [p["id"] for p in data["positions"]] == ["pixel-forge-sr", "dd-designer", "fd-associate"]


def test_bullet_order_follows_the_tailor(master, tailor):
    data = build.resolve(master, tailor, False)
    assert [b["id"] for b in data["positions"][0]["bullets"]] == tailor["positions"]["pixel-forge-sr"]["bullets"]


def test_short_text_is_used_when_listed(master, tailor):
    out = texts(build.resolve(master, tailor, False))
    assert out["rr-lead"] == by_id(master)["rr-lead"]["short"]


def test_override_beats_short_text(master, tailor):
    t = copy.deepcopy(tailor)
    t["overrides"]["rr-lead"] = "Led ranked multiplayer"
    assert texts(build.resolve(master, t, False))["rr-lead"] == "Led ranked multiplayer"


def test_unused_short_and_override_ids_warn(master, tailor):
    t = copy.deepcopy(tailor)
    t["short"] = ["rr-lead", "rr-tools", "nope"]  # rr-tools has no short text
    t["overrides"]["dd-ui"] = "not selected"
    with build.collect_warnings() as w:
        build.resolve(master, t, False)
    assert "short 'nope' does not match a selected bullet that has short text" in w
    assert "short 'rr-tools' does not match a selected bullet that has short text" in w
    assert "override 'dd-ui' does not match any selected bullet" in w


def test_selecting_a_bullet_and_its_variant_is_an_error(master, tailor):
    t = copy.deepcopy(tailor)
    t["positions"]["pixel-forge-sr"]["bullets"].append("rr-live-model")
    t["positions"]["pixel-forge-sr"]["bullets"].append("rr-live")
    with pytest.raises(build.BuildError, match="another version of 'rr-live'"):
        build.resolve(master, t, False)


def test_a_variant_alone_is_fine(master, tailor):
    t = copy.deepcopy(tailor)
    t["positions"]["pixel-forge-sr"]["bullets"] = ["rr-live-model"]
    assert "rr-live-model" in texts(build.resolve(master, t, False))


@pytest.mark.parametrize("target", ["missing", "rr-lead", "dd-enemies"])
def test_variant_of_must_name_another_bullet_in_the_same_position(master, target):
    m = copy.deepcopy(master)
    m["positions"][0]["bullets"][0]["variant_of"] = target  # rr-lead; dd-enemies is in another position
    with pytest.raises(build.BuildError, match="variant_of"):
        build.validate_master(m)


@pytest.mark.parametrize("change, message", [
    (lambda t: t["positions"].update({"nope": {"bullets": []}}), "unknown position id 'nope'"),
    (lambda t: t["positions"]["dd-designer"]["bullets"].append("nope"), "bullet 'nope' not found"),
    (lambda t: t.update(games=["nope"]), "unknown game id 'nope'"),
    (lambda t: t["projects"].update({"nope": {"bullets": []}}), "unknown project id 'nope'"),
])
def test_unknown_ids_are_errors(master, tailor, change, message):
    t = copy.deepcopy(tailor)
    change(t)
    with pytest.raises(build.BuildError, match=message):
        build.resolve(master, t, False)


def test_duplicate_bullet_ids_are_errors(master):
    m = copy.deepcopy(master)
    m["positions"][1]["bullets"].append(dict(m["positions"][0]["bullets"][0]))
    with pytest.raises(build.BuildError, match="used in both"):
        build.validate_master(m)


def test_skills_first_moves_items_to_the_front(master, tailor):
    data = build.resolve(master, tailor, False)
    software = next(s for s in data["skills"] if s["group"] == "Software")
    assert software["items"][:2] == ["Unreal Engine 4/5", "C#"]


def test_unknown_tailor_keys_warn(master, tailor):
    with build.collect_warnings() as w:
        build.resolve(master, {**tailor, "colour": "teal"}, False)
    assert "tailor.yaml key 'colour' is not used by the build" in w


def test_lint_flags_em_dashes_and_banned_phrases():
    with build.collect_warnings() as w:
        build.lint("We leverage synergy — always", "resume")
    assert any("em dash" in x for x in w)
    assert any("'leverage'" in x for x in w) and any("'synergy'" in x for x in w)
