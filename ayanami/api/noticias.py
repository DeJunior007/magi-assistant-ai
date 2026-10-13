"""Notícias puxadas pelo PC (dono: Y3.2; spec §2.2, §5.2; consumidor: ``magi/elo/news_sync.py``).

- ``GET /v1/noticias?desde=<cursor>&n=200``: página de até ``n`` (1..200) itens em ordem de
  ``(atualizado, id)`` estritamente depois do cursor; ``cursor`` = ``"<atualizado ISO µs>Z|<id>"``
  do último item da página (sem itens: o mesmo ``desde``); ``fim`` = não sobrou item depois desta
  página. Cada página leva as ``brutos`` citadas pelos seus itens e as ``fontes`` dessas cruas, para
  o PC gravar a página numa transação só.
- ``PUT /v1/noticias/preferencias``: ``franchise_prefs`` do PC substitui a da Ayanami (o Pedro edita
  no PC); ``progress`` entra por *upsert* sem regredir (fica o ``updated_at`` mais novo, porque o
  ``progresso.atualizar`` da Ayanami também grava). ``204``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ayanami.api.auth import Dispositivo, ErroApi, exigir_rota
from ayanami.db import transacao

router = APIRouter()

PAGINA_MAX = 200


def _iso(ts: datetime | None) -> str | None:
    if ts is None:
        return None
    return ts.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def formatar_cursor(atualizado: datetime, item_id: int) -> str:
    return f"{_iso(atualizado)}|{item_id}"


def ler_cursor(texto: str) -> tuple[datetime, int]:
    try:
        ts, _, ident = texto.rpartition("|")
        quando = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if quando.tzinfo is None:
            raise ValueError("sem fuso")
        return quando, int(ident)
    except ValueError as e:
        raise ErroApi(422, "invalido", "cursor inválido") from e


_ITENS = """
SELECT id, uid::text, title, summary, embedding::text, first_seen, sources, max_trust, franchise,
       kind, spoiler, priority, level, atualizado
FROM news_items
WHERE (%(ts)s::timestamptz IS NULL OR (atualizado, id) > (%(ts)s::timestamptz, %(id)s::bigint))
ORDER BY atualizado, id
LIMIT %(n)s
"""

_BRUTOS = """
SELECT s.item_id, r.url, f.url, r.title, r.body, r.published_at, r.fetched_at
FROM news_item_sources s JOIN news_raw r ON r.id = s.raw_id
LEFT JOIN news_sources f ON f.id = r.source_id
WHERE s.item_id = ANY(%s)
ORDER BY r.id
"""


def pagina(conn: Any, desde: str | None, n: int) -> dict[str, Any]:
    ts, ident = ler_cursor(desde) if desde else (None, None)
    linhas = conn.execute(_ITENS, {"ts": ts, "id": ident, "n": n + 1}).fetchall()
    fim = len(linhas) <= n
    linhas = linhas[:n]
    ids = [r[0] for r in linhas]
    urls_por_item: dict[int, list[str]] = {i: [] for i in ids}
    brutos: dict[str, dict[str, Any]] = {}
    fontes_urls: set[str] = set()
    if ids:
        for item_id, url, fonte_url, title, body, pub, fetched in conn.execute(_BRUTOS, [ids]):
            urls_por_item[item_id].append(url)
            if fonte_url:
                fontes_urls.add(fonte_url)
            brutos.setdefault(url, {"url": url, "fonte_url": fonte_url, "title": title, "body": body,
                                    "published_at": _iso(pub), "fetched_at": _iso(fetched)})
    fontes = [
        {"name": nome, "kind": kind, "url": url, "trust": trust}
        for nome, kind, url, trust in conn.execute(
            "SELECT name, kind, url, trust FROM news_sources WHERE url = ANY(%s) ORDER BY id",
            [sorted(fontes_urls)],
        )
    ] if fontes_urls else []
    itens = [
        {"uid": uid, "title": title, "summary": summary,
         "embedding": json.loads(emb) if emb is not None else None,
         "first_seen": _iso(first_seen), "sources": sources, "max_trust": max_trust,
         "franchise": franchise, "kind": kind, "spoiler": spoiler, "priority": priority,
         "level": level, "brutos": urls_por_item[item_id]}
        for (item_id, uid, title, summary, emb, first_seen, sources, max_trust, franchise, kind,
             spoiler, priority, level, _) in linhas
    ]
    cursor = formatar_cursor(linhas[-1][13], linhas[-1][0]) if linhas else desde
    return {"cursor": cursor, "fim": fim, "fontes": fontes, "brutos": list(brutos.values()),
            "itens": itens}


@router.get("/v1/noticias")
def listar(
    request: Request,
    _: Annotated[Dispositivo, Depends(exigir_rota("GET", "/v1/noticias"))],
    desde: Annotated[str | None, Query(max_length=80)] = None,
    n: Annotated[int, Query(ge=1, le=PAGINA_MAX)] = PAGINA_MAX,
) -> JSONResponse:
    with request.app.state.ctx.db.connection() as conn:
        return JSONResponse(pagina(conn, desde, n))


class Pref(BaseModel):
    franchise: str = Field(min_length=1, max_length=200)
    weight: float = 1.0
    dropped: bool = False
    spoilers_ok: bool = False


class Progresso(BaseModel):
    franchise: str = Field(min_length=1, max_length=200)
    kind: str = Field(min_length=1, max_length=50)
    value: str | None = Field(default=None, max_length=500)
    updated_at: datetime | None = None


class Preferencias(BaseModel):
    franchise_prefs: list[Pref] = Field(default_factory=list, max_length=5000)
    progress: list[Progresso] = Field(default_factory=list, max_length=5000)


def gravar_preferencias(conn: Any, prefs: Preferencias, agora: datetime) -> None:
    conn.execute("DELETE FROM franchise_prefs")
    for p in prefs.franchise_prefs:
        conn.execute(
            "INSERT INTO franchise_prefs (franchise, weight, dropped, spoilers_ok) VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (franchise) DO UPDATE SET weight = EXCLUDED.weight,"
            " dropped = EXCLUDED.dropped, spoilers_ok = EXCLUDED.spoilers_ok",
            [p.franchise, p.weight, p.dropped, p.spoilers_ok],
        )
    for g in prefs.progress:
        conn.execute(
            "INSERT INTO progress (franchise, kind, value, updated_at) VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (franchise, kind) DO UPDATE SET value = EXCLUDED.value,"
            " updated_at = EXCLUDED.updated_at WHERE progress.updated_at <= EXCLUDED.updated_at",
            [g.franchise, g.kind, g.value, g.updated_at or agora],
        )


@router.put("/v1/noticias/preferencias")
def preferencias(
    request: Request,
    corpo: Preferencias,
    _: Annotated[Dispositivo, Depends(exigir_rota("PUT", "/v1/noticias/preferencias"))],
) -> Response:
    ctx = request.app.state.ctx
    with transacao(ctx.db) as conn:
        gravar_preferencias(conn, corpo, ctx.relogio.agora())
    return Response(status_code=204)
