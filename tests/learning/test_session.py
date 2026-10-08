"""LM1.3: sessão do Learning Mode (IDs ``LS-``, retomada, fim por inatividade; spec §10)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from magi.learning.config import LearningConfig
from magi.learning.contracts import SESSION_ID_RE, Author, Source
from magi.learning.repo import JsonlRepo
from magi.learning.session import LearningSession


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 7, 15, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw: float) -> None:
        self.now += timedelta(**kw)


@pytest.fixture
def clock() -> Clock:
    return Clock()


def _session(tmp_path, clock: Clock, **cfg) -> LearningSession:
    return LearningSession(JsonlRepo(tmp_path), LearningConfig(storage="jsonl", **cfg), clock=clock)


async def test_cria_sessao_ls_nova(tmp_path, clock) -> None:
    s = _session(tmp_path, clock)
    assert not s.active and s.id is None
    info, resumed = await s.start()
    assert not resumed and s.active
    assert SESSION_ID_RE.match(info.id) and info.id.endswith("-01")
    assert info.level == "B2" and info.track == "CONVERSATION"
    again, resumed = await s.start()  # já ativa: só devolve a atual
    assert resumed and again.id == info.id


async def test_retoma_sessao_aberta_recente(tmp_path, clock) -> None:
    s = _session(tmp_path, clock)
    info, _ = await s.start()
    await s.add_message(Author.YOU, Source.TEXT, "hello there")
    clock.advance(minutes=10)
    # núcleo reiniciado: outra instância, mesmo repositório em disco
    s2 = _session(tmp_path, clock)
    again, resumed = await s2.start()
    assert resumed and again.id == info.id
    assert s2.n_msgs == 1
    assert [m.text for m in await s2.recent()] == ["hello there"]


async def test_sessao_aberta_velha_fecha_por_idle_e_abre_nova(tmp_path, clock) -> None:
    s = _session(tmp_path, clock)
    info, _ = await s.start()
    clock.advance(minutes=25)
    s2 = _session(tmp_path, clock)
    new, resumed = await s2.start()
    assert not resumed and new.id != info.id and new.id.endswith("-02")
    old = await s2.repo.get_session(info.id)
    assert old is not None and old.end_reason == "idle"


async def test_fim_por_motivo(tmp_path, clock) -> None:
    s = _session(tmp_path, clock)
    info, _ = await s.start()
    with pytest.raises(ValueError):
        await s.end("cansei")
    assert await s.end("button") is not None
    assert not s.active
    assert (await s.repo.get_session(info.id)).end_reason == "button"
    assert await s.end("button") is None  # sem sessão: nada


async def test_inatividade(tmp_path, clock) -> None:
    s = _session(tmp_path, clock, idle_end_min=20)
    info, _ = await s.start()
    clock.advance(minutes=15)
    await s.add_message(Author.YOU, Source.VOICE, "still here")
    clock.advance(minutes=19)
    assert not s.idle_expired()
    assert await s.end_if_idle() is None
    clock.advance(minutes=1)
    assert s.idle_expired()
    assert (await s.end_if_idle()).id == info.id
    assert not s.active
    assert (await s.repo.get_session(info.id)).end_reason == "idle"


async def test_mensagem_fora_da_sessao_e_ignorada(tmp_path, clock) -> None:
    s = _session(tmp_path, clock)
    assert await s.add_message(Author.YOU, Source.TEXT, "oi") is None
    assert await s.recent() == []
    await s.start()
    m = await s.add_message(Author.YOU, Source.VOICE, "I have went", text_final="I went")
    assert m is not None and m.text == "I have went" and m.session_id == s.id


async def test_speak_replies_vem_do_config(tmp_path, clock) -> None:
    assert _session(tmp_path, clock).speak_replies is True
    assert _session(tmp_path, clock, speak_replies=False).speak_replies is False
