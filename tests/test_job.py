"""Job details in job.yaml (link, location, salary, ...) and the Saved stage for leads."""
import threading
from datetime import date
from types import SimpleNamespace

import pytest

import build
from build import ROOT, BuildError
from conftest import EXAMPLE_APP
from studio import job, server, tracking
from studio.draft import Drafts
from test_workspace import fake_pdfs

HARBOR = "harbor-light-games-senior-combat-designer"
TODAY = date(2026, 11, 5)


def studio_of(ws):
    return SimpleNamespace(ws=ws, versions=lambda name=None: {}, preview=lambda *a, **k: {"ok": True})


# ----- checking the fields -----

def test_empty_fields_are_dropped_and_values_trimmed():
    out = job.clean_job({"url": " https://example.com/a ", "location": "", "salary": None, "source": " Friend ",
                         "saved": False, "extra": "ignored"})
    assert out == {"url": "https://example.com/a", "source": "Friend"}
    assert job.clean_job(None) == {} and job.clean_job({"saved": True}) == {"saved": True}


@pytest.mark.parametrize("url", ["javascript:alert(1)", "ftp://example.com", "example.com/jobs", "https://", "https://a b.com"])
def test_only_http_and_https_links_are_accepted(url):
    assert not job.safe_url(url)
    with pytest.raises(BuildError, match="http"):
        job.clean_job({"url": url})


def test_the_deadline_must_be_a_real_day():
    assert job.clean_job({"deadline": "2026-11-20"})["deadline"] == date(2026, 11, 20)
    for bad in ("11/20/2026", "2026-02-30"):
        with pytest.raises(BuildError):
            job.clean_job({"deadline": bad})


# ----- files -----

def test_job_details_round_trip_and_keep_comments(ws):
    app = ws.apps_dir / EXAMPLE_APP
    assert ws.load_app(EXAMPLE_APP)["job"]["location"] == "Remote (US)"
    assert ws.load_app(EXAMPLE_APP)["job"]["deadline"] == "2026-11-20"
    ws.save_job(EXAMPLE_APP, {"url": "https://example.com/new", "location": "Remote (US)", "referral": "Sam Lee"})
    text = (app / "job.yaml").read_text(encoding="utf-8")
    assert "# Where the posting lives" in text and "url: https://example.com/new" in text
    assert "salary" not in text and "deadline" not in text
    assert ws.job(app) == {"url": "https://example.com/new", "location": "Remote (US)", "referral": "Sam Lee"}


def test_a_job_with_nothing_left_removes_the_file(ws):
    ws.save_job(EXAMPLE_APP, {})
    assert not (ws.apps_dir / EXAMPLE_APP / "job.yaml").exists()
    assert ws.load_app(EXAMPLE_APP)["job"] == {}


def test_list_and_load_carry_the_job(ws):
    jobs = {a["name"]: a["job"] for a in ws.list_apps()}
    assert jobs[HARBOR]["referral"] == "Sam Lee, Lead Designer" and jobs[EXAMPLE_APP]["url"].startswith("https://")


def test_submitting_copies_job_yaml_and_the_live_one_stays_editable(ws):
    fake_pdfs(ws)
    ws.submit_app(EXAMPLE_APP, "2026-10-01")
    app = ws.apps_dir / EXAMPLE_APP
    assert (app / "submitted" / "job.yaml").exists()
    ws.save_job(EXAMPLE_APP, {"url": "https://example.com/a", "contact": "Pat Kim, recruiter"})  # no unsubmit needed
    assert ws.load_app(EXAMPLE_APP)["job"]["contact"] == "Pat Kim, recruiter"
    assert build.load_yaml(app / "submitted" / "job.yaml")["contact"] == "Pat Kim, Recruiter"  # as it was when sent


def test_a_bad_link_creates_no_folder(ws):
    with pytest.raises(BuildError):
        ws.create_app("Lantern Works", "Designer", "", {"url": "javascript:x"})
    assert not any("lantern" in p.name for p in ws.apps_dir.iterdir())


# ----- the Saved stage -----

def test_a_saved_lead_needs_only_a_studio_and_a_role():
    t = tracking.summarize([], None, TODAY, saved=True)
    assert t["column"] == "saved" and t["applied"] is None
    assert tracking.summarize([], None, TODAY)["column"] == "drafting"
    assert tracking.summarize([], {"date": "2026-10-01"}, TODAY, saved=True)["column"] == "applied"


def test_saved_leads_sit_in_their_own_column_until_drafting_starts(ws):
    name = ws.create_app("Lantern Works", "Gameplay Designer", "", {"saved": True, "url": "https://example.com/j"})
    assert ws.track(ws.apps_dir / name)["column"] == "saved"
    assert {a["name"]: a["track"]["column"] for a in ws.list_apps()}[name] == "saved"
    ws.save_job(name, {"url": "https://example.com/j"})  # Start drafting clears the flag
    assert ws.track(ws.apps_dir / name)["column"] == "drafting"


def test_saved_leads_do_not_count_in_stats(ws):
    before = ws.stats(TODAY)
    for i in range(3):
        ws.create_app(f"Studio {i}", "Designer", "", {"saved": True})
    assert ws.stats(TODAY) == before


def test_a_saved_lead_cannot_be_logged_as_sent_before_it_is_drafted(ws):
    name = ws.create_app("Lantern Works", "Designer", "", {"saved": True})
    with pytest.raises(BuildError):
        ws.add_event(name, {"date": "2026-11-05", "stage": "applied"})  # no PDFs yet


# ----- redrafts and outside edits -----

def test_a_redraft_leaves_job_yaml_alone(ws):
    path = ws.apps_dir / EXAMPLE_APP / "job.yaml"
    before = path.read_bytes()
    draft = {"target": {"studio": "S", "role": "R"}, "positions": {}}
    Drafts(ws, threading.Lock(), ROOT / "build" / "pytest").apply(EXAMPLE_APP, {"tailor": draft})
    assert path.read_bytes() == before


def test_job_autosave_does_not_overwrite_an_outside_edit(ws):
    s = studio_of(ws)
    server.get_app(s, {}, {}, EXAMPLE_APP)
    path = ws.apps_dir / EXAMPLE_APP / "job.yaml"
    path.write_text("url: https://example.com/edited-outside\n", encoding="utf-8")
    body = {"job": {"url": "https://example.com/mine"}}
    assert server.put_job(s, body, {}, EXAMPLE_APP) == {"conflict": ["job.yaml"]}
    assert "edited-outside" in path.read_text(encoding="utf-8")
    r = server.put_job(s, {**body, "keep": ["job.yaml"]}, {}, EXAMPLE_APP)
    assert r["job"] == {"url": "https://example.com/mine"} and r["track"]["column"] == "drafting"
    assert "conflict" not in server.put_job(s, body, {}, EXAMPLE_APP)  # settled


def test_the_job_route_works_on_a_submitted_application(ws):
    s = studio_of(ws)
    r = server.put_job(s, {"job": {"url": "https://example.com/a", "contact": "Pat Kim"}}, {}, HARBOR)
    assert r["track"]["column"] == "interviewing" and r["job"]["contact"] == "Pat Kim"
    with pytest.raises(BuildError, match="http"):
        server.put_job(s, {"job": {"url": "javascript:alert(1)"}}, {}, HARBOR)
