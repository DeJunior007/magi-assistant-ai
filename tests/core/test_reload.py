"""Recarga da config sem reiniciar (1.22): arquivo temporário e debounce falso."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from collections.abc import AsyncIterable
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from magi.common.config import PathsConfig, load_config
from magi.common.contracts import BudgetExceeded, CardMsg, PcmFormat, ProviderTask, SatelliteHello, Usage
from magi.core.assemble import SwitchBudget
from magi.core.budget import MonthlyBudget
from magi.core.reload import ConfigReloader, changed_sections
from magi.core.tts import PhraseCache, Phrases, PhraseSpeaker
from magi.providers.registry import Registry

FMT = PcmFormat(rate=24_000)

BASE = """
[providers.fake]
keys = ["fake-1"]

[tasks.tts]
provider = "fake"
model = "tts-1"
voice = "{voice}"

[tasks.agent]
provider = "fake"
model = "chat-1"

[budget]
monthly_usd = {cap}

[database]
dsn = "{dsn}"
"""


def write(path: Path, *, voice: str = "nova", cap: float = 5.0, dsn: str = "postgresql://a@h/db") -> None:
    path.write_text(BASE.format(voice=voice, cap=cap, dsn=dsn), encoding="utf-8")


class FakeBackend:
    def __init__(self, pcfg: object) -> None:
        self.built = 1

    def tts_format(self, ctx: object) -> PcmFormat:
        return FMT

    async def synthesize(self, key: object, ctx, text: str):  # noqa: ANN001
        yield f"{ctx.options.get('voice')}:{text}".encode()


class CostsRepo:
    def __init__(self, total: float) -> None:
        self.total = total

    async def add(self, usage: Usage, at: datetime) -> int:
        return 1

    async def month_total(self, year: int, month: int) -> float:
        return self.total


class FakeLink:
    hello = SatelliteHello("pc")

    def __init__(self) -> None:
        self.plays: list[bytes] = []

    async def send(self, msg: object) -> None:  # pragma: no cover
        pass

    async def play(self, audio: AsyncIterable[bytes], fmt: PcmFormat) -> None:
        self.plays.append(b"".join([c async for c in audio]))


class FakeHud:
    def __init__(self) -> None:
        self.sent: list[object] = []

    async def send(self, msg: object) -> None:
        self.sent.append(msg)


class Gate:
    """Debounce falso: ``sleep`` só volta quando o teste libera."""

    def __init__(self) -> None:
        self.calls: list[float] = []
        self.event = asyncio.Event()

    async def __call__(self, s: float) -> None:
        self.calls.append(s)
        await self.event.wait()


@pytest.fixture
def world(tmp_path: Path):
    path = tmp_path / "config.toml"
    write(path)
    cfg = load_config(path)
    local = dataclasses.replace(cfg, paths=PathsConfig(tmp_path, tmp_path))
    budget = SwitchBudget(MonthlyBudget.from_config(local, CostsRepo(3.0)))
    reg = Registry(cfg, budget, backends={"fake": FakeBackend}, get_secret=lambda name: "s3cr3t")
    speaker = PhraseSpeaker(
        reg.tts, phrases=Phrases.build(["Cancelado."]), cache=PhraseCache(tmp_path / "tts"), auto_warm=False
    )
    core = SimpleNamespace(
        providers=reg, budget=budget, deps=SimpleNamespace(speaker=speaker, stt=None, agent=None),
        alerts=None, news=None, news_feedback=None, self_model=None,
    )
    hud = FakeHud()
    gate = Gate()
    reloader = ConfigReloader(core, cfg, hud, path=path, sleep=gate)
    return SimpleNamespace(path=path, reg=reg, speaker=speaker, core=core, hud=hud, gate=gate, r=reloader)


async def save_and_reload(w, **kw) -> None:
    write(w.path, **kw)
    w.r.changed()
    w.r.changed()  # rajada do editor: um só reload
    await asyncio.sleep(0)
    w.gate.event.set()
    await w.r.settle()
    w.gate.event.clear()


async def test_trocar_voz_muda_a_proxima_fala_e_invalida_o_cache(world) -> None:
    link = FakeLink()
    await world.speaker.say("Cancelado.", link, personal=False)
    await world.speaker.say("Cancelado.", link, personal=False)  # do cache
    key_old = world.speaker.key("Cancelado.")
    assert link.plays == [b"nova:Cancelado."] * 2
    agent_before = world.reg.chat()

    await save_and_reload(world, voice="shimmer")

    assert world.gate.calls == [0.5]  # debounce colapsou a rajada
    assert world.reg.tts().voice == "shimmer"
    assert world.speaker.key("Cancelado.") != key_old
    await world.speaker.say("Cancelado.", link, personal=False)
    assert link.plays[-1] == b"shimmer:Cancelado."  # regenerado com a voz nova
    assert world.speaker.key("Cancelado.") in world.speaker.cache
    assert world.reg.chat() is agent_before  # só a tarefa afetada foi refeita


async def test_trocar_teto_do_orcamento_vale_na_hora(world) -> None:
    await world.core.budget.ensure_allowed(ProviderTask.AGENT)  # gasto 3 de 5
    await save_and_reload(world, cap=2.0)
    assert (await world.core.budget.status()).cap_usd == 2.0
    with pytest.raises(BudgetExceeded):
        await world.core.budget.ensure_allowed(ProviderTask.AGENT)


async def test_config_invalida_mantem_a_anterior(world, caplog) -> None:
    world.path.write_text("[tasks.tts\nprovider = ", encoding="utf-8")
    with caplog.at_level(logging.ERROR):
        assert await world.r.reload() is False
    assert world.r.current.tasks["tts"].options["voice"] == "nova"
    assert world.reg.tts().voice == "nova"
    assert "mantendo o anterior" in caplog.text
    assert len(world.hud.sent) == 1 and isinstance(world.hud.sent[0], CardMsg)

    # seção a quente malformada também recusa tudo
    write(world.path, voice="shimmer")
    world.path.write_text(world.path.read_text() + "\n[alerts]\npoll_s = \"x\"\n", encoding="utf-8")
    assert await world.r.reload() is False
    assert world.reg.tts().voice == "nova"


async def test_secao_que_exige_reinicio_so_loga(world, caplog) -> None:
    with caplog.at_level(logging.WARNING):
        await save_and_reload(world, dsn="postgresql://b@h/outro")
    assert "mudança em [database] exige reiniciar o magi-core" in caplog.text
    assert world.reg.tts().voice == "nova"
    assert world.hud.sent == []


def test_changed_sections_por_subchave_de_news(tmp_path: Path) -> None:
    a = load_config(_toml(tmp_path / "a.toml", "[news.delivery]\nmax_per_day = 3\n[news.sources]\nx = 1\n"))
    b = load_config(_toml(tmp_path / "b.toml", "[news.delivery]\nmax_per_day = 4\n[news.sources]\nx = 1\n"))
    assert changed_sections(a, b) == {"news.delivery"}


def _toml(p: Path, text: str) -> Path:
    p.write_text(text, encoding="utf-8")
    return p
