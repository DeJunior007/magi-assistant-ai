"""O chat do Learning mostra as frases fixas no idioma da fala (``[speech] language``): a voz dizia
"Learning mode on" e a tela escrevia "Modo aula ligado"."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from magi.common.contracts import ActionResult, LmModeMsg, Transcript, TurnContext, WakeSource
from magi.core import i18n
from magi.learning.config import LearningConfig
from magi.learning.contracts import Author
from magi.learning.intent_action import SAY_ON
from magi.learning.repo import JsonlRepo
from magi.learning.wiring import LearningWiring


class Hud:
    def __init__(self) -> None:
        self.sent: list = []

    async def send(self, msg) -> None:
        self.sent.append(msg)


@pytest.fixture
def ingles():
    i18n.configure("en-gb")
    yield
    i18n.configure(i18n.DEFAULT)


async def test_frase_fixa_entra_no_chat_traduzida(tmp_path, ingles) -> None:
    repo = JsonlRepo(tmp_path)
    pipeline = SimpleNamespace(deps=SimpleNamespace(speaker=None, agent=None))
    w = LearningWiring(LearningConfig(storage="jsonl"), repo, Hud(), pipeline)  # type: ignore[arg-type]
    await w.on_learning(LmModeMsg(True))
    ctx = TurnContext(satellite="pc", source=WakeSource.WAKE, started_at=datetime.now(UTC))
    w.on_turn(Transcript.raw("learning mode"), ctx, ActionResult(ok=True, speech=SAY_ON))
    for _ in range(20):
        await asyncio.sleep(0.01)
    msgs = await repo.recent_messages(w.session.id)  # type: ignore[arg-type]
    hers = [m.text for m in msgs if m.author is Author.CONDESSA]
    assert hers == [i18n.tr(SAY_ON)] and hers[0] != SAY_ON
