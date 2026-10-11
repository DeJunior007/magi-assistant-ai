"""Overlay da Condessa — parte pura (sem janela): configuração, posição, decisões e gestos.

Contratos do ``specs/condessa-overlay/spec.md`` §1–§3. A janela (``hud/condessa_overlay.py``) só
aplica o que sai daqui. Decisões do Pedro de 2026-10-10: com o HUD principal aberto o overlay se
esconde (D2); em jogo vai para o monitor oposto ao do jogo, ou some com um monitor só (D3); nasce
no canto superior direito do monitor principal, margem 24 px (D6).

Os caminhos são lidos na hora da chamada (argumento ``None`` = constante do módulo), para os
testes trocarem as constantes com ``monkeypatch``. Importa só tipos de ``QtCore``/``QtGui``: nada
aqui precisa de ``QApplication``.
"""

from __future__ import annotations

import logging
import os
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, fields
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QImage

if TYPE_CHECKING:
    from .main_screen import Snapshot

log = logging.getLogger(__name__)

CONFIG_FILE = Path.home() / ".config/magi/overlay.toml"
LOCK_FILE = Path.home() / ".cache/gamerhud/overlay.lock"
HUD_LOCK = Path.home() / ".cache/gamerhud/hud.lock"
REGISTRO_FILE = Path.home() / ".local/state/magi/reacoes-overlay.jsonl"
ATIVIDADE_FILE = Path.home() / ".local/state/magi/atividade-overlay.json"

TAMANHO_MIN, TAMANHO_MAX = 120, 480
MARGEM_MAX = 400
ALTURA_FATOR = 1.15  # o retrato é TALL: quadro = tamanho × tamanho·1,15 (spec §5)

CANTOS = ("sup_esq", "sup_dir", "inf_esq", "inf_dir")
RENDERERS = ("cpu", "gl")
EM_JOGO = ("oposto", "esconde", "fica")  # D3
COM_HUD = ("esconde", "independente")  # D2


@dataclass
class Config:
    """``~/.config/magi/overlay.toml`` (tabela ``[overlay]``). Padrões = decisões de 2026-10-10."""

    tamanho: int = 220  # lado do quadro em px lógicos, preso em 120..480
    tela: str | None = None  # QScreen.name(); None = principal
    canto: str = "sup_dir"  # sup_esq | sup_dir | inf_esq | inf_dir      (D6)
    margem: int = 24  # px da borda da tela até o quadro                (D6)
    fundo: bool = False  # True = desenha o fundo de hexágonos do retrato
    renderer: str = "cpu"  # "cpu" | "gl" (sobrepõe o portrait.toml só no overlay)
    em_jogo: str = "oposto"  # "oposto" | "esconde" | "fica"            (D3)
    tela_jogo: str | None = None  # monitor do jogo; None = principal     (D3)
    com_hud: str = "esconde"  # "esconde" | "independente"              (D2)
    ligado: bool = True  # False = o autostart sai na hora
    x: int | None = None  # só na recaída XWayland (D4)
    y: int | None = None

    @classmethod
    def ler(cls, caminho: Path | None = None) -> Config:
        """Ausente/ilegível → padrões; valor inválido → padrão daquela chave; desconhecida → ignorada."""
        caminho = CONFIG_FILE if caminho is None else caminho
        cfg = cls()
        try:
            bruto = tomllib.loads(caminho.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cfg
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
            log.warning("overlay.toml ilegível (%s): usando os padrões", e)
            return cfg
        dados = bruto.get("overlay", bruto)
        if not isinstance(dados, dict):
            return cfg
        for chave, valor in dados.items():
            if chave in _VALIDA:
                ok, limpo = _VALIDA[chave](valor)
                if ok:
                    setattr(cfg, chave, limpo)
                else:
                    log.warning("overlay.toml: %s = %r inválido, usando o padrão", chave, valor)
        return cfg

    def gravar(self, caminho: Path | None = None) -> None:
        """Escrita atômica (tmp + rename) da tabela ``[overlay]``; chaves ``None`` ficam de fora."""
        caminho = CONFIG_FILE if caminho is None else caminho
        linhas = ["[overlay]"]
        for f in fields(self):
            valor = getattr(self, f.name)
            if valor is not None:
                linhas.append(f"{f.name} = {_toml(valor)}")
        caminho.parent.mkdir(parents=True, exist_ok=True)
        tmp = caminho.with_name(caminho.name + ".tmp")
        tmp.write_text("\n".join(linhas) + "\n", encoding="utf-8")
        os.replace(tmp, caminho)


def _toml(valor: Any) -> str:
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if isinstance(valor, int):
        return str(valor)
    texto = str(valor).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{texto}"'


def _inteiro(valor: Any) -> bool:
    return isinstance(valor, int) and not isinstance(valor, bool)


def _escolha(opcoes: tuple[str, ...]) -> Callable[[Any], tuple[bool, Any]]:
    return lambda v: (v in opcoes, v)


def _texto_ou_nada(v: Any) -> tuple[bool, Any]:
    return (isinstance(v, str) and v.strip() != "", v.strip() if isinstance(v, str) else v)


_VALIDA: dict[str, Callable[[Any], tuple[bool, Any]]] = {
    "tamanho": lambda v: (_inteiro(v), min(TAMANHO_MAX, max(TAMANHO_MIN, v)) if _inteiro(v) else v),
    "tela": _texto_ou_nada,
    "canto": _escolha(CANTOS),
    "margem": lambda v: (_inteiro(v), min(MARGEM_MAX, max(0, v)) if _inteiro(v) else v),
    "fundo": lambda v: (isinstance(v, bool), v),
    "renderer": _escolha(RENDERERS),
    "em_jogo": _escolha(EM_JOGO),
    "tela_jogo": _texto_ou_nada,
    "com_hud": _escolha(COM_HUD),
    "ligado": lambda v: (isinstance(v, bool), v),
    "x": lambda v: (_inteiro(v), v),
    "y": lambda v: (_inteiro(v), v),
}


def tamanho_quadro(cfg: Config) -> tuple[int, int]:
    """Largura e altura do quadro da janela (px lógicos)."""
    return cfg.tamanho, round(cfg.tamanho * ALTURA_FATOR)


def canto_para_posicao(cfg: Config, tela: QRect) -> QPoint:
    """Topo-esquerdo do quadro no ``canto`` de ``tela`` (geometria do monitor), a ``margem`` px."""
    w, h = tamanho_quadro(cfg)
    m = cfg.margem
    x = tela.x() + m if cfg.canto.endswith("esq") else tela.x() + tela.width() - m - w
    y = tela.y() + m if cfg.canto.startswith("sup") else tela.y() + tela.height() - m - h
    return QPoint(x, y)


@dataclass(frozen=True)
class Lugar:
    """O que a janela faz agora (D2/D3). A janela só aplica."""

    visivel: bool
    tela: str | None = None  # monitor onde mostrar; None = principal
    motivo: str = ""  # "normal" | "hud" | "jogo" | "jogo_oposto"


def decidir_lugar(
    cfg: Config, telas: Sequence[str], principal: str | None, gaming: bool, hud: bool
) -> Lugar:
    """Junta D2 (HUD aberto → esconde, ganha do jogo) e D3 (jogo → monitor oposto; um só → some).

    ``telas`` = nomes dos monitores ligados (``QScreen.name()``); ``principal`` = o primário.
    """
    if hud and cfg.com_hud == "esconde":
        return Lugar(False, motivo="hud")
    if gaming and cfg.em_jogo == "esconde":
        return Lugar(False, motivo="jogo")
    if gaming and cfg.em_jogo == "oposto":
        do_jogo = cfg.tela_jogo if cfg.tela_jogo in telas else principal
        if cfg.tela in telas and cfg.tela != do_jogo:
            return Lugar(True, cfg.tela, "jogo_oposto")
        for nome in telas:
            if nome != do_jogo:
                return Lugar(True, nome, "jogo_oposto")
        return Lugar(False, motivo="jogo")
    return Lugar(True, cfg.tela if cfg.tela in telas else principal, "normal")


# --- Stubs com a assinatura final (corpo nas tarefas donas) -------------------------------------


class Gestos:
    """Máquina de estados do botão esquerdo no rosto → eventos do ``Reactor`` (spec §1, CA-O2).

    **Dona: O1.1.** Relógio injetado (``agora``); sem Qt. Simples (vence ``DBL_MS``) →
    ``enviar_click("face", agora)``; duplo → ``enviar_hover("dbl", agora)``; longo (≥ ``LONG_S``) →
    ``"long"``; arrasto na metade de cima ≥ ``DRAG_PX`` → ``"arrasto"`` uma vez; hover
    ``"in"``/``"move"``/``"out"``. Nunca liga a escuta.
    """

    DBL_MS = 250
    LONG_S = 0.6
    DRAG_PX = 18  # mesmos valores do gamerhud (FACE_*), copiados

    def __init__(
        self,
        enviar_click: Callable[[str, float], None],
        enviar_hover: Callable[[str, float], None],
    ) -> None:
        self.enviar_click = enviar_click
        self.enviar_hover = enviar_hover

    def press(self, x: float, y: float, alto: bool, agora: float) -> None:
        """Botão esquerdo apertado; ``alto`` = metade de cima do rosto. (O1.1)"""
        raise NotImplementedError("O1.1")

    def move(self, x: float | None, y: float | None, dentro: bool, agora: float) -> None:
        """Mouse andou (``None`` = saiu da janela). (O1.1)"""
        raise NotImplementedError("O1.1")

    def release(self, agora: float) -> None:
        """Botão esquerdo solto. (O1.1)"""
        raise NotImplementedError("O1.1")

    def tick(self, agora: float) -> None:
        """Vence a espera do duplo → ``on_click("face")``. (O1.1)"""
        raise NotImplementedError("O1.1")


def regiao_entrada(img: QImage, limiar: int = 76, grade: int = 8) -> list[QRect]:
    """Retângulos da silhueta (alfa ≥ ``limiar`` numa grade de ``grade`` px, dilatada 1 célula,
    ≤ 64 retângulos). Imagem vazia → ``[]``. **Dona: O1.2** (spec §1, CA-O3)."""
    raise NotImplementedError("O1.2")


def snapshot_leve(
    magui: str, mouth: float, mood: int | None, turn_tag: Any, track: Any, gaming: bool
) -> Snapshot:
    """``Snapshot`` só com ``magui_state``, ``mouth_level``, ``mood``, ``turn_tag``, ``track`` e
    ``gaming``; o resto no padrão. **Dona: O1.1** (spec §3, CA-O5)."""
    raise NotImplementedError("O1.1")


def hud_aberto(lock: Path | None = None) -> bool:
    """Trava do HUD (``None`` = ``HUD_LOCK``) ocupada? ``flock(LOCK_EX | LOCK_NB)``: conseguiu →
    solta na hora e ``False``. Entrada ``hud`` do ``decidir_lugar`` (D2). **Dona: O1.1.**"""
    raise NotImplementedError("O1.1")


def jogo_aberto() -> bool:
    """``steam_game() or mango_game()`` do ``hud/gamerhud-watch.py`` (carregado por
    ``spec_from_file_location``, sem ``main``); erro → ``False``. Entrada ``gaming`` do
    ``decidir_lugar`` (D3). **Dona: O1.1.**"""
    raise NotImplementedError("O1.1")


DETECTORES_OVERLAY: tuple = ()  # O1.1: det_tempo, det_musica, det_entrada, det_conversa (spec §3)
