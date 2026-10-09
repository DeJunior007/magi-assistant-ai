"""Governador (spec §3): cotas, cooldown, prioridade, fila, bloqueios, blush/lágrima, Ado e as
desligadas do Pedro. Puro, relógio injetado (``agora`` em segundos). Dono: R0.2.

``ctx`` (dict) — chaves lidas, todas opcionais salvo ``defs``:

- ``defs``: catálogo, ``{chave: Def}`` ou ``{(chave, variante): Def}`` (variante tenta primeiro);
- ``estado``: ``Estado`` com o histórico (criado em ``ctx`` se faltar; guarde o ``ctx`` entre ticks);
- ``hora``: hora local 0–23 (padrão: ``time.localtime(agora)``);
- ``humor``: humor do Pedro (0–5; padrão 3); ``jogo``, ``claude``: bool; ``musica_nota``: int;
- ``ado``: bool (faixa tocando é da Ado); ``desligadas``: chaves do ``[reacoes] desligadas``;
- ``parada``: Magui parada (padrão True). Não parada → só a fila (VOLTA/VITORIA) anda.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field, replace

from .contratos import Classe, Def, Disparo, Passo

HORA_S = 3600.0
DIA_S = 86400.0
PASSIVA_MIN_S = 40.0
ATIVAS_POR_HORA = 8
FILA_VALIDADE_S = 30.0
BLUSH_POR_HORA = 1
BLUSH_LIVRE = frozenset({62, 74, 87})  # Nº fora da conta do blush e nunca barrados
FURAM_COTA = frozenset({Classe.SISTEMA, Classe.VITORIA, Classe.VOLTA})
FILA_CLASSES = frozenset({Classe.VOLTA, Classe.VITORIA})
RANK = {Classe.SISTEMA: 5, Classe.PEDRO: 4, Classe.MUSICA: 3, Classe.TEMPO: 2, Classe.PASSIVA: 1}
COBRANCA_BOCAS = frozenset({"C8", "C11"})
COBRANCA_TROCA = "C9"


@dataclass
class Estado:
    """Histórico do governador (tempos em segundos do relógio injetado)."""

    toques: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    passivas: list[float] = field(default_factory=list)
    ativas: list[float] = field(default_factory=list)  # só as que contam no teto
    blush: list[float] = field(default_factory=list)  # só as que contam
    lagrima: list[float] = field(default_factory=list)
    fila: tuple[Def, Disparo, float] | None = None
    ultimo: Disparo | None = None  # disparo da última reação aprovada (para o registro)
    lagrima_liberada: str | None = None  # chave aprovada com lágrima de verdade

    def podar(self, agora: float) -> None:
        corte = agora - DIA_S
        for k in list(self.toques):
            self.toques[k] = [t for t in self.toques[k] if t > corte]
            if not self.toques[k]:
                del self.toques[k]
        self.passivas = [t for t in self.passivas if t > agora - HORA_S]
        self.ativas = [t for t in self.ativas if t > agora - HORA_S]
        self.blush = [t for t in self.blush if t > agora - HORA_S]
        self.lagrima = [t for t in self.lagrima if t > corte]


def noite(hora: int) -> bool:
    """22h–04h (inclui a hora 4)."""
    return hora >= 22 or hora <= 4


def tem_efeito(d: Def, nome: str) -> bool:
    return any(nome in p.efeitos for p in d.passos)


def furou_cota(d: Def) -> bool:
    """Reação que não conta nem é barrada pelo teto de ativas."""
    return bool(d.classes & FURAM_COTA)


def _passiva(d: Def) -> bool:
    return Classe.PASSIVA in d.classes


def _hora(agora: float, ctx: dict) -> int:
    h = ctx.get("hora")
    return int(h) if h is not None else time.localtime(agora).tm_hour


def _estado(ctx: dict) -> Estado:
    est = ctx.get("estado")
    if est is None:
        est = ctx["estado"] = Estado()
    return est


def _achar(disp: Disparo, defs: dict) -> Def | None:
    if disp.variante is not None and (disp.chave, disp.variante) in defs:
        return defs[(disp.chave, disp.variante)]
    return defs.get(disp.chave)


def _rank(d: Def) -> tuple[int, int]:
    return (max((RANK.get(c, 0) for c in d.classes), default=0), d.prio)


def _contexto_ok(d: Def, ctx: dict, hora: int) -> bool:
    """Bloqueios de contexto (R3, R11, Ado)."""
    if d.chave in set(ctx.get("desligadas") or ()):
        return False
    humor = ctx.get("humor", 3)
    if Classe.ZOEIRA in d.classes and (humor <= 1 or noite(hora)):
        return False
    if Classe.SONO in d.classes and (
        ctx.get("jogo") or ctx.get("claude") or ctx.get("musica_nota", 0) >= 1
    ):
        return False
    if Classe.RARA in d.classes and ctx.get("jogo"):
        return False
    return not (ctx.get("ado") and (tem_efeito(d, "blush") or d.mood == "love"))


def _cota_ok(d: Def, agora: float, est: Estado) -> bool:
    """Cotas e cooldowns (R2), com o histórico já podado."""
    toques = est.toques.get(d.chave, ())
    if _passiva(d) and est.passivas and agora - est.passivas[-1] < PASSIVA_MIN_S:
        return False
    if Classe.RARA in d.classes and any(agora - t < HORA_S for t in toques):
        return False
    if Classe.DIARIA in d.classes and toques:
        return False
    if not _passiva(d):
        if toques and agora - toques[-1] < d.cooldown_s:
            return False
        if not furou_cota(d) and len(est.ativas) >= ATIVAS_POR_HORA:
            return False
    return not (
        tem_efeito(d, "blush") and d.n not in BLUSH_LIVRE and len(est.blush) >= BLUSH_POR_HORA
    )


def _aprovar(d: Def, disp: Disparo, agora: float, hora: int, est: Estado) -> Def:
    est.toques[d.chave].append(agora)
    if _passiva(d):
        est.passivas.append(agora)
    elif not furou_cota(d):
        est.ativas.append(agora)
    if tem_efeito(d, "blush") and d.n not in BLUSH_LIVRE:
        est.blush.append(agora)
    est.lagrima_liberada = None
    if tem_efeito(d, "tear") and noite(hora) and not est.lagrima:
        est.lagrima.append(agora)
        est.lagrima_liberada = d.chave
    est.ultimo = disp
    return d


def escolher(disparos: list[Disparo], agora: float, ctx: dict) -> Def | None:
    """No máximo 1 reação aprovada neste tick (ou a que estava na fila)."""
    est = _estado(ctx)
    est.podar(agora)
    hora = _hora(agora, ctx)
    defs = ctx.get("defs") or {}
    cands: list[tuple[Def, Disparo]] = []
    for disp in disparos:
        d = _achar(disp, defs)
        if d is not None and _contexto_ok(d, ctx, hora) and _cota_ok(d, agora, est):
            cands.append((d, disp))

    if est.fila is not None and agora - est.fila[2] > FILA_VALIDADE_S:
        est.fila = None

    if not ctx.get("parada", True):
        fila = [(d, disp) for d, disp in cands if d.classes & FILA_CLASSES]
        if fila:
            d, disp = max(fila, key=lambda c: _rank(c[0]))
            if est.fila is None or _rank(d) >= _rank(est.fila[0]):
                est.fila = (d, disp, agora)
        return None

    if est.fila is not None:
        d, disp, _ = est.fila
        est.fila = None
        if _contexto_ok(d, ctx, hora) and _cota_ok(d, agora, est):
            cands.append((d, disp))
    if not cands:
        return None
    d, disp = max(cands, key=lambda c: _rank(c[0]))
    return _aprovar(d, disp, agora, hora, est)


def aplicar_bloqueios(d: Def, ctx: dict) -> tuple[Passo, ...]:
    """Passos de ``d`` com os bloqueios aplicados (C8/C11 -> C9; tira ``tear`` fora de hora).

    Com ``estado`` no ``ctx``, a lágrima só fica se ``escolher`` a liberou (≤ 1/dia); sem ele,
    basta ser noite."""
    hora = _hora(time.time(), ctx) if ctx.get("hora") is None else int(ctx["hora"])
    cobrar = Classe.COBRANCA in d.classes and (ctx.get("humor", 3) <= 1 or noite(hora))
    est = ctx.get("estado")
    lagrima = noite(hora) and (est is None or est.lagrima_liberada == d.chave)
    passos = []
    for p in d.passos:
        if cobrar and p.mouth in COBRANCA_BOCAS:
            p = replace(p, mouth=COBRANCA_TROCA)
        if not lagrima and "tear" in p.efeitos:
            p = replace(p, efeitos=tuple(e for e in p.efeitos if e != "tear"))
        passos.append(p)
    return tuple(passos)
