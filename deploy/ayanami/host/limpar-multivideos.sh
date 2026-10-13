#!/usr/bin/env bash
# Restos do MultiVideos NO NODE 2 (Y1.2; requirements "O que precisa do Pedro" item 2).
# NUNCA no node 1 (MultiVideos/wedding/gold-crm em produção).
#
#   ./limpar-multivideos.sh --host-esperado <hostname> --ip-esperado <ip>         # só lista
#   sudo ./limpar-multivideos.sh --host-esperado <hostname> --ip-esperado <ip> --sim  # apaga, item a item
#
# Hostname e IP esperados vêm do painel da Contabo (o Pedro digita; não ficam no repo). Antes de
# QUALQUER leitura o script confere os dois e aborta se não baterem, ou se houver contêiner rodando
# com cara de produção (multivideos/wedding/gold): isso é sinal de que a máquina é o node 1.
#
# Itens (e só estes): /opt/multivideos; docker-compose.node2.yml soltos em /opt, /root, /home;
# contêineres PARADOS do MultiVideos/Ollama/Whisper; volumes Ollama/Whisper sem contêiner;
# interface wg0 (a config vai para /var/backups, não é apagada); regras ufw além de 22/tcp e
# 41641/udp. Padrão = dry-run: lista e sai sem tocar em nada. Com --sim, pergunta "s/N" por item
# (lido da entrada padrão); qualquer coisa diferente de "s" pula o item.
set -euo pipefail

RAIZ="${LIMPAR_RAIZ:-}"   # só para testes; vazio = /
HOST_ESPERADO=""
IP_ESPERADO=""
SIM=0
PROD='multivideos|wedding|gold'

uso() {
  echo "uso: $0 --host-esperado <hostname> --ip-esperado <ip> [--sim]" >&2
  exit 2
}
log() { echo "[limpar] $*"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --host-esperado) HOST_ESPERADO="${2:-}"; shift 2 ;;
    --ip-esperado) IP_ESPERADO="${2:-}"; shift 2 ;;
    --sim) SIM=1; shift ;;
    -h|--help) uso ;;
    *) echo "argumento desconhecido: $1" >&2; uso ;;
  esac
done
[ -n "$HOST_ESPERADO" ] && [ -n "$IP_ESPERADO" ] || uso

# --- trava: é mesmo o node 2? ------------------------------------------------------------------
host_real="$(hostname)"
if [ "$host_real" != "$HOST_ESPERADO" ]; then
  echo "ABORTADO: hostname '$host_real' != esperado '$HOST_ESPERADO'. Nada foi lido nem tocado." >&2
  exit 3
fi
ips_reais=" $(hostname -I 2>/dev/null || true) "
case "$ips_reais" in
  *" $IP_ESPERADO "*) ;;
  *)
    echo "ABORTADO: IP '$IP_ESPERADO' não está nesta máquina. Nada foi lido nem tocado." >&2
    exit 3
    ;;
esac

TEM_DOCKER=0
if command -v docker >/dev/null 2>&1; then TEM_DOCKER=1; fi

if [ "$TEM_DOCKER" -eq 1 ]; then
  vivos="$(docker ps --format '{{.Names}} {{.Image}}' | grep -iE "$PROD" || true)"
  if [ -n "$vivos" ]; then
    echo "ABORTADO: há contêiner RODANDO com cara de produção (node 1?):" >&2
    echo "$vivos" >&2
    exit 3
  fi
fi

if [ "$SIM" -eq 1 ] && [ "$(id -u)" -ne 0 ]; then
  echo "--sim precisa de root (sudo)" >&2
  exit 1
fi

# --- levantamento ------------------------------------------------------------------------------
DIR_MV="$RAIZ/opt/multivideos"
mapfile -t COMPOSES < <(
  for base in "$RAIZ/opt" "$RAIZ/root" "$RAIZ/home"; do
    [ -d "$base" ] && find "$base" -maxdepth 4 -name docker-compose.node2.yml -not -path "$DIR_MV/*" 2>/dev/null
  done | sort -u
)

CONTEINERES=()
VOLUMES=()
if [ "$TEM_DOCKER" -eq 1 ]; then
  mapfile -t CONTEINERES < <(
    docker ps -a --filter status=exited --filter status=created --format '{{.Names}}' \
      | grep -iE 'multivideos|ollama|whisper' || true
  )
  mapfile -t VOLUMES < <(
    docker volume ls --format '{{.Name}}' | grep -iE 'ollama|whisper' | grep -viE 'ayanami|magi' || true
  )
fi

TEM_WG=0
WG_CONF="$RAIZ/etc/wireguard/wg0.conf"
if [ -e "$WG_CONF" ]; then TEM_WG=1; fi
if command -v ip >/dev/null 2>&1 && ip link show wg0 >/dev/null 2>&1; then TEM_WG=1; fi

REGRAS=()
if command -v ufw >/dev/null 2>&1; then
  mapfile -t REGRAS < <(
    ufw status numbered 2>/dev/null \
      | sed -nE 's/^\[ *([0-9]+)\] +(.*[^ ]) *$/\1|\2/p' \
      | grep -vE '^[0-9]+\|(22/tcp|41641/udp)( \(v6\))? ' \
      | sort -t'|' -k1,1 -rn || true
  )
fi

# --- lista ---------------------------------------------------------------------------------------
total=0
echo "== Restos do MultiVideos em $host_real =="
if [ -d "$DIR_MV" ]; then
  echo "diretório: $DIR_MV ($(du -sh "$DIR_MV" 2>/dev/null | cut -f1))"; total=$((total + 1))
fi
for c in "${COMPOSES[@]}"; do [ -n "$c" ] && { echo "arquivo: $c"; total=$((total + 1)); }; done
for c in "${CONTEINERES[@]}"; do [ -n "$c" ] && { echo "contêiner parado: $c"; total=$((total + 1)); }; done
for v in "${VOLUMES[@]}"; do [ -n "$v" ] && { echo "volume: $v"; total=$((total + 1)); }; done
if [ "$TEM_WG" -eq 1 ]; then echo "wireguard: wg0 ($WG_CONF)"; total=$((total + 1)); fi
for r in "${REGRAS[@]}"; do [ -n "$r" ] && { echo "regra ufw [${r%%|*}]: ${r#*|}"; total=$((total + 1)); }; done
echo "== $total item(ns) =="

if [ "$SIM" -eq 0 ]; then
  log "dry-run: nada foi apagado. Para apagar, item a item: $0 --host-esperado $HOST_ESPERADO --ip-esperado $IP_ESPERADO --sim"
  exit 0
fi
[ "$total" -gt 0 ] || { log "nada a fazer"; exit 0; }

# --- remoção (só com --sim, uma confirmação por item) --------------------------------------------
confirma() {
  local resp=""
  printf 'apagar %s? [s/N] ' "$1"
  read -r resp || resp=""
  [ "$resp" = "s" ] || [ "$resp" = "S" ]
}

BACKUP="$RAIZ/var/backups/limpar-multivideos-$(date +%Y%m%d-%H%M%S)"

if [ -d "$DIR_MV" ] && confirma "o diretório $DIR_MV"; then
  rm -rf -- "$DIR_MV"; log "apagado $DIR_MV"
fi
for c in "${COMPOSES[@]}"; do
  [ -n "$c" ] || continue
  if confirma "o arquivo $c"; then rm -f -- "$c"; log "apagado $c"; fi
done
for c in "${CONTEINERES[@]}"; do
  [ -n "$c" ] || continue
  if [ "$(docker inspect -f '{{.State.Running}}' "$c")" = "true" ]; then
    log "pulado (rodando): $c"; continue
  fi
  if confirma "o contêiner parado $c"; then docker container rm "$c"; log "removido $c"; fi
done
for v in "${VOLUMES[@]}"; do
  [ -n "$v" ] || continue
  if [ -n "$(docker ps -a -q --filter "volume=$v")" ]; then
    log "pulado (ainda há contêiner usando): $v"; continue
  fi
  if confirma "o volume $v (modelos baixados; não tem dado da Ayanami)"; then
    docker volume rm "$v"; log "removido volume $v"
  fi
done
if [ "$TEM_WG" -eq 1 ] && confirma "a interface wg0 (config vai para $BACKUP)"; then
  if command -v wg-quick >/dev/null 2>&1; then wg-quick down wg0 || true; fi
  systemctl disable wg-quick@wg0 2>/dev/null || true
  if [ -e "$WG_CONF" ]; then
    install -d -m 0700 "$BACKUP"
    mv -- "$WG_CONF" "$BACKUP/"
  fi
  log "wg0 desligada"
fi
# Números da maior para a menor: apagar uma não desloca as que faltam.
for r in "${REGRAS[@]}"; do
  [ -n "$r" ] || continue
  if confirma "a regra ufw [${r%%|*}] ${r#*|}"; then
    ufw --force delete "${r%%|*}"; log "regra ${r%%|*} apagada"
  fi
done
log "fim. Confira com: ufw status numbered; docker volume ls; ip link"
