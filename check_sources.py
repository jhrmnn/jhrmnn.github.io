#!/usr/bin/env python3
"""Cross-check that the three publication sources agree.

The site's reference list comes from the Zotero "My Publications" library;
ORCID and Google Scholar are independent records of the same publications. This
reads a freshly fetched `build/derived.json` and verifies that all three list
the same papers and that, for each paper, ORCID's substance matches Zotero's.

The only differences tolerated are accents, letter case, and unicode-vs-ascii
spelling of the same character (see `common.fold_text`); anything else -- a
paper present in one source but not another, a preprint-vs-published DOI/type
mismatch, a differing year -- is a regression. Run at the end of the fetch job
on pushes to main (see the workflow), a non-zero exit aborts before the artifact
is uploaded, so the site never deploys from inconsistent sources.

Field coverage differs by source: Zotero (CSL-JSON) is richest; ORCID exposes
title, type, year and DOI per work; Google Scholar's profile listing only
exposes titles reliably. So Scholar is checked for presence only, while the
field-level substance check (DOI, preprint-vs-published status, year) is done
against ORCID. ORCID does not carry volume/page, so those are not cross-checked.
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

from common import title_key

# CSL (Zotero) and ORCID name publication types differently; map both onto a
# common vocabulary so e.g. a Zotero preprint and an ORCID preprint compare
# equal while a preprint vs a published article does not. Unknown types fall
# through to their raw string (still compared, just not unified).
ZOTERO_STATUS = {
    'article': 'preprint',
    'article-journal': 'journal',
    'chapter': 'chapter',
    'thesis': 'thesis',
}
ORCID_STATUS = {
    'preprint': 'preprint',
    'journal-article': 'journal',
    'book-chapter': 'chapter',
    'dissertation-thesis': 'thesis',
    'dissertation': 'thesis',
}


def ref_year(ref):
    issued = ref.get('issued') or {}
    parts = issued.get('date-parts') or [[]]
    return str(parts[0][0]) if parts and parts[0] else None


def scholar_titles(derived):
    value = (
        (derived.get('custom_data') or {}).get('scholar_citations', {}).get('value', {})
    )
    return list(value)


def check(refs, orcid, scholar):  # noqa: C901
    """Return a list of human-readable disagreement reasons (empty when clean)."""
    problems = []

    # Index ORCID works both ways: by title (to pair) and by DOI (to collapse
    # ORCID's per-version duplicates onto the Zotero paper they belong to).
    o_by_title = defaultdict(list)
    o_by_doi = defaultdict(list)
    for work in orcid:
        o_by_title[title_key(work['title'])].append(work)
        for doi in work.get('dois') or []:
            o_by_doi[doi].append(work)

    z_titles = set()
    z_dois = set()
    if not orcid:
        problems.append('no ORCID works to cross-check against')
    for ref in refs:
        z_titles.add(title_key(ref['title']))
        doi = ref.get('id')  # canonical DOI: the same join key fetch.py builds
        if doi:
            z_dois.add(doi)
        if not orcid:
            continue
        # Pair on title, falling back to a shared DOI when the titles diverge
        # by more than the tolerated folds.
        cands = o_by_title.get(title_key(ref['title'])) or (o_by_doi.get(doi) or [])
        if not cands:
            problems.append(f'absent from ORCID: {ref["title"]!r}')
            continue
        same_doi = [c for c in cands if doi in (c.get('dois') or [])]
        if not same_doi:
            orcid_dois = sorted({d for c in cands for d in c.get('dois') or []})
            problems.append(
                f'DOI mismatch (preprint vs published?): {ref["title"]!r} '
                f'Zotero {doi} vs ORCID {orcid_dois}'
            )
            continue
        work = same_doi[0]
        z_status = ZOTERO_STATUS.get(ref.get('type'), ref.get('type'))
        o_status = ORCID_STATUS.get(work.get('type'), work.get('type'))
        if z_status != o_status:
            problems.append(
                f'status differs: {ref["title"]!r} '
                f'Zotero {z_status} vs ORCID {o_status}'
            )
        z_year, o_year = ref_year(ref), work.get('year')
        if z_year and o_year and z_year != o_year:
            problems.append(
                f'year differs: {ref["title"]!r} Zotero {z_year} vs ORCID {o_year}'
            )

    # ORCID works that match no Zotero paper -- by title or by a shared DOI (the
    # latter skips ORCID's own duplicate records of papers Zotero does list).
    for work in orcid:
        if title_key(work['title']) not in z_titles and not (
            set(work.get('dois') or []) & z_dois
        ):
            problems.append(f'in ORCID but not Zotero: {work["title"]!r}')

    # Google Scholar auto-indexes extra items (talks, duplicates) we can't
    # curate away, so only require it to cover the Zotero papers, and skip the
    # check entirely when Scholar data is missing (a soft block) rather than
    # flagging every paper.
    if scholar:
        s_titles = {title_key(t) for t in scholar}
        for ref in refs:
            if title_key(ref['title']) not in s_titles:
                problems.append(f'absent from Google Scholar: {ref["title"]!r}')

    return problems


def main(args):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('derived', nargs='?', default='build/derived.json', type=Path)
    a = p.parse_args(args)
    derived = json.loads(a.derived.read_text())
    problems = check(
        derived.get('references', []),
        derived.get('orcid', []),
        scholar_titles(derived),
    )
    if not problems:
        print('publication sources agree')
        return
    print('publication sources disagree:', file=sys.stderr)
    for problem in problems:
        print(f'  - {problem}', file=sys.stderr)
    if summary := os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(summary, 'a') as f:
            f.write('### Publication sources disagree\n')
            f.writelines(f'- {problem}\n' for problem in problems)
    sys.exit(1)


if __name__ == '__main__':
    main(sys.argv[1:])
