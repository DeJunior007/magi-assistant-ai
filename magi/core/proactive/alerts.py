"""Alertas proativos (tarefa 5.3, R15.1, R15.2, R16.3).

``AlertMonitor`` acorda a cada ``poll_s`` (~12 s; só lê meia dúzia de arquivos do sysfs) e checa:

- **temperatura** de CPU (hwmon ``k10temp``/``coretemp``/``zenpower``, ``temp1_input``) e GPU
  (hwmon ``amdgpu``, ``temp2_input`` = junção, com ``temp1_input`` de reserva), como o
  ``Sensors`` do HUD;
- **bateria do controle** (``/sys/class/power_supply/*`` com ``scope=Device``, ex. DualSense):
  ``capacity <= battery_pct`` e sem carregar;
- **custo**: 80% e 100% do teto mensal (``Budget.status()``), cada nível uma vez por mês e teto
  (estado em ``<data_dir>/alerts_state.json``, para não repetir ao reiniciar). O ``on_warn`` do
  ``MonthlyBudget`` chama ``check_cost()`` na hora, sem esperar o próximo ciclo.

Histerese e cooldown (temperatura e bateria): o alarme abre ao cruzar o limiar de aviso e só
fecha ao voltar além do limiar de liberação; cada abertura avisa no máximo uma vez, e nunca antes
de ``cooldown_s`` desde o último aviso da mesma chave (se o cooldown segurou, avisa quando ele
vencer, se ainda estiver em perigo).

Entrega por ``ProactiveSink``: fora de call, fala curta + card; em call, só card e legenda.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from magi.common.config import ConfigError
from magi.common.contracts import Budget, BudgetStatus, CardLevel, CardMsg, Expression
from magi.core.proactive.sink import Priority, ProactiveSink

log = logging.getLogger(__name__)

TZ = ZoneInfo("America/Sao_Paulo")
STATE_FILE = "alerts_state.json"
COST_LEVELS = (100, 80)  # do maior para o menor


@dataclass(frozen=True, slots=True)
class AlertsConfig:
    """Seção ``[alerts]`` da config (padrões em ``config.example.toml``)."""

    enabled: bool = True
    poll_s: float = 12.0
    cooldown_s: float = 900.0
    cpu_warn_c: float = 90.0
    cpu_clear_c: float = 82.0
    gpu_warn_c: float = 95.0
    gpu_clear_c: float = 85.0
    battery_pct: int = 15
    battery_clear_pct: int = 20
    cost: bool = True
    cpu_sensors: tuple[str, ...] = ("k10temp", "coretemp", "zenpower")
    gpu_sensors: tuple[str, ...] = ("amdgpu",)
    sysfs: Path = Path("/sys")

    @classmethod
    def from_raw(cls, raw: Mapping[str, Any] | None) -> AlertsConfig:
        raw = dict(raw or {})
        d = cls()
        kw: dict[str, Any] = {}
        try:
            for name in ("enabled", "cost"):
                if name in raw:
                    if not isinstance(raw[name], bool):
                        raise ConfigError(f"alerts.{name} deve ser true/false")
                    kw[name] = raw[name]
            for name in ("poll_s", "cooldown_s", "cpu_warn_c", "cpu_clear_c", "gpu_warn_c", "gpu_clear_c"):
                if name in raw:
                    kw[name] = float(raw[name])
            for name in ("battery_pct", "battery_clear_pct"):
                if name in raw:
                    kw[name] = int(raw[name])
            for name in ("cpu_sensors", "gpu_sensors"):
                if name in raw:
                    kw[name] = tuple(str(s) for s in raw[name])
            if "sysfs" in raw:
                kw["sysfs"] = Path(raw["sysfs"])
        except (TypeError, ValueError) as e:
            raise ConfigError(f"[alerts] inválido: {e}") from e
        cfg = cls(**{**{f: getattr(d, f) for f in d.__dataclass_fields__}, **kw})
        if cfg.poll_s < 1:
            raise ConfigError("alerts.poll_s deve ser >= 1")
        if cfg.cpu_clear_c >= cfg.cpu_warn_c or cfg.gpu_clear_c >= cfg.gpu_warn_c:
            raise ConfigError("alerts: *_clear_c deve ficar abaixo de *_warn_c")
        if cfg.battery_clear_pct <= cfg.battery_pct:
            raise ConfigError("alerts.battery_clear_pct deve ficar acima de battery_pct")
        return cfg


# -- leitura do sysfs (só leitura, R8 das regras) ---------------------------------------------


def _read(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


class HwmonTemp:
    """Temperatura (°C) do primeiro hwmon cujo ``name`` está em ``names`` (ordem de preferência)."""

    def __init__(self, sysfs: Path, names: tuple[str, ...], inputs: tuple[str, ...]) -> None:
        self.root = sysfs / "class" / "hwmon"
        self.names = names
        self.inputs = inputs
        self._dir: Path | None = None

    def _find(self) -> Path | None:
        found: dict[str, Path] = {}
        with contextlib.suppress(OSError):
            for d in sorted(self.root.iterdir()):
                name = _read(d / "name")
                if name in self.names and name not in found:
                    found[name] = d
        return next((found[n] for n in self.names if n in found), None)

    def read(self) -> float | None:
        for attempt in range(2):
            if self._dir is None:
                self._dir = self._find()
                if self._dir is None:
                    return None
            for inp in self.inputs:
                raw = _read(self._dir / inp)
                if raw is not None:
                    try:
                        return int(raw) / 1000.0
                    except ValueError:
                        continue
            self._dir = None  # hwmon renumerado ou sumiu: procura de novo uma vez
            if attempt:
                break
        return None


@dataclass(frozen=True, slots=True)
class Battery:
    key: str
    pct: int
    charging: bool


def controller_batteries(sysfs: Path) -> list[Battery]:
    """Baterias de periféricos (``scope=Device``), como ``controllers()`` do HUD."""
    out: list[Battery] = []
    root = sysfs / "class" / "power_supply"
    with contextlib.suppress(OSError):
        for d in sorted(root.iterdir()):
            if _read(d / "scope") != "Device":
                continue
            cap = _read(d / "capacity")
            if cap is None or not cap.isdigit():
                continue
            status = _read(d / "status") or ""
            out.append(Battery(d.name, int(cap), status in ("Charging", "Full")))
    return out


# -- histerese + cooldown ---------------------------------------------------------------------


@dataclass(slots=True)
class Hysteresis:
    """Alarme com histerese. ``above``: perigo quando o valor sobe (temperatura); senão quando
    desce (bateria). ``should_fire`` devolve ``True`` uma vez por episódio, respeitando cooldown."""

    warn: float
    clear: float
    above: bool = True
    active: bool = False
    notified: bool = False

    def update(self, value: float, *, force_clear: bool = False) -> None:
        danger = value >= self.warn if self.above else value <= self.warn
        safe = value <= self.clear if self.above else value >= self.clear
        if force_clear or (self.active and safe):
            self.active = False
        elif not self.active and danger:
            self.active, self.notified = True, False


# -- frases ------------------------------------------------------------------------------------


def _temp_speech(part: str, temp: float) -> str:
    return f"Ei, a {part} tá em {round(temp)} graus. Dá uma olhada aí."


def _battery_speech(pct: int) -> str:
    return f"Bateria do controle em {pct}%. Bom pôr pra carregar."


def _cost_speech(level: int, st: BudgetStatus) -> str:
    if level >= 100:
        return f"Bati o teto do mês: US$ {st.spent_usd:.2f} de {st.cap_usd:.2f}. Agora só o básico."
    return f"Já foi {level}% do teto do mês: US$ {st.spent_usd:.2f} de {st.cap_usd:.2f}."


# -- monitor -----------------------------------------------------------------------------------


@dataclass
class _CostState:
    path: Path | None
    data: dict[str, Any] = field(default_factory=dict)

    def load(self) -> None:
        if self.path is None:
            return
        try:
            self.data = json.loads(self.path.read_text())
        except FileNotFoundError:
            self.data = {}
        except (OSError, ValueError) as e:
            log.warning("estado dos alertas ilegível (%s): %s; ignorando", self.path, e)
            self.data = {}

    def save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data))
            os.replace(tmp, self.path)
        except OSError as e:
            log.warning("não consegui gravar o estado dos alertas: %s", e)


class AlertMonitor:
    """Monitor assíncrono de temperatura, bateria do controle e custo (ver docstring do módulo)."""

    def __init__(
        self,
        sink: ProactiveSink,
        config: AlertsConfig | None = None,
        *,
        budget: Budget | None = None,
        state_path: Path | None = None,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.sink = sink
        self.cfg = config or AlertsConfig()
        self.budget = budget
        self._clock = clock
        self._now = now or (lambda: datetime.now(TZ))
        self._cpu = HwmonTemp(self.cfg.sysfs, self.cfg.cpu_sensors, ("temp1_input",))
        self._gpu = HwmonTemp(self.cfg.sysfs, self.cfg.gpu_sensors, ("temp2_input", "temp1_input"))
        self._alarms: dict[str, Hysteresis] = {}
        self._last: dict[str, float] = {}
        self._cost = _CostState(state_path)
        self._cost.load()
        self._cost_lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None

    # -- ciclo ----------------------------------------------------------------------------------

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def aclose(self) -> None:
        task, self._task = self._task, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _loop(self) -> None:
        while True:
            try:
                await self.check()
            except Exception:
                log.exception("checagem de alertas falhou")
            await asyncio.sleep(self.cfg.poll_s)

    async def check(self) -> None:
        """Uma rodada de todas as checagens."""
        await self.check_temps()
        await self.check_batteries()
        await self.check_cost()

    # -- regras ---------------------------------------------------------------------------------

    def _fire(self, key: str, alarm: Hysteresis) -> bool:
        if not alarm.active or alarm.notified:
            return False
        last = self._last.get(key)
        now = self._clock()
        if last is not None and now - last < self.cfg.cooldown_s:
            return False
        alarm.notified = True
        self._last[key] = now
        return True

    def _alarm(self, key: str, warn: float, clear: float, *, above: bool) -> Hysteresis:
        alarm = self._alarms.get(key)
        if alarm is None:
            alarm = self._alarms[key] = Hysteresis(warn, clear, above)
        return alarm

    async def check_temps(self) -> None:
        cfg = self.cfg
        for key, part, sensor, warn, clear in (
            ("temp:cpu", "CPU", self._cpu, cfg.cpu_warn_c, cfg.cpu_clear_c),
            ("temp:gpu", "GPU", self._gpu, cfg.gpu_warn_c, cfg.gpu_clear_c),
        ):
            temp = sensor.read()
            if temp is None:
                continue
            alarm = self._alarm(key, warn, clear, above=True)
            alarm.update(temp)
            if self._fire(key, alarm):
                text = _temp_speech(part, temp)
                card = CardMsg(CardLevel.ALTA, f"{part} a {round(temp)} °C")
                await self.sink.deliver(key, text, card, Priority.VOICE, expression=Expression.ALERT)

    async def check_batteries(self) -> None:
        cfg = self.cfg
        for bat in controller_batteries(cfg.sysfs):
            key = f"battery:{bat.key}"
            alarm = self._alarm(key, cfg.battery_pct, cfg.battery_clear_pct, above=False)
            alarm.update(bat.pct, force_clear=bat.charging)
            if self._fire(key, alarm):
                card = CardMsg(CardLevel.ALTA, f"Controle com {bat.pct}% de bateria")
                text = _battery_speech(bat.pct)
                await self.sink.deliver(key, text, card, Priority.VOICE, expression=Expression.ALERT)

    async def check_cost(self, status: BudgetStatus | None = None) -> None:
        """Avisa 80% e 100% do teto, cada nível uma vez por mês e teto. Também é o ``on_warn``
        do ``MonthlyBudget`` (recebe o status na hora em que o gasto cruza 80%)."""
        if not self.cfg.cost or (self.budget is None and status is None):
            return
        async with self._cost_lock:
            if status is None:
                assert self.budget is not None
                status = await self.budget.status()
            if status.cap_usd <= 0:
                return
            pct = status.fraction * 100
            level = next((lv for lv in COST_LEVELS if pct >= lv - 1e-9), None)
            if level is None:
                return
            month = self._now().astimezone(TZ).strftime("%Y-%m")
            mark = {"month": month, "cap": status.cap_usd}
            data = self._cost.data
            if {k: data.get(k) for k in mark} != mark:
                data.clear()
                data.update(mark, levels=[])
            if level in data["levels"]:
                return
            # 100% cobre o 80%: não avisa os dois de uma vez
            data["levels"] = sorted({*data["levels"], *(lv for lv in COST_LEVELS if lv <= level)})
            self._cost.save()
        text = _cost_speech(level, status)
        card_level = CardLevel.BOMBA if level >= 100 else CardLevel.ALTA
        await self.sink.deliver(
            f"cost:{level}", text, CardMsg(card_level, text), Priority.VOICE, expression=Expression.ALERT
        )
