#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from markupsafe import Markup
from jinja2 import Environment, FileSystemLoader

from common import SMALL_CAPS, load_ctx, reduce_sc, strip_html


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
    x = re.sub(
        r'\[([^\[\]]*)\]\(([^()]*)\)(?:\{:( [^}]*)})?', r'<a href="\2"\3>\1</a>', x
    )
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
            ' '.join(
                [
                    *(f'{n[0]}.' for n in a['given'].split()),
                    *(
                        (a['non-dropping-particle'],)
                        if 'non-dropping-particle' in a
                        else ()
                    ),
                    a['family'],
                ]
            )
            + (f', {a["suffix"]}' if 'suffix' in a else '')
            for a in authors
        ]
        auth_lst = ['__JH__' if a == 'J. Hermann' else a for a in auth_lst]
        return (
            auth_lst[0]
            if len(auth_lst) == 1
            else (
                f'{", ".join(auth_lst[:-1])} & {auth_lst[-1]}'
                if len(auth_lst) <= max_len
                else f'{auth_lst[0]} et al.'
            )
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
            (iden,) = re.match(r'http://arxiv.org/abs/([\d.]+)', item['URL']).groups()
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


def sort_refs(refs):
    return sorted(refs, key=lambda x: x['issued']['date-parts'][0], reverse=True)


def apply_derived(ctx, derived):
    software = derived.get('software', {})
    for item in ctx['software']:
        gh = item.get('github')
        if gh in software:
            item.update(software[gh])
    ctx['references'] = derived['references']
    n_reviews = derived.get('n_reviews')
    if n_reviews is not None:
        ctx['activity'] = [
            a.replace('NUMREV', str(n_reviews)) for a in ctx['activity']
        ]
    ctx['custom_data'] = derived.get('custom_data', {})


def make_env(name):
    """Build a Jinja environment whose autoescaping/delimiters/finalizer match
    the output format implied by the template name. Shared by `render` (CV) and
    `posts.py` (blog) so both stages produce identically normalised output."""
    extra_kwargs = {}
    if '.tex' in name:

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

    elif '.html' in name:

        def finalize(x):
            if isinstance(x, Markup):
                return x
            if isinstance(x, str) and '<' in x:
                return x
            return md_to_html(x)

    elif '.txt' in name:
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
    return env


def finalize_doc(doc, name):
    """Apply the cross-format output cleanups (quote/punctuation shuffling, and
    for plain text the unicode-to-ascii fold) and encode to bytes."""
    doc = re.sub(r'(?<!\?</a>)”([.,])', r'\1”', doc)
    doc = re.sub(r'”[.,]', r'”', doc)
    doc = re.sub(r"(?<!\?})''([.,])", r"\1''", doc)
    doc = re.sub(r"''([.,])", r"''", doc)
    if '.txt' in name:
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
        return doc.encode('ascii')
    return doc.encode()


def render(template, ctx, **kwargs):
    kwargs['now'] = (
        datetime.now()
        .replace(microsecond=0)
        .astimezone(ZoneInfo("Europe/Berlin"))
        .isoformat()
    )
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
    env = make_env(template.name)
    template = env.get_template(str(template))
    doc = template.render(ctx)
    return finalize_doc(doc, template.name)


def main(args):
    p = argparse.ArgumentParser()
    p.add_argument('template', type=Path)
    p.add_argument('ctx', nargs='+', type=Path)
    p.add_argument('--derived', type=Path, required=True)
    p.add_argument('--pic', default='assets/profile-pic.jpeg')
    p.add_argument('--statement', action='store_true', dest='with_statement')
    p.add_argument('--stars', action='store_true', dest='with_stars')
    p.add_argument('--generated')
    p.add_argument('-o', dest='output')
    a = p.parse_args(args)
    if not a.derived.exists():
        sys.exit(f'error: no derived data at {a.derived}; run `make fetch` first')
    derived = json.loads(a.derived.read_text())
    if not derived:
        sys.exit(f'error: derived data at {a.derived} is empty')
    ctx = load_ctx(a.ctx)
    apply_derived(ctx, derived)
    doc = render(
        a.template,
        ctx,
        pic=a.pic,
        with_statement=a.with_statement,
        with_stars=a.with_stars,
        generated=a.generated,
    )
    if a.output:
        Path(a.output).write_bytes(doc)
    else:
        sys.stdout.buffer.write(doc)


if __name__ == '__main__':
    main(sys.argv[1:])
