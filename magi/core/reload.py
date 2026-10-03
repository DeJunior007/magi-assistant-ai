"""Recarga da config sem reiniciar (tarefa 1.22; R21.1).

``ConfigReloader`` observa o ``config.toml`` do núcleo; a cada gravação (com debounce de ~500 ms,
editores gravam em rajadas) relê o arquivo e aplica a quente o que é seguro:

- ``[providers]``/``[tasks]``: ``Registry.reload`` refaz só os backends e tarefas afetados
  (modelo, voz, instructions, timeouts, reasoning_effort, chaves novas). A voz nova vale na
  próxima fala; o cache de frases da voz nova é gerado sob demanda (``PhraseSpeaker.invalidate``);
- ``[budget]``: teto e preços (``MonthlyBudget.apply_config``);
- ``[alerts]``, ``[news.delivery]``, ``[news.feedback]``: troca a ``cfg`` e liga/desliga o laço;
- ``[conversation]``: janela de continuação do serviço e dos satélites já conectados;
- ``[user]`` (e o resto da ficha): ``SelfModel.raw``.

O que exige reinício (``[database]``, ``[paths]``, ``[game]``, ``[music]``, outras chaves de
``[news]``…) só é logado. ``[satellite]`` é do ``magi-satellite``, que recarrega sozinho.
Config inválida (TOML, segredo em texto, seção malformada) → fica a anterior, erro no log e um
card discreto no HUD. O processo nunca é reiniciado.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from magi.common.config import Config, ConfigError, load_config
from magi.common.contracts import CardLevel, CardMsg, HudSink
from magi.core.proactive.alerts import AlertsConfig, HwmonTemp
from magi.core.proactive.news import DeliveryConfig
from magi.core.turn import followup_ms_from_config

log = logging.getLogger(__name__)

DEBOUNCE_S = 0.5
#: Seções aplicadas a quente (``news`` tem tratamento por subchave).
HOT = frozenset({"providers", "tasks", "budget", "alerts", "conversation", "user"})
HOT_NEWS = frozenset({"delivery", "feedback"})
#: Seções de outros processos: ignoradas aqui.
FOREIGN = frozenset({"satellite"})

Sleep = Callable[[float], Awaitable[None]]


def _section(raw: dict[str, Any], key: str) -> Any:
    return raw.get(key) if isinstance(raw, dict) else None


def changed_sections(old: Config, new: Config) -> set[str]:
    """Seções que mudaram; em ``[news]``, por subchave (``news.delivery``…)."""
    out: set[str] = set()
    for key in set(old.raw) | set(new.raw):
        a, b = _section(old.raw, key), _section(new.raw, key)
        if a == b:
            continue
        if key == "news" and isinstance(a or {}, dict) and isinstance(b or {}, dict):
            a, b = a or {}, b or {}
            out |= {f"news.{k}" for k in set(a) | set(b) if a.get(k) != b.get(k)}
        else:
            out.add(key)
    return out


def _hot(section: str) -> bool:
    if section.startswith("news."):
        return section.split(".", 1)[1] in HOT_NEWS
    return section in HOT


class ConfigReloader:
    """Recarga a quente do núcleo montado (``Core``). ``service``: ``CoreService`` (opcional).

    ``sleep`` existe para testes (debounce falso)."""

    def __init__(
        self,
        core: Any,
        config: Config,
        hud: HudSink | None = None,
        *,
        service: Any = None,
        path: str | os.PathLike[str] | None = None,
        debounce_s: float = DEBOUNCE_S,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self.core = core
        self.current = config
        self.hud = hud
        self.service = service
        src = path if path is not None else config.source
        if src is None:
            raise ValueError("ConfigReloader precisa do caminho do config")
        self.path = Path(src).expanduser()
        self.debounce_s = debounce_s
        self._sleep = sleep
        self._pending: asyncio.Task[None] | None = None

    # -- disparo ---------------------------------------------------------------------------

    def changed(self) -> None:
        """Arquivo gravado: (re)agenda a recarga para daqui a ``debounce_s``."""
        if self._pending is not None and not self._pending.done():
            self._pending.cancel()
        self._pending = asyncio.get_running_loop().create_task(self._debounced(), name="config-reload")

    async def _debounced(self) -> None:
        await self._sleep(self.debounce_s)
        await self.reload()

    async def settle(self) -> None:
        """Espera a recarga agendada (testes)."""
        task = self._pending
        if task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def watch(self, stop_event: asyncio.Event | None = None) -> None:
        """Observa o diretório (editores gravam por rename) e filtra pelo arquivo."""
        from watchfiles import awatch

        target = self.path.resolve()
        try:
            async for changes in awatch(target.parent, stop_event=stop_event, debounce=100):
                if any(Path(p).resolve() == target for _, p in changes) and target.exists():
                    self.changed()
        finally:
            if self._pending is not None:
                self._pending.cancel()

    # -- recarga ---------------------------------------------------------------------------

    async def reload(self) -> bool:
        """Relê e aplica. Inválida → mantém a anterior, loga e avisa no HUD."""
        try:
            new = load_config(self.path)
            parsed = self._parse_sections(new)
        except (ConfigError, TypeError, ValueError) as e:
            log.error("config inválido, mantendo o anterior: %s", e)
            await self._card(f"Config inválido, mantive o anterior: {e}")
            return False
        old, self.current = self.current, new
        sections = changed_sections(old, new)
        if not sections:
            log.info("config gravado sem mudanças")
            return True
        for sec in sorted(sections):
            if sec in FOREIGN:
                continue
            if not _hot(sec):
                log.warning("mudança em [%s] exige reiniciar o magi-core", sec)
        try:
            await self._apply(old, new, sections, parsed)
        except Exception:
            log.exception("recarga do config aplicada só em parte")
        hot = ", ".join(sorted(s for s in sections if _hot(s)))
        log.info("config recarregado: %s", hot or "nada a quente")
        return True

    @staticmethod
    def _parse_sections(cfg: Config) -> dict[str, Any]:
        """Valida as seções a quente antes de aplicar qualquer coisa (tudo ou nada)."""
        from magi.news.feedback import FeedbackConfig

        news = cfg.raw.get("news")
        news = news if isinstance(news, dict) else {}
        fb = news.get("feedback")
        return {
            "alerts": AlertsConfig.from_raw(cfg.raw.get("alerts")),
            "news.delivery": DeliveryConfig.from_raw(news.get("delivery")),
            "news.feedback": FeedbackConfig.from_raw(fb if isinstance(fb, dict) else None),
            "conversation": followup_ms_from_config(cfg.raw),
        }

    async def _apply(self, old: Config, new: Config, sections: set[str], parsed: dict[str, Any]) -> None:
        core = self.core
        if sections & {"providers", "tasks"}:
            self._apply_providers(old, new)
        if "budget" in sections:
            inner = getattr(core.budget, "inner", core.budget)
            if hasattr(inner, "apply_config"):
                inner.apply_config(new)
            elif hasattr(inner, "cap_usd"):
                inner.cap_usd = new.budget.monthly_usd
        if "alerts" in sections:
            await self._apply_alerts(parsed["alerts"])
        if "news.delivery" in sections:
            await self._apply_delivery(parsed["news.delivery"])
        if "news.feedback" in sections and core.news_feedback is not None:
            core.news_feedback.cfg = parsed["news.feedback"]
        if "conversation" in sections and self.service is not None:
            ms = parsed["conversation"]
            self.service.followup_ms = ms
            for machine in getattr(self.service, "_machines", {}).values():
                machine.followup_ms = ms
        if core.self_model is not None:
            core.self_model.raw = new.raw

    def _apply_providers(self, old: Config, new: Config) -> None:
        reg = self.core.providers
        if reg is None or not hasattr(reg, "reload"):
            log.warning("mudança em [providers]/[tasks] exige reiniciar o magi-core (sem registro)")
            return
        reg.reload(new)
        tts_old, tts_new = old.tasks.get("tts"), new.tasks.get("tts")
        provider_changed = tts_new is not None and old.providers.get(tts_new.provider) != new.providers.get(
            tts_new.provider
        )
        if tts_old != tts_new or provider_changed:
            speaker = self.core.deps.speaker
            if speaker is None:
                if tts_new is not None:
                    log.warning("TTS novo em [tasks] exige reiniciar o magi-core")
            elif hasattr(speaker, "invalidate"):
                speaker.invalidate()
                log.info("voz do TTS: %s", (tts_new.options.get("voice") if tts_new else None) or "padrão")
        if old.tasks.get("stt") is None and new.tasks.get("stt") is not None and self.core.deps.stt is None:
            log.warning("STT novo em [tasks] exige reiniciar o magi-core")
        deps = self.core.deps
        if old.tasks.get("agent") is None and new.tasks.get("agent") is not None and deps.agent is None:
            log.warning("agente novo em [tasks] exige reiniciar o magi-core")

    async def _apply_alerts(self, cfg: AlertsConfig) -> None:
        mon = self.core.alerts
        if mon is None:
            if cfg.enabled:
                log.warning("ligar [alerts] exige reiniciar o magi-core")
            return
        was = mon.cfg
        mon.cfg = cfg
        if (was.sysfs, was.cpu_sensors) != (cfg.sysfs, cfg.cpu_sensors):
            mon._cpu = HwmonTemp(cfg.sysfs, cfg.cpu_sensors, ("temp1_input",))
        if (was.sysfs, was.gpu_sensors) != (cfg.sysfs, cfg.gpu_sensors):
            mon._gpu = HwmonTemp(cfg.sysfs, cfg.gpu_sensors, ("temp2_input", "temp1_input"))
        if not cfg.enabled:
            await mon.aclose()
        elif not was.enabled:
            mon.start()

    async def _apply_delivery(self, cfg: DeliveryConfig) -> None:
        news = self.core.news
        if news is None:
            if cfg.enabled:
                log.warning("ligar [news.delivery] exige reiniciar o magi-core")
            return
        was = news.cfg
        news.cfg = cfg
        if not cfg.enabled:
            await news.aclose()
        elif not was.enabled or was.poll_s != cfg.poll_s:
            await news.aclose()  # o laço dorme com o poll_s antigo
            news.start()

    async def _card(self, text: str) -> None:
        if self.hud is None:
            return
        try:
            await self.hud.send(CardMsg(CardLevel.NORMAL, text[:200]))
        except Exception:
            log.debug("HUD indisponível para o aviso de config", exc_info=True)
