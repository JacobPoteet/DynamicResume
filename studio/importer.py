"""Import a job listing from a posting's link. Greenhouse, Lever and Ashby have public job
board APIs that need no key, so a link to one of them gives the studio, role, location, pay
and the listing's text. Anything else raises BuildError, and the user pastes the text.

Nothing here runs on its own: a request goes out only when the user asks for an import.
The imported text is saved in listing.md like pasted text, so it outlives the posting.
"""
import json
import re
from html import unescape
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlsplit
from urllib.request import Request, urlopen

from build import BuildError
from studio.job import safe_url

TIMEOUT = 15
AGENT = "DynamicResume listing import"
PASTE = "Paste the listing's text instead."
SLUG = re.compile(r"^[A-Za-z0-9._-]+$")


def get_json(url):
    """GET a URL and parse its JSON. Tests replace this."""
    req = Request(url, headers={"User-Agent": AGENT, "Accept": "application/json"})
    with urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def parse_url(url):
    """(board, company slug, job id, region) for a supported posting link, else None."""
    if not safe_url(url):
        return None
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    path = [p for p in parts.path.split("/") if p]
    query = parse_qs(parts.query)
    if host in ("boards.greenhouse.io", "job-boards.greenhouse.io", "job-boards.eu.greenhouse.io"):
        # /<board>/jobs/<id>, or an embed: /embed/job_app?for=<board>&token=<id>
        if len(path) >= 3 and path[1] == "jobs" and path[2].isdigit():
            return ("greenhouse", path[0], path[2], None)
        if query.get("for") and query.get("token") and query["token"][0].isdigit():
            return ("greenhouse", query["for"][0], query["token"][0], None)
        return None
    if host in ("jobs.lever.co", "jobs.eu.lever.co") and len(path) >= 2:
        return ("lever", path[0], path[1], "eu" if ".eu." in host else None)
    if host == "jobs.ashbyhq.com" and len(path) >= 2:
        return ("ashby", path[0], path[1], None)
    # A studio's own careers page that embeds Greenhouse carries ?gh_jid=<id>. The board name is
    # usually the site's name (careers.example.com -> example), so try that.
    if query.get("gh_jid") and query["gh_jid"][0].isdigit():
        labels = [x for x in host.split(".") if x not in ("www", "careers", "jobs")]
        if len(labels) >= 2:
            return ("greenhouse", labels[-2], query["gh_jid"][0], None)
    return None


def import_listing(url):
    """{studio, role, listing, location, salary, url, board} from a posting link. Raises BuildError."""
    url = str(url or "").strip()
    found = parse_url(url)
    if not found:
        raise BuildError("Import reads Greenhouse, Lever and Ashby links (boards.greenhouse.io, jobs.lever.co, "
                         f"jobs.ashbyhq.com). {PASTE}")
    board, company, job_id, region = found
    if not SLUG.match(company) or not SLUG.match(job_id):
        raise BuildError(f"That link does not look like a {board.title()} posting. {PASTE}")
    try:
        out = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby}[board](company, job_id, region)
    except HTTPError as e:
        if e.code == 404:
            raise BuildError(f"{board.title()} has no open posting at that link; it may have been taken down. {PASTE}")
        raise BuildError(f"{board.title()} answered {e.code}. {PASTE}")
    except (URLError, TimeoutError, OSError) as e:
        raise BuildError(f"Could not reach {board.title()} ({getattr(e, 'reason', e)}). {PASTE}")
    except (ValueError, KeyError, TypeError, AttributeError):
        raise BuildError(f"{board.title()} sent something this import does not understand. {PASTE}")
    out = {k: (v or "").strip() for k, v in out.items()}
    out["listing"] = tidy(out["listing"])
    if not out["listing"]:
        raise BuildError(f"The posting has no description text. {PASTE}")
    out["url"], out["board"] = url, board
    return out


def greenhouse(company, job_id, region):
    j = get_json(f"https://boards-api.greenhouse.io/v1/boards/{quote(company)}/jobs/{quote(job_id)}")
    return {"studio": j.get("company_name") or slug_name(company), "role": j.get("title"),
            "location": (j.get("location") or {}).get("name"),
            "salary": None, "listing": html_text(unescape(j.get("content") or ""))}


def lever(company, job_id, region):
    api = "https://api.eu.lever.co" if region == "eu" else "https://api.lever.co"
    j = get_json(f"{api}/v0/postings/{quote(company)}/{quote(job_id)}")
    parts = [j.get("descriptionPlain") or html_text(j.get("description") or "")]
    for block in j.get("lists") or []:
        items = html_text(f"<ul>{block.get('content') or ''}</ul>")
        parts.append(f"{block.get('text') or ''}\n{items}".strip())
    parts.append(j.get("additionalPlain") or html_text(j.get("additional") or ""))
    cats = j.get("categories") or {}
    return {"studio": slug_name(company), "role": j.get("text"), "location": cats.get("location"),
            "salary": lever_salary(j.get("salaryRange")), "listing": join(parts)}


def lever_salary(r):
    if not isinstance(r, dict) or r.get("min") is None:
        return None
    cur = f"{r['currency']} " if r.get("currency") else ""
    per = f" {r['interval'].replace('-', ' ')}" if r.get("interval") else ""
    top = f" to {r['max']:,}" if r.get("max") not in (None, r["min"]) else ""
    return f"{cur}{r['min']:,}{top}{per}"


def ashby(company, job_id, region):
    board = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{quote(company)}?includeCompensation=true")
    j = next((x for x in board.get("jobs") or [] if str(x.get("id")) == job_id), None)
    if j is None:
        raise HTTPError(None, 404, "not found", None, None)
    comp = j.get("compensation") or {}
    text = html_text(j["descriptionHtml"]) if j.get("descriptionHtml") else j.get("descriptionPlain")
    return {"studio": slug_name(company), "role": j.get("title"), "location": j.get("location"),
            "salary": comp.get("scrapeableCompensationSalarySummary") or comp.get("compensationTierSummary"),
            "listing": text}


def slug_name(slug):
    """A readable studio name from a board slug: 'escape-velocity' -> 'Escape Velocity'. The
    user can fix it before creating."""
    words = re.split(r"[-_.]+", slug)
    return " ".join(w if any(c.isupper() for c in w) else w.capitalize() for w in words if w)


def tidy(text):
    """Trim each line and keep at most one blank line in a row."""
    lines = [ln.replace("\xa0", " ").strip() for ln in text.replace("\r\n", "\n").split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def join(parts):
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


class _Text(HTMLParser):
    BLOCK = {"p", "div", "section", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "table", "tr", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag == "li":
            self.out.append("\n- ")
        elif tag == "br":
            self.out.append("\n")
        elif tag in self.BLOCK:
            self.out.append("\n\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self.out.append("\n\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(re.sub(r"\s+", " ", data))


def html_text(html):
    """Plain text from posting HTML: paragraphs split by blank lines, list items as '- '."""
    p = _Text()
    p.feed(html or "")
    p.close()
    text = tidy("\n".join(ln for ln in tidy("".join(p.out)).split("\n") if ln != "-"))
    text = re.sub(r"\n\n(?=- )", "\n", text)  # keep a list's items together
    return text.strip()
