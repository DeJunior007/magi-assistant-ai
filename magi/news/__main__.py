"""``magi-news``: roda uma execução e termina (design §8). Chamado pelo timer systemd a cada 2 h.

Passos: 1 coleta; depois, no máximo a cada 6 h, o progresso do usuário (AniList e Steam, tarefa
6.8), que o anti-spoiler usa; 2 agrupamento (``magi.news.cluster``), que usa os embeddings da
tarefa ``news`` e só roda com provedor ``free_tier`` com chave no keyring (sem isso, é pulado com
aviso). ``--only`` roda só a coleta. Uso::

    magi-news [--config PATH] [--dsn DSN] [--only rss] [--timeout 50] [-v]

DSN: ``--dsn``, senão ``[database].dsn`` do config, senão ``MAGI_DB_DSN``/padrão. Sem config
válido, usa as fontes padrão. Código de saída: 0 ok (mesmo com fontes com erro), 1 se todas as
fontes falharam, 2 se o banco ou a config de fontes falharam.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import UTC, datetime

import psycopg

from magi.common.config import DEFAULT_DSN, Config, ConfigError, load_config
from magi.common.contracts import (
    BudgetExceeded,
    BudgetStatus,
    EmbeddingProvider,
    ProviderError,
    ProviderTask,
    Usage,
)
from magi.news.cluster import cluster_pending
from magi.news.progress import update_if_due
from magi.news.repo import PgNewsRepo
from magi.news.sources import (
    DEFAULT_TIMEOUT_S,
    SOURCE_KINDS,
    CollectReport,
    SourceError,
    collect_all,
    load_sources,
    make_http_client,
    news_settings,
)

log = logging.getLogger("magi.news")


def _load_config(path: str | None) -> Config | None:
    try:
        return load_config(path)
    except ConfigError as exc:
        log.warning("config ignorado (%s); usando fontes padrão", exc)
        return None


class _FreeTierOnly:
    """``Budget`` do ``magi-news``: só provedores em cota gratuita são usados aqui (o orçamento
    real é do núcleo); um provedor pago é recusado."""

    async def ensure_allowed(self, task: ProviderTask) -> None:
        raise BudgetExceeded(f"magi-news não usa provedor pago ({task})")

    async def record(self, usage: Usage) -> None:
        return None

    async def status(self) -> BudgetStatus:
        raise NotImplementedError

    async def set_cap(self, usd: float) -> None:
        raise NotImplementedError


def make_embedder(config: Config | None) -> EmbeddingProvider | None:
    """Embeddings da tarefa ``news`` (R18.3) ou ``None`` com aviso (sem tarefa, pago, sem chave)."""
    if config is None or ProviderTask.NEWS.value not in config.tasks:
        log.warning("agrupamento pulado: [tasks.news] não configurada")
        return None
    from magi.providers.registry import Registry

    try:
        pcfg = config.provider_for(ProviderTask.NEWS.value)
        if not pcfg.free_tier:
            log.warning("agrupamento pulado: provedor '%s' da tarefa news não é free_tier", pcfg.name)
            return None
        registry = Registry(config, _FreeTierOnly())
        if registry.pool(pcfg.name).available() == 0:
            log.warning("agrupamento pulado: nenhuma chave de '%s' no keyring", pcfg.name)
            return None
        return registry.embeddings(ProviderTask.NEWS)
    except (ConfigError, ProviderError) as exc:
        log.warning("agrupamento pulado: %s", exc)
        return None


async def run_once(
    config: Config | None, dsn: str, *, only: str | None = None, timeout_s: float | None = None
) -> CollectReport:
    sources = load_sources(config)
    if only:
        sources = [s for s in sources if s.kind == only]
    if timeout_s is None:
        timeout_s = float(news_settings(config).get("timeout_s", DEFAULT_TIMEOUT_S))
    repo = await PgNewsRepo.connect(dsn)
    try:
        async with make_http_client() as http:
            report = await collect_all(repo, sources, http, config=config, timeout_s=timeout_s)
            if not only:
                try:
                    prog = await update_if_due(repo, http, sources, news_settings(config),
                                               datetime.now(UTC))
                except (psycopg.Error, OSError, ValueError) as exc:  # não derruba a coleta
                    log.warning("progresso: %s", exc)
                else:
                    if prog is not None:
                        log.info("%s", prog.summary())
        embedder = make_embedder(config)
        if embedder is not None:
            try:
                log.info("agrupamento: %s", (await cluster_pending(repo, embedder)).summary())
            except ProviderError as exc:
                log.warning("agrupamento interrompido: %s", exc)
        return report
    finally:
        await repo.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="magi-news", description="Uma execução do coletor de notícias.")
    ap.add_argument("--config", help="caminho do config.toml (padrão: $MAGI_CONFIG ou ~/.config/magi)")
    ap.add_argument("--dsn", help="DSN do Postgres")
    ap.add_argument("--only", choices=SOURCE_KINDS, help="só fontes deste tipo")
    ap.add_argument(
        "--timeout", type=float, help=f"teto da coleta em segundos (padrão {DEFAULT_TIMEOUT_S:.0f})"
    )
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.DEBUG if args.verbose else logging.WARNING)

    config = _load_config(args.config)
    dsn = args.dsn or (config.database.dsn if config else None)
    dsn = dsn or os.environ.get("MAGI_DB_DSN") or DEFAULT_DSN
    try:
        report = asyncio.run(run_once(config, dsn, only=args.only, timeout_s=args.timeout))
    except SourceError as exc:
        log.error("fontes inválidas: %s", exc)
        return 2
    except psycopg.Error as exc:
        log.error("banco: %s", exc)
        return 2
    for s in report.sources:
        status = "pulada (sem coletor)" if s.skipped else (f"ERRO {s.error}" if s.error else "ok")
        log.info("%-20s %-7s %3d lidos %3d novos %3d repetidos %5.1fs %s",
                 s.name, s.kind, s.fetched, s.new, s.duplicates, s.seconds, status)
    print(f"magi-news: {report.summary()}")
    ran = [s for s in report.sources if not s.skipped]
    return 1 if ran and all(s.error for s in ran) else 0


if __name__ == "__main__":
    sys.exit(main())
