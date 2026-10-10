"""Rosto de repouso (spec §4, acordo §2, §3, §5). Dono: V0.4 (esqueleto: V0.1).

``rosto`` monta o rosto parado (olhos, boca, fone, fundo, balanço, efeitos) a partir do momento, da
faixa de ânimo, dos filtros e da postura; ``fone_alvo`` diz onde o fone deve estar (a troca em si é
um passo de cena, P11 E2→E3, nunca um gesto). O ``ctx`` traz o que não é tipo: ``animo``,
``energia``, ``musica_nota`` (None = sem música), ``faixa_agua``, ``episodio`` (jogo em episódio),
``momento_ha_s`` e ``faixa_ha_s`` (há quanto tempo a faixa atual toca).
"""

from __future__ import annotations

from dataclasses import replace

from .estado import Postura
from .vida import Faixa, Filtro, Fone, Momento, Repouso

__all__ = ["BASE", "Postura", "fone_alvo", "rosto"]

# acordo §2, tabela: faixa → (olhos, boca, fundo)
BASE: dict[Faixa, tuple[str, str, str]] = {
    Faixa.RADIANTE: ("B1", "C5", "happy"),
    Faixa.CONTENTE: ("B1", "C10", "calm"),
    Faixa.NEUTRA: ("B1", "C1", "calm"),
    Faixa.EMBURRADA: ("B7", "C9", "calm"),
}
ENERGIA_BAIXA = 0.3  # acordo §2: energia < 0,3 → olhos B2
SAD_ANIMO = -0.55  # acordo §2: `sad` só de madrugada e com ânimo < −0,55
P10_APOS_S = 120.0  # acordo §3: mão no queixo em Trabalhando junto após 2 min
FONE_TIRA_S = 8.0  # spec §4: nota −1 põe o fone e tira depois de 8 s
SEM_AGUA = frozenset({Momento.CONVERSA, Momento.JOGANDO})
COM_P10 = frozenset({Momento.TRABALHANDO_JUNTO, Momento.ESTUDANDO})


def fone_alvo(momento: Momento, ctx: dict) -> Fone:
    """CABECA com música nota ≥ 0 e sem conversa; nota −1 só nos primeiros 8 s; −2 nem põe (CA-V5)."""
    nota = ctx.get("musica_nota")
    if nota is None or momento == Momento.CONVERSA or nota <= -2:  # noqa: PLR2004
        return Fone.PESCOCO
    if nota < 0:
        return Fone.CABECA if float(ctx.get("faixa_ha_s", 0.0)) < FONE_TIRA_S else Fone.PESCOCO
    return Fone.CABECA


def rosto(momento: Momento, faixa: Faixa, filtros: set[Filtro], postura: Postura, ctx: dict) -> Repouso:
    """O rosto parado pela tabela de faixas, fone, energia, música e episódio de jogo."""
    eyes, mouth, mood = BASE[faixa]
    madrugada = Filtro.MADRUGADA in filtros
    if madrugada and mouth == "C10":
        mouth = "C5"
    if madrugada and float(ctx.get("animo", 0.0)) < SAD_ANIMO:
        mood = "sad"
    if float(ctx.get("energia", 1.0)) < ENERGIA_BAIXA:
        eyes = "B2"
    nota = ctx.get("musica_nota")
    if nota is not None and nota >= 1 and postura.fone == Fone.CABECA:
        eyes = "B4" if nota >= 2 else "B2"  # noqa: PLR2004
    sway = False
    if ctx.get("faixa_agua") and nota is not None and nota >= 0 and momento not in SEM_AGUA:
        eyes, sway = "B3", True  # o retrato abre B2 por 1,5 s a cada 20–30 s
    efeitos: list[str] = []
    if momento in COM_P10 and (momento == Momento.ESTUDANDO
                               or float(ctx.get("momento_ha_s", 0.0)) >= P10_APOS_S):
        efeitos.append("braco:P10")  # sem a arte, o retrato fica com o braço da base
    rep = Repouso(eyes, mouth, postura.fone, mood, sway, tuple(efeitos))
    if Filtro.PEDRO_MAL in filtros:  # calma, olhando para ele
        rep = replace(rep, eyes="B1", mouth="C1", mood="calm", sway=False,
                      efeitos=(*rep.efeitos, "olhando_pedro"))
    if momento == Momento.ALERTA:
        rep = replace(rep, mood="stress")
    if ctx.get("episodio"):
        rep = replace(rep, mood="stress", efeitos=(*rep.efeitos, "sweat"))  # D2
    return rep
