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


def latest_derived_artifact():
    """Return metadata of the most recent non-expired `derived` artifact.

    Prefers the artifact produced on the current branch so a PR exercises its
    own fetched data, falling back to ``main``. Restricting to these two means
    the published site (which renders on ``main``) never picks up an unreviewed
    PR branch's artifact.

    Raises on API/network errors or when no usable artifact exists.
    """
    api = os.environ.get('GITHUB_API_URL', 'https://api.github.com')
    repo = os.environ['GITHUB_REPOSITORY']
    r = requests.get(
        f'{api}/repos/{repo}/actions/artifacts',
        params={'name': NAME, 'per_page': 100},
        headers=_headers(),
        timeout=30,
    )
    r.raise_for_status()
    artifacts = [x for x in r.json()['artifacts'] if not x['expired']]

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
    return max(candidates, key=lambda x: x['created_at'])


def latest_derived_bytes():
    """Return the JSON bytes of the most recent `derived` artifact."""
    z = requests.get(
        latest_derived_artifact()['archive_download_url'],
        headers=_headers(),
        timeout=30,
    )
    z.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(z.content)) as zf:
        names = zf.namelist()
        member = 'derived.json' if 'derived.json' in names else names[0]
        return zf.read(member)


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
