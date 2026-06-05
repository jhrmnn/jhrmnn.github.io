#!/usr/bin/env python3
"""Download the most recent `derived` artifact from a previous run.

Used by the fetch job on events that should not crawl live data (e.g.
pushes): instead of re-running the slow live fetch, reuse the data that
the last schedule/dispatch run already produced and uploaded.
"""
import argparse
import io
import os
import sys
import zipfile
from pathlib import Path

import requests

NAME = 'derived'


def main(args):
    p = argparse.ArgumentParser()
    p.add_argument('-o', dest='output', default='build/derived.json', type=Path)
    a = p.parse_args(args)
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
        sys.exit(
            f"error: no '{NAME}' artifact to reuse; "
            'run a fetch (schedule or manual dispatch) first'
        )
    latest = max(artifacts, key=lambda x: x['created_at'])
    z = requests.get(latest['archive_download_url'], headers=headers, timeout=30)
    z.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(z.content)) as zf:
        names = zf.namelist()
        member = 'derived.json' if 'derived.json' in names else names[0]
        data = zf.read(member)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_bytes(data)
    print(f"reused {NAME} artifact #{latest['id']} from {latest['created_at']}")


if __name__ == '__main__':
    main(sys.argv[1:])
