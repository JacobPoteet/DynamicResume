"""Follow-through on the board: what needs attention, follow-up reminders and calendar files."""
import threading
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import quote
from urllib.request import urlopen

import pytest

import build
from conftest import EXAMPLE_APP
from studio import ics, server, tracking
from studio.server import Handler, Studio, open_server

SENT = {"date": "2026-10-01"}
HARBOR = "harbor-light-games-senior-combat-designer"
NORTHWIND = "northwind-interactive-systems-designer"
QUARRY = "quarry-lane-studio-technical-designer"


def interview(**kw):
    return {"date": "2026-10-05", "stage": "interview", **kw}


def kinds(t):
    return [x["kind"] for x in t["attention"]]


# ----- what needs attention -----

def test_an_interview_is_over_after_its_start_plus_its_length():
    e = interview(scheduled="2026-10-20 14:00", length=60)
    assert not tracking.interview_over(e, datetime(2026, 10, 20, 14, 59))
    assert tracking.interview_over(e, datetime(2026, 10, 20, 15, 0))


def test_a_bare_date_lasts_the_whole_day_and_no_date_is_never_over():
    assert not tracking.interview_over(interview(scheduled="2026-10-20"), datetime(2026, 10, 20, 18, 0))
    assert tracking.interview_over(interview(scheduled="2026-10-20"), datetime(2026, 10, 21, 0, 0))
    assert not tracking.interview_over(interview(), datetime(2030, 1, 1))


def test_a_passed_interview_asks_for_a_debrief_until_it_has_one_or_is_waved_off():
    past = interview(scheduled="2026-10-20 14:00", round=2)
    t = tracking.summarize([past], SENT, date(2026, 10, 21))
    assert t["attention"] == [{"kind": "debrief", "date": "2026-10-20 14:00", "i": 0, "round": 2}]
    assert kinds(tracking.summarize([{**past, "debrief": "Fine"}], SENT, date(2026, 10, 21))) == []
    assert kinds(tracking.summarize([{**past, "no_debrief": True}], SENT, date(2026, 10, 21))) == []
    assert kinds(tracking.summarize([past], SENT, date(2026, 10, 20))) == []  # not over yet


def test_only_interviews_ask_for_a_debrief():
    screen = {"date": "2026-10-05", "stage": "screen", "scheduled": "2026-10-06 10:00"}
    assert kinds(tracking.summarize([screen], SENT, date(2026, 10, 21))) == []


def test_a_follow_up_is_due_on_its_day_and_after():
    reminder = {"date": "2026-10-10", "note": "Email Pat"}
    assert kinds(tracking.summarize([], SENT, date(2026, 10, 9), follow_up=reminder)) == []
    t = tracking.summarize([], SENT, date(2026, 10, 10), follow_up=reminder)
    assert t["attention"] == [{"kind": "follow_up", "date": "2026-10-10", "note": "Email Pat"}]
    assert kinds(tracking.summarize([], SENT, date(2026, 10, 20), follow_up=reminder)) == ["follow_up"]


def test_a_closed_application_asks_for_nothing():
    events = [interview(scheduled="2026-10-06 10:00"), {"date": "2026-10-09", "stage": "rejected"}]
    t = tracking.summarize(events, SENT, date(2026, 10, 20), follow_up={"date": "2026-10-10"})
    assert t["attention"] == [] and t["follow_up"] is None


@pytest.mark.parametrize("today, near", [
    (date(2026, 11, 12), False),  # 8 days ahead
    (date(2026, 11, 13), True),
    (date(2026, 11, 20), True),
    (date(2026, 11, 27), True),
    (date(2026, 11, 28), False),  # 8 days after: the card's pill still says so
])
def test_a_deadline_shows_within_a_week_either_side(today, near):
    t = tracking.summarize([], None, today, deadline="2026-11-20")
    assert t["attention"] == ([{"kind": "deadline", "date": "2026-11-20"}] if near else [])


def test_a_sent_application_has_no_deadline_to_meet():
    assert kinds(tracking.summarize([], SENT, date(2026, 11, 20), deadline="2026-11-20")) == []


def test_a_saved_lead_shows_its_deadline_and_bad_hand_edits_are_ignored():
    assert kinds(tracking.summarize([], None, date(2026, 11, 20), saved=True, deadline="2026-11-20")) == ["deadline"]
    assert kinds(tracking.summarize([], None, date(2026, 11, 20), deadline="soon")) == []
    t = tracking.summarize([], SENT, date(2026, 11, 20), follow_up="whenever")
    assert t["follow_up"] is None and t["attention"] == []


def test_the_demo_board_carries_what_needs_attention(ws):
    assert all("attention" in a["track"] for a in ws.list_apps())
    track = lambda name: ws.track(ws.apps_dir / name, date(2026, 11, 15))  # noqa: E731
    assert kinds(track(HARBOR)) == ["debrief"] and track(HARBOR)["attention"][0]["round"] == 2
    assert kinds(track(QUARRY)) == ["follow_up"] and track(QUARRY)["follow_up"]["note"]
    assert track(NORTHWIND)["attention"] == []
    assert kinds(track(EXAMPLE_APP)) == ["deadline"]


# ----- no_debrief -----

def test_no_debrief_is_kept_on_interviews_and_a_real_debrief_replaces_it():
    base = {"date": "2026-11-03", "stage": "interview", "no_debrief": True}
    assert tracking.clean_event(base)["no_debrief"] is True
    assert "no_debrief" not in tracking.clean_event({**base, "debrief": "Went well"})
    assert "no_debrief" not in tracking.clean_event({**base, "stage": "screen"})


def test_saving_how_it_went_keeps_the_scheduling_fields(ws):
    event = ws.track(ws.apps_dir / HARBOR)["events"][2]
    fields = {k: v for k, v in event.items() if k != "i"}
    ws.update_event(HARBOR, event["i"], {**fields, "debrief": "Went fine"})
    saved = ws.events(ws.apps_dir / HARBOR)[event["i"]]
    assert saved == {**fields, "debrief": "Went fine"}


# ----- follow-up -----

@pytest.mark.parametrize("value, match", [
    ({"date": "next week"}, "should look like"),
    ({"date": "2026-02-30"}, "not a day"),
    ({"note": "Email Pat"}, "needs a date"),
    ("2026-11-12", "must be a mapping"),
])
def test_a_bad_follow_up_is_refused(value, match):
    with pytest.raises(build.BuildError, match=match):
        tracking.clean_follow_up(value)


def test_a_follow_up_is_set_and_cleared_without_touching_the_events(ws):
    app = ws.apps_dir / HARBOR
    before = ws.events(app)
    r = ws.set_follow_up(HARBOR, {"date": "2026-11-12", "note": " Email Pat "})
    assert r["follow_up"] == {"date": "2026-11-12", "note": "Email Pat"}
    assert r["track"]["follow_up"] == r["follow_up"]
    text = (app / "tracking.yaml").read_text(encoding="utf-8")
    assert "date: 2026-11-12\n" in text and ws.events(app) == before
    r = ws.set_follow_up(HARBOR, {"date": "2026-11-20"})  # replaced, and the note goes with it
    assert r["follow_up"] == {"date": "2026-11-20"}
    assert ws.set_follow_up(HARBOR, None)["track"]["follow_up"] is None
    assert "follow_up" not in (app / "tracking.yaml").read_text(encoding="utf-8") and ws.events(app) == before


def test_a_draft_cannot_have_a_follow_up(ws):
    with pytest.raises(build.BuildError, match="has not been sent"):
        ws.set_follow_up(EXAMPLE_APP, {"date": "2026-11-12"})


def test_the_follow_up_route_writes_it(ws):
    r = server.put_follow_up(SimpleNamespace(ws=ws), {"follow_up": {"date": "2026-11-12"}}, {}, HARBOR)
    assert r["track"]["follow_up"] == {"date": "2026-11-12"}


# ----- calendar files -----

ROW = {"app": "a", "stage": "interview", "date": "2026-10-16", "round": 2, "studio": "Harbor Light, Inc; Games", "role": "Designer",
       "scheduled": "2026-11-06 14:00", "length": 45, "format": "video", "interviewers": [{"name": "Sam Lee", "role": "Lead"}],
       "prep": "Read\nthe brief", "url": "https://example.com/j"}
STAMP = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


def unfolded(text):
    return text.replace("\r\n ", "").split("\r\n")


def test_a_timed_event_has_floating_local_times_and_its_length():
    lines = unfolded(ics.calendar([ROW], STAMP))
    assert "DTSTART:20261106T140000" in lines and "DTEND:20261106T144500" in lines
    assert "DTSTAMP:20261105T120000Z" in lines and "METHOD:PUBLISH" in lines
    assert lines[0] == "BEGIN:VCALENDAR" and lines[-2:] == ["END:VCALENDAR", ""]


def test_a_timed_event_with_no_length_gets_an_hour():
    row = {k: v for k, v in ROW.items() if k != "length"}
    assert "DTEND:20261106T150000" in unfolded(ics.calendar([row], STAMP))


def test_a_bare_date_is_an_all_day_event_ending_the_next_day():
    lines = unfolded(ics.calendar([{**ROW, "scheduled": "2026-12-31"}], STAMP))
    assert "DTSTART;VALUE=DATE:20261231" in lines and "DTEND;VALUE=DATE:20270101" in lines


def test_text_is_escaped_and_interviewers_are_not_attendees():
    text = ics.calendar([ROW], STAMP)
    lines = unfolded(text)
    assert "SUMMARY:Interview round 2: Harbor Light\\, Inc\\; Games" in lines
    desc = next(x for x in lines if x.startswith("DESCRIPTION:"))
    assert "Video\\, 45 min" in desc and "With: Sam Lee (Lead)" in desc and "Prep: Read\\nthe brief" in desc
    assert "ATTENDEE" not in text and "ORGANIZER" not in text


def test_long_lines_fold_at_75_octets_without_splitting_a_character():
    text = ics.calendar([{**ROW, "prep": "東京ゲームズ" * 40}], STAMP)
    assert all(len(line.encode("utf-8")) <= 75 for line in text.split("\r\n"))
    assert "東京ゲームズ" * 40 in text.replace("\r\n ", "")


def test_the_uid_survives_a_new_time_but_not_a_new_round():
    assert ics.uid(ROW) == ics.uid({**ROW, "scheduled": "2026-11-07 09:00"})
    assert ics.uid(ROW) != ics.uid({**ROW, "round": 3})


def test_one_event_exports_and_one_with_no_schedule_is_refused(ws):
    text, filename = ws.event_calendar(HARBOR, 1)
    assert "Harbor Light Games" in text and "DTSTART:20261021T140000" in text
    assert "Debrief" not in text and "Went well" not in text
    assert filename == f"{HARBOR}-interview1.ics"
    ws.add_event(HARBOR, {"date": "2026-11-01", "stage": "note", "note": "x"})
    with pytest.raises(build.BuildError, match="no scheduled date"):
        ws.event_calendar(HARBOR, 3)
    with pytest.raises(build.BuildError, match="no event 9"):
        ws.event_calendar(HARBOR, 9)


def test_upcoming_covers_open_applications_from_today_on(ws):
    text = ws.upcoming_calendar(date(2026, 11, 4))
    assert text.count("BEGIN:VEVENT") == 1 and "DTSTART:20261104T130000" in text  # earlier rounds are past
    assert ws.upcoming_calendar(date(2026, 11, 5)).count("BEGIN:VEVENT") == 0
    assert ws.upcoming_calendar(date(2026, 9, 1)).count("Northwind") == 0  # closed


def test_calendar_files_download_over_http(ws, monkeypatch):
    monkeypatch.setattr(build, "find_typst", lambda: "typst")
    monkeypatch.setattr(Handler, "studio", Studio(False))
    srv = open_server(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        with urlopen(f"{base}/api/apps/{quote(HARBOR)}/events/1/calendar") as r:
            assert r.headers["Content-Type"] == "text/calendar; charset=utf-8"
            assert f'attachment; filename="{HARBOR}-interview1.ics"' in r.headers["Content-Disposition"]
            assert r.read().startswith(b"BEGIN:VCALENDAR\r\n")
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        ws.add_event(HARBOR, {"date": "2026-11-01", "stage": "screen", "scheduled": tomorrow})
        with urlopen(f"{base}/api/calendar") as r:
            assert 'filename="upcoming-interviews.ics"' in r.headers["Content-Disposition"]
            assert tomorrow.replace("-", "").encode() in r.read()
    finally:
        srv.shutdown()
        srv.server_close()
