#!/usr/bin/env python3
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from html import unescape
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


# Distribute talks into the homepage tool-hubs by matching their title against a
# few topic keywords (checked in this order). Talks whose title matches nothing
# (e.g. untitled seminars) stay out of the hubs but remain in the full CV.
HUB_KEYWORDS = {
    'Skala': ['skala', 'exchange-correlation', 'exchange–correlation'],
    'DeepQMC': [
        'schrödinger', 'wave function', 'wavefunction', 'quantum monte carlo',
        'fixed-node', 'deep-learning solution', 'neural network solution',
        'neural-network wave', 'deep neural network',
    ],
    'libMBD': [
        'van der waals', 'many-body dispersion', 'dispersion', 'libmbd',
        'zeolite', 'faujasite', 'non-local density', 'nonlocal',
        'electron correlation in density', 'charge fluctuations', 'π–π',
    ],
}


# Titled talks that legitimately belong to no hub (untitled talks are always
# allowed to fall outside the hubs). The completeness check tolerates exactly
# these; any other unmatched titled talk is an error to fix (add a keyword or
# extend this list).
TALK_NOHUB_ALLOWLIST = {
    'Mona: Calculation framework for reproducible science',
    'Python interface to FHI-aims',
}


def classify_talk(title):
    title = (title or '').lower()
    for hub, keywords in HUB_KEYWORDS.items():
        if any(k in title for k in keywords):
            return hub
    return None


def check_completeness(ctx):
    """Fail the build if any fetched publication, software entry, or titled talk
    would silently not appear on the homepage. Publications and talks are
    live-fetched, so this guards against a newly published item vanishing behind
    a green build."""
    problems = []

    # A publication is placed by being cited in hubs.md; everything else would
    # silently not appear on the homepage.
    hubs_md = Path(HUBS_MD).read_text()
    claimed = set(cited_keys(hubs_md))
    ref_ids = {r['id'] for r in ctx['references']}
    if orphans := ref_ids - claimed:
        problems.append(
            'publications cited nowhere (cite them in data/hubs.md): '
            f'{", ".join(sorted(orphans))}'
        )
    if dangling := claimed - ref_ids:
        problems.append(
            f'references absent from fetched data: {", ".join(sorted(dangling))}'
        )

    # Each hub names its anchor software repo in the <h1> github="…" attribute;
    # it must resolve to a software entry (rendered as the section's tool list).
    hub_repos = set(re.findall(r'github="([^"]+)"', hubs_md))
    sw_repos = {s['github'] for s in ctx.get('software', []) if 'github' in s}
    if missing := hub_repos - sw_repos:
        problems.append(
            f'hub repos missing from the software list: {", ".join(sorted(missing))}'
        )

    for talks in ctx.get('presentations', {}).values():
        for talk in talks:
            title = talk.get('title')
            if title and not classify_talk(title) and title not in TALK_NOHUB_ALLOWLIST:
                problems.append(
                    f'talk matched to no hub (add a keyword or allow-list it): {title!r}'
                )

    if problems:
        raise SystemExit(
            'error: homepage completeness check failed:\n  - '
            + '\n  - '.join(problems)
        )


def group_talks_by_hub(presentations):
    hubs = {hub: [] for hub in HUB_KEYWORDS}
    for talks in presentations.values():
        for talk in talks:
            hub = classify_talk(talk.get('title'))
            if hub:
                hubs[hub].append(talk)
    return hubs


def unhubbed_talks(presentations):
    """Talks tied to no hub — untitled seminars and the few titled talks that
    belong to the catch-all fourth theme. They are surfaced there, not dropped."""
    return [
        talk
        for talks in presentations.values()
        for talk in talks
        if not classify_talk(talk.get('title'))
    ]


CSL_STYLE = 'assets/superscript.csl'


def write_bibliography(refs, path):
    """Write the references as a CSL-JSON bibliography for pandoc. Drops the
    Zotero short-title fields (shortTitle/title-short): with them present,
    citeproc returns the title-short where the journal's short form belongs."""
    items = [
        {k: v for k, v in r.items() if k not in ('shortTitle', 'title-short')}
        for r in refs
    ]
    Path(path).write_text(json.dumps(items, ensure_ascii=False))


def run_pandoc(markdown, bib_path):
    """Run pandoc + citeproc on a markdown document, returning the HTML.

    `notes-after-punctuation` moves a superscript citation after an adjacent
    sentence/clause punctuation mark, so prose that cites before the period
    (`cost [@key].`) renders in house style (`cost.<sup>1</sup>`). Citeproc does
    this on the document AST, so it is robust to pandoc's HTML line-wrapping;
    off by default for superscript (non-note) styles, hence opted in here."""
    proc = subprocess.run(
        ['pandoc', '--citeproc', '-M', 'notes-after-punctuation=true',
         '--csl', CSL_STYLE, '--bibliography', bib_path,
         '-f', 'markdown', '-t', 'html5'],
        input=markdown,
        capture_output=True,
        text=True,
        check=True,
    )
    # citeproc reports an unresolved [@key] on stderr but still exits 0; treat it
    # as an error so a typo'd citation fails the build instead of rendering blank.
    if 'not found' in proc.stderr.lower():
        raise SystemExit(f'error: pandoc reported unresolved citations:\n{proc.stderr}')
    return proc.stdout


def section_keys(tool):
    return [k for field in ('pubs', 'datasets', 'satellites') for k in tool.get(field, [])]


HUBS_MD = 'data/hubs.md'


def cited_keys(md_text):
    """Citation keys referenced in the hubs markdown (deduped, in appearance
    order). Used by the completeness check, which must run without invoking
    pandoc (it also runs for the CV templates). HTML comments are stripped first
    so a `[@key]` written in documentation doesn't count, matching pandoc."""
    md_text = re.sub(r'<!--.*?-->', '', md_text, flags=re.S)
    keys = re.findall(r'@([A-Za-z0-9_][\w:.#$%&+?<>~/-]*)', md_text)
    return list(dict.fromkeys(keys))


def render_hub_sections(ctx):
    """Render the homepage sections from data/hubs.md. The whole file (all
    sections) goes through pandoc + citeproc in one pass so citation numbers run
    consecutively across sections. Pandoc is the numbering engine: we keep the
    prose it renders (with superscript citations), read the key->number map from
    its generated bibliography's order, then discard that bibliography — the
    reference lists are rendered by the template in the site's own format. Each
    section's structure comes from its <h1> header attributes (id, github repo,
    a `theme` class for the fourth section), its publications from the [@key]s its
    prose cites, and its injected tool list from the software entries (a hub's one
    anchor tool by repo, the rest under the theme section). Sets ctx['sections']
    (ordered) and ctx['cite_num']."""
    bib = str(Path(os.getenv('BLDDIR', 'build')) / 'refs.csl.json')
    write_bibliography(ctx['references'], bib)
    html = run_pandoc(Path(HUBS_MD).read_text(), bib)

    # Global numbering from the generated bibliography's entry order; then drop it.
    refs = re.search(r'<div id="refs".*</div>', html, re.S)
    order = re.findall(r'id="ref-([^"]+)"', refs.group(0)) if refs else []
    ctx['cite_num'] = {key: i + 1 for i, key in enumerate(order)}
    by_number = lambda k: ctx['cite_num'].get(k, len(order) + 1)
    prose = html[: refs.start()] if refs else html

    # Split into (header, body) per <h1>; read structure from header attributes
    # and the section's references from the citations its body carries.
    parts = re.split(r'(<h1\b[^>]*>.*?</h1>)', prose, flags=re.S)
    sections = []
    for header, body in zip(parts[1::2], parts[2::2]):
        attr = lambda name: (re.search(rf'\b{name}="([^"]+)"', header) or (None, None))[1]
        cited = [k for dc in re.findall(r'data-cites="([^"]+)"', body) for k in dc.split()]
        cls = attr('class') or ''
        sections.append({
            'id': attr('id'),
            'name': unescape(re.sub(r'<[^>]+>', '', re.search(r'<h1\b[^>]*>(.*?)</h1>', header, re.S).group(1)).strip()),
            'github': attr('data-github'),
            'theme': 'theme' in cls.split(),
            'html': Markup(body.strip()),
            'refs': sorted(dict.fromkeys(cited), key=by_number),
        })

    # Inject each section's tool list (kept out of the prose and the numbering): a
    # hub shows the one tool named in its github= header attribute; the theme
    # section gathers every remaining tool.
    hub_githubs = {sec['github'] for sec in sections if sec['github']}
    for sec in sections:
        if sec['github']:
            sec['software'] = [
                t for t in ctx['software'] if t.get('github') == sec['github']
            ]
        elif sec['theme']:
            sec['software'] = [
                t for t in ctx['software'] if t.get('github') not in hub_githubs
            ]
        else:
            sec['software'] = []
    ctx['sections'] = sections


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
    # Lookups for the tool-hub homepage: a reference by id, and talks bucketed
    # into the hubs.
    ctx['refs_by_id'] = {item['id']: item for item in ctx['references']}
    ctx['hub_talks'] = group_talks_by_hub(ctx.get('presentations', {}))
    ctx['theme_talks'] = unhubbed_talks(ctx.get('presentations', {}))
    check_completeness(ctx)
    if 'index' in template.name:
        render_hub_sections(ctx)
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
