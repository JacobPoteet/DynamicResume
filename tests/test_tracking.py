"""Application tracking: events in tracking.yaml, the board column they add up to, the
track command and the job search stats."""
from argparse import Namespace
from datetime import date
from types import SimpleNamespace

import pytest

import build
from conftest import EXAMPLE_APP
from studio import server, tracking

SENT = {"date": "2026-10-01"}
TODAY = date(2026, 10, 28)
HARBOR = "harbor-light-games-senior-combat-designer"
NORTHWIND = "northwind-interactive-systems-designer"
QUARRY = "quarry-lane-studio-technical-designer"


def ev(day, stage, **kw):
    return {"date": day, "stage": stage, **kw}


# ----- summarize -----

def test_an_unsent_application_is_drafting_whatever_its_events_say():
    t = tracking.summarize([ev("2026-10-05", "screen")], None, TODAY)
    assert t["column"] == "drafting" and t["applied"] is None


def test_the_column_follows_the_latest_stage_and_notes_do_not_move_it():
    events = [ev("2026-10-05", "screen"), ev("2026-10-09", "interview"), ev("2026-10-12", "note", note="thank-you sent")]
    t = tracking.summarize(events, SENT, TODAY)
    assert t["column"] == "interviewing" and t["since"] == "2026-10-09"
    assert t["updated"] == "2026-10-12" and t["first_reply"] == 4 and t["round"] == 1


def test_events_count_by_date_not_by_the_order_they_were_logged():
    t = tracking.summarize([ev("2026-10-09", "interview"), ev("2026-10-05", "screen")], SENT, TODAY)
    assert t["column"] == "interviewing" and [e["i"] for e in t["events"]] == [1, 0]


def test_a_rejection_records_where_it_ended_and_how_long_it_took():
    t = tracking.summarize([ev("2026-10-05", "screen"), ev("2026-10-20", "rejected")], SENT, TODAY)
    assert t["column"] == "rejected" and t["closed_from"] == "screen" and t["days_to_close"] == 19
    t = tracking.summarize([ev("2026-10-20", "rejected")], SENT, TODAY)
    assert t["closed_from"] == "applied" and t["first_reply"] == 19


def test_ghosted_is_a_rejection_with_no_time_to_rejection():
    t = tracking.summarize([ev("2026-10-05", "screen"), ev("2026-11-20", "ghosted")], SENT, TODAY)
    assert t["column"] == "ghosted" and t["closed_from"] == "screen" and t["days_to_close"] is None


def test_quiet_after_30_days_with_nothing_logged_or_scheduled():
    assert not tracking.summarize([], SENT, date(2026, 10, 30))["quiet"]
    t = tracking.summarize([], SENT, date(2026, 10, 31))
    assert t["quiet"] and t["days_quiet"] == 30
    # A scheduled interview counts as activity, and an upcoming one is never quiet.
    later = [ev("2026-10-02", "interview", scheduled="2026-10-20 14:00")]
    assert not tracking.summarize(later, SENT, date(2026, 11, 18))["quiet"]
    assert tracking.summarize(later, SENT, date(2026, 11, 19))["quiet"]
    upcoming = [ev("2026-10-02", "interview", scheduled="2026-12-20")]
    t = tracking.summarize(upcoming, SENT, date(2026, 12, 20))
    assert not t["quiet"] and t["next"] == "2026-12-20"


def test_next_is_the_earliest_upcoming_scheduled_event():
    events = [ev("2026-10-05", "screen", scheduled="2026-10-06 10:00"),
              ev("2026-10-20", "interview", scheduled="2026-11-10 09:00"),
              ev("2026-10-21", "interview", scheduled="2026-11-03 15:00")]
    assert tracking.summarize(events, SENT, TODAY)["next"] == "2026-11-03 15:00"


# ----- clean_event -----

def test_clean_event_checks_and_normalizes():
    e = tracking.clean_event({"date": "2026-11-03", "stage": "Interview", "scheduled": "2026-11-06 9:05",
                              "format": "video", "length": "45", "interviewers": [{"name": "Sam", "role": ""}, {}, "Ana"],
                              "prep": " read up ", "note": ""}, round_default=2)
    assert e == {"date": "2026-11-03", "stage": "interview", "scheduled": "2026-11-06 09:05", "round": 2,
                 "format": "video", "length": 45, "interviewers": [{"name": "Sam"}, {"name": "Ana"}], "prep": "read up"}
    # Interview-only fields are dropped from other stages.
    assert tracking.clean_event({"date": "2026-11-03", "stage": "screen", "format": "video", "prep": "x"}) == \
        {"date": "2026-11-03", "stage": "screen"}


@pytest.mark.parametrize("event, match", [
    ({"date": "2026-11-03", "stage": "phone screen"}, "unknown stage"),
    ({"date": "11/03/2026", "stage": "screen"}, "should look like"),
    ({"date": "2026-02-30", "stage": "screen"}, "day is out of range"),
    ({"date": "2026-11-03", "stage": "screen", "scheduled": "Tuesday"}, "scheduled should"),
    ({"date": "2026-11-03", "stage": "screen", "scheduled": "2026-11-06 25:00"}, "not a time"),
    ({"date": "2026-11-03", "stage": "interview", "format": "zoom"}, "unknown interview format"),
    ({"date": "2026-11-03", "stage": "interview", "length": "an hour"}, "minutes"),
])
def test_clean_event_refuses_bad_input(event, match):
    with pytest.raises((build.BuildError, ValueError), match=match):
        tracking.clean_event(event)


# ----- workspace -----

def test_a_draft_moves_to_applied_by_being_submitted(ws):
    with pytest.raises(build.BuildError, match="Move it to Applied first"):
        ws.add_event(EXAMPLE_APP, ev("2026-10-05", "screen"))
    r = ws.add_event(EXAMPLE_APP, ev("2026-10-01", "applied", note="Careers site"))
    assert r["submitted"]["date"] == "2026-10-01" and r["track"]["column"] == "applied"
    assert build.submission(ws.apps_dir / EXAMPLE_APP)["date"] == "2026-10-01"
    assert ws.events(ws.apps_dir / EXAMPLE_APP) == [{"date": "2026-10-01", "stage": "note", "note": "Careers site"}]
    assert r["index"] == 0


def test_events_are_added_numbered_edited_and_deleted_on_a_submitted_application(ws):
    app = ws.apps_dir / HARBOR
    with pytest.raises(build.BuildError, match="Unsubmit"):
        ws.require_editable(HARBOR)
    r = ws.add_event(HARBOR, ev("2026-11-05", "interview", format="onsite"))
    assert r["index"] == 3 and ws.events(app)[3]["round"] == 3
    ws.update_event(HARBOR, 3, ev("2026-11-05", "interview", format="onsite", debrief="Long day"))
    assert ws.events(app)[3] == {"date": "2026-11-05", "stage": "interview", "round": 3, "format": "onsite", "debrief": "Long day"}
    text = (app / "tracking.yaml").read_text(encoding="utf-8")
    assert "date: 2026-11-05\n" in text  # a plain YAML date, easy to edit by hand
    assert ws.delete_event(HARBOR, 3)["track"]["round"] == 2
    with pytest.raises(build.BuildError, match="no event 9"):
        ws.delete_event(HARBOR, 9)


def test_list_and_load_carry_the_tracking_summary(ws):
    cols = {a["name"]: a["track"]["column"] for a in ws.list_apps()}
    assert cols == {EXAMPLE_APP: "drafting", HARBOR: "interviewing", NORTHWIND: "rejected", QUARRY: "applied"}
    assert ws.load_app(HARBOR)["track"]["round"] == 2


def test_stats_across_the_demo(ws):
    s = ws.stats(TODAY)
    assert s["sent"] == 3 and s["replied"] == 2 and s["reply_rate"] == 0.667
    assert s["median_days_to_reply"] == 8  # Harbor 7 days, Northwind 9
    assert s["median_days_to_close"] == 23 and s["active"] == 2 and s["quiet"] == 1
    assert [f["count"] for f in s["funnel"]] == [3, 2, 1, 0]
    assert {r["stage"]: r["rejected"] for r in s["rejections_by_stage"]}["screen"] == 1
    assert s["formats"] == {"video": 1, "take-home": 1} and s["interviews"] == 2
    assert [u["app"] for u in s["upcoming"]] == [HARBOR]
    assert s["weeks"][0] == {"week": "2026-09-07", "count": 1} and s["weeks"][-1]["week"] == "2026-10-26"
    assert sum(w["count"] for w in s["weeks"]) == 3


def test_ghosted_counts_as_rejected_but_not_in_timing(ws):
    ws.add_event(QUARRY, ev("2026-10-28", "ghosted"))
    s = ws.stats(TODAY)
    assert s["outcomes"]["ghosted"] == 1 and s["median_days_to_close"] == 23
    assert {r["stage"]: r["ghosted"] for r in s["rejections_by_stage"]}["applied"] == 1


# ----- server and CLI -----

def test_server_routes_write_events(ws):
    s = SimpleNamespace(ws=ws)
    r = server.add_event(s, {"event": ev("2026-11-01", "note", note="Sent thank-you notes")}, {}, HARBOR)
    server.update_event(s, {"event": ev("2026-11-01", "note", note="Sent thanks")}, {}, HARBOR, str(r["index"]))
    assert ws.events(ws.apps_dir / HARBOR)[r["index"]]["note"] == "Sent thanks"
    server.delete_event(s, {}, {}, HARBOR, str(r["index"]))
    assert len(ws.events(ws.apps_dir / HARBOR)) == 3
    assert server.stats(s, {}, {})["sent"] == 3


def test_track_command_logs_and_prints(home, capsys):
    args = Namespace(target=NORTHWIND, stage=None, date=None, note=None, scheduled=None, format=None, length=None, interviewers=[])
    build.print_track(False, args)
    out = capsys.readouterr().out
    assert "rejected (from screen)" in out and "2026-09-15  applied" in out
    args.stage, args.date, args.format, args.interviewers = "interview", "2026-10-01", "phone", ["Sam Lee, Lead", "Ana"]
    args.target = QUARRY
    build.print_track(False, args)
    out = capsys.readouterr().out
    assert "interview round 1" in out and "with Sam Lee (Lead), Ana" in out
