#!/bin/bash
# SessionStart hook: prepare the environment so the `fetch` and `render`
# CI steps (Makefile targets `fetch` and the default `cv`) can run locally.
#
# It installs the Python deps, pandoc (for render's citeproc pass), the minimal
# LaTeX toolchain needed to build the CV PDF, and downloads the web fonts, then
# persists a few env vars so a plain `make` works out of the box: the poetry
# venv on PATH (the Makefile scripts run `#!/usr/bin/env python3`, so they must
# resolve to the venv that has bs4/nltk/iso4), the repo slug, and the current
# branch (so reuse_data.py reuses this branch's data artifact, not just main's).
# Mirrors the relevant pieces of the Dockerfile and .github/workflows/build.yaml.
set -euo pipefail

# Only run in the Claude Code on the web remote environment.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}"

# 1. Python dependencies (used by both fetch.py and render.py).
poetry install --only main

# 2. pandoc (render's citeproc pass) + the minimal LaTeX toolchain for `make`
#    (cv.pdf via latexmk + xelatex). This is the curated set from the project
#    Dockerfile; its dependency closure provides every package the CV template
#    needs (fontspec, tikz, svg, titlesec, hanging, enumitem, everypage, ulem,
#    geometry, ...). pandoc is checked too: latexmk may already be present (so
#    the latex packages no-op on reinstall) while pandoc is still missing.
if ! command -v pandoc >/dev/null 2>&1 \
  || ! command -v latexmk >/dev/null 2>&1 \
  || ! command -v xelatex >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive TZ=Etc/UTC
  sudo -E apt-get update -qq
  sudo -E apt-get install -y --no-install-recommends \
    latexmk \
    pandoc \
    texlive-base \
    texlive-fonts-recommended \
    texlive-plain-generic \
    texlive-xetex
fi

# 3. Fonts for the CV PDF (same step as the render CI job / devcontainer).
if [ -n "${FONTS_URL:-}" ] && [ ! -d fonts ]; then
  wget -nv -O - "$FONTS_URL" | tar -xz
fi

# 4. Persist env vars for the session so a plain `make` works.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  # a. Put the poetry venv on PATH so the Makefile's `#!/usr/bin/env python3`
  #    scripts resolve to the interpreter that has the project deps installed
  #    (bs4 for fetch.py, nltk/iso4 for check_sources.py), not the bare system
  #    python that only happens to satisfy render.py.
  venv=$(poetry env info -p 2>/dev/null || true)
  if [ -n "$venv" ]; then
    echo "export PATH=$venv/bin:\$PATH" >> "$CLAUDE_ENV_FILE"
  fi

  # b. Expose the repo slug for the render path. `make` reuses the cached data
  #    artifact via reuse_data.py, which reads GITHUB_TOKEN (already provided)
  #    and GITHUB_REPOSITORY. The latter is set in CI but not in web sessions,
  #    so derive it from the git remote and persist it for the session.
  if [ -z "${GITHUB_REPOSITORY:-}" ]; then
    slug=$(git config --get remote.origin.url | tr ':' '/' \
      | sed -E 's#\.git$##' | awk -F/ 'NF>=2{print $(NF-1)"/"$NF}')
    if [ -n "$slug" ]; then
      echo "export GITHUB_REPOSITORY=$slug" >> "$CLAUDE_ENV_FILE"
    fi
  fi

  # c. Expose the current branch as GITHUB_REF_NAME so reuse_data.py reuses this
  #    branch's own data artifact when one exists (falling back to main), instead
  #    of always taking main's. Without this the branch is undetectable outside
  #    CI and a branch whose data scheme diverges from main can't be rendered.
  if [ -z "${GITHUB_REF_NAME:-}" ]; then
    branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)
    if [ -n "$branch" ] && [ "$branch" != "HEAD" ]; then
      echo "export GITHUB_REF_NAME=$branch" >> "$CLAUDE_ENV_FILE"
    fi
  fi
fi

echo "session-start hook: environment ready (fetch/render)"
