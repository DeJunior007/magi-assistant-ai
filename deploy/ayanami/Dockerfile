# Imagem única da Ayanami (spec §9.3, design §11). Contexto de build = raiz do repo:
#   docker build -f deploy/ayanami/Dockerfile -t ayanami:dev .                       # leve
#   docker build -f deploy/ayanami/Dockerfile --build-arg AYANAMI_ML=1 -t ayanami:ml .  # + ayanami-ml
# A variante "ml" (Kokoro, faster-whisper, fastembed, ffmpeg) serve `worker-lento` e `ayanami-voz`;
# a leve serve API, workers rápido/agendado e `migrar`.

ARG PYTHON_IMAGE=python:3.12-slim-bookworm

# ---------------------------------------------------------------- deps + projeto (com uv)
FROM ${PYTHON_IMAGE} AS construtor
COPY --from=ghcr.io/astral-sh/uv:0.12.7 /uv /usr/local/bin/uv

ARG AYANAMI_ML=0
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /src
# PySide6 (HUD) e evdev (teclado/PTT) são do PC: estão nas dependências base, sem uso no node 2
# (o evdev nem tem wheel e exigiria compilador).
ENV UV_SEM_PC="--no-install-package pyside6 --no-install-package pyside6-addons \
--no-install-package pyside6-essentials --no-install-package shiboken6 --no-install-package evdev"

COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    extras="--extra ayanami"; \
    if [ "$AYANAMI_ML" = "1" ]; then extras="$extras --extra ayanami-ml"; fi; \
    uv sync --frozen --no-dev --no-install-project $extras $UV_SEM_PC

COPY magi ./magi
COPY ayanami ./ayanami
RUN --mount=type=cache,target=/root/.cache/uv \
    extras="--extra ayanami"; \
    if [ "$AYANAMI_ML" = "1" ]; then extras="$extras --extra ayanami-ml"; fi; \
    uv sync --frozen --no-dev --no-editable $extras $UV_SEM_PC

# ---------------------------------------------------------------- docker CLI (só o binário)
# `worker-agendado` fala com o Docker do host pelo docker.sock (ex.: `docker exec ayanami-pg pg_dump`).
FROM docker:27.5.1-cli AS docker-cli

# ---------------------------------------------------------------- execução
FROM ${PYTHON_IMAGE} AS final
ARG AYANAMI_ML=0
ARG AYANAMI_UID=10740
ARG AYANAMI_GID=10740

ENV TZ=America/Sao_Paulo \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/app/.venv/bin:$PATH \
    HF_HOME=/modelos/hf \
    AYANAMI_MODELOS=/modelos

RUN set -eux; \
    pacotes="ca-certificates curl tzdata restic"; \
    if [ "$AYANAMI_ML" = "1" ]; then pacotes="$pacotes ffmpeg libgomp1"; fi; \
    apt-get update; \
    apt-get install -y --no-install-recommends $pacotes; \
    rm -rf /var/lib/apt/lists/*; \
    ln -snf /usr/share/zoneinfo/$TZ /etc/localtime; echo "$TZ" > /etc/timezone; \
    groupadd --system --gid "$AYANAMI_GID" ayanami; \
    useradd --system --uid "$AYANAMI_UID" --gid ayanami --home-dir /home/ayanami --create-home \
        --shell /usr/sbin/nologin ayanami; \
    mkdir -p /dados /modelos /etc/ayanami; \
    chown ayanami:ayanami /dados /modelos

COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=construtor --chown=ayanami:ayanami /app/.venv /app/.venv

USER ayanami
WORKDIR /home/ayanami
CMD ["ayanami", "--help"]
