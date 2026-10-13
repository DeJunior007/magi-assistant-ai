"""Feed do celular (``GET /v1/feed?antes=<ts>&n=30``; dono: Y2.3; spec §2.2).

Cards ``{"tipo","titulo","resumo","ts","ref"}`` do mais novo ao mais velho, juntando:

- ``noticia``: ``news_items`` (``title``, ``summary``, ``first_seen``, ``ref`` = ``noticia:<uid>``);
- ``tarefa``: ``tarefas`` terminadas (``ok``/``falhou``, sem as do tipo ``lembrete``) — resumo =
  ``frase``, senão ``erro``, senão o começo de ``resultado.texto``; ``ts`` = ``atualizada``;
- ``lembrete``: ``eventos`` do tipo ``lembrete`` (``ts`` = ``criado``).

Paginação: ``antes`` é exclusivo; a página seguinte usa o ``ts`` do último card recebido (com
microssegundos, então nada se perde; só cards com o ``ts`` idêntico ao do corte ficariam de fora).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Query, Request

from ayanami.api.auth import Dispositivo, ErroApi, exigir_rota

router = APIRouter()

MAX_TITULO: Final = 120
MAX_RESUMO: Final = 200

_SQL: Final = """
SELECT * FROM (
    SELECT 'noticia' AS tipo, title AS titulo, coalesce(summary, '') AS resumo,
           first_seen AS ts, 'noticia:' || uid::text AS ref
      FROM news_items WHERE first_seen < %(antes)s
     ORDER BY first_seen DESC LIMIT %(n)s
) a
UNION ALL
SELECT * FROM (
    SELECT 'tarefa', titulo, coalesce(frase, erro, resultado->>'texto', ''), atualizada,
           'tarefa:' || id::text
      FROM tarefas WHERE estado IN ('ok', 'falhou') AND tipo <> 'lembrete' AND atualizada < %(antes)s
     ORDER BY atualizada DESC LIMIT %(n)s
) b
UNION ALL
SELECT * FROM (
    SELECT 'lembrete', titulo, resumo, criado, ref
      FROM eventos WHERE tipo = 'lembrete' AND criado < %(antes)s
     ORDER BY criado DESC LIMIT %(n)s
) c
ORDER BY ts DESC, ref DESC
LIMIT %(n)s
"""


def _ts(ts: datetime) -> str:
    """ISO em UTC com ``Z``, com microssegundos quando houver (o ``antes`` da página seguinte é exato)."""
    return ts.astimezone(UTC).isoformat().replace("+00:00", "Z")


def cards(db: Any, antes: datetime, n: int) -> list[dict[str, Any]]:
    with db.connection() as conn:
        rs = conn.execute(_SQL, {"antes": antes, "n": n}).fetchall()
    return [
        {"tipo": r[0], "titulo": (r[1] or "")[:MAX_TITULO], "resumo": (r[2] or "")[:MAX_RESUMO],
         "ts": _ts(r[3]), "ref": r[4]}
        for r in rs
    ]


@router.get("/v1/feed")
async def feed(
    request: Request,
    _disp: Annotated[Dispositivo, Depends(exigir_rota("GET", "/v1/feed"))],
    antes: Annotated[str | None, Query()] = None,
    n: Annotated[int, Query(ge=1, le=100)] = 30,
) -> dict[str, Any]:
    ctx = request.app.state.ctx
    if antes:
        try:
            limite = datetime.fromisoformat(antes.replace("Z", "+00:00"))
        except ValueError:
            raise ErroApi(422, "invalido", "antes precisa ser um timestamp ISO 8601") from None
        if limite.tzinfo is None:
            raise ErroApi(422, "invalido", "antes precisa de fuso")
    else:
        limite = ctx.relogio.agora()
    return {"cards": await asyncio.to_thread(cards, ctx.db, limite, n)}
