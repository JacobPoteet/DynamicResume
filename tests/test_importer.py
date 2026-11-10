"""Importing a listing from a Greenhouse, Lever or Ashby link. No test touches the network:
`get_json` is replaced with canned answers shaped like each board's public API."""
import sys
from urllib.error import HTTPError, URLError

import pytest

import build
from build import BuildError
from studio import importer, server
from studio.importer import html_text, import_listing, parse_url

GREENHOUSE = {
    "title": "Senior Quest Designer", "company_name": "Sample Studio", "location": {"name": "Remote (US)"},
    # Greenhouse sends the description's HTML entity-escaped.
    "content": "&lt;p&gt;Build quests.&lt;/p&gt;&lt;h3&gt;You will&lt;/h3&gt;&lt;ul&gt;&lt;li&gt;Script encounters&lt;/li&gt;"
               "&lt;li&gt;Run playtests&amp;nbsp;&lt;/li&gt;&lt;/ul&gt;",
}
LEVER = {
    "text": "Systems Designer", "categories": {"location": "Austin, TX", "team": "Design"},
    "descriptionPlain": "We make games.  \n\n\n\nJoin us.\n",
    "lists": [{"text": "Requirements", "content": "<li>Five years in design</li><li>Unreal</li>"}],
    "additionalPlain": "Benefits are good.",
    "salaryRange": {"min": 120000, "max": 140000, "currency": "USD", "interval": "per-year-salary"},
}
ASHBY = {"jobs": [
    {"id": "other", "title": "Artist", "descriptionPlain": "Art."},
    {"id": "abc-123", "title": "Combat Designer", "location": "Remote",
     "descriptionHtml": "<p>Design combat.</p><ul><li>Bosses</li></ul>",
     "compensation": {"compensationTierSummary": "$100K - $150K", "scrapeableCompensationSalarySummary": "$100K - $150K"}},
]}


@pytest.fixture
def answers(monkeypatch):
    """Map of API URL -> JSON (or an exception to raise). Records the URLs asked for."""
    canned, asked = {}, []

    def fake(url):
        asked.append(url)
        r = canned.get(url)
        if r is None:
            raise HTTPError(url, 404, "Not Found", None, None)
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(importer, "get_json", fake)
    canned["asked"] = asked
    return canned


@pytest.mark.parametrize("url, expected", [
    ("https://boards.greenhouse.io/samplestudio/jobs/4012345", ("greenhouse", "samplestudio", "4012345", None)),
    ("https://job-boards.greenhouse.io/samplestudio/jobs/4012345?gh_src=x", ("greenhouse", "samplestudio", "4012345", None)),
    ("https://boards.greenhouse.io/embed/job_app?for=samplestudio&token=4012345", ("greenhouse", "samplestudio", "4012345", None)),
    ("https://careers.samplestudio.com/job/4012345?gh_jid=4012345", ("greenhouse", "samplestudio", "4012345", None)),
    ("https://jobs.lever.co/samplestudio/0b1c-22/apply", ("lever", "samplestudio", "0b1c-22", None)),
    ("https://jobs.eu.lever.co/samplestudio/0b1c-22", ("lever", "samplestudio", "0b1c-22", "eu")),
    ("https://jobs.ashbyhq.com/SampleStudio/abc-123", ("ashby", "SampleStudio", "abc-123", None)),
    ("https://example.com/jobs/1", None),
    ("https://boards.greenhouse.io/samplestudio", None),
    ("javascript:alert(1)", None),
    ("", None),
])
def test_links_are_recognized_by_board(url, expected):
    assert parse_url(url) == expected


def test_greenhouse_gives_studio_role_location_and_plain_text(answers):
    answers["https://boards-api.greenhouse.io/v1/boards/samplestudio/jobs/4012345"] = GREENHOUSE
    r = import_listing("https://boards.greenhouse.io/samplestudio/jobs/4012345")
    assert (r["studio"], r["role"], r["location"], r["salary"], r["board"]) == (
        "Sample Studio", "Senior Quest Designer", "Remote (US)", "", "greenhouse")
    assert r["listing"] == "Build quests.\n\nYou will\n- Script encounters\n- Run playtests"
    assert r["url"] == "https://boards.greenhouse.io/samplestudio/jobs/4012345"


def test_lever_joins_description_lists_and_pay(answers):
    answers["https://api.lever.co/v0/postings/escape-velocity/0b1c-22"] = LEVER
    r = import_listing("https://jobs.lever.co/escape-velocity/0b1c-22")
    assert r["studio"] == "Escape Velocity"  # Lever has no company name; the slug stands in
    assert r["role"] == "Systems Designer" and r["location"] == "Austin, TX"
    assert r["salary"] == "USD 120,000 to 140,000 per year salary"
    assert r["listing"] == "We make games.\n\nJoin us.\n\nRequirements\n- Five years in design\n- Unreal\n\nBenefits are good."


def test_lever_eu_uses_the_eu_api(answers):
    answers["https://api.eu.lever.co/v0/postings/s/1"] = LEVER
    assert import_listing("https://jobs.eu.lever.co/s/1")["role"] == "Systems Designer"


def test_ashby_finds_the_job_on_the_board(answers):
    answers["https://api.ashbyhq.com/posting-api/job-board/SampleStudio?includeCompensation=true"] = ASHBY
    r = import_listing("https://jobs.ashbyhq.com/SampleStudio/abc-123")
    assert (r["studio"], r["role"], r["salary"]) == ("SampleStudio", "Combat Designer", "$100K - $150K")
    assert r["listing"] == "Design combat.\n- Bosses"


def test_a_job_missing_from_the_ashby_board_reads_as_taken_down(answers):
    answers["https://api.ashbyhq.com/posting-api/job-board/s?includeCompensation=true"] = ASHBY
    with pytest.raises(BuildError, match="taken down.*Paste"):
        import_listing("https://jobs.ashbyhq.com/s/gone")


@pytest.mark.parametrize("error, message", [
    (URLError("no route"), "Could not reach Lever"),
    (TimeoutError("timed out"), "Could not reach Lever"),
    (HTTPError("u", 500, "x", None, None), "Lever answered 500"),
    (ValueError("bad json"), "does not understand"),
])
def test_network_and_payload_failures_say_to_paste(answers, error, message):
    answers["https://api.lever.co/v0/postings/s/1"] = error
    with pytest.raises(BuildError, match=f"{message}.*Paste the listing's text"):
        import_listing("https://jobs.lever.co/s/1")


def test_an_unsupported_link_asks_nothing_of_the_network(answers):
    with pytest.raises(BuildError, match="Greenhouse, Lever and Ashby"):
        import_listing("https://example.com/careers/42")
    assert answers["asked"] == []


def test_a_posting_with_no_text_is_refused(answers):
    answers["https://api.lever.co/v0/postings/s/1"] = {"text": "Designer", "descriptionPlain": " \n "}
    with pytest.raises(BuildError, match="no description"):
        import_listing("https://jobs.lever.co/s/1")


def test_html_text_drops_scripts_and_keeps_breaks():
    assert html_text("<p>One<br>Two</p><script>x()</script><style>p{}</style><p>Three</p>") == "One\nTwo\n\nThree"


def test_the_server_route_returns_the_import(answers):
    answers["https://api.lever.co/v0/postings/s/1"] = LEVER
    assert server.import_listing(None, {"url": "https://jobs.lever.co/s/1"}, {})["role"] == "Systems Designer"


def test_new_with_url_creates_the_application_with_job_details(home, answers, monkeypatch, capsys):
    answers["https://boards-api.greenhouse.io/v1/boards/samplestudio/jobs/4012345"] = GREENHOUSE
    url = "https://boards.greenhouse.io/samplestudio/jobs/4012345"
    monkeypatch.setattr(sys, "argv", ["build.py", "new", "--url", url])
    build.main()
    assert "Imported Senior Quest Designer at Sample Studio from Greenhouse" in capsys.readouterr().out
    app = home / "applications" / "sample-studio-senior-quest-designer"
    assert "- Script encounters" in (app / "listing.md").read_text(encoding="utf-8")
    assert build.load_yaml(app / "job.yaml") == {"url": url, "location": "Remote (US)"}


def test_new_with_url_keeps_a_studio_and_role_given(home, answers, monkeypatch, capsys):
    answers["https://api.lever.co/v0/postings/s/1"] = LEVER
    monkeypatch.setattr(sys, "argv", ["build.py", "new", "Real Name Games", "Lead Designer", "--url", "https://jobs.lever.co/s/1"])
    build.main()
    assert (home / "applications" / "real-name-games-lead-designer" / "listing.md").exists()


def test_new_without_studio_or_url_is_an_error(home, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["build.py", "new"])
    with pytest.raises(SystemExit) as e:
        build.main()
    assert "studio and a role" in str(e.value)
