"""SSE dos eventos (``GET /v1/eventos``; dono: Y2.3; spec §2.2, §2.3).

- :class:`Publicador` (``ctx.extras["sse"]`` via :func:`sse_de`): ``publicar(alvo, nome, corpo,
  id=None)`` entrega a todo SSE aberto cujo dispositivo casa com ``alvo`` (id ``int``, nome, tipo
  ``"celular"``/``"pc"`` ou ``"*"``). Nomes da spec: ``turno.texto`` ``{"turno","texto"}``,
  ``turno.fim`` ``TurnoFim``, ``evento`` ``Evento`` (``id:`` = ``seq``), ``estado`` ``Estado``,
  ``confirma`` ``Confirma``; ``ping`` a cada 15 s. ``data:`` = JSON do corpo. Até 4 SSE por
  dispositivo (o 5º → ``429``).
- Retomada: com ``Last-Event-ID`` o fluxo **primeiro assina** e depois relê ``eventos`` com
  ``id >`` o informado; o que chega ao vivo com ``seq`` já mandado é descartado — sem perder nem
  repetir.
- Revogação: no mesmo processo pelo gancho ``auth.ao_revogar`` (fecha na hora); de outro processo
  pela varredura de ``dispositivos.revogado`` a cada 2,5 s (≤ 5 s), como o hub da Y2.2. A mesma
  varredura manda as confirmações pendentes ainda não mandadas (a ``Confirmacoes`` publica ao vivo
  desde a Y2.2b; a varredura cobre as criadas por outro processo) e, para as mandadas que saíram de
  pendentes sem fechamento ao vivo, o fechamento: ``confirma`` relido do banco (``resposta`` preenchida,
  ou ``null`` com ``expira_em`` ≤ agora = expirou).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from ayanami import confirmacoes
from ayanami.api.auth import Dispositivo, ErroApi, exigir_rota
from ayanami.eventos import eventos_de, listar_desde, vida
from ayanami.hub import esperar_com_prazo
from magi.elo.mensagens import _para_json

log = logging.getLogger("ayanami.sse")

MAX_SSE: Final = 4
PING_S: Final = 15.0
VARREDURA_S: Final = 2.5
RETRY_MS: Final = 3000
FILA_MAX: Final = 512
_FECHAR: Final = object()


def formatar(nome: str, dados: str, id_: int | None = None) -> str:
    linhas = [f"id: {id_}"] if id_ is not None else []
    linhas.append(f"event: {nome}")
    linhas.extend(f"data: {parte}" for parte in dados.split("\n"))
    return "\n".join(linhas) + "\n\n"


def _json(corpo: Any) -> str:
    return json.dumps(_para_json(corpo) if not isinstance(corpo, str) else corpo,
                      ensure_ascii=False, separators=(",", ":"))


@dataclass(eq=False)
class Assinante:
    disp: Dispositivo
    fila: asyncio.Queue[Any] = field(default_factory=lambda: asyncio.Queue(FILA_MAX))
    fechado: bool = False

    def por(self, item: Any) -> None:
        try:
            self.fila.put_nowait(item)
        except asyncio.QueueFull:  # cliente lento: fecha; ele reconecta com Last-Event-ID
            log.info("sse_fila_cheia (%s)", self.disp.nome)
            self.fechado = True


class Publicador:
    """Assinaturas SSE em memória (um processo, como o hub)."""

    def __init__(self, max_por_dispositivo: int = MAX_SSE) -> None:
        self.max = max_por_dispositivo
        self._ass: list[Assinante] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    def contar(self, disp_id: int) -> int:
        return sum(1 for a in self._ass if a.disp.id == disp_id)

    def abrir(self, disp: Dispositivo) -> Assinante:
        if self.contar(disp.id) >= self.max:
            raise ErroApi(429, "muitas_conexoes", f"até {self.max} SSE por dispositivo",
                          {"Retry-After": "5"})
        self._loop = asyncio.get_running_loop()
        a = Assinante(disp)
        self._ass.append(a)
        return a

    def fechar(self, a: Assinante) -> None:
        a.fechado = True
        with contextlib.suppress(ValueError):
            self._ass.remove(a)

    @staticmethod
    def _casa(a: Assinante, alvo: int | str) -> bool:
        if isinstance(alvo, int):
            return a.disp.id == alvo
        return alvo == "*" or a.disp.nome == alvo or a.disp.tipo == alvo

    def publicar(self, alvo: int | str, nome: str, corpo: Any, *, id: int | None = None) -> int:  # noqa: A002
        """Entrega a cada SSE de ``alvo``; devolve quantos receberam. Seguro fora do loop."""
        item = (nome, _json(corpo), id)
        alvos = [a for a in self._ass if not a.fechado and self._casa(a, alvo)]
        self._chamar(lambda: [a.por(item) for a in alvos])
        return len(alvos)

    def revogado(self, disp: Dispositivo) -> None:
        """Gancho de ``auth.ao_revogar``: fecha os SSE do dispositivo."""
        alvos = [a for a in self._ass if a.disp.id == disp.id]
        self._chamar(lambda: [a.por(_FECHAR) for a in alvos])

    def _chamar(self, fn: Callable[[], Any]) -> None:
        loop = self._loop
        try:
            corrente = asyncio.get_running_loop()
        except RuntimeError:
            corrente = None
        if loop is None or corrente is loop:
            fn()
        else:
            loop.call_soon_threadsafe(fn)


def sse_de(ctx: Any) -> Publicador:
    """O publicador da app (``ctx.extras["sse"]``), ligado a ``auth.ao_revogar`` na 1ª vez."""
    pub = ctx.extras.get("sse")
    if pub is None:
        pub = Publicador()
        ctx.extras["sse"] = pub
        ctx.auth.ao_revogar.append(pub.revogado)
    return pub


def _revogado(db: Any, disp_id: int) -> bool:
    with db.connection() as conn:
        r = conn.execute("SELECT revogado IS NOT NULL FROM dispositivos WHERE id = %s",
                         (disp_id,)).fetchone()
    return r is None or bool(r[0])


async def fluxo(ctx: Any, pub: Publicador, a: Assinante, desde: int | None,
                desconectado: Callable[[], Awaitable[bool]] | None = None) -> AsyncIterator[str]:
    """O texto do SSE de ``a`` (já aberto em ``pub``). Termina na revogação, no desligamento do
    cliente ou com a fila cheia; sempre libera a vaga."""
    db, relogio = ctx.db, ctx.relogio
    try:
        yield f"retry: {RETRY_MS}\n\n"
        ultimo = desde
        if desde is not None:
            while True:
                lote = await asyncio.to_thread(listar_desde, db, ultimo, a.disp.tipo)
                for ev in lote:
                    yield formatar("evento", _json(ev), ev.seq)
                    ultimo = ev.seq
                if len(lote) < 200:
                    break
        mandadas: set[str] = set()
        fechadas: set[str] = set()
        prox_varre = relogio.monotonico()
        prox_ping = relogio.monotonico() + PING_S
        while not a.fechado:
            agora = relogio.monotonico()
            if agora >= prox_varre:
                prox_varre = agora + VARREDURA_S
                if await asyncio.to_thread(_revogado, db, a.disp.id):
                    log.info("sse_revogado (%s)", a.disp.nome)
                    return
                if desconectado is not None and await desconectado():
                    return
                pend = await asyncio.to_thread(confirmacoes.pendentes, db, relogio)
                for c in pend:
                    if c.id not in mandadas:
                        mandadas.add(c.id)
                        yield formatar("confirma", _json(c.para_elo()))
                for id_ in sorted(mandadas - fechadas - {c.id for c in pend}):
                    fechadas.add(id_)
                    c = await asyncio.to_thread(confirmacoes.obter, db, id_)
                    if c is not None:
                        yield formatar("confirma", _json(c.para_elo()))
            if agora >= prox_ping:
                prox_ping = agora + PING_S
                yield formatar("ping", "{}")
            espera = max(0.0, min(prox_varre, prox_ping) - relogio.monotonico())
            try:
                item = await esperar_com_prazo(relogio, a.fila.get(), espera)
            except TimeoutError:
                continue
            if item is _FECHAR:
                log.info("sse_revogado (%s)", a.disp.nome)
                return
            nome, dados, id_ = item
            if nome == "evento" and id_ is not None:
                if ultimo is not None and id_ <= ultimo:
                    continue  # já veio na releitura
                ultimo = id_
            if nome == "confirma":
                corpo = json.loads(dados)
                pedido = corpo.get("pedido")
                if corpo.get("resposta") is not None:
                    if pedido in fechadas:
                        continue  # a varredura já mandou o fechamento
                    fechadas.add(pedido)
                else:
                    if pedido in mandadas:
                        continue  # a varredura já mandou a pergunta
                    mandadas.add(pedido)
            yield formatar(nome, dados, id_)
    finally:
        pub.fechar(a)


def _ultimo_id(request: Request) -> int | None:
    valor = request.headers.get("last-event-id", "").strip()
    return int(valor) if valor.isdigit() else None


class RespostaSse(StreamingResponse):
    """``StreamingResponse`` que libera a vaga mesmo se o fluxo nem começar."""

    def __init__(self, conteudo: AsyncIterator[str], liberar: Callable[[], None]) -> None:
        super().__init__(conteudo, media_type="text/event-stream",
                         headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
        self._liberar = liberar

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._liberar()


@contextlib.asynccontextmanager
async def _vida_router(app: Any) -> AsyncIterator[Mapping[str, Any]]:
    async with vida(app.state.ctx):
        yield {}


router = APIRouter(lifespan=_vida_router)


@router.get("/v1/eventos")
async def eventos(
    request: Request,
    disp: Annotated[Dispositivo, Depends(exigir_rota("GET", "/v1/eventos"))],
) -> RespostaSse:
    ctx = request.app.state.ctx
    pub = sse_de(ctx)
    eventos_de(ctx)  # liga hub/estado ao SSE mesmo sem lifespan (testes, 1ª conexão)
    a = pub.abrir(disp)
    return RespostaSse(fluxo(ctx, pub, a, _ultimo_id(request), request.is_disconnected),
                       lambda: pub.fechar(a))
