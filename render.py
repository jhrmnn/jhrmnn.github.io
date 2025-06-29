#!/usr/bin/env python3
import argparse
import concurrent.futures
import json
import logging
import os
import re
import time
from datetime import datetime
from itertools import chain
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import yaml
from jinja2 import Environment, FileSystemLoader
from scholarly import scholarly, MaxTriesExceededException
from bs4 import BeautifulSoup

scholarly.set_timeout(5)
scholarly.set_retries(3)

SMALL_CAPS = dict(zip('ᴍʏɴɢɪɴᴇ', 'myngine'))
MAX_RETRIES = 3


def reduce_sc(x):
    for f, t in SMALL_CAPS.items():
        x = x.replace(f, t)
    return x


def date_format(x):
    x = str(x)
    x = re.sub(r'(\d{4})', r'**\1**', x)
    x = x.replace('-', '–')
    return x


def process_href(m):
    s = m.group(1)
    s = re.sub(
        r'\\emph{([^}]*)}',
        lambda m: r'\emph{' + r'}\ \emph{'.join(m.group(1).split(r'\ ')) + '}',
        s,
    )
    return f'\\href{{{m.group(2)}}}{{{s}}}'


def md_to_tex(x):
    x = str(x)
    x = x.replace('&', r'\&')
    x = x.replace('–', '--')
    for f, t in SMALL_CAPS.items():
        x = x.replace(f, fr'\textsc{{{t}}}')
    x = re.sub(r'"([^"]*)"', r"``\1''", x)
    x = re.sub(r'\*\*([^*]*)\*\*', r'\\strong{\1}', x)
    x = re.sub(r'__([^_]*)__', r'\\textbf{\1}', x)
    x = re.sub(r'\*([^*]*)\*', r'\\emph{\1}', x)
    x = re.sub(r'`([^`]*)`', r'\\emph{\1}', x)
    x = re.sub(r'\.(}?) (?=[A-Z]|\\)', r'.\1\ ', x)
    x = re.sub(r'\[([^\[\]]*)\]\(([^()]*)\)', process_href, x)
    return x


def md_to_html(x):
    x = str(x)
    x = re.sub(r'(?<!=)"([^"]*)"', r'“\1”', x)
    x = re.sub(r'__([^_]*)__', r'<strong>\1</strong>', x)
    x = re.sub(r'\[([^\[\]]*)\]\(([^()]*)\)(?:\{:( [^}]*)})?', r'<a href="\2"\3>\1</a>', x)
    x = re.sub(r'\*\*([^*]*)\*\*', r'<strong>\1</strong>', x)
    x = re.sub(r'\*([^*]*)\*', r'<em>\1</em>', x)
    x = re.sub(r'`([^`]*)`', r'<code>\1</code>', x)
    return x


def md_to_txt(x):
    x = str(x)
    x = x.replace('–', '-')
    x = re.sub(r'"([^"]*)"', r'“\1”', x)
    x = re.sub(r'__([^_]*)__', r'\1', x)
    x = re.sub(r'\[([^\[\]]*)\]\(([^()]*)\)', r'\1', x)
    x = re.sub(r'\*\*([^*]*)\*\*', r'\1', x)
    x = re.sub(r'\*([^*]*)\*', r'\1', x)
    x = re.sub(r'`([^`]*)`', r'\1', x)
    return x


def ref_to_md(item):
    def author_list(authors, max_len):
        auth_lst = [
            ' '.join([*(f'{n[0]}.' for n in a['given'].split()), *((a['non-dropping-particle'],) if 'non-dropping-particle' in a else ()), a['family']])
            + (f', {a["suffix"]}' if 'suffix' in a else '')
            for a in authors
        ]
        auth_lst = ['__JH__' if a == 'J. Hermann' else a for a in auth_lst]
        return (
            auth_lst[0]
            if len(auth_lst) == 1
            else f'{", ".join(auth_lst[:-1])} & {auth_lst[-1]}'
            if len(auth_lst) <= max_len
            else f'{auth_lst[0]} et al.'
        )

    authors = author_list(item['author'], 10)
    url = f'https://doi.org/{item["DOI"]}' if 'DOI' in item else item['URL']
    title = item['title']
    title = re.sub(r': ([a-z])', lambda m: f': {m.group(1).upper()}', title)
    title = strip_html(title)
    year = item['issued']['date-parts'][0][0]
    if item['type'] in ['article-journal', 'article']:
        title = f'{title}'
    elif item['type'] == 'chapter':
        title = f'[{title}]({url})'
    elif item['type'] == 'thesis':
        title = f'[*{title}*]({url})'
    if item['type'] == 'article-journal':
        ref = (
            f'[*{item["container-title-short"]}*'
            + (f' **{item["volume"]}**' if 'volume' in item else '')
            + (f', {item["page"].replace("-", "–")}' if 'page' in item else '')
            + f']({url}) ({year})'
        )
    elif item['type'] == 'article':
        if "arxiv.org" in item['URL']:
            iden, = re.match(r'http://arxiv.org/abs/([\d.]+)', item['URL']).groups()
            iden = f"arXiv:{iden}"
        elif "chemrxiv.org" in item['URL']:
            iden = f"doi:{item['DOI']}"
        ref = f'Preprint at [{iden}]({url}) ({year})'
    elif item['type'] == 'chapter':
        ref = (
            f'In *{item["container-title"]}* (eds {author_list(item["editor"], 3)})'
            f' {item["page"].replace("-", "–")}'
            f' ({item["publisher"]}, {year})'
        )
    elif item['type'] == 'thesis':
        ref = f'{item["publisher"]} ({year})'
    return title, authors, ref


def strip_html(str):
    str = re.sub(r'</?\w+[^<>]*>', '', str)
    return str


def sort_refs(refs):
    return sorted(refs, key=lambda x: x['issued']['date-parts'][0], reverse=True)


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
                    else:
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


def parse_scholar_profile(path):
    soup = BeautifulSoup(path.read_text(), "html.parser")
    return {
        row.select_one(".gsc_a_at").get_text(strip=True):
        int(row.select_one(".gsc_a_c").get_text(strip=True) or 0)
        for row in soup.select("#gsc_a_t .gsc_a_tr")
    }


def update_from_web(ctx, cache):  # noqa: C901
    def stars(item):
        if 'github' in item:
            info = cache.get(
                f'https://api.github.com/repos/{item["github"]}',
                headers={'accept': 'application/vnd.github.v3+json'},
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

    def reviews(activity):
        n_reviews = cache.get(
            'https://publons.com/api/v2/academic/0000-0002-2779-0749/',
            headers={'authorization': f'Token {os.environ["PUBLONS_TOKEN"]}'},
        )['reviews']['pre']['count']
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
        item['cited_by'] = r['message']['is-referenced-by-count']

    def scholar(ctx):
        def func():
            author = scholarly.search_author_id('5TjVq0YAAAAJ')
            scholarly.fill(author)
            for x in chain([author], author['coauthors'], author['publications']):
                del x['filled'], x['source']
            return author

        try:
            ctx['scholar'] = cache.get_custom('scholar', func)
        except MaxTriesExceededException:
            pass

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = [
            pool.submit(func, x)
            for func, x in [
                *((stars, x) for x in ctx['software']),
                (reviews, ctx['activity']),
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
    if "scholar" in ctx:
        cites = {}
        for p in ctx['scholar']['publications']:
            cites[p['bib']['title']] = p['num_citations']
    else:
        cites = parse_scholar_profile(Path("assets") / "_Jan Hermann_ - _Google Scholar_.html")
    for title, cite in cites.items():
        key = reduce_sc(title.lower())[:120]
        if key in {
            "assessment of dispersion corrected density functional methods",
            "theoretical investigation of silver clusters in zeolites",
        }:
            continue
        refs_by_key[key]['cited_by'] = cite




def render(template, ctx, **kwargs):  # noqa: C901
    ctx = dict(
        x
        for c in ctx
        for x in (
            (
                (lambda x: {'references': json.loads(x)})
                if c.name == 'refs.json'
                else yaml.safe_load
            )(c.read_text()).items()
        )
    )
    with Cache() as cache:
        update_from_web(ctx, cache)
    kwargs['now'] = datetime.now().replace(microsecond=0).astimezone(ZoneInfo("Europe/Berlin")).isoformat()
    ctx['settings'] = kwargs
    for item in ctx['references']:
        extras = ctx['ref_extras'].get(item['id'])
        if not extras:
            continue
        item['pdf_url'] = extras['PDF']
        if 'notice' in extras:
            item['pdf_notice'] = extras['notice']
        if item['id'] in ctx['keypubs']:
            item['star'] = True
    extra_kwargs = {}
    if '.tex' in template.name:

        def finalize(x):
            if isinstance(x, str) and '\\' in x:
                return x
            return md_to_tex(x)

        extra_kwargs = {
            'variable_start_string': r'<<',
            'variable_end_string': '>>',
            'block_start_string': '<+',
            'block_end_string': '+>',
            'comment_start_string': '<#',
            'comment_end_string': '#>',
        }

    elif '.html' in template.name:

        def finalize(x):
            if isinstance(x, str) and '<' in x:
                return x
            return md_to_html(x)

    elif '.txt' in template.name:
        finalize = md_to_txt
    env = Environment(
        loader=FileSystemLoader(['.', os.getenv('BLDDIR')]),
        trim_blocks=True,
        autoescape=False,
        finalize=finalize,
        **extra_kwargs,
    )
    env.filters['dateformat'] = date_format
    env.filters['sortrefs'] = sort_refs
    env.filters['reftomd'] = ref_to_md
    env.filters['initials'] = lambda x: [f'{x[0]}.' for x in x.split()]
    template = env.get_template(str(template))
    doc = template.render(ctx)
    doc = re.sub(r'(?<!\?</a>)”([.,])', r'\1”', doc)
    doc = re.sub(r'”[.,]', r'”', doc)
    doc = re.sub(r"(?<!\?})''([.,])", r"\1''", doc)
    doc = re.sub(r"''([.,])", r"''", doc)
    if '.txt' in template.name:
        doc = re.sub(r'€(\d+[kM])', r'\1 EUR', doc)
        doc = (
            doc.replace('ł', 'l')
            .replace('“', '"')
            .replace('”', '"')
            .replace('π', 'pi')
            .replace('²', '2')
            .replace('₃', '3')
            .replace('₆', '6')
            .replace('ž', 'z')
            .replace('Č', 'C')
            .replace('⁺', '+')
            .replace('é', 'e')
            .replace('ö', 'oe')
            .replace('ü', 'ue')
            .replace('ä', 'ae')
            .replace('è', 'e')
            .replace('ý', 'y')
            .replace('ó', 'o')
        )
        doc = reduce_sc(doc)
        doc = doc.encode('ascii')
    else:
        doc = doc.encode()
    return doc


def main(args):
    p = argparse.ArgumentParser()
    p.add_argument('template', type=Path)
    p.add_argument('ctx', nargs='+', type=Path)
    p.add_argument('--pic', default='assets/profile-pic.png')
    p.add_argument('--statement', action='store_true', dest='with_statement')
    p.add_argument('--stars', action='store_true', dest='with_stars')
    p.add_argument('--generated')
    p.add_argument('-o', dest='output')
    kwargs = vars(p.parse_args(args))
    output = kwargs.pop('output')
    if output:
        with open(output, 'wb') as f:
            f.write(render(**kwargs))
    else:
        sys.stdout.buffer.write(render(**kwargs))


if __name__ == '__main__':
    import sys

    main(sys.argv[1:])
