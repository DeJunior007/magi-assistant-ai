"""Alertas proativos (5.3): sysfs falso, relógio falso, orçamento falso, HUD e satélite falsos."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from magi.common.config import ConfigError
from magi.common.contracts import (
    BudgetStatus,
    CardLevel,
    CardMsg,
    PlaybackDone,
    SatelliteHello,
    SubtitleMsg,
    TurnState,
)
from magi.core.proactive import Outcome, Priority, ProactiveSink
from magi.core.proactive.alerts import TZ, AlertMonitor, AlertsConfig
from magi.core.turn import TurnDeps, TurnMachine, TurnPipeline


class Hud:
    def __init__(self) -> None:
        self.msgs: list = []

    async def send(self, msg) -> None:
        self.msgs.append(msg)

    def cards(self) -> list[CardMsg]:
        return [m for m in self.msgs if isinstance(m, CardMsg)]

    def subtitles(self) -> list[str]:
        return [m.text for m in self.msgs if isinstance(m, SubtitleMsg)]


class Target:
    """Satélite falso: fica ocupado por ``busy_for`` tentativas; cada fala o ocupa por ``speak_for``."""

    def __init__(self, *, in_call: bool = False, busy_for: int = 0, speak_for: int = 0) -> None:
        self.in_call = in_call
        self.busy_for = busy_for
        self.speak_for = speak_for
        self.said: list[str] = []
        self.attempts = 0

    async def announce(self, text, expression=None) -> bool:
        self.attempts += 1
        if self.busy_for > 0:
            self.busy_for -= 1
            return False
        self.said.append(text)
        self.busy_for = self.speak_for
        return True


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class FakeBudget:
    def __init__(self, spent: float = 0.0, cap: float = 10.0) -> None:
        self.st = BudgetStatus(spent, cap)

    async def status(self) -> BudgetStatus:
        return self.st


async def no_sleep(_s: float) -> None:
    return None


def hwmon(sysfs: Path, idx: int, name: str, **temps: int) -> Path:
    d = sysfs / "class" / "hwmon" / f"hwmon{idx}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "name").write_text(name + "\n")
    for f, v in temps.items():
        (d / f).write_text(f"{v}\n")
    return d


def set_temp(d: Path, f: str, c: float) -> None:
    (d / f).write_text(f"{int(c * 1000)}\n")


def battery(sysfs: Path, name: str, pct: int, status: str = "Discharging", scope: str = "Device") -> None:
    d = sysfs / "class" / "power_supply" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "scope").write_text(scope + "\n")
    (d / "capacity").write_text(f"{pct}\n")
    (d / "status").write_text(status + "\n")


def rig(tmp_path: Path, target: Target | None = None, **kw):
    hud = Hud()
    t = target or Target()
    clock = Clock()
    sink = ProactiveSink(hud, lambda: [t], sleep=no_sleep, clock=clock)
    cfg = AlertsConfig(sysfs=tmp_path, cooldown_s=600)
    mon = AlertMonitor(sink, cfg, clock=clock, **kw)
    return hud, t, clock, sink, mon


# -- entrega ---------------------------------------------------------------------------------


async def test_alerta_por_voz_fora_de_call(tmp_path) -> None:
    hwmon(tmp_path, 0, "k10temp", temp1_input=95000)
    hud, t, _, sink, mon = rig(tmp_path)
    await mon.check()
    await sink.drain()
    assert t.said == ["Ei, a CPU tá em 95 graus. Dá uma olhada aí."]
    assert [c.title for c in hud.cards()] == ["CPU a 95 °C"]
    assert hud.subtitles() == []  # a legenda vem do próprio satélite ao falar (announce)


async def test_alerta_so_na_tela_em_call(tmp_path) -> None:
    hwmon(tmp_path, 0, "amdgpu", temp1_input=70000, temp2_input=101000)
    hud, t, _, sink, mon = rig(tmp_path, Target(in_call=True))
    await mon.check()
    await sink.drain()
    assert t.said == [] and t.attempts == 0
    assert [c.title for c in hud.cards()] == ["GPU a 101 °C"]
    assert hud.subtitles() == ["Ei, a GPU tá em 101 graus. Dá uma olhada aí."]


async def test_nunca_interrompe_e_enfileira(tmp_path) -> None:
    hud = Hud()
    t = Target(busy_for=3, speak_for=2)
    sink = ProactiveSink(hud, lambda: [t], sleep=no_sleep)
    assert await sink.deliver("a", "primeiro") is Outcome.QUEUED
    assert await sink.deliver("b", "segundo") is Outcome.QUEUED
    await sink.drain()
    assert t.said == ["primeiro", "segundo"]
    assert t.attempts == 3 + 1 + 2 + 1  # ocupado, fala, ocupado com a 1ª fala, fala
    await sink.aclose()


async def test_call_comecou_durante_a_espera_vai_para_a_tela() -> None:
    hud = Hud()
    t = Target(busy_for=10)

    async def sleep(_s: float) -> None:
        t.in_call = True

    sink = ProactiveSink(hud, lambda: [t], sleep=sleep)
    await sink.deliver("x", "aviso")
    await sink.drain()
    assert t.said == [] and hud.subtitles() == ["aviso"]


async def test_espera_demais_vai_para_a_tela() -> None:
    hud, clock = Hud(), Clock()
    t = Target(busy_for=1000)

    async def sleep(s: float) -> None:
        clock.t += s

    sink = ProactiveSink(hud, lambda: [t], sleep=sleep, clock=clock, max_wait_s=5)
    await sink.deliver("x", "aviso")
    await sink.drain()
    assert t.said == [] and hud.subtitles() == ["aviso"]


async def test_prioridade_tela_e_sem_satelite() -> None:
    hud = Hud()
    t = Target()
    sink = ProactiveSink(hud, lambda: [t])
    card = CardMsg(CardLevel.ALTA, "Notícia")
    assert await sink.deliver("news", "texto", card, Priority.SCREEN) is Outcome.SCREEN
    assert await ProactiveSink(hud).deliver("x", "sem satélite") is Outcome.SCREEN
    assert t.said == [] and hud.cards() == [card]
    assert hud.subtitles() == ["texto", "sem satélite"]


# -- histerese e cooldown ------------------------------------------------------------------------


async def test_histerese_e_cooldown(tmp_path) -> None:
    d = hwmon(tmp_path, 3, "k10temp", temp1_input=91000)
    _, t, clock, sink, mon = rig(tmp_path)

    async def step(c: float) -> int:
        set_temp(d, "temp1_input", c)
        await mon.check_temps()
        await sink.drain()
        return len(t.said)

    assert await step(91) == 1
    assert await step(87) == 1  # entre os limiares: continua no mesmo episódio
    assert await step(93) == 1
    assert await step(80) == 1  # esfriou: alarme fecha
    clock.t += 60
    assert await step(92) == 1  # novo episódio, mas dentro do cooldown
    clock.t += 600
    assert await step(92) == 2  # cooldown venceu e segue quente: avisa
    assert await step(92) == 2


async def test_sem_sensor_nao_avisa(tmp_path) -> None:
    hwmon(tmp_path, 0, "nvme", temp1_input=99000)
    _, t, _, sink, mon = rig(tmp_path)
    await mon.check()
    await sink.drain()
    assert t.said == []


# -- bateria ---------------------------------------------------------------------------------------


async def test_bateria_do_controle(tmp_path) -> None:
    battery(tmp_path, "ps-controller-battery-aa:bb", 50)
    battery(tmp_path, "BAT0", 5, scope="System")  # bateria do notebook: ignorada
    hud, t, clock, sink, mon = rig(tmp_path)

    async def step(pct: int, status: str = "Discharging") -> int:
        battery(tmp_path, "ps-controller-battery-aa:bb", pct, status)
        await mon.check_batteries()
        await sink.drain()
        return len(t.said)

    assert await step(50) == 0
    assert await step(15) == 1
    assert t.said[0] == "Bateria do controle em 15%. Bom pôr pra carregar."
    assert hud.cards()[-1].title == "Controle com 15% de bateria"
    assert await step(12) == 1
    assert await step(12, "Charging") == 1  # carregando fecha o alarme
    clock.t += 601
    assert await step(10) == 2
    assert await step(18) == 2  # abaixo do limiar de liberação: mesmo episódio


# -- custo -----------------------------------------------------------------------------------------


async def test_custo_80_e_100_uma_vez_por_mes(tmp_path) -> None:
    budget = FakeBudget(5.0, 10.0)
    now = [datetime(2026, 10, 2, 12, tzinfo=TZ)]
    state = tmp_path / "data" / "alerts_state.json"
    hud, t, _, sink, mon = rig(tmp_path, budget=budget, state_path=state, now=lambda: now[0])

    async def step(spent: float) -> list[str]:
        budget.st = BudgetStatus(spent, 10.0)
        await mon.check_cost()
        await sink.drain()
        return t.said

    assert await step(5.0) == []
    assert len(await step(8.0)) == 1 and "80% do teto" in t.said[0]
    assert len(await step(9.0)) == 1
    assert len(await step(10.0)) == 2 and "teto do mês" in t.said[1]
    assert hud.cards()[-1].level is CardLevel.BOMBA
    assert len(await step(11.0)) == 2

    # reinício: o estado gravado evita repetir no mesmo mês
    hud2, t2, _, sink2, mon2 = rig(tmp_path, budget=budget, state_path=state, now=lambda: now[0])
    await mon2.check_cost()
    await sink2.drain()
    assert t2.said == []

    # mês novo: volta a avisar; pular direto para 100% avisa uma vez só
    now[0] = datetime(2026, 11, 1, 9, tzinfo=TZ)
    assert len(await step(10.5)) == 3 and "teto do mês" in t.said[2]
    assert len(await step(10.5)) == 3


async def test_on_warn_do_orcamento_avisa_na_hora(tmp_path) -> None:
    _, t, _, sink, mon = rig(tmp_path, now=lambda: datetime(2026, 10, 2, tzinfo=TZ))
    await mon.check_cost(BudgetStatus(8.1, 10.0))
    await mon.check_cost(BudgetStatus(8.2, 10.0))
    await sink.drain()
    assert len(t.said) == 1


# -- config ------------------------------------------------------------------------------------------


def test_config_alerts() -> None:
    cfg = AlertsConfig.from_raw({"poll_s": 15, "cpu_warn_c": 88, "cpu_clear_c": 80, "cost": False})
    assert cfg.poll_s == 15.0 and cfg.cpu_warn_c == 88.0 and cfg.cost is False
    assert AlertsConfig.from_raw(None) == AlertsConfig()
    with pytest.raises(ConfigError):
        AlertsConfig.from_raw({"cpu_warn_c": 80, "cpu_clear_c": 85})
    with pytest.raises(ConfigError):
        AlertsConfig.from_raw({"battery_pct": "x"})


# -- TurnMachine.announce -----------------------------------------------------------------------------


class Link:
    hello = SatelliteHello(satellite="pc")

    async def send(self, msg) -> None:
        pass

    async def play(self, audio, fmt) -> None:
        pass


class Speaker:
    def __init__(self) -> None:
        self.said: list[tuple[str, bool]] = []

    async def say(self, text, link, *, personal: bool) -> None:
        self.said.append((text, personal))


async def test_turn_machine_announce() -> None:
    speaker, hud = Speaker(), Hud()
    m = TurnMachine(Link(), hud, TurnPipeline(TurnDeps(speaker=speaker)))
    assert await m.announce("CPU quente.")
    assert m.state is TurnState.SPEAKING
    assert not await m.announce("outro")  # nunca interrompe
    await asyncio.sleep(0)  # deixa a tarefa da fala rodar
    assert not m.busy and not await m.announce("outro")  # ainda falando (até o playback-done)
    await m.handle(PlaybackDone())
    assert m.state is TurnState.SLEEPING
    assert speaker.said == [("CPU quente.", False)]
    assert hud.subtitles() == ["CPU quente."]
    await m.close()
