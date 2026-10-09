"""LM3.5 — guardar palavra (★ no Vocabulary): CA-22 (LM-012, spec §10.3, design §11.1).

Núcleo: ``lm_save`` resolvido pelo ``action_id`` → ``save_word``/``unsave_word`` → ``lm_saved``;
``lm_saved`` depois de cada ``lm_result`` de vocabulary (inclusive do cache); ``lm_save`` de outro
``kind`` é recusado. HUD: estrela do balão com marca otimista desfeita em 3 s ou se vier contrário.
Só ``FakeModel`` e ``JsonlRepo`` (regras 6 e 7).
"""

from __future__ import annotations

import json
from typing import Any

from hud.wired.learning_overlay import (
    NOT_SAVED,
    OK,
    STAR_OFF,
    STAR_ON,
    BridgeProvider,
    Overlay,
    norm_key,
)
from hud.wired.learning_text import ActionKind as UiKind
from magi.common.contracts import HudMessage, LmActionMsg, LmModeMsg, LmResultMsg, LmSavedMsg, LmSaveMsg
from magi.learning.config import LearningConfig
from magi.learning.contracts import ActionKind, Author, Source
from magi.learning.engine import LearningEngine
from magi.learning.model import FakeModel
from magi.learning.repo import JsonlRepo
from magi.learning.wiring import LearningWiring, source_sentence

PEDRO = "I fixed the login. Yesterday I make a new authentication system! It works"
VOCAB = {"term": "Authentication", "meaning": "the process of proving who a user is",
         "in_context": "the login system you built", "pos": "noun", "cefr": "B2",
         "examples": ["We added two-factor authentication."], "synonyms": ["verification"]}
EXPLAIN = {"question": "Why make?", "answer": "Here the past tense is needed."}


class SinkHud:
    def __init__(self) -> None:
        self.sent: list[HudMessage] = []

    async def send(self, msg: HudMessage) -> None:
        self.sent.append(msg)

    def saved(self) -> list[LmSavedMsg]:
        return [m for m in self.sent if isinstance(m, LmSavedMsg)]


def _act(mid: int, piece: str, kind: ActionKind, aid: str) -> LmActionMsg:
    start = PEDRO.index(piece)
    return LmActionMsg(aid, kind, mid, start, start + len(piece))


async def _setup(tmp_path, repo: JsonlRepo | None = None) -> tuple[LearningWiring, JsonlRepo, SinkHud, int]:
    repo = repo or JsonlRepo(tmp_path)
    hud = SinkHud()
    eng = LearningEngine(FakeModel({"vocabulary:*": VOCAB, "explain:*": EXPLAIN}), repo)
    w = LearningWiring(LearningConfig(storage="jsonl"), repo, hud, None, engine=eng)  # type: ignore[arg-type]
    await w.on_learning(LmModeMsg(True))
    msg = await w.session.add_message(Author.YOU, Source.VOICE, PEDRO)
    assert msg is not None
    return w, repo, hud, msg.id


async def _do(w: LearningWiring, m: Any) -> None:
    await w.on_learning(m)
    await w.wait_idle()


async def test_guardar_desfazer_guardar_um_ativo_por_norm(tmp_path) -> None:
    w, repo, hud, mid = await _setup(tmp_path)
    await _do(w, _act(mid, "authentication", ActionKind.VOCABULARY, "ACT-00000001"))
    # lm_saved logo depois do lm_result de vocabulary (estrela abre desmarcada)
    kinds = [type(m) for m in hud.sent if isinstance(m, LmResultMsg | LmSavedMsg)]
    assert kinds == [LmResultMsg, LmSavedMsg]
    assert hud.saved()[-1] == LmSavedMsg("authentication", False)

    await _do(w, LmSaveMsg("ACT-00000001", True))
    first = hud.saved()[-1]
    assert first.norm == "authentication" and first.saved and first.id is not None
    [word] = await repo.saved_words()
    assert (word.term, word.norm, word.pos, word.cefr) == ("Authentication", "authentication", "noun", "B2")
    assert word.example == "Yesterday I make a new authentication system!"  # só a frase da seleção
    assert word.message_id == mid and word.action_id == "ACT-00000001"

    await _do(w, LmSaveMsg("ACT-00000001", True))  # já ativo: não duplica, só confirma
    assert hud.saved()[-1] == first and len(await repo.saved_words()) == 1

    await _do(w, LmSaveMsg("ACT-00000001", False))
    assert hud.saved()[-1] == LmSavedMsg("authentication", False)
    assert await repo.saved_norms() == set()

    await _do(w, LmSaveMsg("ACT-00000001", True))  # de novo: linha nova
    again = hud.saved()[-1]
    assert again.saved and again.id is not None and again.id != first.id
    assert [x.id for x in await repo.saved_words()] == [again.id]  # um ativo por norm
    ops = [json.loads(line)["op"] for line in (tmp_path / "saved_words.jsonl").read_text().splitlines()]
    assert ops == ["save", "unsave", "save"]  # desfazer = marca, nunca apaga

    # cache: outra ação sobre a mesma seleção → lm_result cached + lm_saved já marcado
    await _do(w, _act(mid, "authentication", ActionKind.VOCABULARY, "ACT-00000002"))
    res = [m for m in hud.sent if isinstance(m, LmResultMsg)][-1].result
    assert res.cached and res.id == "ACT-00000002"
    assert hud.saved()[-1] == LmSavedMsg("authentication", True, again.id)
    # e o action_id do cache (que não está no banco) também resolve
    await _do(w, LmSaveMsg("ACT-00000002", False))
    assert hud.saved()[-1] == LmSavedMsg("authentication", False)
    await w.aclose()


async def test_lm_save_de_outro_kind_ou_desconhecido_e_recusado(tmp_path) -> None:
    w, repo, hud, mid = await _setup(tmp_path)
    await _do(w, _act(mid, "make", ActionKind.EXPLAIN, "ACT-0000000e"))
    assert hud.saved() == []  # lm_saved só depois de vocabulary
    await _do(w, LmSaveMsg("ACT-0000000e", True))
    await _do(w, LmSaveMsg("ACT-ffffffff", True))
    assert hud.saved() == [] and await repo.saved_words() == []

    await _do(w, LmModeMsg(False))  # fora do modo: ignorado
    await _do(w, LmSaveMsg("ACT-0000000e", True))
    assert hud.saved() == []
    await w.aclose()


class DownRepo(JsonlRepo):
    async def save_word(self, word):  # type: ignore[no-untyped-def]
        raise ConnectionError("banco fora")


async def test_banco_fora_responde_saved_false(tmp_path) -> None:
    w, repo, hud, mid = await _setup(tmp_path, DownRepo(tmp_path))
    await _do(w, _act(mid, "authentication", ActionKind.VOCABULARY, "ACT-00000003"))
    await _do(w, LmSaveMsg("ACT-00000003", True))
    assert hud.saved()[-1] == LmSavedMsg("authentication", False)  # estrela volta, "not saved"
    await w.aclose()


def test_source_sentence() -> None:
    s = PEDRO.index("authentication")
    assert source_sentence(PEDRO, s, s + 14) == "Yesterday I make a new authentication system!"
    assert source_sentence("no  end\nhere", 0, 2) == "no end here"
    assert len(source_sentence("word " * 100, 0, 4)) == 240


# ---------------------------------------------------------------------------------------------
# HUD: estrela do balão (lógica pura)
# ---------------------------------------------------------------------------------------------


class StubProvider:
    """Como o ``ModelProvider`` da tela: ``inner`` manda, ``screen.info.saved`` guarda o lm_saved."""

    def __init__(self, ok: bool = True) -> None:
        self.sent: list[tuple[str, dict]] = []
        self.inner = BridgeProvider(send=lambda t, f: self.sent.append((t, f)) is None and ok)
        self.screen = type("S", (), {"info": type("I", (), {"saved": {}})()})()

    def feed(self, norm: str, saved: bool) -> None:  # o que o LearningModel faz com lm_saved
        self.screen.info.saved[norm] = {"saved": saved, "id": 7, "at": 0.0}


def _bubble(prov: Any, now: list[float]) -> Overlay:
    o = Overlay(provider=prov, clock=lambda: now[0])
    o.phase, o.kind, o.action_id = OK, UiKind.VOCABULARY, "ui-1"
    o.result = {"id": "ui-1", "kind": "vocabulary", "ok": True, "data": dict(VOCAB)}
    return o


def test_estrela_otimista_confirmada_e_desfeita() -> None:
    now = [100.0]
    prov = StubProvider()
    o = _bubble(prov, now)
    title = o.lines()[0]
    assert title.tags == (STAR_OFF,) and title.target == "save"
    assert norm_key("  Trade-Off! ") == "trade-off"

    assert o.target("save")  # clique: manda lm_save e marca na hora
    assert prov.sent == [("lm_save", {"action_id": "ui-1", "on": True})]
    assert o.lines()[0].tags == (STAR_ON,) and o.deadline() == 103.0
    assert not o.poll()  # nada chegou ainda
    prov.feed("authentication", True)
    assert o.poll() and o.save_pending is None
    assert o.lines()[0].tags == (STAR_ON,) and NOT_SAVED not in [x.text for x in o.lines()]

    # desfazer sem resposta em 3 s → volta a ★ e "not saved"
    assert o.target("save") and o.lines()[0].tags == (STAR_OFF,)
    now[0] += 2.9
    assert not o.poll()
    now[0] += 0.2
    assert o.poll()
    lines = o.lines()
    assert lines[0].tags == (STAR_ON,) and lines[1].text == NOT_SAVED

    # resposta contrária (banco fora) → volta e "not saved"
    prov.screen.info.saved.clear()
    assert o.target("save") and o.lines()[0].tags == (STAR_ON,)
    prov.feed("authentication", False)
    assert o.poll() and o.lines()[0].tags == (STAR_OFF,) and o.lines()[1].text == NOT_SAVED


def test_estrela_reabre_marcada_e_envio_falho() -> None:
    prov = StubProvider()
    prov.feed("authentication", True)
    o = _bubble(prov, [0.0])
    o.close()
    assert o.lines() == []
    o = _bubble(prov, [0.0])  # reabrir: estado do lm_saved por norm
    assert o.lines()[0].tags == (STAR_ON,)

    down = StubProvider(ok=False)
    o = _bubble(down, [0.0])
    assert o.target("save")
    assert o.save_pending is None and o.lines()[0].tags == (STAR_OFF,) and o.lines()[1].text == NOT_SAVED

    o.kind = UiKind.EXPLAIN  # outros balões: sem estrela
    assert o.starred() is None and not o.toggle_save()
