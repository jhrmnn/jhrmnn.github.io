#!/usr/bin/env python3
"""Cross-check that the publication sources agree.

The site's reference list comes from the Zotero "My Publications" library;
ORCID, Google Scholar, Web of Science and Crossref are independent records of
the same publications. This reads a freshly fetched `build/derived.json` and
verifies that they list the same papers and that, for each paper, ORCID's
substance matches Zotero's.

The only differences tolerated are accents, letter case, and unicode-vs-ascii
spelling of the same character (see `common.fold_text`); anything else -- a
paper present in one source but not another, a preprint-vs-published mismatch, a
differing year or venue -- is a regression. Run at the end of the fetch job on
pushes to main (see the workflow), a non-zero exit aborts before the artifact is
uploaded, so the site never deploys from inconsistent sources.

Field coverage differs by source: Zotero (CSL-JSON) is richest; ORCID exposes
title, type, year, an identifier (DOI or handle) and a journal per work; Google
Scholar's profile exposes title, year and venue. So:

- the identifier and preprint-vs-published status are checked against ORCID
  (including flagging a paper ORCID lists as published while Zotero still has it
  as a preprint),
- the year is corroborated against both ORCID and Scholar,
- the venue is compared across all three, folded to a common ISO-4 abbreviation,
- Scholar must additionally list every Zotero paper,
- Web of Science must list every Zotero paper it would index -- i.e. every
  published one, since WoS doesn't index preprints, theses or book chapters --
  and must carry no unexpected record of its own (see WOS_ALLOWED_EXTRAS),
- and Crossref's record of each Zotero DOI must agree on title, year and venue
  (a DOI that resolves to a different work is a wrong DOI in Zotero); Crossref is
  looked up by the DOI, so unlike the others it can't check presence.

Neither ORCID nor Scholar carries volume/page, so those are not cross-checked.
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

# Web of Science (via Publons) indexes the published literature only -- not
# preprints, theses or book chapters -- so a Zotero item of one of those types
# legitimately has no WoS counterpart and isn't required to appear there.
WOS_OPTIONAL_STATUS = {'preprint', 'chapter', 'thesis'}

# WoS records that have no Zotero counterpart yet are expected, so the
# cross-check tolerates them rather than flagging a regression. Keyed by the
# same join identifier fetch.py builds -- the canonical DOI where WoS has one,
# else the WoS/Publons accession id:
WOS_ALLOWED_EXTRAS = {
    # DFTB+ erratum ("vol 152, 124101, 2020"), which WoS indexes as a record
    # distinct from the article itself (Zotero keeps only the article).
    '10.1063/5.0103026',
    # Duplicate preprint of the deep-VMC fixed-node paper; its published version
    # (10.1063/5.0032836) is the record Zotero lists and WoS also carries.
    'PPRN:11490275',
    # Two records mis-attributed to this profile -- a cochlear-implant preprint
    # and a 2006 laser-ablation paper, both by a different J. Hermann.
    '10.1101/19000711',
    'PPRN:49096155',
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


def scholar_years(derived):
    return (derived.get('custom_data') or {}).get('scholar_years', {})


def scholar_venues(derived):
    return (derived.get('custom_data') or {}).get('scholar_venues', {})


def check(  # noqa: C901
    refs, orcid, scholar, scholar_year_by_title, scholar_venue_by_title
):
    """Return a list of human-readable disagreement reasons (empty when clean)."""
    problems = []

    # Index ORCID works both ways: by title (to pair) and by identifier (to
    # collapse ORCID's per-version duplicates onto the Zotero paper they belong
    # to). Identifiers are DOIs or handles (theses are filed under a handle).
    o_by_title = defaultdict(list)
    o_by_id = defaultdict(list)
    for work in orcid:
        o_by_title[title_key(work['title'])].append(work)
        for ident in work.get('ids') or []:
            o_by_id[ident].append(work)

    # Scholar venues arrive keyed by Scholar's raw title; re-key on title_key so
    # they pair with references the same way everything else does.
    s_venues = {title_key(t): v for t, v in (scholar_venue_by_title or {}).items()}

    z_titles = set()
    z_ids = set()
    if not orcid:
        problems.append('no ORCID works to cross-check against')
    for ref in refs:
        key = title_key(ref['title'])
        z_titles.add(key)
        ident = ref.get('canonical-doi') or ref.get(
            'id'
        )  # canonical DOI/handle join key
        if ident:
            z_ids.add(ident)
        if not orcid:
            continue
        # Pair on title, falling back to a shared identifier when the titles
        # diverge by more than the tolerated folds.
        cands = o_by_title.get(key) or (o_by_id.get(ident) or [])
        if not cands:
            problems.append(f'absent from ORCID: {ref["title"]!r}')
            continue
        z_status = ZOTERO_STATUS.get(ref.get('type'), ref.get('type'))
        # A paper ORCID records as a published journal article while Zotero still
        # lists it as a preprint: Zotero should be advanced to the published
        # version. ORCID keeps both versions, so the preprint identifier still
        # matches -- this is the drift the plain identifier check can't see.
        if z_status == 'preprint':
            published = [
                c for c in cands if ORCID_STATUS.get(c.get('type')) == 'journal'
            ]
            if published:
                pub_ids = sorted({i for c in published for i in c.get('ids') or []})
                problems.append(
                    f'published on ORCID but still a preprint in Zotero: '
                    f'{ref["title"]!r} (Zotero preprint {ident}; '
                    f'ORCID published {pub_ids})'
                )
                continue
        same_id = [c for c in cands if ident in (c.get('ids') or [])]
        if not same_id:
            orcid_ids = sorted({i for c in cands for i in c.get('ids') or []})
            problems.append(
                f'identifier mismatch (preprint vs published?): {ref["title"]!r} '
                f'Zotero {ident} vs ORCID {orcid_ids}'
            )
            continue
        work = same_id[0]
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
        # Venue: Zotero's container-title-short, ORCID's journal-title and
        # Scholar's venue, all folded to the same ISO-4 abbreviation (fetch.py
        # abbreviates ORCID/Scholar; Zotero already stores the short form). Only
        # journal articles -- a chapter/thesis "venue" isn't a journal.
        if ref.get('type') == 'article-journal':
            venues = {
                'Zotero': ref.get('container-title-short'),
                'ORCID': work.get('journal'),
                'Google Scholar': s_venues.get(key),
            }
            folded = {src: title_key(v) for src, v in venues.items() if v}
            if len(set(folded.values())) > 1:
                detail = ', '.join(f'{src} {venues[src]!r}' for src in folded)
                problems.append(f'venue differs: {ref["title"]!r} {detail}')

    # ORCID works that match no Zotero paper -- by title or by a shared
    # identifier (the latter skips ORCID's own duplicate records of papers
    # Zotero does list).
    for work in orcid:
        if title_key(work['title']) not in z_titles and not (
            set(work.get('ids') or []) & z_ids
        ):
            problems.append(f'in ORCID but not Zotero: {work["title"]!r}')

    # Google Scholar auto-indexes extra items (talks, duplicates) we can't
    # curate away, so only require it to cover the Zotero papers (skipping the
    # check when Scholar data is missing rather than flagging every paper), and
    # corroborate the year where Scholar reports one.
    if scholar:
        s_titles = {title_key(t) for t in scholar}
        s_years = {title_key(t): y for t, y in scholar_year_by_title.items()}
        for ref in refs:
            key = title_key(ref['title'])
            if key not in s_titles:
                problems.append(f'absent from Google Scholar: {ref["title"]!r}')
                continue
            z_year, s_year = ref_year(ref), s_years.get(key)
            if z_year and s_year and z_year != s_year:
                problems.append(
                    f'year differs: {ref["title"]!r} '
                    f'Zotero {z_year} vs Google Scholar {s_year}'
                )

    return problems


def check_wos(refs, wos):
    """Cross-check the Zotero list against Web of Science (empty = skipped).

    Joins on the canonical identifier fetch.py builds for both sides (DOI, else
    the WoS accession id). WoS must list every Zotero paper it would index --
    preprints, theses and chapters excepted, since WoS doesn't index those --
    and must not carry an unexpected record of its own (WOS_ALLOWED_EXTRAS lists
    the known, tolerated ones). Returns a list of disagreement reasons.
    """
    problems = []
    if not wos:
        # Publons/WoS rate-limits with HTTP 429, leaving fetch.py with an empty
        # list. Skip the WoS cross-check when the source is missing -- as the
        # Scholar check does on a soft block -- rather than failing the deploy on
        # a transient outage. A genuine partial regression still surfaces below.
        return problems
    wos_ids = {w['id'] for w in wos if w['id']}
    # Every Zotero paper WoS is expected to index must be present.
    for ref in refs:
        status = ZOTERO_STATUS.get(ref.get('type'), ref.get('type'))
        if status in WOS_OPTIONAL_STATUS:
            continue
        ident = ref.get('canonical-doi') or ref.get('id')
        if ident and ident not in wos_ids:
            problems.append(f'absent from Web of Science: {ref["title"]!r}')
    # WoS records with no Zotero counterpart, beyond the known-allowed extras.
    zotero_ids = {
        ref.get('canonical-doi') or ref['id']
        for ref in refs
        if ref.get('canonical-doi') or ref.get('id')
    }
    for work in wos:
        key = work['id'] or work.get('accession')
        if key in WOS_ALLOWED_EXTRAS:
            continue
        if work['id'] and work['id'] in zotero_ids:
            continue
        problems.append(f'in Web of Science but not Zotero: {work["title"]!r} ({key})')
    return problems


def check_crossref(refs):
    """Cross-check each Zotero reference against Crossref's record of its DOI.

    fetch.py attaches Crossref's own metadata for the DOI to each reference.
    Crossref is queried *by* the Zotero DOI, so this can't check presence -- but
    a DOI that resolves to a different title, year or venue means the Zotero DOI
    is wrong. Title and venue are folded to the same key the other sources use
    and the year compared, exactly as in check(). Skipped per-ref when Crossref
    has no record (no DOI, or a non-Crossref handle). Returns a list of reasons.
    """
    problems = []
    for ref in refs:
        cr = ref.get('crossref')
        if not cr:
            continue
        c_title = cr.get('title')
        if c_title and title_key(ref['title']) != title_key(c_title):
            problems.append(
                f'title differs from Crossref: {ref["title"]!r} vs {c_title!r}'
            )
        z_year, c_year = ref_year(ref), cr.get('year')
        if z_year and c_year and z_year != c_year:
            problems.append(
                f'year differs: {ref["title"]!r} Zotero {z_year} vs Crossref {c_year}'
            )
        # Venue only for journal articles, folded to the ISO-4 abbreviation both
        # sides are reduced to (Zotero stores it, fetch.py abbreviates Crossref).
        if ref.get('type') == 'article-journal':
            z_venue, c_venue = ref.get('container-title-short'), cr.get(
                'container-title-short'
            )
            if z_venue and c_venue and title_key(z_venue) != title_key(c_venue):
                problems.append(
                    f'venue differs: {ref["title"]!r} Zotero {z_venue!r} '
                    f'vs Crossref {cr.get("container-title")!r}'
                )
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
        scholar_years(derived),
        scholar_venues(derived),
    )
    problems += check_wos(derived.get('references', []), derived.get('wos', []))
    problems += check_crossref(derived.get('references', []))
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
