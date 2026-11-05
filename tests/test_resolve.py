"""How master + tailor merge: overrides, short text, variants, unknown ids, warnings."""
import copy

import pytest

import build
from conftest import EXAMPLE_APP, REPO, texts


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


def test_projects_follow_the_tailor_order(master, tailor):
    t = copy.deepcopy(tailor)
    t["projects"] = dict(reversed(list(t["projects"].items())))
    names = {p["id"]: p["name"] for p in master["projects"]}
    assert [p["name"] for p in build.resolve(master, t, False)["projects"]] == [names[i] for i in t["projects"]]


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


def with_default_paper(master, paper):
    m = copy.deepcopy(master)
    m["basics"]["paper"] = paper
    return m


def test_paper_defaults_to_letter(master, tailor):
    assert "paper" not in master["basics"] and "paper" not in tailor
    assert build.resume_data(master, tailor)["paper"] == "us-letter"
    assert build.letter_data(master, tailor, "Body.")["paper"] == "us-letter"


def test_tailor_paper_applies_to_resume_and_letter_without_a_warning(master, tailor):
    t = {**tailor, "paper": "a4"}
    with build.collect_warnings() as w:
        assert build.resume_data(master, t)["paper"] == "a4"
        assert build.letter_data(master, t, "Body.")["paper"] == "a4"
    assert w == []


def test_master_basics_set_the_default_paper_and_a_tailor_wins(master, tailor):
    m = with_default_paper(master, "a4")
    assert build.resume_data(m, tailor)["paper"] == "a4"
    assert build.letter_data(m, tailor, "Body.")["paper"] == "a4"
    assert build.resolve(m, {}, True)["paper"] == "a4"  # the master build
    assert build.resume_data(m, {**tailor, "paper": "letter"})["paper"] == "us-letter"


@pytest.mark.parametrize("paper", ["legal", "A4", "us-letter", 4, ["a4"]])
def test_an_invalid_tailor_paper_is_a_build_error(master, tailor, paper):
    t = {**tailor, "paper": paper}
    with pytest.raises(build.BuildError, match="unknown paper .* in tailor.yaml. Use one of: letter, a4"):
        build.resume_data(master, t)
    with pytest.raises(build.BuildError, match="unknown paper"):
        build.letter_data(master, t, "Body.")


def test_an_invalid_master_paper_fails_validation(master):
    with pytest.raises(build.BuildError, match="unknown paper 'legal' in master basics"):
        build.validate_master(with_default_paper(master, "legal"))


@pytest.mark.parametrize("letter, what", [
    ("I shipped **three** games.", "bold"),
    ("I shipped __three__ games.", "bold"),
    ("I shipped *three* games.", "italics"),
    ("I shipped _three_ games.", "italics"),
    ("See [my site](https://example.com) for more.", "a link"),
    ("I wrote `tools` for it.", "inline code"),
    ("# About me\n\nI ship games.", "a heading"),
    ("What I did:\n- shipped\n- tuned", "a list"),
    ("What I did:\n1. shipped\n2. tuned", "a list"),
    ("> A quote from a review", "a quote"),
])
def test_a_letter_warns_about_markdown(master, tailor, letter, what):
    with build.collect_warnings() as w:
        data = build.letter_data(master, tailor, letter)
    assert any(f"Markdown ({what})" in x for x in w), w
    assert " ".join(data["paragraphs"]) == " ".join(letter.split())  # printed as typed


@pytest.mark.parametrize("letter", [
    "I shipped three games.\n\nI tuned 2*3*4 grids and wrote snake_case_names.",
    "Rates rose by 5% - a small change (see below).\n\nDear [Team], thanks.",
    "In 2019. I joined the team.",
])
def test_a_plain_letter_has_no_markdown_warning(master, tailor, letter):
    with build.collect_warnings() as w:
        build.letter_data(master, tailor, letter)
    assert not any("Markdown" in x for x in w), w


def test_the_demo_letter_has_no_markdown_warning(master, tailor):
    with build.collect_warnings() as w:
        build.letter_data(master, tailor, (REPO / "examples/applications" / EXAMPLE_APP / "cover-letter.md").read_text(encoding="utf-8"))
    assert not any("Markdown" in x for x in w), w


def test_lint_flags_em_dashes_and_banned_phrases():
    with build.collect_warnings() as w:
        build.lint("We leverage synergy — always", "resume")
    assert any("em dash" in x for x in w)
    assert any("'leverage'" in x for x in w) and any("'synergy'" in x for x in w)
