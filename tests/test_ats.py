"""Real Typst builds of the demo, read back the way an ATS reads them (pypdf text
extraction). Needs the typst CLI: skipped without it, unless REQUIRE_TYPST is set (CI)."""
import copy
import os
import re
import shutil

import pytest
import yaml

import build
from conftest import EXAMPLE_APP, REPO

pytestmark = pytest.mark.typst
APP = REPO / "examples" / "applications" / EXAMPLE_APP
REBUILD = "rebuild the demo with: python build.py --example build-all"


@pytest.fixture(scope="module")
def typst():
    try:
        return build.find_typst()
    except build.BuildError:
        if os.environ.get("REQUIRE_TYPST"):
            raise
        pytest.skip("typst is not installed")


def workdir(name):
    """A fresh folder under build/ (gitignored): typst only reads data from inside the repo."""
    d = REPO / "build" / "pytest" / name
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    return d


def pdf_text(path):
    from pypdf import PdfReader
    return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)


def words(text):
    return " ".join(text.split())


@pytest.fixture(scope="module")
def built(typst):
    """The demo application built fresh, into build/pytest/demo."""
    return build.build_app(typst, APP, True, out_dir=workdir("demo"))


@pytest.fixture(scope="module")
def resume(built):
    return pdf_text(built["resume"])


def render_resume(typst, name, master, tailor):
    work = workdir(name)
    out = work / "resume.pdf"
    f = build.fill(build.render(typst, "resume-inline.typ", build.resume_data(master, tailor), out, work, "resume"))
    return pdf_text(out), f


def test_the_demo_fits_one_page_without_wraps(built):
    assert built["resume_fill"]["pages"] == 1
    assert built["letter_fill"]["pages"] == 1
    assert built["resume_fill"]["wraps"] == []
    assert built["resume_fill"]["bullets"], "the template reported no bullet measurements"


def test_section_headings_extract_as_words(resume):
    for heading in ("EXPERIENCE", "SKILLS", "PROJECTS", "EDUCATION"):
        assert re.search(rf"^{heading}$", resume, re.M), f"{heading} heading missing or spaced out"
    assert not re.search(r"\b[A-Z] [A-Z] [A-Z] [A-Z]\b", resume), "letter-spaced text (tracking too wide)"


def test_skills_come_before_projects(resume):
    # A standard heading must close Experience, or parsers fold projects into the last job.
    assert resume.index("SKILLS") < resume.index("PROJECTS")


def test_contacts_and_companies_extract(resume, master):
    b = master["basics"]
    for value in (b["name"], b["email"], b["phone"]):
        assert value in resume
    for p in master["positions"]:
        assert p["company"] in resume


def test_no_em_dashes(resume):
    assert "—" not in resume


def test_later_roles_at_one_company_repeat_the_company(typst, master, tailor):
    m = copy.deepcopy(master)
    m["positions"][1]["company"] = m["positions"][0]["company"]  # two roles, one employer
    text, _ = render_resume(typst, "one-company", m, tailor)
    company = m["positions"][0]["company"]
    assert re.search(rf"\| {re.escape(company)} \|", text), "the second role line should name the company"


def test_a_long_role_line_is_reported(typst, master, tailor):
    m = copy.deepcopy(master)
    m["games"][1]["name"] = "Dungeon Delvers Remastered Definitive Edition Collection Deluxe"
    _, f = render_resume(typst, "long-role", m, tailor)
    assert [w["what"] for w in f["wraps"]] == ["Role line"]


PAGE_PT = {"letter": (612, 792), "a4": (595.28, 841.89)}


@pytest.fixture(scope="module", params=sorted(PAGE_PT))
def sized(request, typst):
    """The demo application built fresh on each paper size, from a copy of its folder."""
    paper = request.param
    work = workdir(f"paper-{paper}")
    app = work / "app"
    shutil.copytree(APP, app)
    t = build.load_yaml(app / "tailor.yaml")
    t["paper"] = paper
    (app / "tailor.yaml").write_text(yaml.safe_dump(t), encoding="utf-8")
    return paper, build.build_app(typst, app, True, out_dir=work)


def page_size(path):
    from pypdf import PdfReader
    boxes = [(float(p.mediabox.width), float(p.mediabox.height)) for p in PdfReader(path).pages]
    assert len(boxes) == 1, f"{path} should be one page"
    return boxes[0]


def test_both_pdfs_use_the_chosen_paper(sized):
    paper, r = sized
    assert page_size(r["resume"]) == pytest.approx(PAGE_PT[paper], abs=0.1)
    assert page_size(r["letter"]) == pytest.approx(PAGE_PT[paper], abs=0.1)


def test_each_paper_passes_the_ats_text_checks(sized, master):
    _, r = sized
    assert r["resume_fill"]["pages"] == 1 and r["letter_fill"]["pages"] == 1
    assert r["resume_fill"]["wraps"] == []
    text = pdf_text(r["resume"])
    for heading in ("EXPERIENCE", "SKILLS", "PROJECTS", "EDUCATION"):
        assert re.search(rf"^{heading}$", text, re.M), f"{heading} heading missing or spaced out"
    assert not re.search(r"\b[A-Z] [A-Z] [A-Z] [A-Z]\b", text), "letter-spaced text (tracking too wide)"
    assert text.index("SKILLS") < text.index("PROJECTS")
    assert "—" not in text
    for value in (master["basics"]["name"], master["basics"]["email"], master["basics"]["phone"]):
        assert value in text
    for p in master["positions"]:
        assert p["company"] in text


@pytest.mark.parametrize("paper", sorted(PAGE_PT))
@pytest.mark.parametrize("template", build.templates() + ["cover-letter"])
def test_fit_figures_use_the_real_page(typst, master, tailor, template, paper):
    t = {**tailor, "paper": paper}
    data = build.letter_data(master, t, "Body.") if template == "cover-letter" else build.resume_data(master, t)
    work = workdir(f"fit-{template}-{paper}")
    layout = build.render(typst, f"{template}.typ", data, work / "out.pdf", work, "page")
    assert page_size(work / "out.pdf") == pytest.approx(PAGE_PT[paper], abs=0.1)
    assert layout["limit"] == pytest.approx(PAGE_PT[paper][1] - 36, abs=0.1)  # 0.5in bottom margin


def test_committed_demo_pdfs_are_current(built):
    resume, letter = build.output_names(build.load_yaml(REPO / "examples/data/master.yaml"),
                                        build.load_yaml(APP / "tailor.yaml"), APP)
    assert words(pdf_text(APP / resume)) == words(pdf_text(built["resume"])), f"demo resume PDF is stale: {REBUILD}"
    assert words(pdf_text(APP / letter)) == words(pdf_text(built["letter"])), f"demo cover letter PDF is stale: {REBUILD}"
