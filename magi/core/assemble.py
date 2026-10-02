"""Montagem do núcleo a partir da ``Config`` (tarefa 1.19, R3.3).

``assemble(config, hud)`` liga as peças prontas e devolve um ``Core`` com o ``TurnDeps``:

- provedores (``magi.providers.registry.Registry``) sobre um ``SwitchBudget``: começa nulo
  (permissivo) e troca para o ``MonthlyBudget`` (3.2) quando o Postgres responde;
- Postgres: migração com a dimensão dos embeddings da config, ``CorrectionsRepo``, ``CostsRepo`` e
  ``TasteRepo`` (gosto do Spotify importado em segundo plano se a tabela estiver vazia, 2.3);
- ``SteamCatalog`` → ``LocalRouter``; ``HintedStt`` (dica com jogos e correções);
  ``Corrections`` (corretor + ``correction.fix``); ações de jogos, HUD, sistema e Spotify;
  ``PhraseSpeaker`` com cache em ``[paths].cache_dir/tts``.

Degradação (nada derruba a partida; cada aviso sai uma vez, no log e em ``Core.warnings``):

- Postgres fora → correções só em memória (valem até reiniciar) e orçamento permissivo sem
  registro;
- provedor sem chave (ou tarefa não configurada) → STT e/ou TTS indisponíveis: o turno responde
  "não peguei" ou só com a legenda no HUD;
- agente (``GraphAgent`` + ferramentas de sistema) sem chave → perguntas respondem "ainda não
  sei fazer isso".

Os parâmetros com padrão (``providers``, ``open_db``, ``catalog``, ``handlers``, ``agent``) são os
pontos de injeção dos testes, que não abrem nem mudam nada real.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from magi.common.config import Config
from magi.common.contracts import (
    ActionHandler,
    ActionRegistry,
    Agent,
    Budget,
    BudgetStatus,
    CardLevel,
    CardMsg,
    Correction,
    CorrectionsRepo,
    GameCatalog,
    HudSink,
    ProviderTask,
    SubtitleMsg,
    Usage,
)
from magi.core import actions
from magi.core.actions import games, hud, spotify_mpris, system
from magi.core.corrections import Corrections
from magi.core.corrections import handlers as correction_handlers
from magi.core.turn import TurnDeps

log = logging.getLogger(__name__)

DB_TIMEOUT_S = 3


# ---------------------------------------------------------------------------------------------
# Orçamento
# ---------------------------------------------------------------------------------------------


class NullBudget:
    """``Budget`` permissivo e sem registro: usado enquanto não há Postgres."""

    def __init__(self, cap_usd: float = 0.0) -> None:
        self.cap_usd = cap_usd

    async def ensure_allowed(self, task: ProviderTask) -> None:
        return None

    async def record(self, usage: Usage) -> None:
        log.debug("gasto não registrado (sem banco): %s", usage)

    async def status(self) -> BudgetStatus:
        return BudgetStatus(spent_usd=0.0, cap_usd=self.cap_usd)

    async def set_cap(self, usd: float) -> None:
        self.cap_usd = usd


class SwitchBudget:
    """``Budget`` que delega a ``inner``. Ponto de troca: o registro de provedores nasce com ele
    antes do banco, e ``use()`` liga o orçamento real (``MonthlyBudget``) quando o banco sobe."""

    def __init__(self, inner: Budget) -> None:
        self.inner = inner

    def use(self, inner: Budget) -> None:
        self.inner = inner

    async def ensure_allowed(self, task: ProviderTask) -> None:
        await self.inner.ensure_allowed(task)

    async def record(self, usage: Usage) -> None:
        await self.inner.record(usage)

    async def status(self) -> BudgetStatus:
        return await self.inner.status()

    async def set_cap(self, usd: float) -> None:
        await self.inner.set_cap(usd)


# ---------------------------------------------------------------------------------------------
# Banco
# ---------------------------------------------------------------------------------------------


class CostsStore(Protocol):
    async def add(self, usage: Usage, at: Any) -> int: ...

    async def month_total(self, year: int, month: int) -> float: ...


@dataclass
class Repos:
    """Repositórios Postgres abertos. ``close`` fecha a conexão."""

    corrections: CorrectionsRepo
    costs: CostsStore
    close: Callable[[], Awaitable[None]]
    taste: Any = None  # magi.memory.taste_repo.TasteRepo (tarefa 2.3)


class MemoryCorrectionsRepo:
    """``CorrectionsRepo`` em memória: o "não, eu falei X" funciona sem banco, sem persistir."""

    def __init__(self) -> None:
        self._rows: dict[str, Correction] = {}
        self._next = 1

    async def add(self, heard: str, correct: str) -> Correction:
        key = heard.casefold()
        old = self._rows.get(key)
        if old is None:
            old = Correction(heard, correct, id=self._next)
            self._next += 1
        row = dataclasses.replace(old, heard=heard, correct=correct, created_at=datetime.now(UTC))
        self._rows[key] = row
        return row

    async def all(self) -> list[Correction]:
        return list(self._rows.values())

    async def bump(self, correction_id: int) -> None:
        for k, c in self._rows.items():
            if c.id == correction_id:
                self._rows[k] = dataclasses.replace(c, uses=c.uses + 1)

    async def delete(self, correction_id: int) -> None:
        self._rows = {k: c for k, c in self._rows.items() if c.id != correction_id}


OpenDb = Callable[[Config, "int | None", "int | None"], Awaitable[Repos]]


async def open_postgres(config: Config, memories_dim: int | None, news_dim: int | None) -> Repos:
    """Migra (dimensões dos embeddings da config; ``None`` = padrão) e abre a conexão do núcleo."""
    import psycopg

    from magi.memory.corrections_repo import CorrectionsRepo
    from magi.memory.costs_repo import CostsRepo
    from magi.memory.migrate import migrate
    from magi.memory.taste_repo import TasteRepo

    dsn = config.database.dsn

    def _migrate() -> list[str]:
        with psycopg.connect(dsn, connect_timeout=DB_TIMEOUT_S) as conn:
            return migrate(conn, memories_dim=memories_dim, news_dim=news_dim)

    applied = await asyncio.to_thread(_migrate)
    if applied:
        log.info("migrações aplicadas: %s", ", ".join(applied))
    conn = await psycopg.AsyncConnection.connect(dsn, autocommit=True, connect_timeout=DB_TIMEOUT_S)
    return Repos(
        corrections=CorrectionsRepo(conn), costs=CostsRepo(conn), close=conn.close, taste=TasteRepo(conn)
    )


# ---------------------------------------------------------------------------------------------
# Ações
# ---------------------------------------------------------------------------------------------

HandlerFactory = Callable[[GameCatalog, HudSink, Corrections | None], list[ActionHandler]]


def default_handlers(
    catalog: GameCatalog, hud_sink: HudSink, corrections: Corrections | None
) -> list[ActionHandler]:
    """Ações reais: jogos (1.9), HUD (1.10), volume/RGB (1.11), Spotify (2.1) e correção (1.6).
    Construir não toca em nada: cada módulo só abre D-Bus/Pulse/OpenRGB ao executar."""
    from magi.core.actions.spotify_api import make_play_query

    mpris = spotify_mpris.SpotifyMpris()
    found = [
        *games.handlers(catalog),
        *hud.handlers(hud_sink),
        *system.handlers(),
        *spotify_mpris.handlers(mpris, play_query=make_play_query(mpris)),
    ]
    if corrections is not None:
        found += correction_handlers(corrections)
    return found


AgentFactory = Callable[[Any, ActionRegistry], Agent]


def default_agent(providers: Any, registry: ActionRegistry) -> Agent:
    """``GraphAgent`` (3.4) com as ferramentas de sistema sobre o registro de ações."""
    from magi.agent.graph import GraphAgent
    from magi.agent.tools.system import system_tools

    return GraphAgent(providers, system_tools(registry), game=lambda: None)


# ---------------------------------------------------------------------------------------------
# Montagem
# ---------------------------------------------------------------------------------------------


@dataclass
class Core:
    """Núcleo montado. ``deps`` vai para o ``CoreService``; ``aclose()`` ao parar."""

    deps: TurnDeps
    budget: SwitchBudget
    providers: Any = None
    catalog: GameCatalog | None = None
    corrections: Corrections | None = None
    repos: Repos | None = None
    warnings: list[str] = field(default_factory=list)
    tasks: list[asyncio.Task[Any]] = field(default_factory=list)  # tarefas de fundo (gosto, 2.3)

    def warn(self, msg: str) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)
            log.warning("%s", msg)

    async def aclose(self) -> None:
        speaker = self.deps.speaker
        if speaker is not None and hasattr(speaker, "aclose"):
            await speaker.aclose()
        for task in self.tasks:
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
            self.tasks.clear()
        if self.repos is not None:
            try:
                await self.repos.close()
            except Exception:
                log.exception("erro ao fechar o banco")
            self.repos = None


def _budget_warner(hud_sink: HudSink) -> Callable[[BudgetStatus], Awaitable[None]]:
    async def warn(status: BudgetStatus) -> None:
        pct = round(status.fraction * 100)
        text = f"Gasto do mês em {pct}% do teto (US$ {status.spent_usd:.2f} de {status.cap_usd:.2f})."
        log.warning("%s", text)
        await hud_sink.send(CardMsg(CardLevel.ALTA, text))
        await hud_sink.send(SubtitleMsg(text))

    return warn


def _has_key(providers: Any, task: str) -> str | None:
    """``None`` se a tarefa tem provedor com chave; senão o motivo."""
    cfg: Config = providers.config
    t = cfg.tasks.get(task)
    if t is None:
        return f"tarefa '{task}' não está em [tasks]"
    if providers.pool(t.provider).available() == 0:
        return f"sem chave para '{t.provider}' no keyring (magi-keys add <nome>)"
    return None


def _dims(providers: Any) -> tuple[int | None, int | None]:
    """Dimensões dos vetores (memórias, notícias) a partir da config; ``None`` = padrão."""
    out: list[int | None] = []
    for task in (ProviderTask.EMBEDDINGS, ProviderTask.NEWS):
        try:
            known = task.value in providers.config.tasks
            out.append(int(providers.embeddings(task).dimensions) if known else None)
        except Exception as e:
            log.debug("dimensão de %s indisponível: %s", task, e)
            out.append(None)
    return out[0], out[1]


async def assemble(
    config: Config,
    hud_sink: HudSink,
    *,
    providers: Callable[[Config, Budget], Any] | None = None,
    open_db: OpenDb | None = open_postgres,
    catalog: GameCatalog | None = None,
    handlers: HandlerFactory = default_handlers,
    agent: AgentFactory | None = default_agent,
) -> Core:
    """Monta o núcleo. Nunca levanta por peça faltando: avisa e degrada."""
    budget = SwitchBudget(NullBudget(config.budget.monthly_usd))
    core = Core(deps=TurnDeps(), budget=budget)

    # Provedores
    try:
        if providers is None:
            from magi.providers.registry import Registry

            providers = Registry
        core.providers = providers(config, budget)
    except Exception as e:
        core.warn(f"provedores indisponíveis: {e}")

    # Banco: migração, correções, custos e orçamento real
    if open_db is not None:
        memories_dim, news_dim = _dims(core.providers) if core.providers is not None else (None, None)
        try:
            core.repos = await open_db(config, memories_dim, news_dim)
        except Exception as e:
            core.warn(
                f"Postgres indisponível ({config.database.dsn.rsplit('@', 1)[-1]}): {type(e).__name__}: {e}; "
                "seguindo com correções só em memória e orçamento sem registro"
            )
    if core.repos is not None and core.repos.taste is not None:
        # Gosto do Spotify na primeira configuração (R8.2): só com a tabela vazia, em segundo plano.
        from magi.core.music.import_taste import import_if_empty

        core.tasks.append(asyncio.create_task(import_if_empty(core.repos.taste)))
    if core.repos is not None:
        from magi.core.budget import MonthlyBudget

        try:
            budget.use(MonthlyBudget.from_config(config, core.repos.costs, on_warn=_budget_warner(hud_sink)))
        except Exception as e:
            core.warn(f"orçamento real indisponível: {e}; seguindo permissivo")
    core.corrections = Corrections(core.repos.corrections if core.repos else MemoryCorrectionsRepo())

    # Catálogo, roteador e ações
    from magi.core.router import LocalRouter

    if catalog is None:
        from magi.core.catalog import SteamCatalog

        catalog = SteamCatalog()
    core.catalog = catalog
    core.deps.router = LocalRouter(catalog)
    core.deps.corrector = core.corrections
    core.deps.actions = actions.Registry(handlers(catalog, hud_sink, core.corrections))

    # STT e TTS
    if core.providers is not None:
        _wire_voice(core, config, catalog)
    if core.deps.stt is None:
        core.warn("STT indisponível: toda fala responde 'não peguei'")
    if core.deps.speaker is None:
        core.warn("TTS indisponível: respostas só na legenda do HUD")
    if agent is not None and core.providers is not None:
        why = _has_key_safe(core.providers, "agent")
        if why is None:
            try:
                core.deps.agent = agent(core.providers, core.deps.actions)
            except Exception as e:
                why = f"{type(e).__name__}: {e}"
        if why is not None:
            core.warn(f"agente: {why}")
    if core.deps.agent is None:
        core.warn("agente indisponível: perguntas respondem 'ainda não sei fazer isso'")
    return core


def _wire_voice(core: Core, config: Config, catalog: GameCatalog) -> None:
    from magi.core.stt import HintedStt
    from magi.core.tts import PhraseCache, PhraseSpeaker

    p = core.providers
    why = _check(p, "stt")
    if why is None:
        repo = core.corrections.repo if core.corrections else None
        core.deps.stt = HintedStt(p.stt, catalog=catalog, corrections=repo)
    else:
        core.warn(f"STT: {why}")
    why = _check(p, "tts")
    if why is None:
        voice = config.tasks["tts"].options.get("voice")
        core.deps.speaker = PhraseSpeaker(
            p.tts, voice=str(voice) if voice else None, cache=PhraseCache(config.paths.cache_dir / "tts")
        )
    else:
        core.warn(f"TTS: {why}")


def _has_key_safe(providers: Any, task: str) -> str | None:
    try:
        return _has_key(providers, task)
    except Exception as e:
        return f"{type(e).__name__}: {e}"


def _check(providers: Any, task: str) -> str | None:
    try:
        why = _has_key(providers, task)
        if why is None:
            getattr(providers, task)()  # monta o backend agora: erro de config aparece na subida
        return why
    except Exception as e:
        return f"{type(e).__name__}: {e}"
