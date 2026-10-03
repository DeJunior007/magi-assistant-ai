"""Montagem do núcleo a partir da ``Config`` (tarefa 1.19, R3.3).

``assemble(config, hud)`` liga as peças prontas e devolve um ``Core`` com o ``TurnDeps``:

- provedores (``magi.providers.registry.Registry``) sobre um ``SwitchBudget``: começa nulo
  (permissivo) e troca para o ``MonthlyBudget`` (3.2) quando o Postgres responde;
- Postgres: migração com a dimensão dos embeddings da config, ``CorrectionsRepo``, ``CostsRepo`` e
  ``TasteRepo`` (gosto do Spotify importado em segundo plano se a tabela estiver vazia, 2.3);
- ``SteamCatalog`` → ``LocalRouter``; ``HintedStt`` (dica com jogos e correções);
  ``Corrections`` (corretor + ``correction.fix``); ações de jogos, HUD, sistema e Spotify;
  ``PhraseSpeaker`` com cache em ``[paths].cache_dir/tts``;
- proatividade (5.3, 6.10): ``ProactiveSink`` + ``AlertMonitor`` (``[alerts]``) + ``NewsDelivery``
  (``[news.delivery]``, só com Postgres), ligados aos satélites
  por ``Core.start_proactive`` depois que o serviço Wyoming sobe; o aviso de 80% do orçamento
  passa pelo monitor (fala fora de call, só tela em call).

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

from magi.common.config import Config, ConfigError
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
    IntentId,
    ProviderTask,
    SubtitleMsg,
    Usage,
)
from magi.core import actions
from magi.core.actions import games, hud, spotify_mpris, system
from magi.core.corrections import Corrections
from magi.core.corrections import handlers as correction_handlers
from magi.core.proactive.alerts import STATE_FILE as ALERTS_STATE_FILE
from magi.core.proactive.alerts import AlertMonitor, AlertsConfig
from magi.core.proactive.news import DeliveryConfig, NewsDelivery
from magi.core.proactive.sink import ProactiveSink, Targets
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
    news: Any = None  # ``NewsRepo`` (``PgNewsRepo``) para a entrega de notícias (6.10)
    music_signals: Any = None  # magi.memory.music_signals_repo.MusicSignalsRepo (tarefa 2.4)
    memories: Any = None  # magi.memory.memories_repo.PgMemoriesRepo (tarefa 4.1)
    turns: Any = None  # magi.memory.memories_repo.PgTurnsRepo (histórico local, 4.1)


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

    from magi.memory.conn import SerialConn
    from magi.memory.corrections_repo import CorrectionsRepo
    from magi.memory.costs_repo import CostsRepo
    from magi.memory.memories_repo import PgMemoriesRepo, PgTurnsRepo
    from magi.memory.migrate import migrate
    from magi.memory.music_signals_repo import MusicSignalsRepo
    from magi.memory.taste_repo import TasteRepo

    dsn = config.database.dsn

    def _migrate() -> list[str]:
        with psycopg.connect(dsn, connect_timeout=DB_TIMEOUT_S) as conn:
            return migrate(conn, memories_dim=memories_dim, news_dim=news_dim)

    applied = await asyncio.to_thread(_migrate)
    if applied:
        log.info("migrações aplicadas: %s", ", ".join(applied))
    from magi.news.repo import PgNewsRepo

    raw = await psycopg.AsyncConnection.connect(dsn, autocommit=True, connect_timeout=DB_TIMEOUT_S)
    conn = SerialConn(raw)  # repositórios compartilham a conexão: transações em fila
    return Repos(
        corrections=CorrectionsRepo(conn), costs=CostsRepo(conn), close=conn.close,
        taste=TasteRepo(conn), news=PgNewsRepo(conn), music_signals=MusicSignalsRepo(conn),
        memories=PgMemoriesRepo(conn), turns=PgTurnsRepo(conn),
    )


# ---------------------------------------------------------------------------------------------
# Ações
# ---------------------------------------------------------------------------------------------

HandlerFactory = Callable[[GameCatalog, HudSink, Corrections | None], list[ActionHandler]]


def default_handlers(
    catalog: GameCatalog, hud_sink: HudSink, corrections: Corrections | None
) -> list[ActionHandler]:
    """Ações reais: jogos (1.9), HUD (1.10), volume/RGB (1.11), Spotify (2.1), sinais de música
    (2.4) e correção (1.6). Construir não toca em nada: cada módulo só abre D-Bus/Pulse/OpenRGB ao
    executar. O ``MusicSignals`` (sem banco até o ``assemble`` ligar o repo) marca o que o
    ``play_query`` toca como escolha da Magui."""
    from magi.core.actions.spotify_api import SpotifyApi, make_play_query
    from magi.core.music import pick, signals
    from magi.news import feedback as news_feedback

    mpris = spotify_mpris.SpotifyMpris()
    music = signals.MusicSignals(mpris)
    found = [
        *games.handlers(catalog),
        *hud.handlers(hud_sink),
        *system.handlers(),
        *spotify_mpris.handlers(mpris, play_query=make_play_query(mpris, on_play=music.mark_picked)),
        *signals.handlers(music),
        *pick.handlers(pick.MusicPicker(mpris, SpotifyApi(), music)),
        *news_feedback.handlers(),
    ]
    if corrections is not None:
        found += correction_handlers(corrections)
    return found


AgentFactory = Callable[[Any, ActionRegistry, Any], Agent]


def default_agent(providers: Any, registry: ActionRegistry, self_model: Any = None) -> Agent:
    """``GraphAgent`` (3.4) com as ferramentas de sistema e de mídia (3.5) sobre o registro de
    ações, a pesquisa (3.8, se ``[tasks.search]`` existir), a visão (3.7, ``screenshot`` sobre
    ``providers.vision()``) e, com a ficha (3.9, ``SelfModel``), a ferramenta ``self_info`` e a
    seção "Sobre você" no prompt."""
    from magi.agent.graph import GraphAgent
    from magi.agent.self_model import SelfInfoTool
    from magi.agent.tools.media import media_tools
    from magi.agent.tools.search import search_tools
    from magi.agent.tools.system import system_tools
    from magi.agent.tools.vision import vision_tools

    user = getattr(getattr(providers, "config", None), "raw", None) or {}
    name = str((user.get("user") or {}).get("name") or "") if isinstance(user, dict) else ""
    tools: list[Any] = [
        *system_tools(registry),
        *media_tools(registry),
        *search_tools(providers, private_terms=(name,) if name else ()),
        *vision_tools(providers),
    ]
    if self_model is None:
        return GraphAgent(providers, tools, game=lambda: None)
    tools.append(SelfInfoTool(self_model))
    self_model.tools = tuple(t.spec for t in tools)
    return GraphAgent(providers, tools, game=lambda: None, about=self_model.about_section)


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
    proactive: ProactiveSink | None = None
    alerts: AlertMonitor | None = None
    news: NewsDelivery | None = None
    warnings: list[str] = field(default_factory=list)
    tasks: list[asyncio.Task[Any]] = field(default_factory=list)  # tarefas de fundo (gosto, 2.3)
    music: Any = None  # magi.core.music.signals.MusicSignals (2.4); observa em ``start_proactive``
    music_task: asyncio.Task[Any] | None = None
    self_model: Any = None  # magi.agent.self_model.SelfModel (3.9): ficha viva da Magui
    memory: Any = None  # magi.memory.memories_repo.MemoryStore (4.1)

    def warn(self, msg: str) -> None:
        if msg not in self.warnings:
            self.warnings.append(msg)
            log.warning("%s", msg)

    def start_proactive(self, targets: Targets) -> None:
        """Liga a entrega proativa aos satélites do serviço e inicia alertas (5.3), notícias (6.10)
        e a observação do Spotify para os sinais de música (2.4)."""
        if self.proactive is not None:
            self.proactive.targets = targets
        if self.alerts is not None:
            self.alerts.start()
        if self.news is not None:
            self.news.start()
        if self.music is not None and self.music_task is None:
            self.music_task = asyncio.create_task(self.music.run())
            self.tasks.append(self.music_task)

    async def aclose(self) -> None:
        if self.news is not None:
            await self.news.aclose()
        if self.alerts is not None:
            await self.alerts.aclose()
        if self.proactive is not None:
            await self.proactive.aclose()
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

    # Proatividade: fila de avisos e alertas (R15.1, R15.2); o monitor só roda em ``start_proactive``
    core.proactive = ProactiveSink(hud_sink)
    try:
        alerts_cfg = AlertsConfig.from_raw(config.raw.get("alerts"))
    except ConfigError as e:
        core.warn(f"{e}; alertas com os padrões")
        alerts_cfg = AlertsConfig()
    if alerts_cfg.enabled:
        core.alerts = AlertMonitor(
            core.proactive, alerts_cfg, budget=budget, state_path=config.paths.data_dir / ALERTS_STATE_FILE
        )
    on_warn = core.alerts.check_cost if core.alerts is not None else _budget_warner(hud_sink)

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
        # Gosto do Spotify (R8.2): na primeira configuração e depois 1×/dia, em segundo plano (2.4).
        from magi.core.music.import_taste import STATE_FILE, refresh_loop

        state = config.paths.data_dir / STATE_FILE
        core.tasks.append(asyncio.create_task(refresh_loop(core.repos.taste, state)))
    if core.repos is not None:
        from magi.core.budget import MonthlyBudget

        try:
            budget.use(MonthlyBudget.from_config(config, core.repos.costs, on_warn=on_warn))
        except Exception as e:
            core.warn(f"orçamento real indisponível: {e}; seguindo permissivo")
    _wire_news(core, config)
    core.corrections = Corrections(core.repos.corrections if core.repos else MemoryCorrectionsRepo())

    # Catálogo, roteador e ações
    from magi.core.router import LocalRouter

    if catalog is None:
        from magi.core.catalog import SteamCatalog

        catalog = SteamCatalog()
    core.catalog = catalog
    core.deps.router = LocalRouter(catalog)
    core.deps.corrector = core.corrections
    found = handlers(catalog, hud_sink, core.corrections)
    found = _wire_memory_store(core, found)
    core.self_model = _self_model(core, config)
    if not any(IntentId.HELP.value in h.intents for h in found):
        from magi.agent.self_model import HelpHandler

        found = [*found, HelpHandler(core.self_model)]
    core.deps.actions = actions.Registry(found)
    core.self_model.registry = core.deps.actions
    _wire_music(core, found)
    _wire_pick(core, config, found)
    _wire_news_feedback(core, config, found)

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
                core.deps.agent = agent(core.providers, core.deps.actions, core.self_model)
            except Exception as e:
                why = f"{type(e).__name__}: {e}"
        if why is not None:
            core.warn(f"agente: {why}")
    if core.deps.agent is None:
        core.warn("agente indisponível: perguntas respondem 'ainda não sei fazer isso'")
    _wire_memory_agent(core)
    core.self_model.agent_ready = core.deps.agent is not None
    return core


SPOTIFY_CHECK_TTL_S = 60.0


def _self_model(core: Core, config: Config) -> Any:
    """Ficha da Magui (3.9) com leituras baratas do estado: keyring do Spotify (cache de 60 s),
    call pelo ``ProactiveSink``, chaves por tarefa e o orçamento."""
    import time

    from magi.agent.self_model import SelfModel

    seen: list[tuple[float, bool]] = []

    def spotify() -> bool:
        now = time.monotonic()
        if not seen or now - seen[0][0] > SPOTIFY_CHECK_TTL_S:
            from magi.core.actions.spotify_api import TokenStore

            store = TokenStore()
            seen[:] = [(now, bool(store.client_id() and store.load()))]
        return seen[0][1]

    def missing() -> list[str]:
        if core.providers is None:
            return sorted(config.tasks)
        return [f"{t} ({c.provider})" for t, c in config.tasks.items() if _has_key_safe(core.providers, t)]

    proactive = core.proactive
    return SelfModel(
        raw=config.raw,
        spotify=spotify,
        in_call=proactive.in_call if proactive is not None else None,
        missing_keys=missing,
        budget=core.budget.status,
    )


def _wire_news(core: Core, config: Config) -> None:
    """Entrega de notícias (6.10, ``[news.delivery]``): precisa do Postgres; roda em ``start_proactive``."""
    news_raw = config.raw.get("news")
    try:
        cfg = DeliveryConfig.from_raw(news_raw.get("delivery") if isinstance(news_raw, dict) else None)
    except ConfigError as e:
        core.warn(f"{e}; entrega de notícias com os padrões")
        cfg = DeliveryConfig()
    if not cfg.enabled or core.proactive is None:
        return
    repo = core.repos.news if core.repos is not None else None
    if repo is None:
        log.info("notícias: sem Postgres, nada é entregue")
        return
    core.news = NewsDelivery(core.proactive, repo, cfg)


def _wire_news_feedback(core: Core, config: Config, found: list[ActionHandler]) -> None:
    """Liga o repo de notícias ao retorno por voz (6.11); sem Postgres o handler recusa."""
    from magi.news.feedback import FeedbackConfig, NewsFeedbackHandler

    repo = core.repos.news if core.repos is not None else None
    news_raw = config.raw.get("news")
    raw = news_raw.get("feedback") if isinstance(news_raw, dict) else None
    for h in found:
        if isinstance(h, NewsFeedbackHandler):
            try:
                h.feedback.cfg = FeedbackConfig.from_raw(raw if isinstance(raw, dict) else None)
            except ConfigError as e:
                core.warn(f"{e}; retorno de notícias com os padrões")
            h.feedback.repo = repo
            return


def _wire_memory_store(core: Core, found: list[ActionHandler]) -> list[ActionHandler]:
    """Histórico de turnos e ``MemoryStore`` (4.1): repo do banco (ou em memória, sem persistir) e
    embeddings da tarefa ``embeddings``. Liga o "esquece isso" local."""
    from magi.agent.tools.memory import ForgetHandler
    from magi.memory.memories_repo import InMemoryMemoriesRepo, MemoryStore, provider_embed

    if core.repos is not None and core.repos.turns is not None:
        core.deps.turns = core.repos.turns
    if core.providers is None:
        return found
    why = _has_key_safe(core.providers, "embeddings")
    if why is not None:
        core.warn(f"memórias: {why}")
        return found
    repo = core.repos.memories if core.repos is not None and core.repos.memories is not None else None
    if repo is None:
        core.warn("memórias sem banco: valem só até reiniciar")
        repo = InMemoryMemoriesRepo()
    core.memory = MemoryStore(repo, provider_embed(core.providers))
    if not any(IntentId.MEMORY_FORGET.value in h.intents for h in found):
        found = [*found, ForgetHandler(core.memory)]
    return found


def _wire_memory_agent(core: Core) -> None:
    """Dá ao ``GraphAgent`` a busca de memórias e as ferramentas ``remember``/``forget``."""
    from magi.agent.graph import GraphAgent
    from magi.agent.tools.memory import memory_tools

    agent = core.deps.agent
    if core.memory is None or not isinstance(agent, GraphAgent):
        return
    agent.memory = core.memory
    agent.add_tools(memory_tools(core.memory))
    if core.self_model is not None:
        core.self_model.tools = agent.tool_specs


def _wire_music(core: Core, found: list[ActionHandler]) -> None:
    """Acha o ``MusicSignals`` dos handlers (2.4) e liga o repo do banco, se houver."""
    from magi.core.music.signals import MusicSignalsHandler

    for h in found:
        if isinstance(h, MusicSignalsHandler):
            core.music = h.signals
            repo = getattr(core.repos, "music_signals", None) if core.repos is not None else None
            if repo is not None:
                core.music.repo = repo
            return


def _wire_pick(core: Core, config: Config, found: list[ActionHandler]) -> None:
    """"Coloca uma boa" (2.5): liga o gosto do banco e o cache de gêneros ao ``MusicPicker`` e,
    havendo chave da tarefa ``news`` (cota gratuita), classifica os gêneros em segundo plano."""
    from magi.core.music import pick

    picker = next((h.picker for h in found if isinstance(h, pick.MusicPickHandler)), None)
    if picker is None:
        return
    picker.genres = pick.GenreCache(config.paths.data_dir / pick.GENRE_FILE)
    taste = core.repos.taste if core.repos is not None else None
    if taste is None:
        return
    picker.taste = taste
    if core.providers is None:
        return
    why = _has_key(core.providers, ProviderTask.NEWS.value)
    if why is not None:
        core.warn(f"gêneros musicais: {why}")
        return
    chat = core.providers.chat(ProviderTask.NEWS)
    core.tasks.append(asyncio.create_task(pick.genre_loop(taste, picker.genres, chat)))


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
