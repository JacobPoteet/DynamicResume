"""Job details for an application: the posting's link, where it is, pay, how you found it,
who referred you, the deadline and a contact. They live in the application's job.yaml, all
optional, and stay editable after the application is submitted. `saved: true` marks a lead
you have not started drafting.

    saved: true
    url: https://example.com/jobs/123
    location: Remote (US)
    salary: 120k to 140k
    source: Studio careers page
    referral: Sam Lee
    deadline: 2026-11-20
    contact: Pat Kim, recruiter, pat@example.com
"""
import re
from datetime import date
from urllib.parse import urlsplit

from build import BuildError

FILE = "job.yaml"
FIELDS = ("url", "location", "salary", "source", "referral", "deadline", "contact")
DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def safe_url(url):
    """True for an http or https link with a host: the only kind the app shows as a link."""
    try:
        parts = urlsplit(str(url or "").strip())
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.netloc) and not any(c.isspace() for c in str(url).strip())


def clean_job(job):
    """Check job details from the app and drop empty fields. Raises BuildError."""
    if job is None:
        job = {}
    if not isinstance(job, dict):
        raise BuildError("job details must be a mapping")
    out = {}
    if job.get("saved") is True:
        out["saved"] = True
    for k in FIELDS:
        v = str(job.get(k) or "").strip()
        if not v:
            continue
        if k == "url" and not safe_url(v):
            raise BuildError(f"the link should start with http:// or https://, not {v!r}")
        if k == "deadline":
            if not DATE.match(v):
                raise BuildError(f"the deadline should look like 2026-11-20, not {v!r}")
            try:
                v = date.fromisoformat(v)  # a real calendar day, written as a plain YAML date
            except ValueError:
                raise BuildError(f"{v!r} is not a day on the calendar")
        out[k] = v
    return out
