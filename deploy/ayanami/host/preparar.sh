#!/usr/bin/env bash
# Prepara o host do node 2 para a Ayanami (Y1.2; design §10.2, §11; spec §9.3).
# Idempotente: rodar de novo só confere. Roda como root NO NODE 2, revisado pelo Pedro.
# Nunca no node 1 (MultiVideos/wedding/gold-crm).
#
#   sudo ./preparar.sh --repo <url-do-git> [--ref main]
#
# Faz: pacotes (git, curl, ufw, python3, unattended-upgrades, Docker + compose v2), usuário de
# sistema `ayanami` (grupo docker), /opt/ayanami (clone do repo), /opt/ayanami/dados/{entrada,tmp,
# restic-cache}, links de deploy/ayanami/{.env,ayanami.toml,dados} para /opt/ayanami/…,
# DOCKER_GID real no .env (0600), SSH só por chave (só se já houver chave autorizada).
# Não cria segredos: o .env com os valores é do Pedro (runbook, Y1.6).
set -euo pipefail

RAIZ="${PREPARAR_RAIZ:-}"   # só para testes; vazio = /
AYANAMI_DIR="${AYANAMI_DIR:-$RAIZ/opt/ayanami}"
SSHD_DIR="$RAIZ/etc/ssh/sshd_config.d"
USUARIO="ayanami"
REPO_URL=""
REF="main"

uso() { echo "uso: $0 --repo <url> [--ref <branch>]" >&2; exit 2; }
log() { echo "[preparar] $*"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --repo) REPO_URL="${2:-}"; shift 2 ;;
    --ref) REF="${2:-}"; shift 2 ;;
    -h|--help) uso ;;
    *) echo "argumento desconhecido: $1" >&2; uso ;;
  esac
done

if [ "$(id -u)" -ne 0 ]; then
  echo "rode como root (sudo)" >&2
  exit 1
fi

# --- pacotes -----------------------------------------------------------------------------
if [ -r "$RAIZ/etc/os-release" ]; then
  # shellcheck disable=SC1090,SC1091
  . "$RAIZ/etc/os-release"
  case "${ID:-}" in
    ubuntu|debian) ;;
    *) echo "distribuição não prevista (${ID:-?}); só Ubuntu/Debian" >&2; exit 1 ;;
  esac
fi

export DEBIAN_FRONTEND=noninteractive
log "pacotes base"
apt-get update -q
apt-get install -y -q git curl ca-certificates ufw python3 unattended-upgrades

if ! command -v docker >/dev/null 2>&1; then
  log "instalando Docker (pacotes da distribuição)"
  apt-get install -y -q docker.io docker-compose-v2
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "falta o plugin 'docker compose' v2; instale pelo repositório oficial do Docker" >&2
  exit 1
fi
if ! docker compose pull --help 2>/dev/null | grep -q -- '--ignore-buildable'; then
  echo "docker compose antigo (sem 'pull --ignore-buildable'); atualize pelo repositório oficial do Docker" >&2
  exit 1
fi
systemctl enable --now docker

log "atualizações automáticas de segurança"
install -d -m 0755 "$RAIZ/etc/apt/apt.conf.d"
cat > "$RAIZ/etc/apt/apt.conf.d/20auto-upgrades" <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF

# --- usuário -----------------------------------------------------------------------------
if ! getent passwd "$USUARIO" >/dev/null; then
  log "criando usuário de sistema $USUARIO"
  useradd --system --create-home --home-dir "/home/$USUARIO" --shell /bin/bash "$USUARIO"
fi
usermod -aG docker "$USUARIO"

# --- /opt/ayanami --------------------------------------------------------------------------
if [ ! -d "$AYANAMI_DIR/.git" ]; then
  if [ -z "$REPO_URL" ]; then
    echo "$AYANAMI_DIR ainda não é um clone: passe --repo <url>" >&2
    exit 2
  fi
  log "clonando o repo em $AYANAMI_DIR ($REF)"
  install -d -m 0755 "$(dirname "$AYANAMI_DIR")"
  git clone --branch "$REF" "$REPO_URL" "$AYANAMI_DIR"
fi

install -d -m 0750 "$AYANAMI_DIR/dados" "$AYANAMI_DIR/dados/entrada" "$AYANAMI_DIR/dados/tmp" \
  "$AYANAMI_DIR/dados/restic-cache"

# .env só com segredos (spec §9.1), 0600; aqui só garante o arquivo e o DOCKER_GID.
ENV_ARQ="$AYANAMI_DIR/.env"
if [ ! -e "$ENV_ARQ" ]; then
  log "criando $ENV_ARQ vazio (0600); preencha a partir de deploy/ayanami/env.example"
  install -m 0600 /dev/null "$ENV_ARQ"
fi
chmod 0600 "$ENV_ARQ"

DOCKER_GID="$(getent group docker | cut -d: -f3)"
if [ -z "$DOCKER_GID" ]; then
  echo "grupo docker não encontrado" >&2
  exit 1
fi
if grep -q '^DOCKER_GID=' "$ENV_ARQ"; then
  sed -i "s/^DOCKER_GID=.*/DOCKER_GID=$DOCKER_GID/" "$ENV_ARQ"
else
  echo "DOCKER_GID=$DOCKER_GID" >> "$ENV_ARQ"
fi
log "DOCKER_GID=$DOCKER_GID no .env"

# O compose.yml fica em deploy/ayanami/ (build: ../..) e lê .env, ayanami.toml e dados/ ao lado
# dele: links para os arquivos reais em /opt/ayanami (fora do git).
DEPLOY="$AYANAMI_DIR/deploy/ayanami"
for nome in .env ayanami.toml dados; do
  ln -sfn "$AYANAMI_DIR/$nome" "$DEPLOY/$nome"
done
EXCLUDE="$AYANAMI_DIR/.git/info/exclude"
for padrao in /.env /ayanami.toml /dados/ /deploy/ayanami/ayanami.toml; do
  grep -qxF "$padrao" "$EXCLUDE" 2>/dev/null || echo "$padrao" >> "$EXCLUDE"
done
if [ ! -e "$AYANAMI_DIR/ayanami.toml" ]; then
  log "falta $AYANAMI_DIR/ayanami.toml (copie de deploy/ayanami/ayanami.example.toml e ajuste)"
fi

chown -R "$USUARIO:$USUARIO" "$AYANAMI_DIR"

# --- SSH só por chave ------------------------------------------------------------------------
tem_chave=0
for arq in "$RAIZ"/root/.ssh/authorized_keys "$RAIZ"/home/*/.ssh/authorized_keys; do
  if [ -s "$arq" ]; then tem_chave=1; fi
done
if [ "$tem_chave" -eq 1 ]; then
  install -d -m 0755 "$SSHD_DIR"
  printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\n' > "$SSHD_DIR/50-ayanami.conf"
  if sshd -t; then
    systemctl reload ssh 2>/dev/null || systemctl reload sshd
    log "SSH só por chave"
  else
    rm -f "$SSHD_DIR/50-ayanami.conf"
    echo "sshd -t falhou; config de SSH desfeita" >&2
    exit 1
  fi
else
  log "AVISO: nenhuma chave em authorized_keys; senha do SSH continua ligada (ponha a chave e rode de novo)"
fi

log "pronto. Próximos: ufw.sh, tailscale.sh; depois .env + ayanami.toml e deploy.sh (runbook)"
