#!/usr/bin/env bash
# Instala o MAGI Gamer (HUD do segundo monitor) a partir deste repositório.
# Idempotente: pode rodar de novo depois de um git pull.
set -euo pipefail

HUD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYS="$HUD_DIR/system"
SHARE="$HOME/.local/share"
LINK="$SHARE/gamerhud"

render() {  # copia um template trocando @HOME@ pela home atual
    mkdir -p "$(dirname "$2")"
    sed "s|@HOME@|$HOME|g" "$1" > "$2"
}

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
echo
echo "Pronto. Faça logout/login uma vez para o MANGOHUD=1 valer em toda a sessão."
echo "Abra a Steam pelo menu para os jogos herdarem o MangoHud."
