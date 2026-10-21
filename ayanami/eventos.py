"""Eventos da Ayanami (dono: Y2.3; spec §1.2 ``Evento``, §3 ``eventos``, design §4.1/§13).

- :func:`gravar` / :func:`criar_evento`: linha em ``eventos`` (``id`` = ``Evento.seq`` = id do SSE)
  + ``NOTIFY ayanami_eventos`` com o id (mesmo canal e payload que ``tarefas.criar_evento`` da
  Y3.1, então o ouvinte pega os dois). ``titulo`` ≤ 80 e ``resumo`` ≤ 200 caracteres (cortados).
- :class:`Eventos` (``ctx.extras["eventos"]`` via :func:`eventos_de`): :meth:`Eventos.criar` grava e
  distribui; :meth:`Eventos.distribuir` relê o banco **depois** do último ``seq`` distribuído e manda
  ao SSE (``publicar("celular"|"pc", "evento", Evento, id=seq)``) e, para quem tem ``pc`` em ``para``,
  ao ``pc`` pelo hub (``evento`` → ``ack`` → ``entregue_pc``). PC offline: fica pendente e sai no
  próximo ``ola`` do ``pc`` (``retomar_desde`` marca como entregue o que o PC já tem).
- :meth:`Eventos.ouvir`: ``LISTEN ayanami_eventos`` numa conexão própria; a cada (re)conexão relê os
  pendentes antes de esperar — um ``NOTIFY`` perdido na queda não perde o evento (design §13).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Iterable, Sequence
from datetime import datetime, timedelta
from typing import Any, Final

from ayanami.db import Db, transacao
from magi.elo.mensagens import Envelope, Evento, EventoTipo, Ola, Tipo

log = logging.getLogger("ayanami.eventos")

CANAL: Final = "ayanami_eventos"
MAX_TITULO: Final = 80
MAX_RESUMO: Final = 200
PARA_PADRAO: Final = ("pc", "celular")
PRAZO_PC_S: Final = 30.0
RETENCAO_DIAS: Final = 30
LOTE: Final = 200
ESPERA_MAX_S: Final = 30.0

_COLUNAS = "id, tipo, titulo, resumo, ref"

Publicar = Callable[..., Any]  # publicar(alvo, nome, corpo, *, id=None) -> int


def _evento(r: Sequence[Any]) -> Evento | None:
    try:
        tipo = EventoTipo(r[1])
    except ValueError:
        log.warning("evento_tipo_desconhecido (%s)", r[1])
        return None
    return Evento(seq=int(r[0]), tipo=tipo, titulo=(r[2] or "")[:MAX_TITULO],
                  resumo=(r[3] or "")[:MAX_RESUMO], ref=r[4])


def gravar(conn: Any, tipo: EventoTipo | str, titulo: str, resumo: str = "", ref: str | None = None,
           *, para: Iterable[str] = PARA_PADRAO, agora: datetime | None = None,
           notificar: bool = True) -> Evento:
    """Grava na transação de ``conn`` e faz ``NOTIFY`` (sai no commit)."""
    tipo = EventoTipo(tipo)
    titulo = titulo.strip()[:MAX_TITULO]
    resumo = (resumo or "").strip()[:MAX_RESUMO]
    sql = ("INSERT INTO eventos (tipo, titulo, resumo, ref, para{c})"
           " VALUES (%s, %s, %s, %s, %s{v}) RETURNING id")
    args: list[Any] = [tipo.value, titulo, resumo, ref, list(para)]
    if agora is not None:
        sql = sql.format(c=", criado", v=", %s")
        args.append(agora)
    else:
        sql = sql.format(c="", v="")
    eid = int(conn.execute(sql, args).fetchone()[0])
    if notificar:
        conn.execute("SELECT pg_notify(%s, %s)", (CANAL, str(eid)))
    return Evento(seq=eid, tipo=tipo, titulo=titulo, resumo=resumo, ref=ref)


def criar_evento(db: Db, tipo: EventoTipo | str, titulo: str, resumo: str = "", ref: str | None = None,
                 *, para: Iterable[str] = PARA_PADRAO, agora: datetime | None = None) -> Evento:
    """:func:`gravar` numa transação própria (para workers e CLI de outros processos)."""
    with transacao(db) as conn:
        return gravar(conn, tipo, titulo, resumo, ref, para=para, agora=agora)


def listar_desde(db: Db, seq: int, para: str | None = None, limite: int = LOTE) -> list[Evento]:
    """Eventos com ``id > seq`` (em ordem), opcionalmente só os que têm ``para`` no destino."""
    sql = f"SELECT {_COLUNAS} FROM eventos WHERE id > %s"
    args: list[Any] = [seq]
    if para is not None:
        sql += " AND %s = ANY(para)"
        args.append(para)
    sql += " ORDER BY id LIMIT %s"
    args.append(limite)
    with db.connection() as conn:
        rs = conn.execute(sql, args).fetchall()
    return [e for e in (_evento(r) for r in rs) if e is not None]


def _distribuiveis(db: Db, seq: int) -> list[tuple[Evento | None, int, tuple[str, ...]]]:
    with db.connection() as conn:
        rs = conn.execute(
            f"SELECT {_COLUNAS}, para FROM eventos WHERE id > %s ORDER BY id LIMIT %s", (seq, LOTE)
        ).fetchall()
    return [(_evento(r), int(r[0]), tuple(r[5] or ())) for r in rs]


def ultimo_seq(db: Db) -> int:
    with db.connection() as conn:
        return int(conn.execute("SELECT coalesce(max(id), 0) FROM eventos").fetchone()[0])


def _pendentes_pc(db: Db, desde: datetime) -> list[Evento]:
    with db.connection() as conn:
        rs = conn.execute(
            f"SELECT {_COLUNAS} FROM eventos WHERE entregue_pc IS NULL AND 'pc' = ANY(para)"
            " AND criado > %s ORDER BY id LIMIT %s", (desde, LOTE),
        ).fetchall()
    return [e for e in (_evento(r) for r in rs) if e is not None]


def _marcar_pc(db: Db, ids: Sequence[int], agora: datetime, *, ate: int | None = None) -> None:
    with transacao(db) as conn:
        if ate is not None:
            conn.execute("UPDATE eventos SET entregue_pc = %s WHERE entregue_pc IS NULL AND id <= %s"
                         " AND 'pc' = ANY(para)", (agora, ate))
        if ids:
            conn.execute("UPDATE eventos SET entregue_pc = %s WHERE id = ANY(%s) AND entregue_pc IS NULL",
                         (agora, list(ids)))


class Eventos:
    """Distribui eventos ao SSE e ao ``pc``. Um por app (``ctx.extras["eventos"]``)."""

    def __init__(self, db: Db, relogio: Any, *, hub: Any = None, publicar: Publicar | None = None,
                 prazo_pc_s: float = PRAZO_PC_S,
                 push: Callable[[int], Awaitable[Any]] | None = None) -> None:
        self.db = db
        self.push = push  # defere ``push.enviar`` dos eventos para ``celular`` (P2.1)
        self.relogio = relogio
        self.hub = hub
        self.publicar = publicar
        self.prazo_pc_s = prazo_pc_s
        self._ultimo: int | None = None
        self._trava = asyncio.Lock()
        self._trava_pc = asyncio.Lock()
        self._pc_de_novo = False
        self._tarefas: set[asyncio.Task[Any]] = set()

    # --- criar e distribuir --------------------------------------------------------------------

    async def preparar(self) -> None:
        """Fixa o ponto de partida da distribuição (o que já estava no banco não é re-publicado)."""
        if self._ultimo is None:
            self._ultimo = await asyncio.to_thread(ultimo_seq, self.db)

    async def criar(self, tipo: EventoTipo | str, titulo: str, resumo: str = "", ref: str | None = None,
                    *, para: Iterable[str] = PARA_PADRAO) -> Evento:
        await self.preparar()
        ev = await asyncio.to_thread(criar_evento, self.db, tipo, titulo, resumo, ref,
                                     para=tuple(para), agora=self.relogio.agora())
        await self.distribuir()
        return ev

    async def distribuir(self) -> int:
        """Publica no SSE tudo o que entrou depois do último ``seq`` e agenda a entrega ao ``pc``."""
        await self.preparar()
        n = 0
        pc = False
        async with self._trava:
            while True:
                linhas = await asyncio.to_thread(_distribuiveis, self.db, self._ultimo or 0)
                for ev, seq, para in linhas:
                    self._ultimo = seq
                    if ev is None:
                        continue
                    n += 1
                    if self.publicar is not None:
                        for alvo in para:  # SSE de quem é desse tipo ("celular", e "pc" se abrir)
                            self.publicar(alvo, "evento", ev, id=ev.seq)
                    pc = pc or "pc" in para
                    if self.push is not None and "celular" in para:
                        self._agendar(self._push(ev.seq))
                if len(linhas) < LOTE:
                    break
        if pc:
            self.entregar_pc_logo()
        return n

    async def _push(self, seq: int) -> None:
        try:
            await self.push(seq)
        except Exception:  # noqa: BLE001 - push nunca derruba a distribuição
            log.exception("push_agendar_falhou (evento %s)", seq)

    # --- PC ------------------------------------------------------------------------------------

    def _agendar(self, coro: Awaitable[Any]) -> None:
        t = asyncio.ensure_future(coro)
        self._tarefas.add(t)
        t.add_done_callback(self._tarefas.discard)

    def entregar_pc_logo(self) -> None:
        if self.hub is not None:
            self._agendar(self.entregar_pc())

    async def entregar_pc(self) -> int:
        """Manda ao ``pc`` (em ordem) os eventos ainda não entregues; para no 1º sem ``ack``."""
        if self.hub is None:
            return 0
        if self._trava_pc.locked():
            self._pc_de_novo = True
            return 0
        entregues = 0
        async with self._trava_pc:
            while True:
                self._pc_de_novo = False
                if self.hub.destino("pc") is None:
                    return entregues
                desde = self.relogio.agora() - timedelta(days=RETENCAO_DIAS)
                pend = await asyncio.to_thread(_pendentes_pc, self.db, desde)
                for ev in pend:
                    env = Envelope(t=Tipo.EVENTO, corpo=ev, de="ayanami", para="pc")
                    try:
                        await self.hub.enviar_e_esperar(env, self.prazo_pc_s)
                    except Exception as e:  # noqa: BLE001 - offline/tempo: tenta no próximo ola
                        log.info("evento_pc_pendente (%s)", type(e).__name__)
                        return entregues
                    await asyncio.to_thread(_marcar_pc, self.db, [ev.seq], self.relogio.agora())
                    entregues += 1
                if not self._pc_de_novo and len(pend) < LOTE:
                    return entregues

    async def ao_ola_pc(self, _disp: Any, ola: Ola) -> None:
        """Gancho ``hub.ao_ola("pc")``: marca o que o PC já tem e manda o resto (em segundo plano)."""
        if ola.retomar_desde and ola.retomar_desde.isdigit():
            await asyncio.to_thread(_marcar_pc, self.db, [], self.relogio.agora(),
                                    ate=int(ola.retomar_desde))
        self.entregar_pc_logo()

    # --- LISTEN --------------------------------------------------------------------------------

    async def ouvir(self, conectar: Callable[[], Awaitable[Any]]) -> None:
        """``LISTEN`` para sempre (cancelar para parar). ``conectar()`` devolve uma
        ``psycopg.AsyncConnection`` em autocommit. Em cada (re)conexão relê os pendentes."""
        espera = 1.0
        while True:
            try:
                conn = await conectar()
                async with conn:
                    await conn.execute(f"LISTEN {CANAL}")
                    espera = 1.0
                    await self.distribuir()
                    self.entregar_pc_logo()
                    async for _ in conn.notifies():
                        await self.distribuir()
                log.info("eventos_listen_caiu")
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - banco caiu: reconecta com espera
                log.warning("eventos_listen_falhou (%s)", type(e).__name__)
                await self.relogio.dormir(espera)
                espera = min(espera * 2, ESPERA_MAX_S)

    async def fechar(self) -> None:
        for t in list(self._tarefas):
            t.cancel()
        with contextlib.suppress(Exception):
            await asyncio.gather(*self._tarefas, return_exceptions=True)


def _dsn(db: Any) -> str | None:
    return getattr(db, "dsn", None) or getattr(db, "conninfo", None)


def eventos_de(ctx: Any) -> Eventos:
    """O serviço da app (``ctx.extras["eventos"]``), ligado ao hub (``ola`` do ``pc``, ``estado``
    da casa → SSE) e ao publicador do SSE na 1ª vez."""
    svc = ctx.extras.get("eventos")
    if svc is not None:
        return svc
    from ayanami.api.eventos import sse_de
    from ayanami.hub import hub_de

    sse = sse_de(ctx)
    hub = hub_de(ctx)
    async def push(seq: int) -> None:
        # fila dos testes (``extras["fila"]``) ou a de produção (``app_de_producao`` liga a flag)
        app = ctx.extras.get("fila")
        if app is None and not ctx.extras.get("fila_producao"):
            return
        from ayanami import fila
        from ayanami import push as pushmod

        await pushmod.agendar(await fila.app_aberto(app), seq)

    svc = Eventos(ctx.db, ctx.relogio, hub=hub, publicar=sse.publicar, push=push)
    hub.ao_ola("pc", svc.ao_ola_pc)

    def estado_ao_sse(_disp: Any, env: Envelope) -> None:
        sse.publicar("celular", "estado", env.corpo)

    hub.ao_receber(Tipo.ESTADO, estado_ao_sse)
    ctx.extras["eventos"] = svc
    return svc


async def conectar_listen(dsn: str) -> Any:
    import psycopg

    return await psycopg.AsyncConnection.connect(dsn, autocommit=True, connect_timeout=5)


@contextlib.asynccontextmanager
async def vida(ctx: Any):  # noqa: ANN201 - gerenciador de contexto do lifespan
    """Sobe o ouvinte ``LISTEN`` junto com a app (só se o ``Db`` expõe o DSN)."""
    svc = eventos_de(ctx)
    dsn = _dsn(ctx.db)
    tarefa = asyncio.ensure_future(svc.ouvir(lambda: conectar_listen(dsn))) if dsn else None
    if tarefa is None:
        log.info("eventos_sem_listen")
    try:
        yield svc
    finally:
        if tarefa is not None:
            tarefa.cancel()
            with contextlib.suppress(BaseException):
                await tarefa
        await svc.fechar()
