"""Passivas por momento e faixa (spec §9, acordo §3–§4). Dono: R1.1, V0.7.

O ``Reactor`` chama ``sortear`` a cada 10 s. A próxima passiva tem hora marcada: intervalo
**exponencial** com a média do momento (``[vida.passiva_media_min]``), ×0,8 com energia ≥ 0,7, ×1,5 com
energia < 0,3, ÷0,7 de madrugada, nunca abaixo de ``passiva_min_s``. Na hora, sai uma passiva do
**grupo do momento** (``momento.passivas``, já com as regras da linha e os filtros) ∩ as que a
**faixa** permite ∩ catálogo ativo, fora de cooldown e não desligadas; negativas só com causa
(``governador.causas_recentes`` + sinais vivos) e nunca sob filtro; gestos de fone/ritmo só com música
e fone na cabeça (E2). Peso ×``passiva_peso_por_uso`` por uso na última hora; ≤ ``passivas_hora``.

**Piso de vida**: Pedro presente, fora de Conversa e Jogando, ``piso_vida_min`` sem expressão nem
atenção (``ctx["ultima_expressao_em"]`` ou a última passiva daqui) → sai já a próxima do grupo; com o
grupo vazio, uma atenção dirigida (``Disparo(ATENCAO, "piso")``). O governador ainda decide se toca.

Estado próprio no ``ctx``: ``_passivas_inicio``, ``_passivas_proxima``, ``_passivas_momento``,
``_passivas_usos`` (lista de ``(em, chave)``).
"""

from __future__ import annotations

import random

from . import humor
from . import momento as _momento
from .contratos import Disparo
from .governador import CAUSAS_NEGATIVAS, causas_recentes
from .vida import VIDA_PADRAO, Faixa, Filtro, Fone, Momento

AQUECIMENTO_S = 60.0  # ao abrir o HUD ela não se mexe à toa no primeiro minuto
HORA_S = 3600.0
ATENCAO = "atencao"  # chave da olhada dirigida do piso de vida (o diretor resolve o alvo)

# "Ajeitando o fone" e "cabeça no ritmo" nunca sem música e E2 (acordo §7)
FONE_RITMO = frozenset({"ajeitando_fone", "cabeca_ritmo", "fone_repouso"})

# Negativa -> causas que valem para ela (spec §6). Sem nenhuma recente, não sai.
NEGATIVAS: dict[str, frozenset[str]] = {
    "suspiro": CAUSAS_NEGATIVAS,
    "soprando_franja": frozenset({
        "claude_demorando", "claude_esperando", "faixa_nota_menos1", "pulo_faixa_amada", "ignorada",
    }),
    "beicinho": frozenset({"ignorada", "pulo_faixa_amada", "truque_ignorado", "faixa_nota_menos1"}),
    "impaciente": frozenset({"claude_esperando", "claude_demorando"}),
    "indiferente": frozenset({"faixa_nota_menos1", "pulo_faixa_amada"}),
}

# Faixa -> passivas que ela não faz (acordo §2: a cara de repouso manda no tom)
FAIXA_BLOQUEIA: dict[Faixa, frozenset[str]] = {
    Faixa.RADIANTE: frozenset({"indiferente", "beicinho", "suspiro"}),
    Faixa.CONTENTE: frozenset(),
    Faixa.NEUTRA: frozenset({"rindo_sozinha"}),
    Faixa.EMBURRADA: frozenset({"sorriso_canto", "rindo_sozinha", "cantarolando", "cantando_junto"}),
}

SEM_PISO = frozenset({Momento.CONVERSA, Momento.JOGANDO, Momento.ALERTA})


def _vida(ctx: dict) -> dict:
    v = ctx.get("vida")
    return VIDA_PADRAO if not v else {**VIDA_PADRAO, **v}


def _em_cooldown(ctx: dict, chave: str, agora: float) -> bool:
    d = (ctx.get("defs") or {}).get(chave)
    toques = getattr(ctx.get("estado"), "toques", None) or {}
    lista = toques.get(chave) if d is not None else None
    return bool(lista) and agora - lista[-1] < d.cooldown_s


def causas(ctx: dict, agora: float) -> frozenset[str]:
    """Causas de negativa recentes (``ctx["causas"]``) + as que os sinais vivos mostram agora."""
    vivas = set(causas_recentes(ctx, agora))
    s = humor.sinais(ctx)
    if s.get("claude_esperando"):
        vivas.add("claude_esperando")
    if s.get("claude_demorando"):
        vivas.add("claude_demorando")
    if s.get("ei_ignorado"):
        vivas.add("ignorada")
    if s.get("musica_nota") == -1:
        vivas.add("faixa_nota_menos1")
    return frozenset(vivas)


def permitidas(ctx: dict, agora: float) -> tuple[str, ...]:
    """Grupo do momento ∩ faixa ∩ catálogo ativo, com negativas e fone/ritmo nas regras."""
    s = humor.sinais(ctx)
    m = humor.momento(ctx)
    fs = humor.filtros(ctx)
    bloq = FAIXA_BLOQUEIA[humor.faixa(ctx, agora)]
    defs = ctx.get("defs")
    desligadas = ctx.get("desligadas") or frozenset()
    com_fone = s.get("musica_nota") is not None and humor.fone(ctx) == Fone.CABECA
    cs = causas(ctx, agora)
    out = []
    for chave in _momento.passivas(m, s, fs):
        if chave in bloq or chave in desligadas:
            continue
        if defs is not None and chave not in defs:
            continue
        if chave in FONE_RITMO and not com_fone:
            continue
        if chave in NEGATIVAS and (fs or not (NEGATIVAS[chave] & cs)):
            continue
        if _em_cooldown(ctx, chave, agora):
            continue
        out.append(chave)
    return tuple(out)


def _usos(ctx: dict, agora: float) -> list[tuple[float, str]]:
    usos = [u for u in ctx.get("_passivas_usos", ()) if agora - u[0] < HORA_S]
    ctx["_passivas_usos"] = usos
    return usos


def pesos(ctx: dict, agora: float | None = None) -> dict[str, float]:
    """Peso de cada passiva sorteável agora: ×``passiva_peso_por_uso`` por uso na última hora."""
    agora = float(ctx.get("agora", 0.0)) if agora is None else agora
    fator = _vida(ctx)["passiva_peso_por_uso"]
    usos = _usos(ctx, agora)
    return {c: fator ** sum(1 for _, u in usos if u == c) for c in permitidas(ctx, agora)}


def media_s(ctx: dict, m: Momento | None = None) -> float | None:
    """Média (s) até a próxima passiva no momento, com energia e madrugada; None = sem passiva."""
    vida = _vida(ctx)
    m = humor.momento(ctx) if m is None else m
    base = _momento.media_min(m, vida)
    if base is None:
        return None
    s = base * 60.0
    energia = ctx.get("energia")
    if energia is not None and energia >= 0.7:
        s *= 0.8
    elif energia is not None and energia < 0.3:
        s *= 1.5
    if Filtro.MADRUGADA in humor.filtros(ctx):
        s /= 0.7
    return s


def _agendar(ctx: dict, agora: float, m: Momento, rng: random.Random) -> None:
    media = media_s(ctx, m)
    ctx["_passivas_momento"] = m
    if media is None:
        ctx["_passivas_proxima"] = None
        return
    ctx["_passivas_proxima"] = agora + max(_vida(ctx)["passiva_min_s"], rng.expovariate(1.0 / media))


def piso_vencido(ctx: dict, agora: float, m: Momento) -> bool:
    if m in SEM_PISO or not ctx.get("pedro_presente", m != Momento.PEDRO_SUMIU):
        return False
    usos = ctx.get("_passivas_usos") or []
    marcas = [ctx.get("ultima_expressao_em"), usos[-1][0] if usos else None, ctx["_passivas_inicio"]]
    ult = max(t for t in marcas if t is not None)
    return agora - ult > _vida(ctx)["piso_vida_min"] * 60.0


def sortear(ctx: dict, agora: float, rng: random.Random) -> Disparo | None:
    """A cada 10 s: na hora marcada (ou no piso de vida) devolve 1 passiva do grupo do momento."""
    inicio = ctx.setdefault("_passivas_inicio", agora)
    if agora - inicio < AQUECIMENTO_S:
        return None
    m = humor.momento(ctx)
    if ctx.get("_passivas_momento") != m or "_passivas_proxima" not in ctx:
        _agendar(ctx, agora, m, rng)
    piso = piso_vencido(ctx, agora, m)
    prox = ctx["_passivas_proxima"]
    if not piso and (prox is None or agora < prox):
        return None
    cheia = sum(1 for u in _usos(ctx, agora) if u[1] != ATENCAO) >= _vida(ctx)["passivas_hora"]
    if cheia and not piso:
        return None
    ps = {} if cheia else pesos(ctx, agora)  # cota da hora cheia: o piso vira atenção (fora de cota)
    if not ps:
        if piso:
            ctx["_passivas_usos"].append((agora, ATENCAO))
            return Disparo(ATENCAO, "piso")
        return None  # nada cabe agora: tenta de novo no próximo sorteio
    chaves = list(ps)
    chave = rng.choices(chaves, weights=[ps[c] for c in chaves], k=1)[0]
    ctx["_passivas_usos"].append((agora, chave))
    _agendar(ctx, agora, m, rng)
    return Disparo(chave, "piso" if piso else "passiva")
