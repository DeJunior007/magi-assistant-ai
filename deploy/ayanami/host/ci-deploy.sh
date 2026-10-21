#!/usr/bin/env bash
# Comando forçado da chave de deploy da CI (Y1.4). Instalado no node 2 como
# /usr/local/bin/ayanami-ci-deploy (root:root 0755) e amarrado à chave pública da CI no
# ~ayanami/.ssh/authorized_keys:
#
#   restrict,command="/usr/local/bin/ayanami-ci-deploy" ssh-ed25519 AAAA… ayanami-ci
#
# A chave não abre shell: só aceita, em $SSH_ORIGINAL_COMMAND, um destes dois pedidos:
#
#   deploy <sha de 40 hex>   # código em <sha> (fetch + merge --ff-only) e
#                            # deploy.sh --tag <sha> --sem-git --sem-build (imagens do ghcr)
#   saude                    # /saude respondeu e banco == "ok" (o `ok` geral pode ser false
#                            # enquanto faltam segredos de terceiros)
set -euo pipefail

AYANAMI_DIR="${AYANAMI_DIR:-/opt/ayanami}"
URL_SAUDE="http://127.0.0.1:8740/saude"

pedido="${SSH_ORIGINAL_COMMAND:-}"
read -r verbo arg resto <<<"$pedido" || true

case "${verbo:-}" in
  deploy)
    if [ -n "${resto:-}" ] || ! [[ "${arg:-}" =~ ^[0-9a-f]{40}$ ]]; then
      echo "recusado: uso 'deploy <sha de 40 hex>'" >&2
      exit 2
    fi
    exec 9>"$AYANAMI_DIR/.git/ci-deploy.lock"
    flock -w 600 9 || { echo "outro deploy em andamento" >&2; exit 1; }
    git -C "$AYANAMI_DIR" fetch --quiet origin main
    git -C "$AYANAMI_DIR" merge --ff-only --quiet "$arg"
    exec "$AYANAMI_DIR/deploy/ayanami/host/deploy.sh" --tag "$arg" --sem-git --sem-build
    ;;
  saude)
    [ -z "${arg:-}" ] || { echo "recusado: 'saude' não leva argumento" >&2; exit 2; }
    curl -fsS --max-time 10 "$URL_SAUDE" | python3 -c '
import json, sys
s = json.load(sys.stdin)
print("banco=%s ok=%s faltando=%s" % (s.get("banco"), s.get("ok"), s.get("faltando")))
sys.exit(0 if s.get("banco") == "ok" else 1)
'
    ;;
  *)
    echo "recusado: esta chave só aceita 'deploy <sha>' ou 'saude'" >&2
    exit 2
    ;;
esac
