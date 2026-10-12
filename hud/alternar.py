#!/usr/bin/env python3
"""Atalhos do HUD e do overlay da Condessa (O4.3). Leve de propósito (sem Qt): roda a cada tecla.

- ``Meta+M`` (``magi-view.py``): HUD fechado → abre o HUD; aberto → alterna painel completo ↔
  tela de ociosidade (como antes).
- ``Meta+O`` (``condessa-alternar``): HUD aberto → fecha o HUD e deixa o overlay ligado (uma
  instância só); HUD fechado → liga/desliga o overlay.

O overlay já se esconde sozinho com o HUD aberto (trava ``hud.lock``, D2): aqui só se liga/desliga
o processo. As decisões são funções puras; o resto recebe comandos injetáveis (testes sem processo
real)."""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

HOME = Path.home()
HUD_LOCK = HOME / ".cache/gamerhud/hud.lock"
SETTINGS = HOME / ".config/gamerhud/settings.json"
BIN = HOME / ".local/bin"
HUD_PATTERN = r"^python3 .*/gamerhud\.py$"  # mesmos padrões de hud/system/bin/*
OVERLAY_PATTERN = r"^python3 .*/condessa_overlay\.py$"

ABRIR_HUD = "abrir_hud"
FECHAR_HUD = "fechar_hud"
ALTERNAR_VIEW = "alternar_view"
LIGAR_OVERLAY = "ligar_overlay"
DESLIGAR_OVERLAY = "desligar_overlay"


def decidir_meta_m(hud: bool) -> tuple[str, ...]:
    """Meta+M: HUD fechado abre o HUD; aberto alterna a tela de ociosidade."""
    return (ALTERNAR_VIEW,) if hud else (ABRIR_HUD,)


def decidir_alternar(hud: bool, overlay: bool) -> tuple[str, ...]:
    """Meta+O: com o HUD aberto, fecha o HUD e garante o overlay (se o processo já roda, escondido
    pelo HUD, ele volta sozinho: não liga outro); com o HUD fechado, liga/desliga o overlay."""
    if hud:
        return (FECHAR_HUD,) if overlay else (FECHAR_HUD, LIGAR_OVERLAY)
    return (DESLIGAR_OVERLAY,) if overlay else (LIGAR_OVERLAY,)


def trava_ocupada(lock: Path) -> bool:
    """Mesma leitura de ``wired.overlay.hud_aberto`` (sem importar o Qt): trava presa = HUD vivo."""
    try:
        fd = os.open(lock, os.O_RDONLY)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    except OSError:
        return False
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


Rodar = Callable[[Sequence[str]], int]


def _rodar(cmd: Sequence[str]) -> int:
    return subprocess.run(list(cmd), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode


def processo_vivo(padrao: str, rodar: Rodar = _rodar) -> bool:
    return rodar(["pgrep", "-f", padrao]) == 0


def hud_aberto(rodar: Rodar = _rodar, lock: Path = HUD_LOCK) -> bool:
    """HUD aberto = trava presa ou processo vivo (o processo recém-aberto ainda sem a trava conta)."""
    return trava_ocupada(lock) or processo_vivo(HUD_PATTERN, rodar)


def alternar_view(caminho: Path = SETTINGS) -> str:
    """Troca ``view`` no settings.json do HUD (o HUD aberto percebe em ~0,3 s). Devolve a nova."""
    try:
        cfg = json.loads(caminho.read_text())
        if not isinstance(cfg, dict):
            cfg = {}
    except (OSError, ValueError):
        cfg = {}
    cfg["view"] = "full" if cfg.get("view", "full") == "idle" else "idle"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(cfg))
    return cfg["view"]


def executar(
    acoes: Sequence[str], rodar: Rodar = _rodar, bin_dir: Path = BIN, settings: Path = SETTINGS
) -> None:
    """Aplica as ações. HUD e overlay pelos mesmos comandos do menu (``gamerhud`` e
    ``condessa-overlay``, que alternam): o ``gamerhud`` fecha com SIGTERM (o HUD restaura o papel
    de parede e solta a trava), espera sair e roda o ``--restore`` de segurança."""
    for acao in acoes:
        if acao in (ABRIR_HUD, FECHAR_HUD):
            rodar([str(bin_dir / "gamerhud")])
        elif acao in (LIGAR_OVERLAY, DESLIGAR_OVERLAY):
            rodar([str(bin_dir / "condessa-overlay")])
        elif acao == ALTERNAR_VIEW:
            alternar_view(settings)
        else:
            raise ValueError(f"ação desconhecida: {acao}")


def meta_m(rodar: Rodar = _rodar, lock: Path = HUD_LOCK, bin_dir: Path = BIN,
           settings: Path = SETTINGS) -> tuple[str, ...]:
    acoes = decidir_meta_m(hud_aberto(rodar, lock))
    executar(acoes, rodar, bin_dir, settings)
    return acoes


def condessa_alternar(rodar: Rodar = _rodar, lock: Path = HUD_LOCK, bin_dir: Path = BIN,
                      settings: Path = SETTINGS) -> tuple[str, ...]:
    acoes = decidir_alternar(hud_aberto(rodar, lock), processo_vivo(OVERLAY_PATTERN, rodar))
    executar(acoes, rodar, bin_dir, settings)
    return acoes


if __name__ == "__main__":
    if sys.argv[1:] == ["--meta-m"]:
        meta_m()
    else:
        condessa_alternar()
