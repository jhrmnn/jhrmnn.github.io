FROM ubuntu
RUN --mount=type=cache,target=/var/lib/apt/lists apt update && \
    DEBIAN_FRONTEND=noninteractive TZ=Etc/UTC apt install -y --no-install-recommends \
        entr \
        make \
        latexmk \
        python3-pip \
        python3-venv \
        texlive-base \
        texlive-fonts-recommended \
        texlive-plain-generic \
        texlive-xetex
RUN --mount=type=cache,target=/root/.cache export PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin && \
    pip install pipx && \
    pipx ensurepath && \
    pipx install poetry
