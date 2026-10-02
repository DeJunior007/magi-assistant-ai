"""Testes das correções (tarefa 1.6) com repositório falso."""

from __future__ import annotations

from datetime import datetime

import pytest

from magi.common.contracts import (
    ActionRequest,
    ActionResult,
    Correction,
    CorrectionsRepo,
    Corrector,
    Intent,
    IntentId,
    RouteKind,
    RouteResult,
    Slot,
    SlotName,
    Transcript,
    TurnContext,
    WakeSource,
)
from magi.core.actions import Registry
from magi.core.corrections import (
    SAY_NOTHING_TO_FIX,
    SAY_SAME,
    CorrectionHandler,
    Corrections,
    deduce_pair,
    handlers,
)
from magi.core.turn import TurnDeps, TurnPipeline


class FakeRepo:
    def __init__(self, items: list[tuple[str, str]] = ()) -> None:
        self.rows: dict[int, Correction] = {}
        self.bumps: list[int] = []
        self.fail = False
        for h, c in items:
            self._put(h, c)

    def _put(self, heard: str, correct: str) -> Correction:
        old = next((r for r in self.rows.values() if r.heard == heard), None)
        cid = old.id if old else len(self.rows) + 1
        row = Correction(heard, correct, 0, datetime(2026, 1, 1), cid)
        self.rows[cid] = row
        return row

    async def add(self, heard: str, correct: str) -> Correction:
        return self._put(heard, correct)

    async def all(self) -> list[Correction]:
        if self.fail:
            raise RuntimeError("banco fora")
        return list(self.rows.values())

    async def bump(self, correction_id: int) -> None:
        self.bumps.append(correction_id)

    async def delete(self, correction_id: int) -> None:
        self.rows.pop(correction_id, None)


CTX = TurnContext(satellite="pc", source=WakeSource.WAKE, started_at=datetime(2026, 1, 1))


def fix_req(text: str, slot: str | None = None, **args) -> ActionRequest:
    slots = (Slot(SlotName.TEXT, slot, raw=slot),) if slot else ()
    return ActionRequest(Intent(IntentId.CORRECTION, slots), CTX, text=text, args=args)


def test_protocolos():
    assert isinstance(FakeRepo(), CorrectionsRepo)
    assert isinstance(Corrections(FakeRepo()), Corrector)
    assert [h.intents for h in handlers(Corrections(FakeRepo()))] == [frozenset({"correction.fix"})]


async def test_substitui_com_fronteira_sem_acento_e_caixa():
    repo = FakeRepo([("valoran", "Valorant"), ("abre o", "abre o")])
    c = Corrections(repo)
    t = await c.apply(Transcript.raw("Abre o VALORAN agora, valorante não"))
    assert t.final == "Abre o Valorant agora, valorante não"
    assert t.heard == "Abre o VALORAN agora, valorante não"
    assert repo.bumps == [1]


async def test_acento_e_frase_maior_primeiro():
    repo = FakeRepo([("cão", "X"), ("o cao de guarda", "Watch Dogs")])
    t = await Corrections(repo).apply(Transcript.raw("abre o Cão de Guarda"))
    assert t.final == "abre Watch Dogs"
    assert repo.bumps == [2]


async def test_fuzzy_so_em_frase_curta():
    repo = FakeRepo([("cyberpunque", "Cyberpunk")])
    c = Corrections(repo)
    assert (await c.apply(Transcript.raw("abre ciberpunque"))).final == "abre Cyberpunk"
    longa = "quero muito jogar um pouco de ciberpunque hoje"
    assert (await c.apply(Transcript.raw(longa))).final == longa
    # limiar alto: palavra só parecida não troca
    assert (await c.apply(Transcript.raw("abre cyber"))).final == "abre cyber"


async def test_sem_correcoes_e_banco_fora():
    repo = FakeRepo([("a", "b")])
    repo.fail = True
    t = Transcript.raw("abre a porta")
    assert await Corrections(repo).apply(t) == t
    assert repo.bumps == []


@pytest.mark.parametrize(
    ("prev", "said", "pair"),
    [
        ("abre o valoran", "abre o valorant", ("valoran", "valorant", "abre o valorant")),
        ("abre o valoran", "valorant", ("valoran", "valorant", "abre o valorant")),
        ("abre o valoran", "o Valorant", ("valoran", "Valorant", "abre o Valorant")),
        ("toca rock no spot", "toca rock no Spotify", ("spot", "Spotify", "toca rock no Spotify")),
        ("abre o Dota dois", "abre o dota 2", ("dois", "2", "abre o Dota 2")),
    ],
)
def test_deduz_par(prev, said, pair):
    assert deduce_pair(prev, said) == pair


def test_deduz_par_igual():
    assert deduce_pair("abre o valorant", "Abre o Valorant") is None
    assert deduce_pair("", "x") is None


async def test_nao_eu_falei_refaz_turno():
    repo = FakeRepo()
    corr = Corrections(repo)
    seen: list[str] = []

    class Router:
        def route(self, text, ctx):
            if text.startswith("não"):
                return RouteResult(RouteKind.LOCAL, text, 99, fix_intent)
            seen.append(text)
            return RouteResult(RouteKind.LOCAL, text, 99, Intent(IntentId.GAME_OPEN))

    class Game:
        intents = frozenset({IntentId.GAME_OPEN.value})

        async def run(self, req):
            return ActionResult(ok=True, speech=f"Abrindo: {req.text}.")

    fix_intent = Intent(IntentId.CORRECTION, (Slot(SlotName.TEXT, "Valorant"),))
    fix = CorrectionHandler(corr)
    pipe = TurnPipeline(TurnDeps(corrector=corr, router=Router(), actions=Registry([fix, Game()])))
    fix.redo = pipe.respond

    t1 = await corr.apply(Transcript.raw("abre o valoran"))
    await pipe.respond(t1, CTX)
    t2 = await corr.apply(Transcript.raw("não, eu falei Valorant"))
    res = await pipe.respond(t2, CTX)

    assert res.ok and res.speech == "Anotado. Abrindo: abre o Valorant."
    assert seen == ["abre o valoran", "abre o Valorant"]
    assert [(c.heard, c.correct) for c in repo.rows.values()] == [("valoran", "Valorant")]
    # próxima vez já sai corrigido, antes do roteador
    assert (await corr.apply(Transcript.raw("abre o Valoran"))).final == "abre o Valorant"
    assert corr.previous().final == "abre o Valorant"


async def test_sem_redo_devolve_texto_corrigido():
    corr = Corrections(FakeRepo())
    res = await CorrectionHandler(corr).run(
        fix_req("não, eu falei dota 2", previous_text="abre o dota dois")
    )
    assert res.ok and res.full_text == "abre o dota 2"
    assert (await corr.apply(Transcript.raw("Dota dois"))).final == "Dota 2"


async def test_texto_do_req_sem_slot_e_casos_sem_correcao():
    corr = Corrections(FakeRepo())
    h = CorrectionHandler(corr)
    assert (await h.run(fix_req("não, eu falei X"))).speech == SAY_NOTHING_TO_FIX
    await corr.apply(Transcript.raw("abre o valorant"))
    await corr.apply(Transcript.raw("não, eu disse abre o valorant"))
    assert (await h.run(fix_req("não, eu disse abre o valorant"))).speech == SAY_SAME
    res = await h.run(fix_req("eu falei abre o Valorant 2."))
    assert res.ok and res.full_text == "abre o valorant 2"
