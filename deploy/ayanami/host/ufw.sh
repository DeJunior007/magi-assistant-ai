#!/usr/bin/env bash
# Firewall do node 2 (Y1.2; design §10.2): nega entrada; libera 22/tcp e 41641/udp; nada mais.
# Idempotente. Roda como root NO NODE 2, revisado pelo Pedro. A regra do 22 entra ANTES de ligar o
# ufw para não derrubar a sessão SSH. Regras antigas (MultiVideos) não são apagadas aqui: o script
# as lista; quem remove é o limpar-multivideos.sh (item a item, com --sim).
# Docker ignora o ufw para portas publicadas: por isso o compose só publica em 127.0.0.1, e este
# script avisa se achar contêiner publicado em 0.0.0.0.
set -euo pipefail

log() { echo "[ufw] $*"; }

if [ "$(id -u)" -ne 0 ]; then
  echo "rode como root (sudo)" >&2
  exit 1
fi

ufw allow 22/tcp
ufw allow 41641/udp
ufw default deny incoming
ufw default allow outgoing
ufw --force enable

# Sobras: qualquer regra além das duas (v4 e v6).
extras="$(ufw status | grep -E 'ALLOW|DENY|REJECT|LIMIT' | grep -vE '^(22/tcp|41641/udp)( \(v6\))? ' || true)"
if [ -n "$extras" ]; then
  log "AVISO: regras além de 22/tcp e 41641/udp (rode limpar-multivideos.sh para revisar):"
  echo "$extras"
fi

if command -v docker >/dev/null 2>&1; then
  abertas="$(docker ps --format '{{.Names}} {{.Ports}}' | grep -E '0\.0\.0\.0:|\[::\]:' || true)"
  if [ -n "$abertas" ]; then
    log "AVISO: contêineres publicados fora de 127.0.0.1 (o ufw NÃO os protege):"
    echo "$abertas"
  fi
fi

ufw status verbose
