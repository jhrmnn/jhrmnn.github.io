#!/usr/bin/env python3
import argparse
import concurrent.futures
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import requests
import reuse_data
from bs4 import BeautifulSoup

from common import load_ctx, reduce_sc, strip_html

MAX_RETRIES = 3
# Google Scholar blocks IPs with a bad reputation (429 "sorry" CAPTCHA). When a
# residential proxy is configured each connection gets a fresh exit IP, so retry
# a handful of times to land a clean one.
SCHOLAR_PROXY_RETRIES = 5
# Fetch the full publication list in a single request (the profile shows only
# 20 rows by default); parse_scholar_profile_html reads the citation counts.
SCHOLAR_PROFILE_URL = (
    'https://scholar.google.com/citations?hl=en&user=5TjVq0YAAAAJ&pagesize=100'
)
SCHOLAR_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/124.0 Safari/537.36'
    ),
    'Accept-Language': 'en-US,en;q=0.9',
}
# Publications come from the public Zotero "My Publications" library as CSL-JSON
# (the same shape the references were previously committed in). The item-type
# filter drops attachments/notes server-side.
ZOTERO_REFS_URL = (
    'https://api.zotero.org/users/1562978/publications/items?'
    + urlencode({'format': 'csljson', 'itemType': '-attachment || note', 'limit': 100})
)


class Cache:
    def __init__(self):
        self._file = Path('.cache.json')
        self._store = json.loads(self._file.read_text()) if self._file.exists() else {}
        self._updated = False

    def get(self, url, **kwargs):
        def func():
            for attempt in range(MAX_RETRIES):
                r = requests.get(url, timeout=5.0, **kwargs)
                try:
                    r.raise_for_status()
                except requests.exceptions.HTTPError as e:
                    if attempt < MAX_RETRIES - 1 and e.args[0].startswith('500'):
                        time.sleep(1)
                        continue
                    elif e.args[0].startswith('429') and 'api.crossref.org' in url:
                        return {}
                    raise
                else:
                    break
            return r.json()

        return self.get_custom(url, func)

    def get_custom(self, key, func):
        if key not in self._store:
            self._updated = True
            self._store[key] = func()
        return self._store[key]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._updated:
            self._file.write_text(json.dumps(self._store))


def norm_desc(s):
    s = re.sub(r'\.$', '', s)
    s = re.sub(r'\(.*\)', '', s)
    return s


def parse_scholar_profile_html(html):
    soup = BeautifulSoup(html, "html.parser")
    return {
        row.select_one(".gsc_a_at").get_text(strip=True): int(
            row.select_one(".gsc_a_c").get_text(strip=True) or 0
        )
        for row in soup.select("#gsc_a_t .gsc_a_tr")
    }


def parse_scholar_profile(path):
    return parse_scholar_profile_html(path.read_text())


def published_scholar_citations():
    try:
        return json.loads(reuse_data.latest_derived_bytes())['custom_data'][
            'scholar_citations'
        ]
    except (requests.exceptions.RequestException, LookupError, KeyError, ValueError):
        return {'timestamp': '1970-01-01T00:00:00', 'value': {}}


def _ensure_nltk():
    """Make sure the corpora `iso4` needs are present (fetch step only)."""
    import nltk

    for pkg, path in (
        ('wordnet', 'corpora/wordnet'),
        ('stopwords', 'corpora/stopwords'),
        ('punkt_tab', 'tokenizers/punkt_tab'),
    ):
        try:
            nltk.data.find(path)
        except LookupError:
            nltk.download(pkg, quiet=True)


def abbreviate_journal(name):
    """ISO-4 journal abbreviation, matching Better BibTeX's output."""
    from iso4 import abbreviate

    return abbreviate(name, periods=True, disambiguation_langs=['en'])


def canonical_doi(doi, cache):
    """Full `10.prefix/suffix` DOI, resolving shortDOIs via the handle system.

    Non-DOI identifiers (e.g. the handle Zotero stores for a thesis) pass
    through unchanged. The result is lower-cased so it is a stable join key.
    """
    doi = re.sub(r'^https?://(dx\.)?doi\.org/', '', doi.strip(), flags=re.I)
    if doi.startswith('10/'):
        values = cache.get(f'https://doi.org/api/handles/{doi}').get('values', [])
        doi = next(
            (v['data']['value'] for v in values if v.get('type') == 'HS_ALIAS'), doi
        )
    return doi.lower()


def fetch_references(cache):
    items = cache.get(ZOTERO_REFS_URL)['items']
    _ensure_nltk()
    refs = []
    for it in items:
        it = dict(it)
        # Key each reference by its canonical DOI: the stable join key for
        # ref_extras/keypubs.
        it['id'] = canonical_doi(it['DOI'], cache)
        # Zotero emits year as int for full dates but str for year-only ones;
        # normalize so date-parts sort and compare consistently.
        for field in ('issued', 'accessed', 'submitted'):
            date = it.get(field)
            if isinstance(date, dict) and 'date-parts' in date:
                date['date-parts'] = [
                    [int(x) if str(x).isdigit() else x for x in part]
                    for part in date['date-parts']
                ]
        if (
            it.get('type') == 'article-journal'
            and it.get('container-title')
            and 'container-title-short' not in it
        ):
            it['container-title-short'] = abbreviate_journal(it['container-title'])
        refs.append(it)
    return refs


def update_from_web(ctx, cache):  # noqa: C901
    def stars(item):
        if 'github' in item:
            headers = {'accept': 'application/vnd.github.v3+json'}
            # Authenticate when a token is available (CI and web sessions both
            # export GITHUB_TOKEN); unauthenticated calls are rate-limited/403.
            if token := os.environ.get('GITHUB_TOKEN'):
                headers['authorization'] = f'Bearer {token}'
            info = cache.get(
                f'https://api.github.com/repos/{item["github"]}',
                headers=headers,
            )
            item.update(
                {
                    'url': f'https://github.com/{item["github"]}',
                    'description': (
                        f'{norm_desc(info["description"])} ({info["language"]})'
                    ),
                    'stars': info['stargazers_count'],
                }
            )

    def reviews(ctx):
        n_reviews = cache.get(
            'https://publons.com/api/v2/academic/0000-0002-2779-0749/',
            headers={'authorization': f'Token {os.environ["PUBLONS_TOKEN"]}'},
        )['reviews']['pre']['count']
        ctx['_n_reviews'] = n_reviews
        activity = ctx['activity']
        for i in range(len(activity)):
            activity[i] = activity[i].replace('NUMREV', str(n_reviews))

    def citations(item):
        try:
            doi = item['DOI']
        except KeyError:
            return
        if doi.split('/')[0] == '10':
            r = cache.get(f'https://doi.org/api/handles/{doi}')
            doi = r['values'][1]['data']['value']
        if doi == '10.1063/5.0059356':
            return
        if len(doi.split('/')[0].split('.')[1]) != 4:
            return
        r = cache.get(f'https://api.crossref.org/works/{doi}')
        if r:
            item['cited_by'] = r['message']['is-referenced-by-count']

    def scholar(ctx):
        def func():
            # Route through a residential proxy when configured; Scholar blocks
            # datacenter IPs but lets residential ones through. SCHOLAR_PROXY is
            # a full proxy URL, e.g. http://user:pass@gw.dataimpulse.com:823.
            proxies = None
            if proxy := os.environ.get('SCHOLAR_PROXY'):
                proxies = {'http': proxy, 'https': proxy}
            # A fresh connection per attempt rotates the proxy's exit IP, so
            # retrying sheds a flagged IP. No point retrying without a proxy:
            # a datacenter IP stays blocked.
            attempts = SCHOLAR_PROXY_RETRIES if proxies else 1
            for attempt in range(attempts):
                try:
                    r = requests.get(
                        SCHOLAR_PROFILE_URL,
                        headers=SCHOLAR_HEADERS,
                        timeout=30,
                        proxies=proxies,
                    )
                    r.raise_for_status()
                    # A soft block serves a CAPTCHA / "sorry" page with HTTP 200,
                    # so raise_for_status() can't catch it. Detect it from the
                    # response itself -- Google redirects blocked traffic to a
                    # /sorry/ page and the body asks to solve a CAPTCHA -- and
                    # retry on a fresh exit IP; if it never clears, raise so the
                    # snapshot fallback takes over rather than publishing (and
                    # timestamping) an empty result.
                    if '/sorry/' in r.url or 'unusual traffic' in r.text.lower():
                        raise requests.exceptions.RequestException(
                            'Scholar served a CAPTCHA/block page (HTTP 200 soft block)'
                        )
                except requests.exceptions.RequestException as e:
                    if attempt < attempts - 1:
                        logging.info('Scholar fetch attempt %d failed: %r', attempt + 1, e)
                        time.sleep(2)
                        continue
                    raise
                return parse_scholar_profile_html(r.text)

        # Google Scholar blocks datacenter/CI IPs; on failure fall back to the
        # committed profile snapshot instead of failing the whole fetch.
        try:
            ctx['scholar_cites'] = cache.get_custom('scholar', func)
        except requests.exceptions.RequestException as e:
            logging.warning('Could not fetch Google Scholar profile: %r', e)

    ctx['references'] = fetch_references(cache)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [
            pool.submit(func, x)
            for func, x in [
                *((stars, x) for x in ctx['software']),
                (reviews, ctx),
                *((citations, x) for x in ctx['references']),
                (scholar, ctx),
            ]
        ]
    has_errors = False
    for future in concurrent.futures.as_completed(futures):
        try:
            future.result()
        except requests.exceptions.HTTPError as e:
            logging.error(repr(e))
            has_errors = True
    if has_errors:
        sys.exit(1)
    refs_by_key = {
        reduce_sc(strip_html(item['title'].lower()))[:120]: item
        for item in ctx['references']
    }
    if ctx.get("scholar_cites"):
        cites = ctx["scholar_cites"]
        ts = datetime.now().isoformat()
    else:
        path = Path("assets") / "_Jan Hermann_ - _Google Scholar_.html"
        scholar_citations = published_scholar_citations()
        # Prefer the more recent of the committed snapshot and the last published
        # value, but never carry forward an empty published value (a stale soft
        # block): fall back to the snapshot so citation numbers don't vanish.
        if (
            ts := datetime.fromtimestamp(path.stat().st_mtime).isoformat()
        ) > scholar_citations["timestamp"] or not scholar_citations["value"]:
            cites = parse_scholar_profile(path)
        else:
            cites = scholar_citations["value"]
            ts = scholar_citations["timestamp"]
    ctx["custom_data"]["scholar_citations"] = {
        "timestamp": ts,
        "value": cites,
    }
    for title, cite in cites.items():
        key = reduce_sc(title.lower())[:120]
        # Scholar lists publications that aren't tracked as references here
        # (and the live profile can surface new ones at any time); only apply
        # counts to references we actually have.
        if key in refs_by_key:
            refs_by_key[key]['cited_by'] = cite


def extract_derived(ctx):
    return {
        'software': {
            item['github']: {
                'url': item['url'],
                'description': item['description'],
                'stars': item['stars'],
            }
            for item in ctx['software']
            if 'github' in item and 'stars' in item
        },
        'references': ctx['references'],
        'n_reviews': ctx.get('_n_reviews'),
        'custom_data': ctx['custom_data'],
    }


def main(args):
    p = argparse.ArgumentParser()
    p.add_argument('ctx', nargs='+', type=Path)
    p.add_argument('-o', dest='output', required=True)
    a = p.parse_args(args)
    ctx = load_ctx(a.ctx)
    ctx['custom_data'] = {}
    with Cache() as cache:
        update_from_web(ctx, cache)
    derived = extract_derived(ctx)
    Path(a.output).write_text(json.dumps(derived))


if __name__ == '__main__':
    main(sys.argv[1:])
