"""O2.1: comando, autostart e regra do KWin do overlay (CA-O7, CA-O8).

Nada ao vivo: `HOME` falso e `kwriteconfig6`/`kreadconfig6` trocados por scripts que gravam num
arquivo de texto (uma linha `grupo<TAB>chave<TAB>valor`). Nenhum D-Bus.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

HUD = Path(__file__).resolve().parents[2] / "hud"
SYS = HUD / "system"

FAKE_WRITE = r"""#!/usr/bin/env bash
# kwriteconfig6 --file F --group G --key K VALUE
while [ $# -gt 1 ]; do
    case "$1" in --file) shift 2 ;; --group) g="$2"; shift 2 ;; --key) k="$2"; shift 2 ;; *) break ;; esac
done
db="$FAKE_KCONFIG"; touch "$db"
awk -v g="$g" -v k="$k" -v v="$1" 'BEGIN{FS=OFS="\t"} $1==g && $2==k {next} {print} END{print g,k,v}' \
    "$db" > "$db.tmp" && mv "$db.tmp" "$db"
"""

FAKE_READ = r"""#!/usr/bin/env bash
while [ $# -gt 0 ]; do
    case "$1" in --file) shift 2 ;; --group) g="$2"; shift 2 ;; --key) k="$2"; shift 2 ;; *) shift ;; esac
done
[ -f "$FAKE_KCONFIG" ] || exit 0
awk -v g="$g" -v k="$k" 'BEGIN{FS="\t"} $1==g && $2==k {print $3}' "$FAKE_KCONFIG"
"""


@pytest.fixture
def ambiente(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    for nome, corpo in (("kwriteconfig6", FAKE_WRITE), ("kreadconfig6", FAKE_READ)):
        (bin_ / nome).write_text(corpo)
        (bin_ / nome).chmod(0o755)
    db = tmp_path / "kconfig.tsv"
    env = {
        "HOME": str(home),
        "PATH": f"{bin_}:{os.environ['PATH']}",
        "FAKE_KCONFIG": str(db),
        "MAGI_OVERLAY_TELA": "0,0,2560,1440",
        "QT_QPA_PLATFORM": "offscreen",
    }
    return env, db


def _rodar(env):
    r = subprocess.run(
        ["bash", str(HUD / "install.sh"), "--overlay-rule"],
        env=env, capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, r.stderr
    return r


def _ler(db: Path) -> dict[tuple[str, str], str]:
    out = {}
    for linha in db.read_text().splitlines():
        g, k, v = linha.split("\t", 2)
        assert (g, k) not in out, f"chave duplicada {g}/{k}"
        out[(g, k)] = v
    return out


def test_bash_n_limpo():
    assert subprocess.run(["bash", "-n", str(HUD / "install.sh")]).returncode == 0


def test_regra_nova_com_posicao_d6(ambiente):
    env, db = ambiente
    _rodar(env)
    kv = _ler(db)
    R = "condessa-overlay-rule"
    assert kv[("General", "rules")] == R
    assert kv[("General", "count")] == "1"
    assert kv[(R, "wmclass")] == "condessa-overlay"
    assert kv[(R, "above")] == "true"
    assert kv[(R, "skipswitcher")] == "true"
    assert kv[(R, "positionrule")] == "4"
    # D6: canto superior direito do principal, margem 24 px
    from PySide6.QtCore import QRect
    from wired.overlay import Config, canto_para_posicao

    p = canto_para_posicao(Config(), QRect(0, 0, 2560, 1440))
    assert kv[(R, "position")] == f"{p.x()},{p.y()}"
    assert p.y() == 24 and p.x() > 1280


def test_ca_o8_segunda_rodada_nao_duplica_nem_sobrescreve(ambiente):
    env, db = ambiente
    # já havia a regra do HUD
    db.write_text("General\trules\tgamerhud-rule\nGeneral\tcount\t1\n")
    _rodar(env)
    R = "condessa-overlay-rule"
    assert _ler(db)[("General", "rules")] == f"gamerhud-rule,{R}"
    assert _ler(db)[("General", "count")] == "2"
    # o KWin "lembrou" outra posição; reinstalar (com outra tela) não apaga
    linhas = [
        f"{R}\tposition\t100,200" if ln.startswith(f"{R}\tposition\t") else ln
        for ln in db.read_text().splitlines()
    ]
    db.write_text("\n".join(linhas) + "\n")
    _rodar({**env, "MAGI_OVERLAY_TELA": "0,0,1920,1080"})
    kv = _ler(db)
    assert kv[("General", "rules")] == f"gamerhud-rule,{R}"
    assert kv[("General", "count")] == "2"
    assert kv[(R, "position")] == "100,200"


def test_ca_o7_sem_dbus_do_kwin():
    proibidos = ("qdbus", "gdbus", "kglobalaccel", "org.kde.KWin")
    alvos = [HUD / "wired" / "overlay.py", SYS / "bin" / "condessa-overlay"]
    if (HUD / "condessa_overlay.py").exists():  # O1.3
        alvos.append(HUD / "condessa_overlay.py")
    for arq in alvos:
        texto = arq.read_text().lower()
        for p in proibidos:
            assert p.lower() not in texto, f"{p} em {arq.name}"
    install = (HUD / "install.sh").read_text()
    inicio = install.index("overlay_posicao() {")
    bloco = install[inicio:install.index("install_hud() {")]
    for p in proibidos + ("dbus-send",):
        assert p.lower() not in bloco.lower()


def test_templates(tmp_path):
    bin_ = (SYS / "bin" / "condessa-overlay").read_text()
    assert "^python3 .*/condessa_overlay\\.py$" in bin_
    assert os.access(SYS / "bin" / "condessa-overlay", os.X_OK)
    auto = (SYS / "autostart" / "condessa-overlay.desktop").read_text()
    assert "Exec=python3 @HOME@/.local/share/gamerhud/condessa_overlay.py" in auto
    assert "X-KDE-autostart-after=panel" in auto and "NoDisplay=true" in auto
    menu = (SYS / "applications" / "condessa-overlay.desktop").read_text()
    assert "Name=Condessa (overlay)" in menu
