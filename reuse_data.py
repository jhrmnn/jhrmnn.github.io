#!/usr/bin/env python3
"""Locate / reuse the data produced by a previous run.

The most recent `derived` artifact is the single source of truth for the
fetched data. The fetch job refreshes it (on schedule/dispatch and on
pushes/PRs that touch the fetch inputs); every other run, and the Scholar
fallback, reuse it instead of crawling again.

With ``--run-id`` this prints the id of the run that owns the latest
artifact, so a workflow can hand it to ``actions/download-artifact``.
Otherwise it downloads that artifact's JSON to ``-o``.
"""
import argparse
import io
import os
import sys
import zipfile
from pathlib import Path

import requests

NAME = 'derived'
DEFAULT_BRANCH = 'main'


def _headers():
    return {
        'Authorization': f'Bearer {os.environ["GITHUB_TOKEN"]}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    }


def _current_branch():
    """Branch the current run belongs to, matching artifacts' head_branch.

    On ``pull_request`` events ``GITHUB_REF_NAME`` is ``<pr>/merge`` while the
    artifact's ``workflow_run.head_branch`` carries the PR's source branch, which
    GitHub exposes as ``GITHUB_HEAD_REF``. Everywhere else (push, schedule,
    dispatch) ``GITHUB_REF_NAME`` is the branch itself.
    """
    return os.environ.get('GITHUB_HEAD_REF') or os.environ.get('GITHUB_REF_NAME')


def _get(path, **params):
    """GET a repo-scoped GitHub API endpoint and return parsed JSON."""
    api = os.environ.get('GITHUB_API_URL', 'https://api.github.com')
    repo = os.environ['GITHUB_REPOSITORY']
    r = requests.get(
        f'{api}/repos/{repo}/{path}',
        params=params or None,
        headers=_headers(),
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def _derived_artifacts():
    """Non-expired `derived` artifacts, newest first."""
    artifacts = [
        x
        for x in _get('actions/artifacts', name=NAME, per_page=100)['artifacts']
        if not x['expired']
    ]
    return sorted(artifacts, key=lambda x: x['created_at'], reverse=True)


def _download(artifact):
    """Return the `derived.json` bytes from an artifact's zip."""
    z = requests.get(
        artifact['archive_download_url'], headers=_headers(), timeout=30
    )
    z.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(z.content)) as zf:
        names = zf.namelist()
        member = 'derived.json' if 'derived.json' in names else names[0]
        return zf.read(member)


def latest_derived_artifact():
    """Return metadata of the most recent non-expired `derived` artifact.

    Prefers the artifact produced on the current branch so a PR exercises its
    own fetched data, falling back to ``main``. Restricting to these two means
    the published site (which renders on ``main``) never picks up an unreviewed
    PR branch's artifact.

    Raises on API/network errors or when no usable artifact exists.
    """
    artifacts = _derived_artifacts()

    def on_branch(branch):
        return [
            x
            for x in artifacts
            if (x.get('workflow_run') or {}).get('head_branch') == branch
        ]

    branch = _current_branch()
    candidates = (branch and on_branch(branch)) or on_branch(DEFAULT_BRANCH)
    if not candidates:
        raise LookupError(f"no '{NAME}' artifact to reuse")
    return candidates[0]


def latest_derived_bytes():
    """Return the JSON bytes of the most recent `derived` artifact."""
    return _download(latest_derived_artifact())


def _baseline_sha():
    """SHA of the most recent default-branch commit the current run descends from.

    On the default branch this is the current commit's first parent (the
    previously published state); on any other branch or PR it is the merge base
    with the default branch (the commit the branch forked from). Either way the
    integrity check grades a fresh fetch against published ``main`` state, never
    against the current branch's own in-progress artifacts.
    """
    head = os.environ.get('GITHUB_HEAD_REF') or os.environ['GITHUB_REF_NAME']
    if head == DEFAULT_BRANCH:
        return _get(f'commits/{os.environ["GITHUB_SHA"]}')['parents'][0]['sha']
    return _get(f'compare/{DEFAULT_BRANCH}...{head}')['merge_base_commit']['sha']


def _is_ancestor(sha, descendant):
    """True if `sha` is an ancestor of (or equal to) `descendant`."""
    if sha == descendant:
        return True
    return _get(f'compare/{sha}...{descendant}')['status'] in ('ahead', 'identical')


def baseline_derived_artifact():
    """The `derived` artifact a fresh fetch should be graded against.

    Among default-branch artifacts (newest first), the first whose commit is an
    ancestor of the baseline commit (see `_baseline_sha`). Restricting to the
    default branch and to ancestors of the fork point means a PR never grades
    itself against its own intermediate artifacts, nor against ``main`` commits
    made after it branched.
    """
    baseline = _baseline_sha()
    for artifact in _derived_artifacts():
        run = artifact.get('workflow_run') or {}
        if run.get('head_branch') != DEFAULT_BRANCH:
            continue
        if run.get('head_sha') and _is_ancestor(run['head_sha'], baseline):
            return artifact
    raise LookupError(f"no '{NAME}' artifact for baseline {baseline}")


def baseline_derived_bytes():
    """Return the JSON bytes of the baseline `derived` artifact."""
    return _download(baseline_derived_artifact())


def main(args):
    p = argparse.ArgumentParser()
    p.add_argument('-o', dest='output', default='build/derived.json', type=Path)
    p.add_argument(
        '--run-id',
        action='store_true',
        help='print the run id of the latest artifact instead of downloading',
    )
    a = p.parse_args(args)
    try:
        if a.run_id:
            print(latest_derived_artifact()['workflow_run']['id'])
            return
        data = latest_derived_bytes()
    except (requests.exceptions.RequestException, LookupError, KeyError) as e:
        sys.exit(
            f'error: could not reuse data ({e}); '
            'run a fetch (schedule or manual dispatch) first'
        )
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_bytes(data)


if __name__ == '__main__':
    main(sys.argv[1:])
