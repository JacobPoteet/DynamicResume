"""Where each application stands after it was sent: a list of dated events in the
application's tracking.yaml, the board column they add up to, and job search stats.

The Applied date is the day the application was marked submitted (submitted/submitted.yaml),
so it is never stored twice. Everything after that is an event:

    events:
      - date: 2026-11-03            # the day it happened, not the day you logged it
        stage: interview            # screen, interview, offer, rejected, ghosted, withdrew, note
        scheduled: 2026-11-06 14:00 # optional: when the call or interview takes place
        round: 1                    # interview only, numbered automatically
        format: video               # interview only: phone, video, onsite, take-home
        length: 60                  # interview only, minutes
        interviewers: [{name: Sam Lee, role: Lead Designer}]
        prep: what to read up on before
        debrief: how it went
        no_debrief: true            # interview only: nothing to write, so stop asking
        note: anything else

The file can also hold one reminder, next to the events (see clean_follow_up):

    follow_up: {date: 2026-11-12, note: Email the recruiter}

Ghosted is a kind of rejection with no real end date, so it counts as a rejection but is
left out of every "days to" figure.
"""
import re
from datetime import date, datetime, timedelta
from statistics import median

from build import BuildError

STAGES = ("applied", "screen", "interview", "offer", "rejected", "ghosted", "withdrew", "note")
CLOSED = ("rejected", "ghosted", "withdrew")
COLUMN = {"applied": "applied", "screen": "screen", "interview": "interviewing", "offer": "offer",
          "rejected": "rejected", "ghosted": "ghosted", "withdrew": "withdrew"}
FORMATS = ("phone", "video", "onsite", "take-home")
RESPONSES = ("screen", "interview", "offer", "rejected")  # the studio answered (withdrawing is you)
QUIET_DAYS = 30
DEADLINE_DAYS = 7  # a deadline shows as needing attention this many days either side of it
FILE = "tracking.yaml"
DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
WHEN = re.compile(r"^([0-9]{4}-[0-9]{2}-[0-9]{2})(?:[ T]([0-9]{1,2}):([0-9]{2}))?$")
TEXT = ("note", "prep", "debrief")


def day(s):
    return date.fromisoformat(str(s)[:10])


def clean_event(e, round_default=None):
    """Check one event from the app or the CLI and drop empty fields. Raises BuildError."""
    if not isinstance(e, dict):
        raise BuildError("an event must be a mapping")
    stage = str(e.get("stage") or "").strip().lower()
    if stage not in STAGES:
        raise BuildError(f"unknown stage {stage!r}; use one of {', '.join(STAGES)}")
    when = str(e.get("date") or "").strip()
    if not DATE.match(when):
        raise BuildError(f"the date should look like 2026-11-03, not {when!r}")
    day(when)  # a real calendar day
    out = {"date": when, "stage": stage}
    sched = str(e.get("scheduled") or "").strip()
    if sched:
        m = WHEN.match(sched)
        if not m:
            raise BuildError(f"scheduled should look like 2026-11-06 or 2026-11-06 14:00, not {sched!r}")
        day(m.group(1))
        if m.group(2) is not None:
            h, mi = int(m.group(2)), int(m.group(3))
            if h > 23 or mi > 59:
                raise BuildError(f"{sched!r} is not a time of day")
            sched = f"{m.group(1)} {h:02d}:{mi:02d}"
        out["scheduled"] = sched
    if stage == "interview":
        if e.get("no_debrief") is True and not str(e.get("debrief") or "").strip():
            out["no_debrief"] = True
        rnd = e.get("round") or round_default
        if rnd not in (None, ""):
            try:
                out["round"] = int(rnd)
            except (TypeError, ValueError):
                raise BuildError(f"round should be a number, not {rnd!r}")
        fmt = str(e.get("format") or "").strip().lower()
        if fmt:
            if fmt not in FORMATS:
                raise BuildError(f"unknown interview format {fmt!r}; use one of {', '.join(FORMATS)}")
            out["format"] = fmt
        length = e.get("length")
        if length not in (None, ""):
            try:
                out["length"] = int(length)
            except (TypeError, ValueError):
                raise BuildError(f"length is in minutes, not {length!r}")
        people = []
        for p in e.get("interviewers") or []:
            p = p if isinstance(p, dict) else {"name": p}
            name, role = str(p.get("name") or "").strip(), str(p.get("role") or "").strip()
            if name or role:
                people.append({k: v for k, v in (("name", name), ("role", role)) if v})
        if people:
            out["interviewers"] = people
    for k in TEXT:
        v = str(e.get(k) or "").strip()
        if v and (k == "note" or stage == "interview"):
            out[k] = v
    return out


def clean_follow_up(value):
    """Check a reminder from the app. Returns {date, note} with no empty note, or None when
    the date is blank, which clears it. Raises BuildError."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise BuildError("a follow-up must be a mapping")
    due = str(value.get("date") or "").strip()
    note = str(value.get("note") or "").strip()
    if not due:
        if note:
            raise BuildError("a follow-up needs a date")
        return None
    if not DATE.match(due):
        raise BuildError(f"the follow-up date should look like 2026-11-12, not {due!r}")
    try:
        day(due)
    except ValueError:
        raise BuildError(f"{due!r} is not a day on the calendar")
    return {"date": due, **({"note": note} if note else {})}


def read_follow_up(value):
    """The reminder as the file holds it. A plain date is fine by hand, and anything the app
    cannot read counts as no reminder rather than breaking the board."""
    try:
        return clean_follow_up(value if isinstance(value, dict) or not value else {"date": value})
    except BuildError:
        return None


def ordered(events):
    """Events by date; same-day events keep the order they were logged in. Each keeps its
    index in the file as `i`, which the app uses to edit or delete it."""
    rows = [{**e, "i": i} for i, e in enumerate(events or []) if isinstance(e, dict)]
    return sorted(rows, key=lambda e: str(e.get("date")))


def next_round(events):
    return sum(1 for e in events or [] if isinstance(e, dict) and e.get("stage") == "interview") + 1


def interview_over(e, now):
    """True once a scheduled interview's start plus its length has gone by. A bare date lasts
    the whole day. An interview with nothing scheduled may not have a date yet, so it is False."""
    if not e.get("scheduled"):
        return False
    end = when(e["scheduled"])
    if WHEN.match(str(e["scheduled"])).group(2):
        try:
            end += timedelta(minutes=int(e.get("length") or 0))
        except (TypeError, ValueError):
            pass
    return end <= now


def deadline_item(deadline, today):
    try:
        due = day(deadline)
    except (TypeError, ValueError):
        return []
    return [{"kind": "deadline", "date": due.isoformat()}] if abs((due - today).days) <= DEADLINE_DAYS else []


def summarize(events, submitted, today=None, saved=False, follow_up=None, deadline=None):
    """What the board needs to know about one application.

    `submitted` is the submitted.yaml mapping or None. Without it the application is still
    being drafted, whatever its events say. `saved` (job.yaml) makes an unsent one a lead in the
    Saved column instead; it is ignored once the application is submitted. `attention` lists
    what wants doing: a past interview with no debrief, a follow-up that is due, or the deadline
    (job.yaml) of something unsent. A closed application asks for nothing."""
    clock = datetime.now() if today is None else datetime.combine(today, datetime.min.time())
    today = today or date.today()
    evs = ordered(events)
    applied = str(submitted.get("date")) if submitted else None
    out = {"column": "drafting", "applied": applied, "since": None, "updated": applied, "round": 0,
           "next": None, "closed_from": None, "days_to_close": None, "first_reply": None, "quiet": False,
           "days_quiet": None, "events": evs, "follow_up": None, "attention": []}
    if not submitted:
        if saved:
            out["column"] = "saved"
        if deadline:
            out["attention"] = deadline_item(deadline, today)
        return out
    column, since, prev = "applied", applied, "applied"
    for e in evs:
        if e["stage"] == "note":
            continue
        col = COLUMN[e["stage"]]
        if col != column:
            if col in CLOSED and column not in CLOSED:
                prev = column
            column, since = col, e["date"]
    out.update(column=column, since=since)
    out["round"] = sum(1 for e in evs if e["stage"] == "interview")
    out["updated"] = max([applied, *(e["date"] for e in evs)])
    replies = [e["date"] for e in evs if e["stage"] in RESPONSES]
    if replies:
        out["first_reply"] = (day(replies[0]) - day(applied)).days
    if column in CLOSED:
        out["closed_from"] = prev
        if column != "ghosted":
            out["days_to_close"] = (day(since) - day(applied)).days
        return out
    out["follow_up"] = read_follow_up(follow_up)
    out["attention"] = [{"kind": "debrief", "date": e["scheduled"], "i": e["i"], "round": e.get("round")}
                        for e in evs if e["stage"] == "interview" and not e.get("debrief")
                        and not e.get("no_debrief") and interview_over(e, clock)]
    if out["follow_up"] and day(out["follow_up"]["date"]) <= today:
        out["attention"].append({"kind": "follow_up", **out["follow_up"]})
    now = datetime.combine(today, datetime.min.time())
    upcoming = sorted(e["scheduled"] for e in evs if e.get("scheduled") and when(e["scheduled"]) >= now)
    out["next"] = upcoming[0] if upcoming else None
    if column != "offer" and not upcoming:
        last = max([day(out["updated"]), *(day(e["scheduled"]) for e in evs if e.get("scheduled"))])
        out["days_quiet"] = (today - last).days
        out["quiet"] = out["days_quiet"] >= QUIET_DAYS
    return out


def when(s):
    m = WHEN.match(str(s))
    d = datetime.fromisoformat(m.group(1))
    # A bare date counts as the whole day, so an interview today is still upcoming.
    return d.replace(hour=int(m.group(2)), minute=int(m.group(3))) if m.group(2) else d.replace(hour=23, minute=59)


def stats(apps, today=None):
    """Job search figures across every sent application. `apps` are summaries (see
    summarize) of applications that were submitted."""
    today = today or date.today()
    sent = [a for a in apps if a["applied"]]
    order = ("applied", "screen", "interviewing", "offer")

    def reached(a, col):
        if col == "applied":
            return True
        hit = {COLUMN[e["stage"]] for e in a["events"] if e["stage"] in ("screen", "interview", "offer")}
        return any(order.index(c) >= order.index(col) for c in hit)

    replied = [a for a in sent if a["first_reply"] is not None]
    closed = [a for a in sent if a["column"] in ("rejected", "withdrew") and a["days_to_close"] is not None]
    rejected = [a for a in sent if a["column"] == "rejected"]
    by_stage = []
    for col in order:
        days = [a["days_to_close"] for a in rejected if a["closed_from"] == col]
        ghosted = sum(1 for a in sent if a["column"] == "ghosted" and a["closed_from"] == col)
        by_stage.append({"stage": col, "rejected": len(days), "ghosted": ghosted,
                         "median_days": med(days)})
    weeks = {}
    for a in sent:
        d = day(a["applied"])
        monday = (d - timedelta(days=d.weekday())).isoformat()
        weeks[monday] = weeks.get(monday, 0) + 1
    if weeks:
        first, last = day(min(weeks)), today - timedelta(days=today.weekday())
        w = first
        while w <= last:
            weeks.setdefault(w.isoformat(), 0)
            w += timedelta(days=7)
    interviews = [e for a in sent for e in a["events"] if e["stage"] == "interview"]
    formats = {}
    for e in interviews:
        f = e.get("format") or "unknown"
        formats[f] = formats.get(f, 0) + 1
    upcoming = sorted(({"app": a["name"], "studio": a.get("studio"), "role": a.get("role"),
                        "scheduled": e["scheduled"], "stage": e["stage"], "round": e.get("round")}
                       for a in sent if a["column"] not in CLOSED
                       for e in a["events"] if e.get("scheduled") and when(e["scheduled"]).date() >= today),
                      key=lambda u: when(u["scheduled"]))
    count = lambda col: sum(1 for a in sent if a["column"] == col)  # noqa: E731
    return {
        "sent": len(sent),
        "replied": len(replied),
        "reply_rate": round(len(replied) / len(sent), 3) if sent else None,
        "median_days_to_reply": med([a["first_reply"] for a in replied]),
        "median_days_to_close": med([a["days_to_close"] for a in closed if a["column"] == "rejected"]),
        "active": sum(1 for a in sent if a["column"] not in CLOSED),
        "outcomes": {c: count(c) for c in ("applied", "screen", "interviewing", "offer", *CLOSED)},
        "funnel": [{"stage": c, "count": sum(1 for a in sent if reached(a, c))} for c in order],
        "rejections_by_stage": by_stage,
        "weeks": [{"week": k, "count": weeks[k]} for k in sorted(weeks)],
        "interviews": len(interviews),
        "formats": formats,
        "upcoming": upcoming,
        "quiet": sum(1 for a in sent if a["quiet"]),
    }


def med(xs):
    return median(xs) if xs else None
