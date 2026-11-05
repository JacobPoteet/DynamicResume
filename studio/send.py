"""The plain text of an application, for pasting into application forms. Built from the same
resolved data as the PDFs, so overrides, short texts and the letter's greeting all apply."""
import build
from build import BuildError

CONTACT = ("name", "email", "phone", "location", "linkedin")
# What a tailor or master the build refuses can raise (as in build.pdf_hashes).
REFUSED = (BuildError, AttributeError, KeyError, TypeError, ValueError)


def letter_text(data):
    """The letter as it prints below the header: date if set, greeting, paragraphs, closing, name."""
    date = [str(data["date"])] if data.get("date") else []
    return "\n\n".join([*date, data["greeting"], *data["paragraphs"], f"{data['closing']}\n{data['basics']['name']}"])


def role_text(position):
    """One line per bullet, in resume order."""
    return "\n".join(f"- {b['text']}" for b in position["bullets"])


def contact_text(basics):
    return "\n".join(str(basics[k]).strip() for k in CONTACT if str(basics.get(k) or "").strip())


def plain_text(master, tailor, letter):
    """{contact, roles, letter, error}. `letter` is None with no letter text, and `error` says
    why when the tailor does not build (roles are then empty and the letter may be None)."""
    out = {"contact": contact_text(master["basics"]), "roles": [], "letter": None, "error": None}
    with build.collect_warnings():  # the build reports these; pasting text is not the place
        try:
            out["roles"] = [{"id": p["id"], "title": p["title"], "company": p["company"], "game": p["game"],
                             "dates": p["dates"], "text": role_text(p)}
                            for p in build.resume_data(master, tailor)["positions"] if p["bullets"]]
        except REFUSED as e:
            out["error"] = str(e)
        try:
            if letter.strip():
                out["letter"] = letter_text(build.letter_data(master, tailor, letter))
        except REFUSED as e:
            out["error"] = out["error"] or str(e)
    return out
