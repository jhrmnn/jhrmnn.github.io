FROM ubuntu
RUN --mount=type=cache,target=/var/lib/apt/lists apt-get update && \
    DEBIAN_FRONTEND=noninteractive TZ=Etc/UTC apt-get install -y --no-install-recommends \
        entr \
        make \
        latexmk \
        pipx \
        python3-pip \
        python3-venv \
        texlive-base \
        texlive-fonts-recommended \
        texlive-plain-generic \
        texlive-xetex \
        wget
RUN --mount=type=cache,target=/root/.cache export PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin && \
    pipx install poetry
