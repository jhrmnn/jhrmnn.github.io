#!/usr/bin/env python3
"""Federate changed posts via our own self-hosted ActivityPub Worker.

For each changed post, read its rendered page (`_site/notes/<slug>/index.html`),
pull the `e-content` HTML and the `dt-published`/`dt-updated` timestamps out of
the h-entry, and POST the batch to the Worker's `/ap/admin/deliver` endpoint.
The Worker stores each Note and fans a signed Create/Update out to followers.

Best-effort: federation problems are logged but never fail the build. Skips
quietly if `AP_ADMIN_TOKEN` is unset (before the self-hosted actor is configured).
"""
import argparse
import os
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL = 'https://hrmnn.net'


def extract(site_dir, slug):
    """Build the delivery payload for one post from its rendered h-entry."""
    html = Path(site_dir, 'notes', slug, 'index.html').read_text(encoding='utf-8')
    soup = BeautifulSoup(html, 'html.parser')
    entry = soup.find(class_='h-entry')
    content = entry.find(class_='e-content').decode_contents().strip()
    # Notes have no separate title field; fold the post title (if any) into the
    # content as a leading bold line so it shows up on Mastodon.
    name = entry.find(class_='p-name')
    if name:
        content = f'<p><strong>{name.get_text().strip()}</strong></p>\n{content}'
    published = entry.find(class_='dt-published')
    updated = entry.find(class_='dt-updated')
    post = {
        'slug': slug,
        'url': f'{BASE_URL}/notes/{slug}/',
        'contentHtml': content,
        'published': published['datetime'] if published else '',
    }
    if updated and updated.has_attr('datetime'):
        post['updated'] = updated['datetime']
    return post


def main(argv):
    p = argparse.ArgumentParser()
    p.add_argument('--site', default='_site', help='rendered site directory')
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

    posts = [extract(a.site, s) for s in a.slugs]
    print(f'Federating {len(posts)} post(s) to {a.base}/ap/admin/deliver')
    try:
        r = requests.post(
            f'{a.base}/ap/admin/deliver',
            headers={'Authorization': f'Bearer {token}'},
            json={'posts': posts},
            timeout=30,
        )
        print(f'deliver -> {r.status_code}: {r.text[:400]}')
    except requests.RequestException as e:
        print(f'warn: {e}')
    return 0  # best-effort: never fail the build


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
