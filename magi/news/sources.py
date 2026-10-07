"""Registro de fontes, interface de coletor e passo 1 da Ayanami (design §8; R18.1, R18.4).

Fontes
------
Carregadas de :data:`DEFAULT_SOURCES_FILE` (``magi/news/sources.toml``) e ajustadas pela seção
``[news]`` do ``config.toml``::

    [news]
    defaults = true          # false: ignora o arquivo padrão
    timeout_s = 50           # teto da coleta inteira (padrão 50 s; uma execução cabe em 1 min)

    [[news.sources]]         # mesmo ``name`` de uma padrão: sobrescreve só os campos dados
    name = "IGN Games"
    trust = 1

    [[news.sources]]
    name = "Gematsu"
    enabled = false          # desliga

    [[news.sources]]         # nome novo: fonte nova (precisa de kind, url e trust)
    name = "Meu site"
    kind = "scrape"
    url = "https://exemplo.com/noticias"
    trust = 2
    selector = "article h2 a"   # campos extras vão para ``SourceConfig.options``

Coletores (como as tarefas 6.2-6.5 se plugam)
---------------------------------------------
Cada ``kind`` tem um módulo ``magi.news.collect.<kind>`` com uma função
``make_collector(config: Config | None) -> Collector``. Ele é importado sob demanda; se o módulo
ainda não existe, as fontes daquele tipo são puladas (com aviso no log). Também dá para registrar
à mão com :func:`register_collector` (testes, plugins).

Um :class:`Collector` recebe a fonte já gravada no banco (``source.id`` preenchido) e um
:class:`CollectContext` (cliente ``httpx`` compartilhado, hora da execução, config) e devolve
``NewsRaw`` com ``source_id=source.id``. Não precisa deduplicar: :func:`collect_all` normaliza a
URL (:func:`normalize_url`) e o banco recusa URL repetida (``NewsRepo.add_raw`` devolve ``None``).
Erros de uma fonte não derrubam as outras; cada fonte tem um tempo máximo.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import time
import tomllib
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar, Protocol, runtime_checkable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from magi.common.config import Config
from magi.common.contracts import NewsRaw, NewsRepo, NewsSource

log = logging.getLogger(__name__)

SOURCE_KINDS = ("rss", "steam", "anilist", "reddit", "scrape")
DEFAULT_SOURCES_FILE = Path(__file__).with_name("sources.toml")
DEFAULT_TIMEOUT_S = 50.0  # coleta inteira
SOURCE_TIMEOUT_S = 25.0  # uma fonte
HTTP_TIMEOUT_S = 10.0  # uma requisição
MAX_CONCURRENCY = 8
USER_AGENT = "magi-news/0.1 (assistente pessoal; coleta a cada 2 h)"

_BASE_FIELDS = ("name", "kind", "url", "trust", "enabled")


class SourceError(ValueError):
    """Fonte mal configurada."""


@dataclass(frozen=True, slots=True)
class SourceConfig:
    """Uma fonte do registro. ``id`` só existe depois de gravada no banco."""

    name: str
    kind: str
    url: str
    trust: int
    enabled: bool = True
    options: Mapping[str, Any] = field(default_factory=dict)
    id: int | None = None

    def to_news_source(self) -> NewsSource:
        return NewsSource(name=self.name, kind=self.kind, url=self.url, trust=self.trust, id=self.id)


def _validate(src: SourceConfig) -> SourceConfig:
    where = f"fonte {src.name!r}"
    if not src.name.strip():
        raise SourceError("fonte sem nome")
    if src.kind not in SOURCE_KINDS:
        raise SourceError(f"{where}: kind {src.kind!r} inválido (use {', '.join(SOURCE_KINDS)})")
    if not src.url.startswith(("http://", "https://")):
        raise SourceError(f"{where}: url precisa ser http(s): {src.url!r}")
    if isinstance(src.trust, bool) or not isinstance(src.trust, int) or not 1 <= src.trust <= 3:
        raise SourceError(f"{where}: trust precisa ser 1, 2 ou 3 (veio {src.trust!r})")
    return src


def _from_mapping(data: Mapping[str, Any], base: SourceConfig | None = None) -> SourceConfig:
    if not isinstance(data, Mapping) or not isinstance(data.get("name"), str):
        raise SourceError(f"fonte sem 'name': {data!r}")
    extra = {k: v for k, v in data.items() if k not in _BASE_FIELDS}
    if base is None:
        missing = [k for k in ("kind", "url", "trust") if k not in data]
        if missing:
            raise SourceError(f"fonte {data['name']!r}: faltam {', '.join(missing)}")
        return SourceConfig(
            name=data["name"],
            kind=str(data["kind"]),
            url=str(data["url"]),
            trust=data["trust"],
            enabled=bool(data.get("enabled", True)),
            options=extra,
        )
    return replace(
        base,
        kind=str(data.get("kind", base.kind)),
        url=str(data.get("url", base.url)),
        trust=data.get("trust", base.trust),
        enabled=bool(data.get("enabled", base.enabled)),
        options={**base.options, **extra},
    )


def read_sources_file(path: Path = DEFAULT_SOURCES_FILE) -> list[SourceConfig]:
    with Path(path).open("rb") as f:
        data = tomllib.load(f)
    return [_validate(_from_mapping(s)) for s in data.get("sources", [])]


def news_settings(config: Config | Mapping[str, Any] | None) -> Mapping[str, Any]:
    """Seção ``[news]`` do config (``Config`` ou dict cru)."""
    if config is None:
        return {}
    raw = config.raw if isinstance(config, Config) else config
    news = raw.get("news") or {}
    if not isinstance(news, Mapping):
        raise SourceError("[news] precisa ser uma tabela")
    return news


def load_sources(
    config: Config | Mapping[str, Any] | None = None,
    *,
    defaults_file: Path = DEFAULT_SOURCES_FILE,
    include_disabled: bool = False,
) -> list[SourceConfig]:
    """Fontes padrão + overrides de ``[news]`` (ver docstring do módulo), validadas."""
    news = news_settings(config)
    by_name: dict[str, SourceConfig] = {}
    if news.get("defaults", True):
        for src in read_sources_file(defaults_file):
            by_name[src.name] = src
    overrides = news.get("sources") or []
    if not isinstance(overrides, list):
        raise SourceError("news.sources precisa ser uma lista ([[news.sources]])")
    for data in overrides:
        name = data.get("name") if isinstance(data, Mapping) else None
        by_name[name] = _validate(_from_mapping(data, by_name.get(name)))  # type: ignore[index]
    result = list(by_name.values())
    seen: dict[str, str] = {}
    for src in result:
        key = normalize_url(src.url)
        if key in seen:
            raise SourceError(f"fontes {seen[key]!r} e {src.name!r} têm a mesma url")
        seen[key] = src.name
    return result if include_disabled else [s for s in result if s.enabled]


# --- URL -------------------------------------------------------------------------------------

_TRACKING_PREFIXES = ("utm_",)
_TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref_src"}


def normalize_url(url: str) -> str:
    """Forma canônica para deduplicação exata (R18.1): sem espaços, sem fragmento, esquema e host
    em minúsculas, sem parâmetros de rastreio (``utm_*``, ``fbclid``...). O resto fica igual."""
    parts = urlsplit(url.strip())
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith(_TRACKING_PREFIXES) and k.lower() not in _TRACKING_KEYS
    ]
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", urlencode(query), "")
    )


# --- coletores -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CollectContext:
    """O que um coletor recebe além da fonte. ``http`` já tem User-Agent e timeouts."""

    http: httpx.AsyncClient
    now: datetime
    config: Config | None = None


@runtime_checkable
class Collector(Protocol):
    """Coletor de um ``kind`` de fonte (tarefas 6.1-6.5)."""

    kind: ClassVar[str]

    async def collect(self, source: SourceConfig, ctx: CollectContext) -> Sequence[NewsRaw]:
        """Busca a fonte e devolve as notícias cruas (``source_id=source.id``). Pode levantar
        exceção: :func:`collect_all` registra e segue com as outras fontes."""
        ...


CollectorFactory = Callable[[Config | None], Collector]
_registry: dict[str, CollectorFactory] = {}


def register_collector(kind: str, factory: CollectorFactory) -> None:
    if kind not in SOURCE_KINDS:
        raise SourceError(f"kind {kind!r} inválido")
    _registry[kind] = factory


def unregister_collector(kind: str) -> None:
    _registry.pop(kind, None)


def collector_factory(kind: str) -> CollectorFactory | None:
    """Fábrica registrada, ou ``magi.news.collect.<kind>.make_collector``; ``None`` se não há."""
    if kind in _registry:
        return _registry[kind]
    modname = f"magi.news.collect.{kind}"
    try:
        mod = importlib.import_module(modname)
    except ModuleNotFoundError as exc:
        if exc.name == modname:
            return None
        raise
    return getattr(mod, "make_collector", None)


# --- execução --------------------------------------------------------------------------------


@dataclass(slots=True)
class SourceReport:
    name: str
    kind: str
    fetched: int = 0
    new: int = 0
    duplicates: int = 0
    error: str | None = None
    skipped: bool = False
    seconds: float = 0.0


@dataclass(slots=True)
class CollectReport:
    sources: list[SourceReport] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def new(self) -> int:
        return sum(s.new for s in self.sources)

    @property
    def duplicates(self) -> int:
        return sum(s.duplicates for s in self.sources)

    @property
    def errors(self) -> int:
        return sum(1 for s in self.sources if s.error)

    def summary(self) -> str:
        ran = sum(1 for s in self.sources if not s.skipped)
        return (
            f"{ran} fontes, {self.new} novos, {self.duplicates} repetidos, "
            f"{self.errors} erros em {self.seconds:.1f} s"
        )


def make_http_client(**kwargs: Any) -> httpx.AsyncClient:
    kwargs.setdefault("timeout", HTTP_TIMEOUT_S)
    kwargs.setdefault("follow_redirects", True)
    headers = {"User-Agent": USER_AGENT, **kwargs.pop("headers", {})}
    return httpx.AsyncClient(headers=headers, **kwargs)


async def _store(repo: NewsRepo, raws: Iterable[NewsRaw], src: SourceConfig, now: datetime,
                 rep: SourceReport, seen: set[str]) -> None:
    for raw in raws:
        rep.fetched += 1
        url = normalize_url(raw.url)
        if url in seen:
            rep.duplicates += 1
            continue
        seen.add(url)
        raw = replace(raw, url=url, source_id=src.id, fetched_at=raw.fetched_at or now)
        if await repo.add_raw(raw) is None:
            rep.duplicates += 1
        else:
            rep.new += 1


async def collect_all(
    repo: NewsRepo,
    sources: Sequence[SourceConfig],
    http: httpx.AsyncClient,
    *,
    config: Config | None = None,
    now: datetime | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    source_timeout_s: float = SOURCE_TIMEOUT_S,
) -> CollectReport:
    """Passo 1 do §8: grava as fontes, roda os coletores em paralelo (com teto por fonte e
    total) e guarda as notícias novas, deduplicadas por URL."""
    started = time.monotonic()
    now = now or datetime.now(UTC)
    ctx = CollectContext(http=http, now=now, config=config)
    report = CollectReport()
    seen: set[str] = set()
    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    collectors: dict[str, Collector | None] = {}

    async def run(src: SourceConfig, rep: SourceReport) -> None:
        t0 = time.monotonic()
        try:
            async with sem:
                raws = await asyncio.wait_for(collectors[src.kind].collect(src, ctx), source_timeout_s)
                await _store(repo, raws, src, now, rep, seen)
        except TimeoutError:
            rep.error = f"tempo esgotado ({source_timeout_s:.0f} s)"
        except Exception as exc:  # uma fonte ruim não derruba as outras
            rep.error = f"{type(exc).__name__}: {exc}"
        finally:
            rep.seconds = time.monotonic() - t0
        if rep.error:
            log.warning("fonte %s (%s): %s", src.name, src.kind, rep.error)

    tasks: dict[asyncio.Task[None], SourceReport] = {}
    for src in sources:
        if not src.enabled:
            continue
        rep = SourceReport(src.name, src.kind)
        report.sources.append(rep)
        src = replace(src, id=await repo.upsert_source(src.to_news_source()))
        if src.kind not in collectors:
            factory = collector_factory(src.kind)
            collectors[src.kind] = factory(config) if factory else None
            if factory is None:
                log.info("sem coletor para kind=%s ainda; fontes desse tipo puladas", src.kind)
        if collectors[src.kind] is None:
            rep.skipped = True
            continue
        tasks[asyncio.create_task(run(src, rep), name=f"news:{src.name}")] = rep

    if tasks:
        remaining = max(0.1, timeout_s - (time.monotonic() - started))
        _done, pending = await asyncio.wait(tasks, timeout=remaining)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
            for task in pending:
                tasks[task].error = f"tempo total esgotado ({timeout_s:.0f} s)"
                log.warning("fonte %s: %s", tasks[task].name, tasks[task].error)
    report.seconds = time.monotonic() - started
    return report
