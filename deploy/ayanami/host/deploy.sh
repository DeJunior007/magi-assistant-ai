#!/usr/bin/env bash
# Deploy da Ayanami no node 2 (Y1.2; spec §9.3 "Deploy", design §11). Roda NO NODE 2 como o
# usuário `ayanami` (grupo docker) ou root; a CI (Y1.4) chama este mesmo script por SSH.
#
#   ./deploy.sh                 # git pull + imagens + migrar + up -d + /saude
#   ./deploy.sh --tag <sha>     # fixa AYANAMI_TAG no .env (rollback por tag de imagem)
#   ./deploy.sh --sem-git       # não faz git pull (rollback sem mexer no código)
#   ./deploy.sh --sem-build     # não constrói: as imagens vêm prontas do PC (docker save | docker load),
#                               # como no node 2 compartilhado com o Minecraft (runbook §2.1)
#
# Sequência (§9.3): git pull → docker compose pull --ignore-buildable (+ build enquanto a imagem
# for local, sem ghcr) → docker compose --profile ops run --rm migrar → docker compose up -d →
# curl -fsS http://127.0.0.1:8740/saude (com novas tentativas). Nunca derruba a pilha nem apaga
# volume: só sobe por cima.
set -euo pipefail

AYANAMI_DIR="${AYANAMI_DIR:-/opt/ayanami}"
TENTATIVAS="${AYANAMI_SAUDE_TENTATIVAS:-30}"
ESPERA="${AYANAMI_SAUDE_ESPERA:-2}"
URL_SAUDE="http://127.0.0.1:8740/saude"
TAG=""
GIT=1
BUILD=1

uso() { echo "uso: $0 [--tag <tag>] [--sem-git] [--sem-build]" >&2; exit 2; }
log() { echo "[deploy] $*"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --tag) TAG="${2:-}"; [ -n "$TAG" ] || uso; shift 2 ;;
    --sem-git) GIT=0; shift ;;
    --sem-build) BUILD=0; shift ;;
    -h|--help) uso ;;
    *) echo "argumento desconhecido: $1" >&2; uso ;;
  esac
done

DEPLOY="$AYANAMI_DIR/deploy/ayanami"
ENV_ARQ="$AYANAMI_DIR/.env"
[ -f "$DEPLOY/compose.yml" ] || { echo "sem $DEPLOY/compose.yml (rode preparar.sh)" >&2; exit 1; }
[ -f "$ENV_ARQ" ] || { echo "sem $ENV_ARQ (0600, spec §9.1)" >&2; exit 1; }

if [ -n "$TAG" ]; then
  case "$TAG" in
    *[!A-Za-z0-9._-]*) echo "tag inválida: $TAG" >&2; exit 2 ;;
  esac
  if grep -q '^AYANAMI_TAG=' "$ENV_ARQ"; then
    sed -i "s/^AYANAMI_TAG=.*/AYANAMI_TAG=$TAG/" "$ENV_ARQ"
  else
    echo "AYANAMI_TAG=$TAG" >> "$ENV_ARQ"
  fi
  log "AYANAMI_TAG=$TAG no .env"
fi

if [ "$GIT" -eq 1 ]; then
  log "git pull"
  git -C "$AYANAMI_DIR" pull --ff-only
fi

cd "$DEPLOY"

log "imagens"
docker compose pull --ignore-buildable
# Sem AYANAMI_IMAGEM (ghcr) a imagem é local (A1): constrói aqui.
if [ "$BUILD" -eq 1 ] && [ -z "${AYANAMI_IMAGEM:-}" ] && ! grep -q '^AYANAMI_IMAGEM=.' "$ENV_ARQ"; then
  log "imagem local: docker compose build"
  docker compose build
fi

log "migrações"
docker compose --profile ops run --rm migrar

log "subindo"
if [ "$BUILD" -eq 1 ]; then
  docker compose up -d
else
  docker compose up -d --no-build --pull never
fi

log "conferindo $URL_SAUDE"
i=1
while :; do
  if curl -fsS "$URL_SAUDE"; then
    echo
    log "ok"
    exit 0
  fi
  if [ "$i" -ge "$TENTATIVAS" ]; then
    echo "/saude não respondeu ok depois de $TENTATIVAS tentativas; veja 'docker compose ps' e os logs" >&2
    exit 1
  fi
  i=$((i + 1))
  sleep "$ESPERA"
done
