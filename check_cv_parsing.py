#!/usr/bin/env python3
"""
Regression test for CV PDF text extraction.

Checks three independent properties across several extractor families:

  1. LEAD    -- name and contact details appear near the top of the
                extracted text (parsers that key on position find them).
  2. RECORDS -- each job's title, employer, dates and bullets come out
                together, so the employment record survives as a record.
  3. ORDER   -- the main column's landmarks appear in document order.

A layout can pass one and fail the others; all three matter.

Before any of them, PAGES asserts the document is still one page. That is
the whole premise of this CV, and nothing checked it: a summary two words
too long silently spilled the main column's last block onto a second page
while every extraction check went on passing, because text that moved to
page two still extracts in the right order.

RECORDS replaced an earlier check that demanded the main column extract as
one uninterrupted run. Two columns of unequal length always displace the
sidebar somewhere, so that bar could only be met by luck, and clearing it
said little: the sidebar landing between two sections costs a reader
nothing. Landing *inside* a job record costs a lot -- it detaches a title
from its dates, or strands a job's achievements fifty lines from the job.
That is the failure worth gating on, and it is what RECORDS measures.

Usage:  python3 check_cv_parsing.py cv.pdf
Exit:   0 if all extractors pass every check, 1 otherwise.
"""

import subprocess
import sys

# --- expectations -----------------------------------------------------------

NAME = "Jan Hermann"
CONTACT_TOKEN = "info@hrmnn.net"
LEAD_WINDOW = 8  # name and contact must fall within this many lines
EXPECTED_PAGES = 1  # this CV is a one-pager; spilling to two is a failure

# Headings that live in the sidebar. None of these may land inside a job
# record; between records they are harmless.
SIDEBAR_MARKERS = [
    "Skills",
    "Open source",
    "Education",
    "Awards",
    "Ships inside",
    "Mentoring and service",
]

# A layout-preserving extractor keeps the sidebar in its own column, indented
# past the main text. A heading that far right is where it belongs, so it is
# not an intrusion. Flowed extractions have no indentation and this never
# fires.
SIDEBAR_COLUMN_INDENT = 40

# Ordered landmarks that belong to the main column narrative.
MAIN_MARKERS = [
    "Experience",
    "Principal Research Manager",
    "Junior Research Group Leader",
    "Doctoral Researcher",
    "Selected publications",
]

# The employment records an applicant-tracking system builds its history from:
# a job title, who it was with, when, and what came of it. All four parts have
# to stay together for the record to mean anything. Fragments are chosen to be
# unique in the document -- "Microsoft Research" and "Co-lead" also occur in the
# summary paragraph, for instance, so the fuller company line and a phrase from
# the bullet stand in for them. The two "Postdoctoral Researcher" titles are
# left out precisely because they are not unique.
JOB_RECORDS = [
    ("Principal Research Manager", "Microsoft Research, AI for Science", "Nov 2022", "60-year-old"),
    ("Junior Research Group Leader", "Department of Mathematics", "Nov 2020", "Founded and led"),
    ("Doctoral Researcher", "Theory Department", "Oct 2013", "Developed many-body"),
]

# How far from its title the rest of a record may sit. Extractors disagree on
# the order of a right-aligned date (pdfminer emits it before the title,
# poppler after), so the window is measured in both directions. Six lines is
# the widest gap any current extractor produces; twelve leaves room for that
# spread without tolerating a sidebar dumped into the middle of a job.
RECORD_WINDOW = 12

# --- extractors -------------------------------------------------------------


def extract_poppler(path):
    return subprocess.run(
        ["pdftotext", path, "-"], capture_output=True, text=True, check=True
    ).stdout


def extract_poppler_layout(path):
    return subprocess.run(
        ["pdftotext", "-layout", path, "-"], capture_output=True, text=True, check=True
    ).stdout


def extract_pymupdf(path):
    import fitz

    with fitz.open(path) as doc:
        return "\n".join(page.get_text() for page in doc)


def extract_pdfminer(path):
    from pdfminer.high_level import extract_text

    return extract_text(path)


EXTRACTORS = {
    "poppler (pdftotext)": extract_poppler,
    "poppler -layout": extract_poppler_layout,
    "pymupdf": extract_pymupdf,
    "pdfminer.six": extract_pdfminer,
}

# --- checks -----------------------------------------------------------------


def find_line(lines, needle, start=0):
    for i in range(start, len(lines)):
        if needle in lines[i]:
            return i
    return None


def check_lead(lines):
    """Name and contact near the top."""
    name_at = find_line(lines, NAME)
    contact_at = find_line(lines, CONTACT_TOKEN)
    if name_at is None:
        return False, "name not found at all"
    if contact_at is None:
        return False, "contact not found at all"
    if name_at >= LEAD_WINDOW or contact_at >= LEAD_WINDOW:
        return False, f"name at line {name_at + 1}, contact at line {contact_at + 1}"
    return True, f"name line {name_at + 1}, contact line {contact_at + 1}"


def sidebar_intrusions(lines, lo, hi):
    """Standalone sidebar headings flowed into the main column between lo/hi."""
    found = []
    for i in range(max(lo, 0), min(hi, len(lines) - 1) + 1):
        line = lines[i]
        if len(line) - len(line.lstrip()) >= SIDEBAR_COLUMN_INDENT:
            continue  # still in the sidebar's own column
        if line.strip() in SIDEBAR_MARKERS:
            found.append((line.strip(), i + 1))
    return found


def check_records(lines):
    """Every job's title, employer, dates and bullets stay together."""
    worst = 0
    for role, employer, date, bullet in JOB_RECORDS:
        at = find_line(lines, role)
        if at is None:
            return False, f"{role!r} not found at all"
        span = [at]
        for label, needle in (("employer", employer), ("date", date), ("bullets", bullet)):
            found = find_line(lines, needle)
            if found is None:
                return False, f"{role}: {label} not found at all"
            gap = abs(found - at)
            if gap > RECORD_WINDOW:
                return False, (
                    f"{role} (line {at + 1}) split from its {label} "
                    f"(line {found + 1}, {gap} lines away)"
                )
            worst = max(worst, gap)
            span.append(found)
        # The date can precede the title (pdfminer does that with a right-aligned
        # one), so the record's span is the full extent of its parts, not
        # title-to-bullets.
        split = sidebar_intrusions(lines, min(span), max(span))
        if split:
            detail = ", ".join(f"{m} @ line {n}" for m, n in split)
            return False, f"sidebar dropped inside the {role} record: {detail}"
    return True, f"{len(JOB_RECORDS)} records intact (widest gap {worst} lines)"


def check_order(lines):
    """Main-column landmarks come out in document order."""
    seen = [(m, find_line(lines, m)) for m in MAIN_MARKERS]
    seen = [(m, p) for m, p in seen if p is not None]
    if len(seen) < 2:
        return False, "could not locate main column markers"
    out_of_order = [
        f"{seen[i][0]!r} (line {seen[i][1] + 1}) before {seen[i - 1][0]!r} (line {seen[i - 1][1] + 1})"
        for i in range(1, len(seen))
        if seen[i][1] < seen[i - 1][1]
    ]
    if out_of_order:
        return False, "reading order scrambled: " + "; ".join(out_of_order)
    return True, f"{len(seen)} landmarks in order (lines {seen[0][1] + 1}-{seen[-1][1] + 1})"


CHECKS = [("LEAD", check_lead), ("RECORDS", check_records), ("ORDER", check_order)]

# --- main -------------------------------------------------------------------


def page_count(path):
    """Pages in the PDF, read with whichever of the extractor backends loads.
    pdfinfo ships with poppler, which this script already requires."""
    out = subprocess.run(
        ["pdfinfo", path], capture_output=True, text=True, check=True
    ).stdout
    for line in out.splitlines():
        if line.startswith("Pages:"):
            return int(line.split(":", 1)[1])
    raise RuntimeError("pdfinfo reported no page count")


def check_pages(path):
    n = page_count(path)
    return n == EXPECTED_PAGES, f"{n} page{'s' if n != 1 else ''}"


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    path = sys.argv[1]

    all_ok = True
    ok, detail = check_pages(path)
    all_ok &= ok
    print(f"\ndocument\n  {'PASS' if ok else 'FAIL'}  PAGES    {detail}")
    for name, fn in EXTRACTORS.items():
        print(f"\n{name}")
        try:
            lines = fn(path).splitlines()
        except Exception as exc:  # extractor missing or failed
            # Not tolerated: an absent extractor used to print SKIP and leave
            # the run reporting ALL PASS, so CI green meant only "the
            # extractors that happened to be installed passed". pdftotext was
            # missing from the image for exactly that reason, and the poppler
            # half of this gate never ran at all.
            all_ok = False
            print(f"  MISSING  {exc}")
            continue
        for label, check in CHECKS:
            ok, detail = check(lines)
            all_ok &= ok
            print(f"  {'PASS' if ok else 'FAIL'}  {label:<8} {detail}")

    print("\n" + ("ALL PASS" if all_ok else "FAILURES PRESENT"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
