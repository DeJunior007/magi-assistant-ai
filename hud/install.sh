#!/usr/bin/env bash
# Instala o MAGI Gamer (HUD do segundo monitor) e a Magui (satélite, núcleo, notícias e Postgres)
# a partir deste repositório. Idempotente: pode rodar de novo depois de um git pull ou depois de
# mover o repositório (as units são geradas com o caminho real dele).
#
# Uso: hud/install.sh [--start] [--dry-run] [--no-hud]
#   --start     inicia (ou reinicia) os serviços da Magui depois de habilitá-los
#   --dry-run   só mostra o que faria na parte da Magui (não escreve nada; pula o HUD)
#   --no-hud    instala só a Magui
#   --render-units DIR   só gera as units em DIR e sai (usado nos testes e no systemd-analyze)
set -euo pipefail

START=0
DRY=0
HUD=1
RENDER_ONLY=""
while [ $# -gt 0 ]; do
    case "$1" in
        --start) START=1 ;;
        --dry-run) DRY=1 ;;
        --no-hud) HUD=0 ;;
        --render-units) RENDER_ONLY="${2:?--render-units precisa de um diretório}"; shift ;;
        -h|--help) sed -n '2,10p' "${BASH_SOURCE[0]}"; exit 0 ;;
        *) echo "opção desconhecida: $1" >&2; exit 2 ;;
    esac
    shift
done

# pwd -P resolve links: rodar pelo ~/.local/share/gamerhud ainda acha o repositório real.
HUD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
REPO_DIR="$(cd "$HUD_DIR/.." && pwd -P)"
SYS="$HUD_DIR/system"
SHARE="$HOME/.local/share"
LINK="$SHARE/gamerhud"

render() {  # copia um template trocando @HOME@ pela home atual
    mkdir -p "$(dirname "$2")"
    sed "s|@HOME@|$HOME|g" "$1" > "$2"
}

install_hud() {
echo "== código: $LINK -> $HUD_DIR"
if [ -L "$LINK" ]; then
    ln -sfn "$HUD_DIR" "$LINK"
elif [ -e "$LINK" ]; then
    echo "   $LINK existe e não é link; mova ou apague antes de instalar" >&2
    exit 1
else
    ln -s "$HUD_DIR" "$LINK"
fi
chmod +x "$HUD_DIR"/magi-view.py "$HUD_DIR"/steam-mangohud.sh

echo "== comando, menu e autostart"
render "$SYS/bin/gamerhud" "$HOME/.local/bin/gamerhud"
chmod +x "$HOME/.local/bin/gamerhud"
render "$SYS/applications/gamerhud.desktop" "$SHARE/applications/gamerhud.desktop"
render "$SYS/applications/magi-view.desktop" "$SHARE/applications/magi-view.desktop"
render "$SYS/autostart/gamerhud-watch.desktop" "$HOME/.config/autostart/gamerhud-watch.desktop"

echo "== Steam aberta pelo MangoHud (FPS em todos os jogos)"
if [ -f /usr/share/applications/steam.desktop ]; then
    sed "s|^Exec=/usr/bin/steam|Exec=$LINK/steam-mangohud.sh|" \
        /usr/share/applications/steam.desktop > "$SHARE/applications/steam.desktop"
fi

echo "== MangoHud invisível + log de FPS"
render "$SYS/mangohud/MangoHud.conf" "$HOME/.config/MangoHud/MangoHud.conf"
render "$SYS/environment.d/mangohud.conf" "$HOME/.config/environment.d/mangohud.conf"

echo "== ícones"
python3 "$HUD_DIR/gamerhud.py" --install-icons

echo "== regra do KWin (abaixo das janelas, sem foco, fora do Alt+Tab)"
F="$HOME/.config/kwinrulesrc"
RULE=gamerhud-rule
rules="$(kreadconfig6 --file "$F" --group General --key rules 2>/dev/null || true)"
case ",$rules," in
    *",$RULE,"*) ;;
    *)
        rules="${rules:+$rules,}$RULE"
        kwriteconfig6 --file "$F" --group General --key rules "$rules"
        kwriteconfig6 --file "$F" --group General --key count "$(tr ',' '\n' <<<"$rules" | grep -c .)"
        ;;
esac
while IFS='=' read -r key value; do
    kwriteconfig6 --file "$F" --group "$RULE" --key "$key" "$value"
done <<'EOF'
Description=MAGI Gamer (fica abaixo das janelas no monitor secundario)
acceptfocus=false
acceptfocusrule=2
below=true
belowrule=2
skippager=true
skippagerrule=2
skipswitcher=true
skipswitcherrule=2
types=1
wmclass=gamerhud
wmclassmatch=1
EOF
dbus-send --session --type=method_call --dest=org.kde.KWin /KWin org.kde.KWin.reconfigure || true

echo "== atalho Meta+M (tela de ociosidade)"
ID='array:string:"magi-view.desktop","_launch","MAGI Gamer: alternar tela de ociosidade","Alternar tela de ociosidade"'
eval dbus-send --session --print-reply --dest=org.kde.kglobalaccel /kglobalaccel \
    org.kde.KGlobalAccel.doRegister "$ID" >/dev/null || true
eval dbus-send --session --print-reply --dest=org.kde.kglobalaccel /kglobalaccel \
    org.kde.KGlobalAccel.setShortcut "$ID" array:int32:268435533 uint32:2 >/dev/null || true

kbuildsycoca6 >/dev/null 2>&1 || true
}

# ---------------------------------------------------------------- Magui (tarefa 1.17)
UNITS_SRC="$REPO_DIR/deploy/systemd"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
MAGI_CONF="${XDG_CONFIG_HOME:-$HOME/.config}/magi/config.toml"
SERVICES=(magi-satellite.service magi-core.service)
UNIT_FILES=(magi-satellite.service magi-core.service magi-news.service magi-news.timer)

run() {  # executa, ou só mostra no --dry-run
    if [ "$DRY" = 1 ]; then
        printf '+'; printf ' %q' "$@"; printf '\n'
    else
        "$@"
    fi
}

render_units() {  # gera as units em $1 trocando @REPO@ pelo caminho real do repositório
    case "$REPO_DIR" in
        *[\"\\%\|\&\$\`]* | *$'\n'*)
            echo "caminho do repositório com caractere não suportado nas units: $REPO_DIR" >&2
            exit 1 ;;
    esac
    mkdir -p "$1"
    local u
    for u in "${UNIT_FILES[@]}"; do
        sed "s|@REPO@|$REPO_DIR|g" "$UNITS_SRC/$u" > "$1/$u"
    done
}

install_magui() {
    echo "== Magui: dependências (uv sync em $REPO_DIR)"
    local uv
    uv="$(command -v uv || echo "$HOME/.local/bin/uv")"
    run "$uv" sync --frozen --project "$REPO_DIR"

    echo "== Magui: units systemd --user em $UNIT_DIR"
    if [ "$DRY" = 1 ]; then
        local u
        for u in "${UNIT_FILES[@]}"; do
            echo "+ gera $UNIT_DIR/$u (@REPO@ -> $REPO_DIR)"
        done
    else
        render_units "$UNIT_DIR"
    fi
    run systemctl --user daemon-reload
    run systemctl --user enable "${SERVICES[@]}" magi-news.timer

    echo "== Magui: Postgres (container magi-pg)"
    # Só sobe se não estiver rodando; nunca derruba nem remove (o banco é compartilhado).
    local running
    running="$(docker inspect -f '{{.State.Running}}' magi-pg 2>/dev/null || true)"
    if [ "$running" = true ]; then
        echo "   magi-pg já está rodando"
    elif command -v docker >/dev/null 2>&1; then
        run docker compose -f "$REPO_DIR/deploy/docker-compose.yml" up -d
    else
        echo "   docker não encontrado; suba o Postgres depois:" \
            "docker compose -f $REPO_DIR/deploy/docker-compose.yml up -d" >&2
    fi

    echo "== Magui: config em $MAGI_CONF"
    if [ -e "$MAGI_CONF" ]; then
        echo "   já existe; mantida"
    else
        run mkdir -p "$(dirname "$MAGI_CONF")"
        run cp "$REPO_DIR/config.example.toml" "$MAGI_CONF"
    fi

    if [ "$START" = 1 ]; then
        echo "== Magui: iniciando serviços"
        run systemctl --user restart "${SERVICES[@]}"
        run systemctl --user start magi-news.timer
    fi
}

if [ -n "$RENDER_ONLY" ]; then
    render_units "$RENDER_ONLY"
    exit 0
fi

if [ "$HUD" = 1 ]; then
    if [ "$DRY" = 1 ]; then
        echo "== HUD: pulado no --dry-run"
    else
        install_hud
    fi
fi
install_magui

echo
if [ "$DRY" = 1 ]; then
    echo "Dry-run: nada foi alterado."
    exit 0
fi
echo "Pronto."
if [ "$HUD" = 1 ]; then
    echo "Faça logout/login uma vez para o MANGOHUD=1 valer em toda a sessão."
    echo "Abra a Steam pelo menu para os jogos herdarem o MangoHud."
fi
if [ "$START" = 1 ]; then
    echo "Serviços da Magui iniciados: systemctl --user status ${SERVICES[*]}"
else
    echo "Serviços da Magui habilitados; sobem no próximo login (ou rode de novo com --start)."
fi
