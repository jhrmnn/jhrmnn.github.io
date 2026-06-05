#!/usr/bin/env python3
"""Reuse the data produced by a previous run.

The most recent `derived` artifact is the single source of truth for the
fetched data. The fetch job (schedule/dispatch only) refreshes it; every
other run, and the Scholar fallback, reuse it instead of crawling again.
"""
import argparse
import io
import os
import sys
import zipfile
from pathlib import Path

import requests

NAME = 'derived'


def latest_derived_bytes():
    """Return the JSON bytes of the most recent `derived` artifact.

    Raises on API/network errors or when no usable artifact exists.
    """
    api = os.environ.get('GITHUB_API_URL', 'https://api.github.com')
    repo = os.environ['GITHUB_REPOSITORY']
    headers = {
        'Authorization': f'Bearer {os.environ["GITHUB_TOKEN"]}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    }
    r = requests.get(
        f'{api}/repos/{repo}/actions/artifacts',
        params={'name': NAME, 'per_page': 100},
        headers=headers,
        timeout=30,
    )
    r.raise_for_status()
    artifacts = [x for x in r.json()['artifacts'] if not x['expired']]
    if not artifacts:
        raise LookupError(f"no '{NAME}' artifact to reuse")
    latest = max(artifacts, key=lambda x: x['created_at'])
    z = requests.get(latest['archive_download_url'], headers=headers, timeout=30)
    z.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(z.content)) as zf:
        names = zf.namelist()
        member = 'derived.json' if 'derived.json' in names else names[0]
        return zf.read(member)


def main(args):
    p = argparse.ArgumentParser()
    p.add_argument('-o', dest='output', default='build/derived.json', type=Path)
    a = p.parse_args(args)
    try:
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
