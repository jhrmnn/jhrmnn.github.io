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

echo "session-start hook: environment ready (fetch/render)"
