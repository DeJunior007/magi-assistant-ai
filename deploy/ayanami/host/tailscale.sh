#!/usr/bin/env bash
# Tailscale no host do node 2 (Y1.2; design §10.1). Idempotente. Roda como root NO NODE 2.
#   - instala o tailscale se faltar (script oficial; revise antes);
#   - `tailscale up` com hostname `ayanami`, tag `tag:ayanami` e Tailscale SSH (login interativo,
#     ou TS_AUTHKEY no ambiente — nunca em arquivo);
#   - `tailscale serve --bg --https=443 http://127.0.0.1:8740` (só tailnet);
#   - `tailscale serve --bg --https=8443 http://127.0.0.1:8742` (ntfy, só tailnet);
#   - recusa Funnel ligado (proibido salvo D2c/D1b).
# Sem subnet router nem exit node. ACL (grants) é aprovada pelo Pedro no painel (runbook).
set -euo pipefail

HOSTNAME_TS="ayanami"
ALVO="http://127.0.0.1:8740"
ALVO_NTFY="http://127.0.0.1:8742"

log() { echo "[tailscale] $*"; }

if [ "$(id -u)" -ne 0 ]; then
  echo "rode como root (sudo)" >&2
  exit 1
fi

if ! command -v tailscale >/dev/null 2>&1; then
  log "instalando tailscale (https://tailscale.com/install.sh)"
  curl -fsSL https://tailscale.com/install.sh | sh
fi
systemctl enable --now tailscaled

estado="$(tailscale status --json 2>/dev/null | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    print("? ?"); raise SystemExit
eu = d.get("Self") or {}
print(d.get("BackendState", "?"), eu.get("HostName", "?"))
' || echo "? ?")"
backend="${estado%% *}"
nome="${estado#* }"

if [ "$backend" = "Running" ] && [ "$nome" = "$HOSTNAME_TS" ]; then
  log "já no tailnet como $HOSTNAME_TS"
else
  args=(up --hostname="$HOSTNAME_TS" --advertise-tags=tag:ayanami --ssh)
  if [ -n "${TS_AUTHKEY:-}" ]; then
    args+=(--auth-key="$TS_AUTHKEY")
  fi
  log "tailscale up --hostname=$HOSTNAME_TS --advertise-tags=tag:ayanami --ssh"
  tailscale "${args[@]}"
fi

if tailscale serve status 2>/dev/null | grep -qF "$ALVO"; then
  log "serve já aponta para $ALVO"
else
  tailscale serve --bg --https=443 "$ALVO"
fi

# ntfy (push do app Android, condessa-celular spec §10): https://ayanami.<tailnet>:8443 -> 127.0.0.1:8742.
if tailscale serve status 2>/dev/null | grep -qF "$ALVO_NTFY"; then
  log "serve já aponta para $ALVO_NTFY"
else
  tailscale serve --bg --https=8443 "$ALVO_NTFY"
fi

if tailscale funnel status 2>/dev/null | grep -qi 'funnel on'; then
  echo "Funnel ligado: proibido (design §10.1). Desligue com 'tailscale funnel reset'." >&2
  exit 1
fi

tailscale serve status
log "teste do PC: curl -fsS https://$HOSTNAME_TS.<tailnet>.ts.net/saude (depois do deploy)"
