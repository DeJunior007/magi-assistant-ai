"""Passivas (spec §5): 1–4, 6–14, 16, 21, 22, 23, sorteadas pelo humor. Dono: R1.1.

O ``Reactor`` chama ``sortear`` a cada 10 s. Com chance ``CHANCE`` (metade com o fator
"desempenho em jogo") sai uma passiva, escolhida por sorteio ponderado (``humor.peso``) entre as
que estão no catálogo ativo, não desligadas e fora do cooldown. Respirar/piscar contínuos do
retrato não passam por aqui; o governador ainda decide se o disparo toca.
"""

from __future__ import annotations

import random

from . import humor
from .contratos import Disparo

# Nº da planilha -> chave do catálogo
PASSIVAS: dict[int, str] = {
    1: "respirar", 2: "sacada_olhar", 3: "piscada_dupla", 4: "piscada_gato",
    6: "observando_hud", 7: "sorriso_canto", 8: "beicinho", 9: "suspiro",
    10: "cantarolando", 11: "rindo_sozinha", 12: "corando", 13: "falando_sozinha",
    14: "brilho_presilha", 16: "soprando_franja", 21: "fone_repouso", 22: "ajeitando_fone",
    23: "cabeca_ritmo",
}

CHANCE = 0.35  # chance de sair uma passiva num sorteio de 10 s
AQUECIMENTO_S = 60.0  # ao abrir o HUD ela não se mexe à toa no primeiro minuto


def _em_cooldown(ctx: dict, chave: str, agora: float) -> bool:
    d = (ctx.get("defs") or {}).get(chave)
    toques = getattr(ctx.get("estado"), "toques", None) or {}
    lista = toques.get(chave) if d is not None else None
    return bool(lista) and agora - lista[-1] < d.cooldown_s


def pesos(ctx: dict, agora: float | None = None, ativos: dict[str, float] | None = None) -> dict[str, float]:
    """Peso de cada passiva sorteável agora (só as > 0)."""
    agora = float(ctx.get("agora", 0.0)) if agora is None else agora
    ativos = humor.fatores(ctx) if ativos is None else ativos
    defs = ctx.get("defs")
    desligadas = ctx.get("desligadas") or frozenset()
    out: dict[str, float] = {}
    for n, chave in PASSIVAS.items():
        if defs is not None and chave not in defs:
            continue
        if chave in desligadas or str(n) in desligadas or _em_cooldown(ctx, chave, agora):
            continue
        p = humor.peso(chave, ativos)
        if p > 0:
            out[chave] = p
    return out


def sortear(ctx: dict, agora: float, rng: random.Random) -> Disparo | None:
    """A cada 10 s pode devolver 1 disparo passivo, pesado por ``humor.fatores(ctx)``."""
    inicio = ctx.setdefault("_passivas_inicio", agora)
    if agora - inicio < AQUECIMENTO_S:
        return None
    ativos = humor.fatores(ctx)
    ps = pesos(ctx, agora, ativos)
    chance = CHANCE / 2 if humor.DESEMPENHO_JOGO in ativos else CHANCE
    if not ps or rng.random() >= chance:
        return None
    chaves = list(ps)
    chave = rng.choices(chaves, weights=[ps[c] for c in chaves], k=1)[0]
    return Disparo(chave, "passiva")
