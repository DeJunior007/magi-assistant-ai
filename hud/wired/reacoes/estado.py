"""Humor da Condessa (spec §2, acordo §1). Dono: V0.2.

``Humor`` (ânimo, energia, decaimento, retorno decrescente, faixa com histerese), ``Postura`` (fone
com motivo) e ``Estado`` (persistência em ``~/.local/state/magi/condessa-estado.json``).

Os números vêm do ``[vida.humor]`` (``VIDA_PADRAO["humor"]`` só onde faltar chave). A tabela de
acontecimentos é transcrita do acordo §1 como dados (``EVENTOS``).

Chaves do ``ctx`` lidas por ``Humor.tick``: ``pedro_ausente_min`` (Pedro fora há N min),
``silencio_min`` (sem som há N min), ``musica_nota`` (nota da faixa tocando, ou None), ``jogo``
(bool), ``pedro_mal`` (bool, filtro do acordo §3) e ``momento`` (texto para o medidor).
"""

from __future__ import annotations

import json
import math
import os
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from .vida import VIDA_PADRAO, Causa, Evento, Faixa, Fone, mesclar

ESTADO_FILE = Path.home() / ".local/state/magi/condessa-estado.json"

# acordo §1, tabela: tipo → (Δ ânimo, Δ energia, texto da causa no medidor)
EVENTOS: dict[str, tuple[float, float, str]] = {
    "faixa_nota2": (0.25, 0.15, "faixa nota 2"),
    "faixa_nota1": (0.10, 0.10, "faixa nota 1"),
    "faixa_nota_menos1": (-0.10, 0.0, "faixa nota −1"),
    "faixa_nota_menos2": (-0.20, 0.0, "faixa nota −2"),
    "ado": (0.30, 0.15, "Ado"),
    "favorita": (0.30, 0.15, "Favorita do Dia"),
    "birra": (-0.15, 0.0, "Pedro pulou a faixa que ela deu 2"),
    "pedro_volta": (0.25, 0.10, "Pedro voltou"),
    "tag_elogio": (0.25, 0.0, "elogio"),
    "tag_zoeira": (0.05, 0.05, "zoeira"),
    "tag_correcao": (-0.10, 0.0, "correção"),
    "clique_carinho": (0.05, 0.0, "clique carinhoso"),
    "claude_fim": (0.08, 0.0, "Claude terminou"),
    "commit": (0.10, 0.0, "commit"),
    "faxina": (0.15, 0.0, "faxina"),
    "claude_erro": (-0.05, 0.0, "Claude errou"),
    "jogo_abriu": (0.05, 0.25, "jogo abriu"),
    "fps_episodio": (-0.10, 0.0, "FPS/calor"),
    "fps_recuperou": (0.10, 0.0, "recuperou"),
    "truque_aplauso": (0.20, 0.0, "truque aplaudido"),
    "truque_ignorado": (-0.05, 0.0, "truque ignorado"),
}
SEM_HABITUACAO = frozenset({"ado", "favorita"})  # acordo §1
CLIQUE_HORA = 3  # acordo §1: clique carinhoso conta ≤ 3/h

# Cor do medidor por faixa = a cor do fundo do repouso (acordo §6 e §2): Radiante `happy`; as outras
# `calm`, que é a cor do acento (a da Melchior, `theme.CPU`). `stress` de episódio/Alerta não muda a faixa.
COR_FAIXA = {
    Faixa.RADIANTE: "#f2a7c3",
    Faixa.CONTENTE: "#b392f0",
    Faixa.NEUTRA: "#b392f0",
    Faixa.EMBURRADA: "#b392f0",
}

_MAX_CAUSAS = 10


@dataclass
class Postura:
    """Fone CABECA/PESCOCO, com o motivo da última troca (spec §4)."""

    fone: Fone = Fone.PESCOCO
    motivo: str = ""


def _meia_vida(valor: float, alvo: float, dt_s: float, meia_min: float) -> float:
    if dt_s <= 0 or meia_min <= 0:
        return valor
    return alvo + (valor - alvo) * 0.5 ** (dt_s / (meia_min * 60))


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


class Humor:
    """Ânimo e energia (spec §2). Números do ``[vida.humor]``."""

    def __init__(self, cfg: dict | None = None) -> None:
        self.cfg = mesclar(VIDA_PADRAO["humor"], cfg or {})
        self.animo: float = self.cfg["base_animo"]
        self.energia_nivel: float = self._alvo_energia(time.localtime().tm_hour)
        self.energia: float = self.energia_nivel
        self.causas: deque[Causa] = deque(maxlen=_MAX_CAUSAS)
        self.recentes: list[tuple[str, str, float, float]] = []  # (tipo, fonte, em, Δ efetivo)
        self.momento: str = ""
        self.pedro_mal: bool = False
        self.ultimo_tick: float | None = None
        self.sumido_aplicados: int = 0
        self._faixa: Faixa = self._classificar(self.animo)
        self._pendente: Faixa | None = None
        self._pendente_desde: float = 0.0

    # ── eventos ────────────────────────────────────────────────────────────
    def aplicar(self, evento: Evento, agora: float) -> float:
        """Aplica o Δ do evento (habituação, trava por fonte, piso, teto); devolve o Δ efetivo."""
        c = self.cfg
        d_animo, d_energia, texto = EVENTOS.get(evento.tipo, (0.0, 0.0, evento.tipo))
        janela = c["habituacao_janela_min"] * 60
        self.recentes = [r for r in self.recentes if agora - r[2] < max(janela, 3600)]
        if evento.tipo == "clique_carinho":
            n_cliques = sum(1 for r in self.recentes if r[0] == "clique_carinho" and agora - r[2] < 3600)
            if n_cliques >= CLIQUE_HORA:
                return 0.0
        fator = 1.0
        if evento.tipo not in SEM_HABITUACAO:
            n = sum(1 for r in self.recentes if r[0] == evento.tipo and agora - r[2] < janela)
            fator = c["habituacao"] ** n
        delta = d_animo * fator
        # trava ±trava_fonte_hora por fonte, cada sentido separado
        trava = c["trava_fonte_hora"]
        mesma = [r[3] for r in self.recentes if r[1] == evento.fonte and agora - r[2] < 3600]
        if delta > 0:
            delta = min(delta, max(0.0, trava - sum(x for x in mesma if x > 0)))
        elif delta < 0:
            delta = max(delta, -max(0.0, trava + sum(x for x in mesma if x < 0)))
        novo = self.animo + delta
        if evento.fonte == "sistema" and delta < 0:
            novo = max(novo, min(self.animo, c["piso_sistema"]))
        if self.pedro_mal and delta > 0:
            novo = min(novo, max(self.animo, c["teto_pedro_mal"]))
        novo = _clamp(novo, -1.0, 1.0)
        efetivo = novo - self.animo
        self.animo = novo
        self.energia_nivel = _clamp(self.energia_nivel + d_energia * fator, 0.0, 1.0)
        self.recentes.append((evento.tipo, evento.fonte, agora, efetivo))
        if efetivo or d_energia:
            self.causas.append(Causa(texto, round(efetivo, 4), agora))
        return efetivo

    # ── relógio ────────────────────────────────────────────────────────────
    def _alvo_energia(self, hora: int) -> float:
        tabela = sorted((int(k), v) for k, v in self.cfg["energia_alvo"].items())
        alvo = tabela[-1][1]  # antes do primeiro horário: vale o último (vira a meia-noite)
        for h, v in tabela:
            if hora >= h:
                alvo = v
        return alvo

    def _decair(self, dt_s: float, hora: int) -> None:
        c = self.cfg
        base = c["base_animo"]
        meia = c["meia_vida_acima_min"] if self.animo > base else c["meia_vida_abaixo_min"]
        self.animo = _meia_vida(self.animo, base, dt_s, meia)
        self.energia_nivel = _meia_vida(self.energia_nivel, self._alvo_energia(hora), dt_s,
                                        c["energia_meia_vida_min"])

    def tick(self, agora: float, hora: int, ctx: dict) -> None:
        """Volta à base, Pedro sumido, energia pelo relógio. O silêncio só mexe na energia."""
        c = self.cfg
        self.pedro_mal = bool(ctx.get("pedro_mal"))
        if ctx.get("momento") is not None:
            self.momento = str(ctx["momento"])
        dt = 0.0 if self.ultimo_tick is None else max(0.0, agora - self.ultimo_tick)
        self.ultimo_tick = agora
        self._decair(dt, hora)
        # Pedro sumido: −0,05 a cada 15 min depois dos primeiros 30 (fora da habituação)
        ps = c["pedro_sumido"]
        ausente = float(ctx.get("pedro_ausente_min") or 0.0)
        devidos = max(0, int((ausente - ps["depois_min"]) // ps["cada_min"]))
        if ausente < ps["depois_min"]:
            self.sumido_aplicados = 0
        while self.sumido_aplicados < devidos:
            self.sumido_aplicados += 1
            antes = self.animo
            self.animo = _clamp(self.animo + ps["delta"], -1.0, 1.0)
            self.causas.append(Causa("Pedro sumido", round(self.animo - antes, 4), agora))
        # energia: nível + bônus enquanto duram − silêncio
        bonus = 0.0
        nota = ctx.get("musica_nota")
        if nota is not None and nota >= 1:
            bonus += c["energia_musica"]
        if ctx.get("jogo"):
            bonus += c["energia_jogo"]
        se = c["silencio_energia"]
        silencio = float(ctx.get("silencio_min") or 0.0)
        if silencio > se["depois_min"]:
            bonus += max(se["ate"], se["por_min"] * (silencio - se["depois_min"]))
        self.energia = _clamp(self.energia_nivel + bonus, 0.0, 1.0)

    # ── faixa e medidor ────────────────────────────────────────────────────
    def _classificar(self, v: float) -> Faixa:
        lim = self.cfg["limiar"]
        if v >= lim["radiante"]:
            return Faixa.RADIANTE
        if v >= lim["contente"]:
            return Faixa.CONTENTE
        if v <= lim["emburrada"]:
            return Faixa.EMBURRADA
        return Faixa.NEUTRA

    def _segura(self, f: Faixa, v: float) -> bool:
        lim, h = self.cfg["limiar"], self.cfg["histerese"]
        faixas = {
            Faixa.RADIANTE: (lim["radiante"], math.inf),
            Faixa.CONTENTE: (lim["contente"], lim["radiante"]),
            Faixa.NEUTRA: (lim["emburrada"], lim["contente"]),
            Faixa.EMBURRADA: (-math.inf, lim["emburrada"]),
        }
        lo, hi = faixas[f]
        return lo - h <= v <= hi + h

    def faixa(self, agora: float) -> Faixa:
        """Faixa atual, com histerese (±histerese no limiar e ``troca_faixa_s`` na faixa nova)."""
        if self._segura(self._faixa, self.animo):
            self._pendente = None
            return self._faixa
        alvo = self._classificar(self.animo)
        if alvo != self._pendente:
            self._pendente, self._pendente_desde = alvo, agora
        if agora - self._pendente_desde >= self.cfg["troca_faixa_s"]:
            self._faixa, self._pendente = alvo, None
        return self._faixa

    def medidor(self) -> tuple[float, str, str, tuple[Causa, ...]]:
        """(valor -1..+1, cor, momento, últimas 3 causas)."""
        return (self.animo, COR_FAIXA[self._faixa], self.momento, tuple(list(self.causas)[-3:]))

    # ── persistência ───────────────────────────────────────────────────────
    def para_dict(self) -> dict:
        return {
            "animo": self.animo, "energia": self.energia, "energia_nivel": self.energia_nivel,
            "faixa": str(self._faixa),
            "pendente": str(self._pendente) if self._pendente else None,
            "pendente_desde": self._pendente_desde,
            "causas": [[c.texto, c.delta, c.em] for c in self.causas],
            "recentes": [list(r) for r in self.recentes],
            "momento": self.momento, "ultimo_tick": self.ultimo_tick,
            "sumido_aplicados": self.sumido_aplicados,
        }

    @classmethod
    def de_dict(cls, d: dict, cfg: dict | None = None) -> Humor:
        h = cls(cfg)
        h.animo = _clamp(float(d["animo"]), -1.0, 1.0)
        h.energia = _clamp(float(d["energia"]), 0.0, 1.0)
        h.energia_nivel = _clamp(float(d.get("energia_nivel", h.energia)), 0.0, 1.0)
        h._faixa = Faixa(d["faixa"])
        h._pendente = Faixa(d["pendente"]) if d.get("pendente") else None
        h._pendente_desde = float(d.get("pendente_desde", 0.0))
        h.causas.extend(Causa(str(t), float(dl), float(em)) for t, dl, em in d.get("causas", []))
        h.recentes = [(str(t), str(f), float(em), float(dl)) for t, f, em, dl in d.get("recentes", [])]
        h.momento = str(d.get("momento", ""))
        h.ultimo_tick = d.get("ultimo_tick")
        h.sumido_aplicados = int(d.get("sumido_aplicados", 0))
        return h


class Estado:
    """Humor + postura + contadores do governador, persistidos com escrita atômica."""

    def __init__(self, humor: Humor | None = None, postura: Postura | None = None,
                 governador: dict | None = None) -> None:
        self.humor = humor or Humor()
        self.postura = postura or Postura()
        self.governador = governador or {}

    def salvar(self, agora: float, path: Path | None = None) -> None:
        p = Path(path or ESTADO_FILE)
        p.parent.mkdir(parents=True, exist_ok=True)
        dados = {
            "salvo_em": agora,
            "humor": self.humor.para_dict(),
            "postura": {"fone": str(self.postura.fone), "motivo": self.postura.motivo},
            "governador": self.governador,
        }
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)

    @classmethod
    def carregar(cls, agora: float, cfg: dict | None = None, path: Path | None = None) -> Estado:
        """Lê o estado (inválido → base) e aplica o decaimento do tempo com o HUD fechado."""
        p = Path(path or ESTADO_FILE)
        try:
            dados = json.loads(p.read_text(encoding="utf-8"))
            humor = Humor.de_dict(dados["humor"], cfg)
            pd = dados.get("postura") or {}
            postura = Postura(Fone(pd.get("fone", Fone.PESCOCO)), str(pd.get("motivo", "")))
            governador = dict(dados.get("governador") or {})
            salvo_em = float(dados["salvo_em"])
        except (OSError, ValueError, KeyError, TypeError):
            return cls(Humor(cfg))
        fechado = max(0.0, agora - salvo_em)
        humor._decair(fechado, time.localtime(agora).tm_hour)
        humor.energia = humor.energia_nivel
        humor.ultimo_tick = agora
        return cls(humor, postura, governador)
