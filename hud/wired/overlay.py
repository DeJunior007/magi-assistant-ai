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

import fcntl
import importlib.util
import json
import logging
import math
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
POS_FILE = Path.home() / ".local/state/magi/overlay-pos.json"  # O4.2: {"tela", "ancora"}

TAMANHO_MIN, TAMANHO_MAX = 120, 480
MARGEM_MAX = 400
ALTURA_FATOR = 1.15  # o retrato é TALL: quadro = tamanho × tamanho·1,15 (spec §5)

CANTOS = ("sup_esq", "sup_dir", "inf_esq", "inf_dir")
RENDERERS = ("cpu", "gl")
EM_JOGO = ("oposto", "esconde", "fica")  # D3
COM_HUD = ("esconde", "independente")  # D2
ESTILOS = ("card", "solto")  # O4.1: card com moldura (padrão) | só o rosto solto (antigo)
PLATAFORMAS = ("xcb", "wayland")  # O4.2: XWayland (padrão, o app se posiciona) | nativo
# O4.2: pontos de encaixe por tela — 4 cantos + o meio de cada borda
ANCORAS = ("sup_esq", "sup_meio", "sup_dir", "meio_esq", "meio_dir", "inf_esq", "inf_meio",
           "inf_dir")


@dataclass
class Config:
    """``~/.config/magi/overlay.toml`` (tabela ``[overlay]``). Padrões = decisões de 2026-10-10."""

    tamanho: int = 220  # lado do quadro em px lógicos, preso em 120..480
    tela: str | None = None  # QScreen.name(); None = principal
    canto: str = "sup_dir"  # sup_esq | sup_dir | inf_esq | inf_dir      (D6)
    margem: int = 24  # px da borda da tela até o quadro                (D6)
    fundo: bool = False  # True = desenha o fundo de hexágonos do retrato (no card é sempre True)
    estilo: str = "card"  # "card" | "solto"                             (O4.1)
    renderer: str = "cpu"  # "cpu" | "gl" (sobrepõe o portrait.toml só no overlay)
    em_jogo: str = "oposto"  # "oposto" | "esconde" | "fica"            (D3)
    tela_jogo: str | None = None  # monitor do jogo; None = principal     (D3)
    com_hud: str = "esconde"  # "esconde" | "independente"              (D2)
    ligado: bool = True  # False = o autostart sai na hora
    x: int | None = None  # obsoleto (D4 antiga): lido e ignorado; a memória é a âncora (O4.2)
    y: int | None = None
    plataforma: str = "xcb"  # "xcb" (XWayland) | "wayland" (nativo, sem encaixe)   (D4, O4.2)
    encaixe: bool = True  # gruda no ponto de encaixe mais próximo ao soltar        (O4.2)
    ancoras: list[str] | None = None  # limita os pontos de encaixe; None = os 8   (O4.2)

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
    if isinstance(valor, list):
        return "[" + ", ".join(_toml(v) for v in valor) + "]"
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
    "estilo": _escolha(ESTILOS),
    "renderer": _escolha(RENDERERS),
    "em_jogo": _escolha(EM_JOGO),
    "tela_jogo": _texto_ou_nada,
    "com_hud": _escolha(COM_HUD),
    "ligado": lambda v: (isinstance(v, bool), v),
    "x": lambda v: (_inteiro(v), v),
    "y": lambda v: (_inteiro(v), v),
    "plataforma": _escolha(PLATAFORMAS),
    "encaixe": lambda v: (isinstance(v, bool), v),
    "ancoras": lambda v: (isinstance(v, list) and v != [] and all(a in ANCORAS for a in v),
                          list(dict.fromkeys(v)) if isinstance(v, list) else v),
}


def tamanho_quadro(cfg: Config) -> tuple[int, int]:
    """Largura e altura do quadro da janela (px lógicos)."""
    return cfg.tamanho, round(cfg.tamanho * ALTURA_FATOR)


def fundo_efetivo(cfg: Config) -> bool:
    """No ``card`` o fundo do retrato é sempre ligado (O4.1); no ``solto`` vale ``cfg.fundo``."""
    return True if cfg.estilo == "card" else cfg.fundo


def _gravar_json(dados: dict, caminho: Path | None) -> None:
    caminho = POS_FILE if caminho is None else caminho
    caminho.parent.mkdir(parents=True, exist_ok=True)
    tmp = caminho.with_name(caminho.name + ".tmp")
    tmp.write_text(json.dumps(dados), encoding="utf-8")
    os.replace(tmp, caminho)


def gravar_posicao(x: int, y: int, tela: str | None, caminho: Path | None = None) -> None:
    """Posição livre ao soltar o arraste (O4.1; no O4.2 só com ``encaixe = false``)."""
    _gravar_json({"x": int(x), "y": int(y), "tela": tela}, caminho)


def gravar_ancora(tela: str | None, ancora: str, caminho: Path | None = None) -> None:
    """Ponto de encaixe ao soltar (O4.2): ``{"tela": QScreen.name(), "ancora": "inf_dir"}``."""
    _gravar_json({"tela": tela, "ancora": ancora}, caminho)


def ler_posicao(caminho: Path | None = None) -> tuple[int, int, str | None] | None:
    """``(x, y, tela)`` gravados por ``gravar_posicao``; ausente/ilegível → None."""
    caminho = POS_FILE if caminho is None else caminho
    try:
        d = json.loads(caminho.read_text(encoding="utf-8"))
        x, y, tela = d["x"], d["y"], d.get("tela")
    except (OSError, ValueError, TypeError, KeyError):
        return None
    if not (_inteiro(x) and _inteiro(y)) or not (tela is None or isinstance(tela, str)):
        return None
    return x, y, tela


@dataclass(frozen=True)
class Ancora:
    """Ponto de encaixe escolhido: tela, nome e o topo-esquerdo do quadro (O4.2)."""

    tela: str | None
    nome: str
    x: int
    y: int


def ponto_ancora(nome: str, area: QRect, tamanho: tuple[int, int], margem: int) -> QPoint:
    """Topo-esquerdo do quadro ``tamanho`` na âncora ``nome`` da ``area`` útil, a ``margem`` px."""
    w, h = tamanho
    horiz, vert = nome.split("_")[1], nome.split("_")[0]
    if horiz == "esq":
        x = area.x() + margem
    elif horiz == "dir":
        x = area.x() + area.width() - margem - w
    else:
        x = area.x() + (area.width() - w) // 2
    if vert == "sup":
        y = area.y() + margem
    elif vert == "inf":
        y = area.y() + area.height() - margem - h
    else:
        y = area.y() + (area.height() - h) // 2
    return QPoint(x, y)


def encaixar(
    centro: QPoint,
    telas: Sequence[tuple[str | None, QRect]],
    tamanho: tuple[int, int],
    margem: int,
    ancoras: Sequence[str] | None = None,
) -> Ancora:
    """Âncora mais próxima do ``centro`` da janela, em qualquer monitor (O4.2).

    ``telas`` = ``(QScreen.name(), availableGeometry())``: a área útil não cobre o painel do KDE.
    Distância entre o centro da janela e o centro do quadro na âncora; empate → a primeira.
    """
    nomes = [a for a in (ancoras or ANCORAS) if a in ANCORAS] or list(ANCORAS)
    w, h = tamanho
    melhor: tuple[float, Ancora] | None = None
    for tela, area in telas:
        for nome in nomes:
            p = ponto_ancora(nome, area, tamanho, margem)
            d = math.hypot(p.x() + w / 2 - centro.x(), p.y() + h / 2 - centro.y())
            if melhor is None or d < melhor[0]:
                melhor = (d, Ancora(tela, nome, p.x(), p.y()))
    if melhor is None:
        raise ValueError("encaixar sem telas")
    return melhor[1]


def ler_ancora(
    telas: Sequence[tuple[str | None, QRect]],
    tamanho: tuple[int, int],
    margem: int,
    caminho: Path | None = None,
) -> tuple[str | None, str] | None:
    """``(tela, ancora)`` gravados por ``gravar_ancora``; o formato antigo ``{x, y, tela}`` (O4.1)
    vira a âncora mais próxima do quadro naquele ponto. Ausente/ilegível/sem telas → None."""
    caminho = POS_FILE if caminho is None else caminho
    try:
        d = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or not (d.get("tela") is None or isinstance(d.get("tela"), str)):
        return None
    if d.get("ancora") in ANCORAS:
        return d.get("tela"), d["ancora"]
    antiga = ler_posicao(caminho)
    if antiga is None or not telas:
        return None
    x, y, _ = antiga
    w, h = tamanho
    a = encaixar(QPoint(x + w // 2, y + h // 2), telas, tamanho, margem)
    return a.tela, a.nome


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
        self._press: tuple[float, float, float, bool, bool] | None = None  # (t, x, y, alto, arrastou)
        self._espera: float | None = None  # prazo do 2º clique (duplo); None = sem espera
        self._dentro = False

    def press(self, x: float, y: float, alto: bool, agora: float) -> None:
        """Botão esquerdo apertado; ``alto`` = metade de cima do rosto. (O1.1)"""
        self.tick(agora)  # espera vencida sem tick: o simples sai antes deste novo press
        if self._espera is not None:  # 2º clique dentro da espera: duplo, sem clique
            self._espera = None
            self._press = None
            self.enviar_hover("dbl", agora)
            return
        self._press = (agora, x, y, alto, False)

    def move(self, x: float | None, y: float | None, dentro: bool, agora: float) -> None:
        """Mouse andou (``None`` = saiu da janela). (O1.1)"""
        dentro = dentro and x is not None and y is not None
        if dentro != self._dentro:
            self._dentro = dentro
            self.enviar_hover("in" if dentro else "out", agora)
        elif dentro:
            self.enviar_hover("move", agora)
        p = self._press
        if p is None or x is None or y is None or p[4] or not p[3]:
            return
        if math.hypot(x - p[1], y - p[2]) >= self.DRAG_PX:
            self._press = (*p[:4], True)
            self.enviar_hover("arrasto", agora)

    def release(self, agora: float) -> None:
        """Botão esquerdo solto. (O1.1)"""
        p, self._press = self._press, None
        if p is None or p[4]:  # arrastou: já reagiu
            return
        if agora - p[0] >= self.LONG_S:
            self.enviar_hover("long", agora)
            return
        self._espera = agora + self.DBL_MS / 1000

    def tick(self, agora: float) -> None:
        """Vence a espera do duplo → ``on_click("face")``. (O1.1)"""
        if self._espera is not None and agora >= self._espera:
            self._espera = None
            self.enviar_click("face", agora)


def regiao_entrada(img: QImage, limiar: int = 76, grade: int = 8) -> list[QRect]:
    """Retângulos da silhueta (alfa ≥ ``limiar`` numa grade de ``grade`` px, dilatada 1 célula,
    ≤ 64 retângulos). Imagem vazia → ``[]``. **Dona: O1.2** (spec §1, CA-O3)."""
    if img.isNull() or img.width() <= 0 or img.height() <= 0:
        return []
    alfa = img.convertToFormat(QImage.Format.Format_Alpha8)
    w, h, passo = alfa.width(), alfa.height(), alfa.bytesPerLine()
    dados = bytes(alfa.constBits())[: passo * h]
    grade = max(1, int(grade))
    while True:
        cols, lins = -(-w // grade), -(-h // grade)
        cheia = [[False] * cols for _ in range(lins)]
        for y in range(h):
            linha, cel = dados[y * passo: y * passo + w], cheia[y // grade]
            for c in range(cols):
                if not cel[c] and max(linha[c * grade: (c + 1) * grade]) >= limiar:
                    cel[c] = True
        if not any(any(r) for r in cheia):
            return []
        # dilata 1 célula (o cabelo balança)
        dil = [[any(cheia[j][i] for j in range(max(0, r - 1), min(lins, r + 2))
                    for i in range(max(0, c - 1), min(cols, c + 2))) for c in range(cols)]
               for r in range(lins)]
        # trechos por linha; trechos iguais em linhas seguidas viram um retângulo só
        rects: list[list[int]] = []  # [c0, c1, r0, r1]
        abertos: dict[tuple[int, int], list[int]] = {}
        for r in range(lins):
            novos: dict[tuple[int, int], list[int]] = {}
            c = 0
            while c < cols:
                if not dil[r][c]:
                    c += 1
                    continue
                c0 = c
                while c < cols and dil[r][c]:
                    c += 1
                k = (c0, c)
                if k in abertos:
                    abertos[k][3] = r
                    novos[k] = abertos[k]
                else:
                    novos[k] = [c0, c, r, r]
                    rects.append(novos[k])
            abertos = novos
        if len(rects) <= 64:
            return [QRect(c0 * grade, r0 * grade, min(w, c1 * grade) - c0 * grade,
                          min(h, (r1 + 1) * grade) - r0 * grade) for c0, c1, r0, r1 in rects]
        grade *= 2  # recorte fino demais: grade mais grossa até caber


def snapshot_leve(
    magui: str, mouth: float, mood: int | None, turn_tag: Any, track: Any, gaming: bool
) -> Snapshot:
    """``Snapshot`` só com ``magui_state``, ``mouth_level``, ``mood``, ``turn_tag``, ``track`` e
    ``gaming``; o resto no padrão. **Dona: O1.1** (spec §3, CA-O5)."""
    from .main_screen import Snapshot

    return Snapshot(
        magui_state=magui, mouth_level=mouth, mood=mood, turn_tag=turn_tag, track=track,
        gaming=gaming,
    )


def hud_aberto(lock: Path | None = None) -> bool:
    """Trava do HUD (``None`` = ``HUD_LOCK``) ocupada? ``flock(LOCK_EX | LOCK_NB)``: conseguiu →
    solta na hora e ``False``. Entrada ``hud`` do ``decidir_lugar`` (D2). **Dona: O1.1.**"""
    lock = HUD_LOCK if lock is None else lock
    try:
        fd = os.open(lock, os.O_RDONLY)  # sem a trava no disco = HUD nunca abriu: não cria
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


def jogo_aberto() -> bool:
    """``steam_game() or mango_game()`` do ``hud/gamerhud-watch.py`` (carregado por
    ``spec_from_file_location``, sem ``main``); erro → ``False``. Entrada ``gaming`` do
    ``decidir_lugar`` (D3). **Dona: O1.1.**"""
    try:
        w = _carregar_watch()
        return bool(w.steam_game() or w.mango_game())
    except Exception as e:  # noqa: BLE001 — vigia quebrado/ausente não derruba o overlay
        log.debug("jogo_aberto: %s", e)
        return False


_WATCH: Any = None  # módulo hud/gamerhud-watch.py, carregado uma vez


def _carregar_watch() -> Any:
    """Carrega ``hud/gamerhud-watch.py`` sem rodar o ``main`` (o nome não é ``__main__``)."""
    global _WATCH  # noqa: PLW0603
    if _WATCH is None:
        caminho = Path(__file__).resolve().parents[1] / "gamerhud-watch.py"
        spec = importlib.util.spec_from_file_location("gamerhud_watch_overlay", caminho)
        if spec is None or spec.loader is None:
            raise ImportError(f"sem loader para {caminho}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _WATCH = mod
    return _WATCH


# Só os detectores que não precisam dos sensores/threads do HUD (spec §3).
from .reacoes import det_conversa, det_entrada, det_musica, det_tempo  # noqa: E402

DETECTORES_OVERLAY: tuple = (
    det_tempo.detectar,
    det_musica.detectar,
    det_entrada.detectar,
    det_conversa.detectar,
)
