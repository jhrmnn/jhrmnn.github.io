#!/usr/bin/env python3
import argparse
import concurrent.futures
import json
import logging
import os
import re
import sys
import time
import unicodedata
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
# Public ORCID record of the same publications, used by check_sources.py to
# cross-check the Zotero list. The summary works endpoint gives title, type,
# year and DOI per work -- enough to catch a paper that's missing from, or
# recorded differently than, Zotero (e.g. preprint vs published).
ORCID_ID = '0000-0002-2779-0749'
ORCID_WORKS_URL = f'https://pub.orcid.org/v3.0/{ORCID_ID}/works'
ORCID_HEADERS = {'Accept': 'application/json'}
# Web of Science publication list, exposed through the Publons "WoS-OP" API for
# the same researcher profile reviews() reads its review count from. WoS indexes
# the published literature, so check_sources.py uses it to catch a published
# paper missing from Zotero (and an unexpected record on the WoS side). The
# academic record carries the paginated publication-list URL.
WOS_ACADEMIC_URL = f'https://publons.com/api/v2/academic/{ORCID_ID}/'


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


def _scholar_rows(html):
    soup = BeautifulSoup(html, "html.parser")
    for row in soup.select("#gsc_a_t .gsc_a_tr"):
        title = row.select_one(".gsc_a_at").get_text(strip=True)
        cites = int(row.select_one(".gsc_a_c").get_text(strip=True) or 0)
        year_cell = row.select_one(".gsc_a_y")
        year = year_cell.get_text(strip=True) if year_cell else ''
        # The second grey line is the venue, e.g. "J. Chem. Inf. Model. 65 (18),
        # 9576-9580, 2025". Keep only the name: everything before the first
        # volume number, with a truncation ellipsis trimmed off.
        grays = row.select(".gs_gray")
        venue = grays[1].get_text(strip=True) if len(grays) > 1 else ''
        venue = re.split(r'\s+(?=\d)', venue, 1)[0].strip().rstrip('…').strip()
        yield title, cites, year or None, venue or None


def parse_scholar_profile_html(html):
    return {title: cites for title, cites, _, _ in _scholar_rows(html)}


def parse_scholar_years_html(html):
    # The profile lists a publication year per row; check_sources.py uses it as a
    # third witness on each paper's year. Rows without a year are skipped.
    return {title: year for title, _, year, _ in _scholar_rows(html) if year}


def parse_scholar_venues_html(html):
    # ISO-4 abbreviation of each row's venue, so check_sources.py can compare it
    # to Zotero's container-title-short and ORCID's journal-title on equal terms.
    return {
        title: journal_abbrev(venue)
        for title, _, _, venue in _scholar_rows(html)
        if venue
    }


def published_n_reviews():
    try:
        return json.loads(reuse_data.latest_derived_bytes())['n_reviews']
    except (requests.exceptions.RequestException, LookupError, KeyError, ValueError):
        return None


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


def journal_abbrev(name):
    """ISO-4 abbreviation of a venue, tolerant of missing/odd input.

    Used to fold each source's venue (ORCID's journal-title, Scholar's venue
    line) onto the same abbreviated form Zotero already stores in
    container-title-short, so the cross-check can compare them. Returns None for
    empty input and falls back to the raw name if abbreviation fails (e.g. a
    preprint server, which the venue check ignores anyway).
    """
    if not name:
        return None
    try:
        return abbreviate_journal(name)
    except Exception:
        return name


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


def _ascii_fold(s):
    """Drop diacritics (Stöhr -> Stohr, Schätzle -> Schatzle), matching the
    transliteration Better BibTeX applies when building citation keys."""
    return unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()


def citation_key(item):
    """A human-readable key in the form <Surname><JournalInitials><YY>, e.g.
    ``HermannNC20``: the first author's surname, the upper-case initials of the
    abbreviated journal (omitted when the work has no such short title — a
    preprint, thesis or book chapter), and the two-digit year. Reproduces the
    historical Better BibTeX keys, which the Zotero web API does not expose.
    Callers disambiguate collisions with a suffix."""
    author = (item.get('author') or item.get('editor') or [{}])[0]
    surname = _ascii_fold(
        (author.get('non-dropping-particle', '') + author.get('family', '')).replace(
            ' ', ''
        )
    )
    short = item.get('container-title-short')
    initials = ''.join(w[0] for w in short.split() if w[:1].isupper()) if short else ''
    year = str(item['issued']['date-parts'][0][0])[-2:]
    return f'{surname}{initials}{year}'


def assign_citation_keys(refs):
    """Set a unique human-readable ``id`` (the citation key) on each reference.
    When the derived key collides, the earliest (by date, then canonical DOI)
    keeps the bare key and the rest get a lowercase ``a``/``b``/... suffix, as
    Better BibTeX does. The canonical DOI/handle stays in ``canonical-doi`` as
    the stable cross-source join key."""
    groups = {}
    for ref in refs:
        groups.setdefault(citation_key(ref), []).append(ref)
    for base, group in groups.items():
        group.sort(key=lambda r: (r['issued']['date-parts'][0], r['canonical-doi']))
        for i, ref in enumerate(group):
            ref['id'] = base + ('' if i == 0 else chr(ord('a') + i - 1))


def fetch_references(cache):
    items = cache.get(ZOTERO_REFS_URL)['items']
    _ensure_nltk()
    refs = []
    for it in items:
        it = dict(it)
        # The canonical DOI/handle is the stable cross-source join key
        # (check_sources/check_derived); the citation key assigned below is the
        # human-readable id used by ref_extras/keypubs/tools and pandoc.
        it['canonical-doi'] = canonical_doi(it['DOI'], cache)
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
    assign_citation_keys(refs)
    return refs


def fetch_orcid(cache):
    """Flat list of the public ORCID works, one record per work summary.

    ORCID lists each work's versions (preprint, published, ...) under the same
    title, so duplicates are expected; check_sources.py collapses them by
    identifier. Identifiers are canonicalised to the same join key Zotero uses.
    """
    data = cache.get(ORCID_WORKS_URL, headers=ORCID_HEADERS)
    works = []
    for group in data.get('group', []):
        for summary in group.get('work-summary', []):
            title = (((summary.get('title') or {}).get('title')) or {}).get('value')
            if not title:
                continue
            # Match on DOIs *and* handles. Theses are identified by a handle
            # (e.g. a dspace/edoc handle), which ORCID files under external-id
            # type "handle" and Zotero keeps in its DOI field; collecting only
            # DOIs would leave a thesis with no identifier to join on.
            # canonical_doi resolves shortDOIs and lower-cases handles unchanged.
            ids = sorted(
                {
                    canonical_doi(eid['external-id-value'], cache)
                    for eid in (summary.get('external-ids') or {}).get(
                        'external-id', []
                    )
                    if eid.get('external-id-type') in ('doi', 'handle')
                }
            )
            pubdate = summary.get('publication-date') or {}
            year = ((pubdate.get('year') or {}).get('value')) if pubdate else None
            journal = (summary.get('journal-title') or {}).get('value')
            works.append(
                {
                    'title': title,
                    'ids': ids,
                    'type': summary.get('type'),
                    'year': str(year) if year else None,
                    'journal': journal_abbrev(journal),
                }
            )
    return works


def fetch_wos(cache):
    """Flat list of the Web of Science (Publons) publication records.

    The academic record exposes a paginated publication-list URL; each record is
    reduced to the fields the cross-check needs -- the title, the publication
    year, and a join key: the canonical DOI where WoS has one (resolved and
    lower-cased the same way Zotero's identifiers are, so the two sides compare
    equal), else the WoS/Publons accession id (e.g. a ``PPRN:...`` preprint id)
    so DOI-less records can still be named.
    """
    headers = {'authorization': f'Token {os.environ["PUBLONS_TOKEN"]}'}
    url = cache.get(WOS_ACADEMIC_URL, headers=headers)['publications']['url']
    works = []
    while url:
        page = cache.get(url, headers=headers)
        for record in page['results']:
            pub = record['publication']
            doi = pub['ids'].get('doi')
            works.append(
                {
                    'title': pub['title'],
                    'id': canonical_doi(doi, cache) if doi else None,
                    'accession': pub['ids'].get('ut') or None,
                    'year': (pub.get('date_published') or '')[:4] or None,
                }
            )
        url = page.get('next')
    return works


def fetch_scholar(cache):
    """Raw HTML of the Google Scholar profile (a single page listing every row).

    Google Scholar blocks datacenter/CI IPs with a 429 "sorry" CAPTCHA, so route
    through a residential proxy when SCHOLAR_PROXY is set (a full proxy URL, e.g.
    http://user:pass@gw.dataimpulse.com:823). A fresh connection per attempt
    rotates the proxy's exit IP, so retrying sheds a flagged IP; there's no point
    retrying without a proxy, since a datacenter IP stays blocked. Raises on a
    persistent failure so the caller can degrade like any other source.
    """

    def func():
        proxies = None
        if proxy := os.environ.get('SCHOLAR_PROXY'):
            proxies = {'http': proxy, 'https': proxy}
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
                # A soft block serves a CAPTCHA / "sorry" page with HTTP 200, so
                # raise_for_status() can't catch it. Detect it from the response
                # itself -- Google redirects blocked traffic to a /sorry/ page
                # whose body asks to solve a CAPTCHA -- and retry on a fresh exit
                # IP; if it never clears, raise rather than parsing a CAPTCHA page.
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
            return r.text

    return cache.get_custom('scholar', func)


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
        try:
            n_reviews = cache.get(
                WOS_ACADEMIC_URL,
                headers={'authorization': f'Token {os.environ["PUBLONS_TOKEN"]}'},
            )['reviews']['pre']['count']
        except requests.exceptions.HTTPError as e:
            # Publons/WoS rate-limits with HTTP 429; don't let a transient block
            # fail the whole fetch (fetch_wos degrades the same way). Fall back
            # to the last published review count so NUMREV still renders; skip
            # the replacement entirely only if there's no prior value to reuse.
            if not e.args[0].startswith('429'):
                raise
            logging.warning('Could not fetch Web of Science reviews: %r', e)
            n_reviews = published_n_reviews()
            if n_reviews is None:
                return
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
            # Recorded for reference only; the citation count shown on the site
            # (item['cited_by']) comes solely from Google Scholar below.
            item['crossref_cited_by'] = r['message']['is-referenced-by-count']

    ctx['references'] = fetch_references(cache)
    # ORCID only gates the push-to-main cross-check; a transient outage
    # shouldn't fail unrelated fetches, so degrade to an empty list (which
    # check_sources.py reports as "no ORCID data" on main).
    try:
        ctx['orcid'] = fetch_orcid(cache)
    except requests.exceptions.RequestException as e:
        logging.warning('Could not fetch ORCID works: %r', e)
        ctx['orcid'] = []
    # Same tolerance for Web of Science: a fetch failure leaves an empty list,
    # which check_sources.py reports as "no Web of Science data" on main.
    try:
        ctx['wos'] = fetch_wos(cache)
    except requests.exceptions.RequestException as e:
        logging.warning('Could not fetch Web of Science works: %r', e)
        ctx['wos'] = []
    # Google Scholar supplies the citation counts shown on the site. A fetch
    # failure (datacenter/CI IP soft block) leaves the counts unset for this run,
    # the same way an ORCID or WoS outage leaves those lists empty -- the
    # publication's cited_by is simply omitted rather than the fetch failing.
    try:
        html = fetch_scholar(cache)
    except requests.exceptions.RequestException as e:
        logging.warning('Could not fetch Google Scholar profile: %r', e)
    else:
        ctx['scholar_cites'] = parse_scholar_profile_html(html)
        ctx['scholar_years'] = parse_scholar_years_html(html)
        ctx['scholar_venues'] = parse_scholar_venues_html(html)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [
            pool.submit(func, x)
            for func, x in [
                *((stars, x) for x in ctx['software']),
                (reviews, ctx),
                *((citations, x) for x in ctx['references']),
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
    if ctx.get("scholar_cites"):
        refs_by_key = {
            reduce_sc(strip_html(item['title'].lower()))[:120]: item
            for item in ctx['references']
        }
        cites = ctx["scholar_cites"]
        ctx["custom_data"]["scholar_citations"] = {
            "timestamp": datetime.now().isoformat(),
            "value": cites,
        }
        ctx["custom_data"]["scholar_years"] = ctx.get("scholar_years", {})
        ctx["custom_data"]["scholar_venues"] = ctx.get("scholar_venues", {})
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
        'orcid': ctx.get('orcid', []),
        'wos': ctx.get('wos', []),
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
