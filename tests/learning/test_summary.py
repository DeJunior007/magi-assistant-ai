"""LM4.5: resumo ao sair (CA-20; spec §10.2). Só JSONL (o ``save_summary`` nos dois backends já
é coberto em ``test_repo.py``); sem LLM."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta

import pytest

from magi.common.contracts import LmModeMsg, LmSummaryMsg
from magi.learning.config import LearningConfig
from magi.learning.contracts import Author, ObsCategory, Observation, SavedWord, Source, Topic
from magi.learning.repo import JsonlRepo, SessionInfo, normalize_term
from magi.learning.session import LearningSession
from magi.learning.summary import MessageStats, summarize

T0 = datetime(2026, 10, 7, 15, 0, tzinfo=UTC)
SID = "LS-20261007-03"


def _obs(cat: ObsCategory, label: str, mid: int = 1) -> Observation:
    return Observation(None, SID, mid, cat, f"{cat}.{label.lower()}", label, None, None)


def _word(term: str) -> SavedWord:
    return SavedWord(None, normalize_term(term), term, "x", "noun", "B2", "ex", SID, 1,
                     "ACT-1", T0, None)


def _info(**kw) -> SessionInfo:
    base = dict(id=SID, started_at=T0, ended_at=None, end_reason=None, level="B2",
                track="CONVERSATION", topic=Topic.GAME,
                topics=[(Topic.FREE, T0), (Topic.GAME, T0 + timedelta(minutes=5))])
    base.update(kw)
    return SessionInfo(**base)


def test_summarize_regras():
    obs = [
        _obs(ObsCategory.GRAMMAR, "Past tense"),
        _obs(ObsCategory.VOCABULARY, "trade-off"),
        _obs(ObsCategory.GRAMMAR, "Prepositions"),
        _obs(ObsCategory.GRAMMAR, "Past tense", 2),  # repetido: não conta de novo
        _obs(ObsCategory.RECURRING, "Prepositions"),
        *[_obs(ObsCategory.GRAMMAR, f"G{i}") for i in range(4)],
        *[_obs(ObsCategory.VOCABULARY, f"w{i}") for i in range(7)],
    ]
    saved = [_word("Trade-off"), _word("leverage")]
    last = T0 + timedelta(minutes=24)
    ended = last + timedelta(minutes=20)  # cauda ociosa
    s = summarize(_info(), MessageStats(38, 19, last), obs, saved, ended_at=ended, end_reason="idle")
    assert s.n == 3 and s.session_id == SID and s.end_reason == "idle"
    assert s.duration_s == 24 * 60  # sem a cauda ociosa
    assert s.n_msgs == 38 and s.n_you == 19
    # distintos por (category, label): 6 grammar + 8 vocabulary + 1 recurring
    assert s.obs_count == 15
    assert s.practiced == ["Prepositions", "Past tense", "G0", "G1", "G2"]
    assert s.more_practiced == 1
    assert s.new_words == ["trade-off", *[f"w{i}" for i in range(7)]]
    assert s.more_words == 1  # "leverage" (salva) ficou de fora; "Trade-off" já estava
    assert s.saved == ["Trade-off", "leverage"]
    assert s.topics == ["free", "game"]


def test_summarize_sem_mensagem_usa_ended_at():
    ended = T0 + timedelta(minutes=3)
    s = summarize(_info(topics=[]), MessageStats(0, 0, None), [], [], ended_at=ended,
                  end_reason="button")
    assert s.duration_s == 180 and s.topics == ["game"]
    assert s.practiced == [] and s.new_words == [] and s.more_words == 0 and s.obs_count == 0


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


class Sink:
    """Imita o caminho do ``wiring``: ``end()`` e logo depois ``send(lm_mode off)``."""

    def __init__(self) -> None:
        self.sent: list[tuple[float, object]] = []

    async def send(self, msg) -> None:
        self.sent.append((time.monotonic(), msg))

    def types(self) -> list[str]:
        return [m.T for _, m in self.sent]


class SlowRepo(JsonlRepo):
    def __init__(self, root, delay: float) -> None:
        super().__init__(root)
        self.delay = delay

    async def session_stats(self, session_id):
        await asyncio.sleep(self.delay)
        return await super().session_stats(session_id)


async def _close(s: LearningSession, sink: Sink, reason: str = "button") -> float:
    t = time.monotonic()
    await s.end(reason)
    await sink.send(LmModeMsg(False))
    return time.monotonic() - t


async def _run(repo, clock, sink, *, you: int, reason: str = "button") -> tuple[LearningSession, float]:
    s = LearningSession(repo, LearningConfig(storage="jsonl"), clock=clock, send=sink.send)
    info, _ = await s.start()
    for i in range(you):
        clock.now += timedelta(minutes=1)
        m = await s.add_message(Author.YOU, Source.TEXT, f"I goed {i}")
        await s.add_message(Author.CONDESSA, Source.TEXT, "ok")
        await repo.add_observation(Observation(None, info.id, m.id, ObsCategory.GRAMMAR,
                                               "grammar.past_simple.irregular", "Past tense",
                                               "goed", "went"))
    clock.now += timedelta(minutes=30)
    took = await _close(s, sink, reason)
    await s.wait_summaries()
    return s, took


async def test_resumo_publicado_depois_do_off_e_gravado(tmp_path):
    repo, clock, sink = JsonlRepo(tmp_path), Clock(), Sink()
    s, _ = await _run(repo, clock, sink, you=2)
    assert sink.types() == ["lm_mode", "lm_summary"]
    msg = sink.sent[1][1]
    assert isinstance(msg, LmSummaryMsg)
    assert msg.summary.n_you == 2 and msg.summary.n_msgs == 4
    assert msg.summary.duration_s == 120  # sem os 30 min ociosos
    assert msg.summary.obs_count == 1 and msg.summary.practiced == ["Past tense"]
    stored = await JsonlRepo(tmp_path).get_session(msg.summary.session_id)
    assert stored is not None and stored.summary == msg.summary == s.last_summary


@pytest.mark.parametrize("you, reason", [(0, "button"), (2, "shutdown")])
async def test_sem_envio_mas_gravado(tmp_path, you, reason):
    repo, clock, sink = JsonlRepo(tmp_path), Clock(), Sink()
    s, _ = await _run(repo, clock, sink, you=you, reason=reason)
    assert "lm_summary" not in sink.types()
    assert s.last_summary is not None and s.last_summary.end_reason == reason
    stored = await JsonlRepo(tmp_path).get_session(s.last_summary.session_id)
    assert stored is not None and stored.summary == s.last_summary


async def test_repo_lento_off_em_50ms_e_resumo_depois(tmp_path):
    repo, clock, sink = SlowRepo(tmp_path, 0.0), Clock(), Sink()
    s = LearningSession(repo, LearningConfig(storage="jsonl"), clock=clock, send=sink.send)
    await s.start()
    clock.now += timedelta(minutes=2)
    await s.add_message(Author.YOU, Source.VOICE, "hello there")
    repo.delay = 2.0  # banco lento no fechamento
    took = await _close(s, sink)
    assert took <= 0.05
    assert sink.types() == ["lm_mode"]
    await s.wait_summaries()
    assert sink.types() == ["lm_mode", "lm_summary"]
    (t_off, _), (t_sum, msg) = sink.sent
    assert t_sum > t_off
    # o prazo de 2 s estourou: resumo da contagem guardada na sessão
    assert msg.summary.n_you == 1 and msg.summary.n_msgs == 1 and msg.summary.duration_s == 120
