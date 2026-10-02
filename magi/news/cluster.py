"""Passo 2 do ``magi-news``: agrupar notícias cruas em itens (design §8, R18.3, R18.6).

Para cada ``news_raw`` ainda sem item, gera o embedding de título + lead (provedor de embeddings da
tarefa ``news``, ``personal=False``) e junta a um item das últimas 72 h com cosseno >= 0,88; sem
parecido, cria item novo. Os embeddings saem em lotes (uma chamada por lote). Se a cota acabar
(``QuotaExhausted``, que inclui ``FreeQuotaExhausted``), para sem erro: o que faltou continua fora de
``news_item_sources`` e é pego na próxima execução.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from magi.common.contracts import EmbeddingProvider, NewsItem, NewsRaw, NewsRepo, QuotaExhausted

log = logging.getLogger(__name__)

MIN_COSINE = 0.88
WINDOW = timedelta(hours=72)
BATCH_SIZE = 32
MAX_RAW = 200
LEAD_CHARS = 300

_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"\s+")


@dataclass(slots=True)
class ClusterReport:
    embedded: int = 0
    joined: int = 0
    created: int = 0
    deferred: int = 0  # cruas deixadas para a próxima execução (cota esgotada)
    quota_exhausted: bool = False

    def summary(self) -> str:
        s = f"{self.embedded} agrupadas ({self.created} itens novos, {self.joined} juntadas)"
        if self.quota_exhausted:
            s += f"; cota esgotada, {self.deferred} pendentes"
        return s


def lead(body: str, limit: int = LEAD_CHARS) -> str:
    """Primeiro trecho do corpo, sem HTML e com espaços normalizados."""
    text = _SPACES.sub(" ", _TAGS.sub(" ", body or "")).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return (cut or text[:limit]) + "…"


def embed_text(raw: NewsRaw) -> str:
    return f"{raw.title.strip()}\n{lead(raw.body)}".strip()


async def cluster_pending(
    repo: NewsRepo,
    embedder: EmbeddingProvider,
    *,
    min_cosine: float = MIN_COSINE,
    window: timedelta = WINDOW,
    batch_size: int = BATCH_SIZE,
    max_raw: int = MAX_RAW,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ClusterReport:
    """Agrupa até ``max_raw`` cruas pendentes. Cotas esgotadas não levantam erro."""
    report = ClusterReport()
    pending = await repo.ungrouped_raw(limit=max_raw)
    for start in range(0, len(pending), batch_size):
        batch = pending[start : start + batch_size]
        try:
            vectors = await embedder.embed([embed_text(r) for r in batch], personal=False)
        except QuotaExhausted as exc:
            report.quota_exhausted = True
            report.deferred = len(pending) - start
            log.warning("cota de embeddings esgotada (%s); %d cruas ficam para depois", exc, report.deferred)
            break
        if len(vectors) != len(batch):
            raise ValueError(f"embeddings: {len(vectors)} vetores para {len(batch)} textos")
        since = now() - window
        for raw, vec in zip(batch, vectors, strict=True):
            assert raw.id is not None
            found = await repo.similar_items(vec, since, min_cosine, limit=1)
            if found:
                item, cos = found[0]
                assert item.id is not None
                await repo.attach_raw(item.id, raw.id)
                report.joined += 1
                log.debug("crua %d -> item %d (cos %.3f)", raw.id, item.id, cos)
            else:
                item_id = await repo.add_item(
                    NewsItem(title=raw.title.strip() or raw.url, summary=lead(raw.body)), vec, [raw.id]
                )
                report.created += 1
                log.debug("crua %d -> item novo %d", raw.id, item_id)
            report.embedded += 1
    return report
