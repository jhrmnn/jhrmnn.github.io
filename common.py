#!/usr/bin/env python3
"""Helpers shared by the fetch and render stages.

These live here so `fetch.py` and `render.py` stay independent of each other
(neither imports the other) without duplicating the small pieces they both
need.
"""
import re

import yaml

SMALL_CAPS = dict(zip('ᴍʏɴɢɪɴᴇ', 'myngine'))


def reduce_sc(x):
    for f, t in SMALL_CAPS.items():
        x = x.replace(f, t)
    return x


def strip_html(str):
    str = re.sub(r'</?\w+[^<>]*>', '', str)
    return str


def load_ctx(paths):
    # References are fetched from Zotero into the derived artifact; the static
    # context files are all YAML.
    return dict(x for c in paths for x in yaml.safe_load(c.read_text()).items())
