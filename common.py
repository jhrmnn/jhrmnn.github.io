#!/usr/bin/env python3
"""Helpers shared by the fetch and render stages.

These live here so `fetch.py` and `render.py` stay independent of each other
(neither imports the other) without duplicating the small pieces they both
need.
"""
import re
import unicodedata

import yaml

SMALL_CAPS = dict(zip('ᴍʏɴɢɪɴᴇ', 'myngine'))


def reduce_sc(x):
    for f, t in SMALL_CAPS.items():
        x = x.replace(f, t)
    return x


def fold_text(s):
    """Fold away the only differences treated as insignificant when comparing
    bibliographic data across sources: small-caps unicode (``PʏSCF`` ->
    ``pyscf``), accents, other unicode/ascii spellings of the same character,
    and letter case. Everything else is preserved so a real difference (a
    different word, a different number) still shows up.
    """
    s = reduce_sc(s or '')
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return s.casefold()


def title_key(s):
    """Loose key for deciding whether two records describe the same work.

    ``fold_text`` plus dropping HTML markup and collapsing every run of
    non-alphanumerics to a single space, so punctuation, spacing or markup
    differences never split a pair. Used only to *pair* records; their substance
    is then compared field by field.
    """
    s = re.sub(r'<[^>]+>', '', fold_text(s))
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', s).split())


def strip_html(str):
    str = re.sub(r'</?\w+[^<>]*>', '', str)
    return str


def load_ctx(paths):
    # The static context files are YAML/JSON; other data files (e.g. the
    # hubs.md miniarticle source, read directly by render.py) are skipped.
    return dict(
        x
        for c in paths
        if c.suffix in ('.yaml', '.yml', '.json')
        for x in yaml.safe_load(c.read_text()).items()
    )
