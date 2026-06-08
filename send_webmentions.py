#!/usr/bin/env python3
"""Notify Bridgy Fed about published/updated posts so they federate to the
Fediverse. For each post URL, send a webmention with `target=https://fed.brid.gy/`
to Bridgy Fed's endpoint; Bridgy then fetches the post, translates its h-entry to
ActivityPub, and delivers it to followers.

Bridgy-side errors are logged but never fail the build: federation is best-effort
and shouldn't block a deploy.
"""
import argparse
import sys
import time

import requests

ENDPOINT = 'https://fed.brid.gy/webmention'
TARGET = 'https://fed.brid.gy/'


def send(url):
    for attempt in range(4):
        try:
            r = requests.post(
                ENDPOINT, data={'source': url, 'target': TARGET}, timeout=30
            )
            if r.status_code < 400:
                print(f'ok   {url} -> {r.status_code}')
                return True
            print(f'warn {url} -> {r.status_code}: {r.text[:200]}')
        except requests.RequestException as e:
            print(f'warn {url}: {e}')
        if attempt < 3:
            time.sleep(2 ** (attempt + 1))
    print(f'fail {url}: giving up after retries')
    return False


def main(argv):
    p = argparse.ArgumentParser()
    p.add_argument('urls', nargs='*')
    a = p.parse_args(argv)
    if not a.urls:
        print('no changed posts to federate')
        return 0
    for url in a.urls:
        send(url)
    return 0  # best-effort: never fail the build on Bridgy-side issues


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
