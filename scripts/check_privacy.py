#!/usr/bin/env python3
"""Fail if a committed file looks like personal data. Run by CI on every push and PR.

This repo is public and the tool runs on personal data, so .gitignore is the first line of
defense and this is the second (a `git add -f` or a wrong path gets past the first). It
checks every tracked file, and the text inside the example PDFs, for:

  - paths that only ever hold personal data (data/, applications/, Local/, ...)
  - PDFs outside examples/
  - email addresses and phone numbers that are not the demo's fictional ones
  - absolute paths into a home folder, which name the person and their machine
  - PRIVATE_TERMS: an optional, comma or newline separated list (a GitHub secret, never a
    file) of words that must never appear, such as your name and employers. Matches are
    reported by file only, so the log does not repeat the term.

scripts/public-terms.txt lists exact phrases that are public on purpose, such as the
author credit on the project page. They are removed before PRIVATE_TERMS are matched, so
"Jane Doe" there lets the credit through while "Doe" alone, or an employer, still fails.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRIVATE_DIRS = ("data/", "applications/", "Local/", "snapshots/", "build/")
PRIVATE_FILES = ("CLAUDE.local.md",)
PUBLIC_TERMS_FILE = ROOT / "scripts" / "public-terms.txt"
BINARY = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".zip", ".woff", ".woff2", ".ttf", ".otf"}

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
ALLOWED_EMAIL = re.compile(r"@(example\.(com|org|net)|users\.noreply\.github\.com)$|^noreply@anthropic\.com$", re.I)
PHONE = re.compile(r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)")
HOME_PATH = re.compile(r"(?i)\b[a-z]:[\\/]+users[\\/]+[^\\/\s\"'`]+|/(?:home|Users)/[a-z][\w.-]*/")


def tracked_files():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
    return [f for f in out.stdout.decode("utf-8").split("\0") if f]


def pdf_text(path):
    try:
        from pypdf import PdfReader
    except ImportError:
        sys.exit("check_privacy: pip install pypdf to scan the example PDFs")
    return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)


def private_terms():
    raw = os.environ.get("PRIVATE_TERMS", "")
    return [t.strip().lower() for t in re.split(r"[,\n]", raw) if len(t.strip()) >= 3]


def public_terms():
    if not PUBLIC_TERMS_FILE.exists():
        return []
    lines = PUBLIC_TERMS_FILE.read_text(encoding="utf-8").splitlines()
    return [t.strip().lower() for t in lines if t.strip() and not t.lstrip().startswith("#")]


def scan_text(name, text, terms, public=()):
    problems = []
    for m in EMAIL.finditer(text):
        if not ALLOWED_EMAIL.search(m.group()):
            problems.append(f"{name}: email address {m.group()!r} (only example.com addresses belong in the repo)")
    for m in PHONE.finditer(text):
        if "555" not in m.group():  # 555 numbers are reserved for fiction
            problems.append(f"{name}: phone number {m.group()!r} (use a 555 number in examples)")
    for m in HOME_PATH.finditer(text):
        problems.append(f"{name}: absolute path into a home folder {m.group()!r}")
    # Compared without spaces too, since PDF text extraction can split or join words.
    low = text.lower()
    for p in public:
        low = low.replace(p, " ")
    squashed = re.sub(r"\s+", "", low)
    for p in public:
        squashed = squashed.replace(re.sub(r"\s+", "", p), "")
    if any(t in low or re.sub(r"\s+", "", t) in squashed for t in terms):
        problems.append(f"{name}: contains a PRIVATE_TERMS entry")
    return problems


def main():
    terms, public = private_terms(), public_terms()
    me = Path(__file__).resolve().relative_to(ROOT).as_posix()
    problems = []
    for name in tracked_files():
        if name.startswith(PRIVATE_DIRS) or name in PRIVATE_FILES:
            problems.append(f"{name}: this path holds personal data and is gitignored; remove it from git")
            continue
        suffix = Path(name).suffix.lower()
        if suffix == ".pdf" and not name.startswith("examples/"):
            problems.append(f"{name}: PDFs outside examples/ are built from personal data")
            continue
        if name == me:
            continue  # its own patterns would match
        if suffix == ".pdf":
            problems += scan_text(name, pdf_text(ROOT / name), terms, public)
        elif suffix not in BINARY:
            try:
                text = (ROOT / name).read_text(encoding="utf-8")
            except (UnicodeDecodeError, FileNotFoundError):
                continue
            problems += scan_text(name, text, terms, public)
    if problems:
        print("Possible personal data in the repo:")
        print("\n".join(f"  {p}" for p in problems))
        sys.exit(1)
    print(f"Privacy check passed ({len(tracked_files())} files{', with PRIVATE_TERMS' if terms else ''}).")


if __name__ == "__main__":
    main()
