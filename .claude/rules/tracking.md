---
paths:
  - "studio/tracking.py"
  - "studio/job.py"
  - "studio/ics.py"
  - "studio/workspace.py"
  - "studio/static/tracker.js"
  - "applications/**/tracking.yaml"
  - "applications/**/job.yaml"
  - "examples/**/tracking.yaml"
  - "examples/**/job.yaml"
---

# Application tracking

## The board

The home page is a board: Saved (leads not started), Drafting (not submitted), Applied, Screen, Interviewing, Offer, and Rejected, Ghosted and Withdrew trays. Each column lists the most recently updated first. Dragging a card opens a dialog for the date it happened, an optional scheduled date and time, and a note; interviews also take round (numbered automatically), format, length, interviewers and prep notes. The debrief is separate: How it went (`openDebrief` in `tracker.js`) opens from the Needs attention strip or a button on the history row once the start time has passed, and saves the whole event back so the scheduling fields stay. Moving a draft to Applied opens the Send dialog instead. Clicking a card opens its history, where every event can be edited or deleted. A card in Applied, Screen or Interviewing with nothing logged or scheduled for 30 days shows Quiet and offers Ghosted, which counts as a rejection but is left out of time-to-rejection. Saved comes from `saved: true` in the application's `job.yaml`: New application has Save for later, which needs only a studio, a role and optionally a link; a card's Start drafting (or dragging it onto Drafting) clears the flag. Cards show the link and deadline, and the history dialog lists every job detail. Saved leads are not counted in Stats.

Needs attention is a strip at the top of the board, hidden when empty and not narrowed by the search or stage menu. `tracking.summarize` fills `track.attention` with three kinds: `debrief` (an interview whose scheduled start plus length has passed, with no `debrief` or `no_debrief`; an interview with nothing scheduled never asks), `follow_up` (the reminder's date is today or earlier) and `deadline` (an unsent application within `DEADLINE_DAYS`, 7, either side of its `job.yaml` deadline). A closed application asks for nothing. The Quiet flag stays on the card, outside the strip. Set follow-up in the history dialog writes `follow_up` in `tracking.yaml`, only on a sent, open application; Done on the strip clears it (with Undo) and logs no event.

Every scheduled event has a Calendar link in the history (`GET /api/apps/<name>/events/<i>/calendar`), and the board's metric row and Stats' Coming up link to every upcoming one (`GET /api/calendar`). `studio/ics.py` writes the file: floating local times, all-day for a bare date, 60 minutes when no length is set, and interviewers in the description, never as attendees. The app only offers the download and never sends anything.

Timeline and Stats (reply rate, days to reply and to rejection by stage, funnel, applications per week, interviews by format, upcoming) are computed by `studio/tracking.py`.

## tracking.yaml schema

In each application folder. The Applied date is `submitted/submitted.yaml`'s date, never stored here. Events are kept in the order logged; the board orders them by date. `follow_up` is an optional reminder, not an event; only an application that was sent and is still open uses it, and a plain date works when editing by hand. It lives here, not in `job.yaml`, because restoring a snapshot keeps the current `tracking.yaml`.

```yaml
follow_up:
  date: 2026-11-12                 # shows under Needs attention from this day on
  note: Email the recruiter        # optional
events:
  - date: 2026-11-03               # the day it happened
    stage: interview               # screen, interview, offer, rejected, ghosted, withdrew, note (applied only to move back)
    scheduled: 2026-11-06 14:00    # optional: YYYY-MM-DD or YYYY-MM-DD HH:MM
    round: 2                       # interview only, from here down
    format: video                  # phone, video, onsite, take-home
    length: 60                     # minutes
    interviewers: [{name: Sam Lee, role: Lead Designer}]
    prep: what to review
    debrief: how it went
    no_debrief: true               # nothing to write, so the board stops asking; a debrief replaces it
    note: anything else            # any stage
```

## job.yaml schema

In each application folder, edited on the Listing tab (it stays open on submitted applications). Every field is optional and empty ones are dropped; the file is deleted when nothing is left. `studio/job.py` checks it. The `url` must be http or https, and the app only shows it as a link then. The `deadline` is `YYYY-MM-DD`.

```yaml
saved: true                        # a lead you have not started drafting (Saved column); removed by Start drafting
url: https://example.com/jobs/123
location: Remote (US)
salary: 120k to 140k
source: Studio careers page
referral: Sam Lee
deadline: 2026-11-20
contact: Pat Kim, recruiter, pat@example.com
```

A redraft never touches `job.yaml`, and `Workspace.outside_edits` guards it like the other autosaved files. `GET /api/apps` and `GET /api/apps/<name>` carry it as `job`; `PUT /api/apps/<name>/job` saves it.
