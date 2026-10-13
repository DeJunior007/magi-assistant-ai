"""Notícias na nuvem (dono: Y3.2; spec §5.1, design §8; corpos chamados por ``ayanami.fila``).

- ``noticias.coletar`` (:func:`coletar`): confere que ``news_items.embedding`` do ``ayanami-pg`` tem
  a dimensão de ``[noticias] dim`` (= ``NEWS_DIM`` do PC; diferente → :class:`DimensaoErrada`, sem
  coletar), chama ``magi.news.__main__.run_once(config, dsn)`` com o ``Config`` de
  :func:`montar_config` e, no fim, cria ``evento noticia_bomba`` para cada item tocado nesta coleta
  com ``level = 'bomba'`` (o critério de ``magi/core/proactive/news.py``: nível ``bomba``, obra não
  largada, ``first_seen`` dentro de ``max_age_h``), uma vez por ``uid`` (``ref = noticia:<uid>``).
- ``progresso.atualizar`` (:func:`progresso`): AniList/Steam (``magi.news.progress.update_if_due``)
  e a pontuação local (``score_pending``); nunca chama provedor de LLM.

Provedores: o ``magi-news`` só usa o provedor da tarefa ``news`` se ele for ``free_tier`` (texto
público de notícia); ``progress``/``franchise_prefs`` nunca saem para LLM.

``[noticias]`` → ``Config`` do PC (:func:`montar_config`): ``timeout_s`` → ``[news] timeout_s``;
``fontes`` (nomes das fontes padrão de ``magi/news/sources.toml``) → as demais ficam desligadas;
``embedder = {provider, model, free_tier, keys, …}`` → ``[providers.<provider>]`` +
``[tasks.news]`` (o resto da tabela vai como opção do provedor).

DSN: ``deps.extras["dsn"]`` (testes) ou :func:`ayanami.db.dsn_padrao` (variáveis libpq do
Compose); recusado se apontar para o ``magi-pg``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from procrastinate import JobContext

from ayanami.config import Noticias
from ayanami.db import Db, dsn_padrao, recusar_magi, transacao
from ayanami.deps import Deps
from ayanami.tarefas import criar_evento
from magi.common.config import Config, ConfigError, parse_config

log = logging.getLogger("ayanami.noticias")

MAX_IDADE_H = 48.0  # = DeliveryConfig.max_age_h do proactive/news.py
TITULO_MAX = 80
RESUMO_MAX = 200


class DimensaoErrada(RuntimeError):
    """``news_items.embedding`` do banco ≠ ``[noticias] dim`` (= ``NEWS_DIM`` do PC)."""


# --------------------------------------------------------------------------- config


def _nomes_padrao() -> list[str]:
    from magi.news.sources import DEFAULT_SOURCES_FILE, read_sources_file

    return [s.name for s in read_sources_file(DEFAULT_SOURCES_FILE)]


def montar_config(n: Noticias) -> Config:
    """``Config`` do ``magi-news`` a partir de ``[noticias]`` do ``ayanami.toml``."""
    news: dict[str, Any] = {}
    if n.timeout_s is not None:
        news["timeout_s"] = float(n.timeout_s)
    if n.fontes is not None:
        padrao = _nomes_padrao()
        desconhecidas = sorted(set(n.fontes) - set(padrao))
        if desconhecidas:
            log.warning("[noticias] fontes desconhecidas ignoradas: %s", ", ".join(desconhecidas))
        news["sources"] = [{"name": nome, "enabled": False} for nome in padrao if nome not in n.fontes]
    dados: dict[str, Any] = {"news": news}
    if n.embedder:
        emb = dict(n.embedder)
        prov, modelo = emb.pop("provider", None), emb.pop("model", None)
        if not prov or not modelo:
            raise ConfigError("[noticias.embedder] precisa de provider e model")
        dados["providers"] = {str(prov): emb}
        dados["tasks"] = {"news": {"provider": str(prov), "model": str(modelo)}}
    return parse_config(dados)


def _dsn(deps: Deps) -> str:
    dsn = deps.extras.get("dsn") or dsn_padrao()
    recusar_magi(dsn)
    return str(dsn)


def dimensao_banco(db: Db) -> int | None:
    with db.connection() as conn:
        row = conn.execute(
            "SELECT atttypmod FROM pg_attribute"
            " WHERE attrelid = 'news_items'::regclass AND attname = 'embedding'"
        ).fetchone()
    return int(row[0]) if row and row[0] and row[0] > 0 else None


def conferir_dimensao(deps: Deps) -> None:
    dim = dimensao_banco(deps.db)
    if dim != deps.cfg.noticias.dim:
        raise DimensaoErrada(
            f"news_items.embedding tem {dim} dimensões; [noticias] dim = {deps.cfg.noticias.dim}"
        )


# --------------------------------------------------------------------------- bombas


def _mostrado(titulo: str, franquia: str | None, spoiler: Any, spoilers_ok: bool) -> tuple[str, str]:
    """(manchete, pode_mostrar_resumo) sem revelar spoiler (como o ``spoiler.present`` do PC)."""
    sp = spoiler if isinstance(spoiler, Mapping) else {}
    if sp.get("has") and not spoilers_ok:
        seguro = str(sp.get("safe_title") or "").strip()
        if seguro and seguro != titulo:
            return seguro, ""
        return f"Tem notícia de {franquia or 'uma obra'} com spoiler", ""
    return titulo, "ok"


_BOMBAS = """
SELECT i.uid::text, i.title, i.summary, i.franchise, i.spoiler, COALESCE(p.spoilers_ok, false)
FROM news_items i LEFT JOIN franchise_prefs p ON p.franchise = i.franchise
WHERE i.level = 'bomba' AND i.atualizado >= %(inicio)s AND i.first_seen >= %(idade)s
  AND NOT COALESCE(p.dropped, false)
  AND NOT EXISTS (SELECT 1 FROM eventos e
                  WHERE e.tipo = 'noticia_bomba' AND e.ref = 'noticia:' || i.uid::text)
ORDER BY i.id
"""


def avisar_bombas(deps: Deps, inicio: Any) -> list[str]:
    """``evento noticia_bomba`` para as bombas tocadas desde ``inicio``; devolve os ``uid``."""
    agora = deps.relogio.agora()
    feitos: list[str] = []
    with transacao(deps.db) as conn:
        linhas = conn.execute(
            _BOMBAS, {"inicio": inicio, "idade": inicio - timedelta(hours=MAX_IDADE_H)}
        ).fetchall()
        for uid, titulo, resumo, franquia, spoiler, spoilers_ok in linhas:
            manchete, mostra = _mostrado(titulo, franquia, spoiler, bool(spoilers_ok))
            criar_evento(conn, "noticia_bomba", f"Notícia bomba: {manchete}"[:TITULO_MAX],
                         (resumo or "")[:RESUMO_MAX] if mostra else "", f"noticia:{uid}", agora)
            feitos.append(uid)
    return feitos


def _agora_banco(db: Db) -> Any:
    with db.connection() as conn:
        return conn.execute("SELECT clock_timestamp()").fetchone()[0]


# --------------------------------------------------------------------------- jobs


async def coletar(deps: Deps, contexto: JobContext, *, timestamp: int) -> dict[str, Any] | None:
    """``noticias.coletar`` (cron ``0 */2 * * *`` UTC) (dono: Y3.2)."""
    if not deps.cfg.noticias.ligado:
        return {"texto": "notícias desligadas", "dados": {"ligado": False}}
    from magi.news import __main__ as news

    await asyncio.to_thread(conferir_dimensao, deps)
    config = montar_config(deps.cfg.noticias)
    dsn = _dsn(deps)
    inicio = await asyncio.to_thread(_agora_banco, deps.db)
    relatorio = await news.run_once(config, dsn)
    bombas = await asyncio.to_thread(avisar_bombas, deps, inicio)
    resumo = relatorio.summary() if hasattr(relatorio, "summary") else str(relatorio)
    log.info("coleta: %s; bombas: %d", resumo, len(bombas))
    return {"texto": f"coleta: {resumo}; {len(bombas)} bomba(s)", "dados": {"bombas": bombas}}


async def progresso(deps: Deps, contexto: JobContext, *, timestamp: int) -> dict[str, Any] | None:
    """``progresso.atualizar``: AniList/Steam e pontuação local, nunca LLM (dono: Y3.2)."""
    if not deps.cfg.noticias.ligado:
        return {"texto": "notícias desligadas", "dados": {"ligado": False}}
    from magi.news.priority import score_pending
    from magi.news.progress import update_if_due
    from magi.news.repo import PgNewsRepo
    from magi.news.sources import load_sources, make_http_client, news_settings

    config = montar_config(deps.cfg.noticias)
    agora = deps.relogio.agora()
    repo = await PgNewsRepo.connect(_dsn(deps))
    try:
        async with make_http_client() as http:
            prog = await update_if_due(repo, http, load_sources(config), news_settings(config), agora)
        pont = await score_pending(repo, agora)
    finally:
        await repo.close()
    texto = f"progresso: {prog.summary() if prog else 'nada a fazer'}; pontuação: {pont.summary()}"
    return {"texto": texto, "dados": {}}
