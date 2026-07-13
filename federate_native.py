#!/usr/bin/env python3
"""Ping our self-hosted ActivityPub Worker to federate changed posts.

Just hands the changed slugs to the Worker's `/ap/admin/deliver` endpoint; the
Worker reads each Note from its own deployed static assets
(notes/<slug>/note.json, produced by posts.py) and fans a signed Create/Update
out to followers. No HTML parsing here — the post record is the single source of
truth, serialized once at build time.

Best-effort: federation problems are logged but never fail the build. Skips
quietly if `AP_ADMIN_TOKEN` is unset (before the self-hosted actor is configured).
"""
import argparse
import os
import sys

import requests

BASE_URL = 'https://hrmnn.net'


def main(argv):
    p = argparse.ArgumentParser()
    p.add_argument(
        '--base',
        # `or BASE_URL` so an empty env var (unset GitHub `vars.AP_BASE_URL`)
        # falls back to the apex rather than producing a broken empty origin.
        default=os.environ.get('AP_BASE_URL') or BASE_URL,
        help='origin of the ActivityPub Worker',
    )
    p.add_argument('slugs', nargs='*', help='post stems, e.g. 2026-06-15-llm-skeptic')
    a = p.parse_args(argv)

    if not a.slugs:
        print('no changed posts to federate')
        return 0
    token = os.environ.get('AP_ADMIN_TOKEN')
    if not token:
        print('AP_ADMIN_TOKEN unset; skipping native federation')
        return 0

    print(f'Federating {len(a.slugs)} post(s) to {a.base}/ap/admin/deliver')
    try:
        r = requests.post(
            f'{a.base}/ap/admin/deliver',
            headers={'Authorization': f'Bearer {token}'},
            json={'slugs': a.slugs},
            timeout=30,
        )
        print(f'deliver -> {r.status_code}: {r.text[:400]}')
    except requests.RequestException as e:
        print(f'warn: {e}')
    return 0  # best-effort: never fail the build


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
