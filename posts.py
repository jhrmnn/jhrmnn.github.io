#!/usr/bin/env python3
"""Render the blog: each `posts/YYYY-MM-DD-slug.md` into an h-entry permalink
page at `notes/YYYY-MM-DD-slug/index.html`, plus an h-feed index at
`notes/index.html`.

The microformats2 markup (h-card on the home page, h-entry here) is what lets
Bridgy Fed (https://fed.brid.gy) bridge the site into the Fediverse. Reuses the
Jinja environment and output normalisation from `render.py` so blog pages come
out identical in style to the rest of the site.
"""
import argparse
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from markupsafe import Markup

from render import finalize_doc, make_env, md_to_html

BASE_URL = 'https://jan.hermann.name'
FILENAME_RE = re.compile(r'(\d{4})-(\d{2})-(\d{2})-(.+)\.md$')
BULLET_RE = re.compile(r'[-*]\s')
ORDERED_RE = re.compile(r'\d+\.\s')
ORDERED_PREFIX_RE = re.compile(r'^\d+\.\s*')


def md_blocks_to_html(text):
    """Turn a Markdown post body into HTML. Block-level only (paragraphs,
    headings, lists, blockquotes); inline spans (links, emphasis, code, smart
    quotes) reuse `render.py`'s `md_to_html`. Deliberately tiny and
    dependency-free, matching the site's house-style regex Markdown."""
    out = []
    for block in re.split(r'\n\s*\n', text.strip()):
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        if all(ln.lstrip().startswith('#') for ln in lines):
            for ln in lines:
                level = len(ln) - len(ln.lstrip('#'))
                tag = f'h{min(level + 1, 6)}'
                out.append(f'<{tag}>{md_to_html(ln.lstrip("# ").strip())}</{tag}>')
        elif all(ln.lstrip().startswith('>') for ln in lines):
            inner = ' '.join(ln.lstrip().lstrip('>').strip() for ln in lines)
            out.append(f'<blockquote><p>{md_to_html(inner)}</p></blockquote>')
        elif all(BULLET_RE.match(ln.lstrip()) for ln in lines):
            items = ''.join(
                f'<li>{md_to_html(ln.lstrip()[2:].strip())}' for ln in lines
            )
            out.append(f'<ul>{items}</ul>')
        elif all(ORDERED_RE.match(ln.lstrip()) for ln in lines):
            items = ''.join(
                f'<li>{md_to_html(ORDERED_PREFIX_RE.sub("", ln.lstrip()))}'
                for ln in lines
            )
            out.append(f'<ol>{items}</ol>')
        else:
            out.append(f'<p>{md_to_html(" ".join(ln.strip() for ln in lines))}')
    return '\n'.join(out)


def git_dates(path):
    """First and last git author dates touching `path`, as ISO-8601 strings,
    or (None, None) if the file isn't tracked yet (e.g. a brand-new post in
    local dev, or git history unavailable). The last date drives dt-updated:
    Bridgy Fed reads that timestamp off the h-entry and federates the edit as
    an ActivityPub Update, so a post that's been edited after publication
    actually changes on Mastodon. Without it the re-sent webmention refers to
    an object that looks unchanged and the edit never surfaces. Needs full
    history at render time (CI checks out with fetch-depth: 0)."""
    try:
        out = subprocess.run(
            ['git', 'log', '--format=%aI', '--', str(path)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None, None
    if not out:
        return None, None
    return out[-1], out[0]  # git log is newest-first: oldest, newest


def parse_post(path):
    text = path.read_text()
    meta = {}
    body = text
    if text.startswith('---\n'):
        _, front_matter, body = text.split('---\n', 2)
        meta = yaml.safe_load(front_matter) or {}
    m = FILENAME_RE.search(path.name)
    if not m:
        sys.exit(f'error: post filename must be YYYY-MM-DD-slug.md: {path.name}')
    year, month, day, _slug = m.groups()
    date = datetime(int(year), int(month), int(day))
    # URL segment is the full filename stem (date + slug), e.g.
    # 2026-05-05-consciousness, so the date lives in the permalink too.
    segment = path.stem
    # Timestamps come from git: the first commit is publication, the latest is
    # the last edit. dt-published thus carries a real time (not just the
    # filename's midnight) and, when a post has been committed more than once,
    # dt-updated advertises a newer timestamp — which is what makes Bridgy Fed
    # federate the edit as an ActivityPub Update instead of a silent no-op.
    # Falls back to the filename date for an as-yet-uncommitted post (local dev).
    first_commit, last_commit = git_dates(path)
    published = first_commit or date.strftime('%Y-%m-%d')
    updated = last_commit if first_commit and last_commit != first_commit else None
    return {
        'segment': segment,
        # Relative permalink for in-page links and u-url, so navigation works on
        # any deployment (production, Cloudflare preview, local). Bridgy Fed
        # fetches the production page and resolves it against that, so the
        # federated identity is still the canonical URL below.
        'url': f'/notes/{segment}/',
        'canonical': f'{BASE_URL}/notes/{segment}/',
        # Optional: a post with a title is an article, one without is a note (a
        # short, Mastodon-style post). The templates omit p-name when absent so
        # microformats/Bridgy Fed treat it as a note.
        'title': meta.get('title'),
        # dt-published timestamp (full ISO-8601 from git); the display string and
        # the sort key stay on the filename date, which is the canonical day and
        # already lives in the permalink.
        'datetime': published,
        'date_display': date.strftime('%-d %B %Y'),
        'date': date,
        # Full ISO-8601 (with time) so each subsequent edit is a distinct value
        # Bridgy Fed/Mastodon recognise; None when the post hasn't been edited.
        'updated': updated,
        'updated_display': (
            datetime.fromisoformat(updated).strftime('%-d %B %Y') if updated else None
        ),
        'content_html': Markup(md_blocks_to_html(body)),
    }


def render_to(env, template_name, ctx, dest):
    doc = finalize_doc(env.get_template(template_name).render(ctx), template_name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(doc)


def main(argv):
    p = argparse.ArgumentParser()
    p.add_argument('posts_dir', type=Path)
    # The static context files are accepted (so the Makefile can pass $(CTX))
    # but unused: blog pages only need constant author info.
    p.add_argument('ctx', nargs='*', type=Path)
    p.add_argument('--generated')
    p.add_argument('-o', dest='outdir', type=Path, required=True)
    a = p.parse_args(argv)

    now = (
        datetime.now()
        .replace(microsecond=0)
        .astimezone(ZoneInfo('Europe/Berlin'))
        .isoformat()
    )
    settings = {'now': now, 'generated': a.generated}

    posts = sorted(
        (parse_post(f) for f in a.posts_dir.glob('*.md')),
        key=lambda x: x['date'],
        reverse=True,
    )

    env = make_env('templates/post.html.in')  # HTML env, shared with the index
    for post in posts:
        render_to(
            env,
            'templates/post.html.in',
            {'post': post, 'settings': settings},
            a.outdir / 'notes' / post['segment'] / 'index.html',
        )
    render_to(
        env,
        'templates/blog.html.in',
        {'posts': posts, 'settings': settings},
        a.outdir / 'notes' / 'index.html',
    )
    print(f'rendered {len(posts)} post(s) + blog index', file=sys.stderr)


if __name__ == '__main__':
    main(sys.argv[1:])
