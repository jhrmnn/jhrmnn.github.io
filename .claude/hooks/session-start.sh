#!/bin/bash
# SessionStart hook: prepare the environment so the `fetch` and `render`
# CI steps (Makefile targets `fetch` and the default `cv`) can run locally.
#
# It installs the Python deps, the minimal LaTeX toolchain needed to build
# the CV PDF, and downloads the web fonts. Mirrors the relevant pieces of
# the Dockerfile and .github/workflows/build.yaml.
set -euo pipefail

# Only run in the Claude Code on the web remote environment.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-.}"

# 1. Python dependencies (used by both fetch.py and render.py).
poetry install --only main

# 2. Minimal LaTeX toolchain for `make` (cv.pdf via latexmk + xelatex).
#    This is the curated set from the project Dockerfile; its dependency
#    closure provides every package the CV template needs (fontspec, tikz,
#    svg, titlesec, hanging, enumitem, everypage, ulem, geometry, ...).
if ! command -v latexmk >/dev/null 2>&1 || ! command -v xelatex >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive TZ=Etc/UTC
  sudo -E apt-get update -qq
  sudo -E apt-get install -y --no-install-recommends \
    latexmk \
    texlive-base \
    texlive-fonts-recommended \
    texlive-plain-generic \
    texlive-xetex
fi

# 3. Fonts for the CV PDF (same step as the render CI job / devcontainer).
if [ -n "${FONTS_URL:-}" ] && [ ! -d fonts ]; then
  wget -nv -O - "$FONTS_URL" | tar -xz
fi

# 4. Expose the repo slug for the render path. `make` reuses the cached data
#    artifact via reuse_data.py, which reads GITHUB_TOKEN (already provided)
#    and GITHUB_REPOSITORY. The latter is set in CI but not in web sessions,
#    so derive it from the git remote and persist it for the session.
if [ -n "${CLAUDE_ENV_FILE:-}" ] && [ -z "${GITHUB_REPOSITORY:-}" ]; then
  slug=$(git config --get remote.origin.url | tr ':' '/' \
    | sed -E 's#\.git$##' | awk -F/ 'NF>=2{print $(NF-1)"/"$NF}')
  if [ -n "$slug" ]; then
    echo "export GITHUB_REPOSITORY=$slug" >> "$CLAUDE_ENV_FILE"
  fi
fi

echo "session-start hook: environment ready (fetch/render)"
