"""O4.3: atalhos Meta+M / Meta+O (HUD ↔ overlay) sem processo real, sem pkill, sem D-Bus."""

import fcntl
import json
from pathlib import Path

import alternar as al
import pytest

REPO = Path(__file__).resolve().parents[2]


class Falso:
    """Roda comandos de mentira: ``pgrep`` responde pelo conjunto ``vivos``; o resto só registra."""

    def __init__(self, *vivos: str) -> None:
        self.vivos = set(vivos)
        self.cmds: list[list[str]] = []

    def __call__(self, cmd):
        cmd = list(cmd)
        self.cmds.append(cmd)
        if cmd[0] == "pgrep":
            return 0 if cmd[-1] in self.vivos else 1
        return 0

    def lancados(self) -> list[str]:
        return [Path(c[0]).name for c in self.cmds if c[0] != "pgrep"]


@pytest.mark.parametrize(
    ("hud", "overlay", "esperado"),
    [
        (True, False, (al.FECHAR_HUD, al.LIGAR_OVERLAY)),
        (True, True, (al.FECHAR_HUD,)),  # overlay já vivo (escondido): volta sozinho, sem outro
        (False, True, (al.DESLIGAR_OVERLAY,)),
        (False, False, (al.LIGAR_OVERLAY,)),
    ],
)
def test_decidir_alternar(hud, overlay, esperado):
    assert al.decidir_alternar(hud, overlay) == esperado


def test_decidir_meta_m():
    assert al.decidir_meta_m(False) == (al.ABRIR_HUD,)
    assert al.decidir_meta_m(True) == (al.ALTERNAR_VIEW,)


def test_trava_ocupada(tmp_path):
    lock = tmp_path / "hud.lock"
    assert not al.trava_ocupada(lock)  # sem arquivo = HUD nunca abriu
    with open(lock, "w") as f:
        assert not al.trava_ocupada(lock)
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert al.trava_ocupada(lock)


def test_hud_aberto_pelo_processo_sem_trava(tmp_path):
    assert al.hud_aberto(Falso(al.HUD_PATTERN), tmp_path / "x.lock")
    assert not al.hud_aberto(Falso(), tmp_path / "x.lock")


def _kw(tmp_path):
    return {"lock": tmp_path / "hud.lock", "bin_dir": tmp_path / "bin", "settings": tmp_path / "s.json"}


def test_meta_m_hud_fechado_abre_o_hud(tmp_path):
    rodar = Falso()
    assert al.meta_m(rodar, **_kw(tmp_path)) == (al.ABRIR_HUD,)
    assert rodar.lancados() == ["gamerhud"]
    assert not (tmp_path / "s.json").exists()


def test_meta_m_hud_aberto_alterna_a_view(tmp_path):
    rodar = Falso(al.HUD_PATTERN)
    settings = tmp_path / "s.json"
    settings.write_text(json.dumps({"ui": "wired", "view": "full"}))
    assert al.meta_m(rodar, **_kw(tmp_path)) == (al.ALTERNAR_VIEW,)
    assert rodar.lancados() == []
    assert json.loads(settings.read_text()) == {"ui": "wired", "view": "idle"}
    al.meta_m(rodar, **_kw(tmp_path))
    assert json.loads(settings.read_text())["view"] == "full"


def test_alternar_view_settings_quebrado(tmp_path):
    s = tmp_path / "novo" / "s.json"
    assert al.alternar_view(s) == "idle"
    s.write_text("[1, 2]")
    assert al.alternar_view(s) == "idle"


def test_condessa_alternar_hud_aberto_fecha_hud_e_liga_overlay(tmp_path):
    rodar = Falso(al.HUD_PATTERN)
    al.condessa_alternar(rodar, **_kw(tmp_path))
    assert rodar.lancados() == ["gamerhud", "condessa-overlay"]
    assert all(c[0] == "pgrep" or c[0].startswith(str(tmp_path)) for c in rodar.cmds)


def test_condessa_alternar_hud_aberto_overlay_vivo_nao_duplica(tmp_path):
    rodar = Falso(al.HUD_PATTERN, al.OVERLAY_PATTERN)
    al.condessa_alternar(rodar, **_kw(tmp_path))
    assert rodar.lancados() == ["gamerhud"]


@pytest.mark.parametrize("vivo", [True, False])
def test_condessa_alternar_hud_fechado_alterna_overlay(tmp_path, vivo):
    rodar = Falso(*([al.OVERLAY_PATTERN] if vivo else []))
    acoes = al.condessa_alternar(rodar, **_kw(tmp_path))
    assert acoes == ((al.DESLIGAR_OVERLAY,) if vivo else (al.LIGAR_OVERLAY,))
    assert rodar.lancados() == ["condessa-overlay"]


def test_padroes_iguais_aos_comandos():
    bin_ = REPO / "hud/system/bin"
    assert f"PATTERN='{al.HUD_PATTERN}'" in (bin_ / "gamerhud").read_text()
    assert f"PATTERN='{al.OVERLAY_PATTERN}'" in (bin_ / "condessa-overlay").read_text()


def test_desktop_e_install_sem_dbus_novo():
    desk = (REPO / "hud/system/applications/condessa-alternar.desktop").read_text()
    assert "X-KDE-Shortcuts=Meta+O" in desk.splitlines()
    assert "Exec=@HOME@/.local/bin/condessa-alternar" in desk.splitlines()
    inst = (REPO / "hud/install.sh").read_text()
    assert 'render "$SYS/bin/condessa-alternar"' in inst
    assert 'render "$SYS/applications/condessa-alternar.desktop"' in inst
    assert inst.count("dbus-send") == 3  # só os antigos (KWin reconfigure + 2 do Meta+M)
    assert "alternar.py" in (REPO / "hud/system/bin/condessa-alternar").read_text()


# O4.6: o autostart do KDE sobe o overlay como ``/usr/bin/python3 …``; o padrão (ERE do pgrep,
# compatível com ``re``) tem que casar qualquer python3 e não o pgrep/bash que carregam o padrão.
OVERLAY_PY = "/home/pedrojr/.local/share/gamerhud/condessa_overlay.py"
HUD_PY = "/home/pedrojr/.local/share/gamerhud/gamerhud.py"


@pytest.mark.parametrize("py", ["python3", "/usr/bin/python3", "python3.12", "/usr/bin/python3.12"])
def test_padroes_casam_qualquer_python3(py):
    import re

    assert re.search(al.OVERLAY_PATTERN, f"{py} {OVERLAY_PY}")
    assert re.search(al.HUD_PATTERN, f"{py} {HUD_PY}")
    assert not re.search(al.OVERLAY_PATTERN, f"{py} {HUD_PY}")
    assert not re.search(al.HUD_PATTERN, f"{py} {OVERLAY_PY}")


@pytest.mark.parametrize(
    "linha",
    [
        f"pgrep -f {al.OVERLAY_PATTERN}",
        f"pkill -f {al.OVERLAY_PATTERN}",
        f"bash -c pgrep -f '{al.OVERLAY_PATTERN}'",
        f"/usr/bin/python2 {OVERLAY_PY}",
        f"python3 {OVERLAY_PY} --debug",
        f"vim {OVERLAY_PY}",
    ],
)
def test_padrao_nao_casa_o_proprio_pgrep_nem_outros(linha):
    import re

    assert not re.search(al.OVERLAY_PATTERN, linha)
