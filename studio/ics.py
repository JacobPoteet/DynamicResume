"""Calendar files for scheduled calls and interviews (RFC 5545), to download and open in any
calendar. Times are floating, so they mean the local time the person typed. Interviewers go in
the description, never as attendees, so a calendar has nobody to send an invitation to.
"""
import hashlib
from datetime import datetime, timedelta, timezone

from studio import tracking

DEFAULT_MINUTES = 60
FORMAT_LABEL = {"phone": "Phone", "video": "Video", "onsite": "Onsite", "take-home": "Take-home"}


def escape(text):
    return str(text).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\n").replace("\n", "\\n")


def fold(line):
    """Break a content line so none passes 75 octets, never inside a character."""
    out, cur, size = [], "", 0
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > 75:
            out.append(cur)
            cur, size = " ", 1  # the leading space counts toward the next line
        cur += ch
        size += n
    return "\r\n".join([*out, cur])


def summary(row):
    stage = {"interview": "Interview", "screen": "Screen"}.get(row["stage"], str(row["stage"]).capitalize())
    rnd = f" round {row['round']}" if row.get("round") else ""
    return f"{stage}{rnd}: {row['studio']}"


def description(row):
    how = [FORMAT_LABEL.get(row.get("format"), row.get("format")), f"{row['length']} min" if row.get("length") else None]
    people = [p.get("name", "") + (f" ({p['role']})" if p.get("role") else "") for p in row.get("interviewers") or []]
    lines = [row.get("role"), ", ".join(x for x in how if x), f"With: {', '.join(people)}" if people else None,
             f"Prep: {row['prep']}" if row.get("prep") else None, row.get("note"), row.get("url")]
    return "\n".join(x for x in lines if x)


def times(row):
    """DTSTART and DTEND lines. A bare date is an all-day event."""
    scheduled = str(row["scheduled"]).strip()
    m = tracking.WHEN.match(scheduled)
    if not m.group(2):
        start = tracking.day(scheduled)
        return [f"DTSTART;VALUE=DATE:{start:%Y%m%d}", f"DTEND;VALUE=DATE:{start + timedelta(days=1):%Y%m%d}"]
    start = tracking.when(scheduled)
    try:
        minutes = int(row.get("length") or DEFAULT_MINUTES)
    except (TypeError, ValueError):
        minutes = DEFAULT_MINUTES
    return [f"DTSTART:{start:%Y%m%dT%H%M%S}", f"DTEND:{start + timedelta(minutes=minutes):%Y%m%dT%H%M%S}"]


def uid(row):
    """Stays the same when the time or details change, so a calendar that matches on UID can
    update its copy on a second import."""
    key = "|".join(str(row.get(k)) for k in ("app", "stage", "round", "date"))
    return f"{hashlib.sha256(key.encode('utf-8')).hexdigest()[:32]}@dynamicresume.invalid"


def calendar(rows, stamp=None):
    """A calendar file holding each row: a scheduled event plus app, studio, role and url."""
    stamp = stamp or datetime.now(timezone.utc)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//DynamicResume//Application tracker//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
    for row in rows:
        details = description(row)
        lines += ["BEGIN:VEVENT", f"UID:{uid(row)}", f"DTSTAMP:{stamp:%Y%m%dT%H%M%SZ}", *times(row),
                  f"SUMMARY:{escape(summary(row))}", *([f"DESCRIPTION:{escape(details)}"] if details else []), "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(x) for x in lines) + "\r\n"
