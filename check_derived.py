#!/usr/bin/env python3
"""Check that a freshly fetched derived dataset hasn't regressed.

`fetch.py` rebuilds `build/derived.json` from live sources, which can degrade:
an API hiccup, a soft block, a deleted Zotero item, or a recount can drop
publications, rewrite bibliographic data, or report lower counts than what was
last published. This compares the new dataset against the published `derived`
artifact for the most recent default-branch commit the run descends from (the
previous `main` commit on `main`, the fork point on a PR branch) and exits
non-zero if anything was removed, an identity field changed, or a count that
should only grow went down. Grading against the default-branch ancestor — rather
than the current branch's own latest artifact — means a PR is checked against
published `main` state, not against its own in-progress commits. Running it at
the end of the fetch job means a regression aborts before the artifact is
uploaded.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import requests

import reuse_data

# Reference fields that identify a publication and must stay stable once
# published. Volatile fields (cited_by is checked separately as a count; URL and
# the GitHub-sourced software description/language change legitimately) are
# intentionally excluded.
REF_IDENTITY_FIELDS = ('title', 'author', 'issued', 'container-title')


def load_baseline():
    """Published derived data for the most recent default-branch ancestor of the
    current run, or None when there's nothing to compare against."""
    try:
        return json.loads(reuse_data.baseline_derived_bytes())
    except (requests.exceptions.RequestException, LookupError, KeyError, ValueError):
        return None


def scholar_value(derived):
    return (
        (derived.get('custom_data') or {}).get('scholar_citations', {}).get('value', {})
    )


def refs_by_id(derived):
    return {r['id']: r for r in derived.get('references', [])}


def check(old, new):  # noqa: C901
    """Return a list of human-readable regression reasons (empty when clean)."""
    problems = []

    def removed(kind, old_keys, new_keys):
        for k in old_keys:
            if k not in new_keys:
                problems.append(f'{kind} removed: {k}')

    def decreased(kind, key, old_val, new_val):
        # Only compare when both runs reported a number; a value going missing is
        # treated as a transient gap (e.g. a Crossref 429), not a decrease.
        if isinstance(old_val, int) and isinstance(new_val, int) and new_val < old_val:
            problems.append(f'{kind} decreased: {key} {old_val} -> {new_val}')

    # software: repos are append-only; stars only grow.
    old_sw, new_sw = old.get('software', {}), new.get('software', {})
    removed('software', old_sw, new_sw)
    for repo, info in old_sw.items():
        if repo in new_sw:
            decreased('stars', repo, info.get('stars'), new_sw[repo].get('stars'))

    # references: keyed by canonical DOI; append-only, stable identity, cited_by
    # only grows.
    old_refs, new_refs = refs_by_id(old), refs_by_id(new)
    removed('reference', old_refs, new_refs)
    for doi, ref in old_refs.items():
        new_ref = new_refs.get(doi)
        if new_ref is None:
            continue
        for field in REF_IDENTITY_FIELDS:
            if ref.get(field) != new_ref.get(field):
                problems.append(f'reference {doi} field changed: {field}')
        decreased('cited_by', doi, ref.get('cited_by'), new_ref.get('cited_by'))

    # n_reviews: monotonic.
    decreased('n_reviews', 'n_reviews', old.get('n_reviews'), new.get('n_reviews'))

    # Google Scholar citations: titles append-only, counts only grow.
    old_sc, new_sc = scholar_value(old), scholar_value(new)
    removed('scholar citation', old_sc, new_sc)
    for title, count in old_sc.items():
        if title in new_sc:
            decreased('scholar citation', title, count, new_sc[title])

    return problems


def main(args):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('new', nargs='?', default='build/derived.json', type=Path)
    a = p.parse_args(args)
    new = json.loads(a.new.read_text())
    old = load_baseline()
    if old is None:
        print('no baseline derived data to compare against; skipping check')
        return
    problems = check(old, new)
    if not problems:
        print('derived-data integrity OK')
        return
    print('derived-data integrity check failed:', file=sys.stderr)
    for problem in problems:
        print(f'  - {problem}', file=sys.stderr)
    if summary := os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(summary, 'a') as f:
            f.write('### Derived-data integrity check failed\n')
            f.writelines(f'- {problem}\n' for problem in problems)
    sys.exit(1)


if __name__ == '__main__':
    main(sys.argv[1:])
