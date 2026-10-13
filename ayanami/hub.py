"""Hub dos nós ``pc``/``casa`` (dono: Y2.2; spec §1.3, §2.2, design §4.1).

Um processo só (as conexões ficam em memória). Cada dispositivo tem **uma** conexão ativa (WS ou
long-poll); a nova fecha a antiga com ``4002``. Os frames recebidos passam pelo ``Receptor`` do
elo (idempotência por ``id``, ``erro`` em inválido, ``1008`` por abuso).

- :meth:`Hub.enviar_e_esperar`: manda um envelope que pede resposta ao nó (por nome ou pelo tipo
  ``"pc"``/``"casa"``), reenvia o **mesmo** envelope a cada 10 s sem resposta (até 3×, sempre à
  conexão ativa do momento) e levanta :class:`NoOffline` / ``TimeoutError`` no ``prazo``.
- ``visto``/``online``: ``ola`` e ``bate`` atualizam o relógio do nó e ``dispositivos.visto``; online
  = ``bate`` dentro de ``[rede] offline_apos_s``. Guarda o último ``ola``/``estado`` da casa.
- Ganchos: :meth:`ao_ola` ``(tipo_dispositivo, fn(disp, ola))`` e :meth:`ao_receber`
  ``(Tipo, fn(disp, env) -> Envelope | Corpo | None)`` para Y5.1/Y6.x.
- Revogação: :meth:`revogado` (gancho de ``auth.ao_revogar``, mesmo processo) fecha com ``4001``
  na hora. Revogação feita por **outro processo** (``ayanami dispositivo revogar``): enquanto há
  conexão aberta, uma varredura a cada ``varredura_s`` (2,5 s) lê ``dispositivos.revogado`` dos
  conectados e fecha os revogados com ``4001`` (≤ 5 s, R1.4).

O relógio (``agora``/``monotonico``/``dormir``) é injetado; nada de ``sleep`` próprio.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, Protocol

from ayanami.api.auth import Dispositivo
from ayanami.db import Db, transacao
from magi.elo.mensagens import (
    CORPOS,
    PEDE_RESPOSTA,
    Ack,
    AppInfo,
    EloError,
    Envelope,
    Estado,
    EstadoTv,
    Ola,
    Tipo,
    TvInfo,
    decode,
    encode,
    responder,
)
from magi.elo.receptor import Receptor

log = logging.getLogger("ayanami.hub")

FECHA_REVOGADO: Final = 4001
FECHA_SUBSTITUIDA: Final = 4002
FECHA_SEM_OLA: Final = 4003
FECHA_POLITICA: Final = 1008
OLA_PRAZO_S: Final = 5.0
REENVIO_S: Final = 10.0
REENVIOS: Final = 3
VARREDURA_S: Final = 2.5
LONGPOLL_FILA: Final = 256
NOME: Final = "ayanami"

_TIPO_DO_CORPO: Final = {cls: t for t, cls in CORPOS.items()}


class NoOffline(Exception):
    """Nenhuma conexão ativa para o destino (ou ela caiu com o pedido em voo)."""


class Canal(Protocol):
    """Lado servidor de uma conexão: WS (``enviar`` manda já) ou long-poll (enfileira)."""

    async def enviar(self, texto: str) -> None: ...
    async def fechar(self, codigo: int) -> None: ...


@dataclass(eq=False)
class No:
    disp: Dispositivo
    canal: Canal
    modo: str  # "ws" | "longpoll"
    receptor: Receptor
    ola: Ola | None = None
    visto: float | None = None  # monotônico do último ola/bate
    fechado: bool = False


@dataclass(eq=False)
class CanalLongpoll:
    """Fila de saída de um nó em long-poll: ``GET /v1/longpoll?desde=`` lê daqui."""

    seq: int = 0
    fila: deque[tuple[int, str]] = field(default_factory=lambda: deque(maxlen=LONGPOLL_FILA))
    novo: asyncio.Event = field(default_factory=asyncio.Event)
    fechado_com: int | None = None
    ultimo_get: float = 0.0

    async def enviar(self, texto: str) -> None:
        self.seq += 1
        self.fila.append((self.seq, texto))
        self.novo.set()

    async def fechar(self, codigo: int) -> None:
        self.fechado_com = codigo
        self.novo.set()

    def desde(self, seq: int) -> list[tuple[int, str]]:
        return [(s, t) for s, t in self.fila if s > seq]


@dataclass
class EstadoCasa:
    online: bool
    visto: datetime | None
    tvs: tuple[TvInfo, ...]
    estados: tuple[EstadoTv, ...]
    apps: tuple[AppInfo, ...]


GanchoOla = Callable[[Dispositivo, Ola], Any]
GanchoReceber = Callable[[Dispositivo, Envelope], Any]


class Hub:
    def __init__(
        self,
        db: Db,
        relogio: Any,
        *,
        offline_apos_s: float = 30.0,
        reenvio_s: float = REENVIO_S,
        reenvios: int = REENVIOS,
        varredura_s: float = VARREDURA_S,
        auditar: Callable[..., Any] | None = None,
    ) -> None:
        self.db = db
        self.relogio = relogio
        self.offline_apos_s = offline_apos_s
        self.reenvio_s = reenvio_s
        self.reenvios = reenvios
        self.varredura_s = varredura_s
        self._auditar = auditar
        self._nos: dict[int, No] = {}
        self._pendentes: dict[str, asyncio.Future[Envelope]] = {}
        self._resolvidos: deque[str] = deque(maxlen=512)
        self._ganchos_ola: dict[str, list[GanchoOla]] = {}
        self._ganchos_receber: dict[Tipo, list[GanchoReceber]] = {}
        self._casa_ola: Ola | None = None
        self._casa_estado: Estado | None = None
        self._casa_visto: datetime | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._varredura: asyncio.Task[None] | None = None
        self.longpolls: dict[int, CanalLongpoll] = {}

    # --- ganchos -------------------------------------------------------------------------------

    def ao_ola(self, tipo: str, fn: GanchoOla) -> None:
        self._ganchos_ola.setdefault(str(tipo), []).append(fn)

    def ao_receber(self, tipo: Tipo | str, fn: GanchoReceber) -> None:
        self._ganchos_receber.setdefault(Tipo(tipo), []).append(fn)

    # --- conexões ------------------------------------------------------------------------------

    async def registrar(self, disp: Dispositivo, canal: Canal, modo: str = "ws") -> No:
        """Nova conexão do dispositivo; a antiga (se houver) fecha com ``4002``."""
        self._loop = asyncio.get_running_loop()
        no = No(disp, canal, modo, Receptor(NOME, lambda env: self._trata(no, env), self.relogio.monotonico))
        antigo = self._nos.get(disp.id)
        self._nos[disp.id] = no
        if antigo is not None:
            await self._fechar_no(antigo, FECHA_SUBSTITUIDA)
            log.info("no_substituido", extra={"dispositivo": disp.nome})
        if self._varredura is None or self._varredura.done():
            self._varredura = asyncio.ensure_future(self._varrer())
        return no

    def remover(self, no: No) -> None:
        no.fechado = True
        if self._nos.get(no.disp.id) is no:
            del self._nos[no.disp.id]

    def ativo(self, disp_id: int) -> No | None:
        return self._nos.get(disp_id)

    async def _fechar_no(self, no: No, codigo: int) -> None:
        if no.fechado:
            return
        self.remover(no)
        try:
            await no.canal.fechar(codigo)
        except Exception:  # noqa: BLE001 - a conexão pode já ter caído
            pass

    async def fechar_dispositivo(self, disp_id: int, codigo: int = FECHA_REVOGADO) -> bool:
        no = self._nos.get(disp_id)
        if no is None:
            return False
        await self._fechar_no(no, codigo)
        return True

    def revogado(self, disp: Dispositivo) -> None:
        """Gancho de ``auth.ao_revogar`` (pode vir de uma thread do threadpool)."""
        loop = self._loop
        if loop is None or disp.id not in self._nos:
            return
        coro = self.fechar_dispositivo(disp.id, FECHA_REVOGADO)
        try:
            corrente = asyncio.get_running_loop()
        except RuntimeError:
            corrente = None
        if corrente is loop:
            loop.create_task(coro)
        else:
            asyncio.run_coroutine_threadsafe(coro, loop)

    async def _varrer(self) -> None:
        """Enquanto há conexão aberta, fecha com 4001 quem foi revogado por outro processo."""
        while self._nos:
            await self.relogio.dormir(self.varredura_s)
            ids = list(self._nos)
            if not ids:
                break
            try:
                revogados = await asyncio.to_thread(self._revogados, ids)
            except Exception as e:  # noqa: BLE001 - banco fora: tenta na próxima volta
                log.warning("hub_varredura_falhou (%s)", type(e).__name__)
                continue
            for i in revogados:
                await self.fechar_dispositivo(i, FECHA_REVOGADO)

    def _revogados(self, ids: list[int]) -> list[int]:
        with self.db.connection() as conn:
            linhas = conn.execute(
                "SELECT id FROM dispositivos WHERE id = ANY(%s) AND revogado IS NOT NULL", (ids,)
            ).fetchall()
        return [r[0] for r in linhas]

    # --- recepção ------------------------------------------------------------------------------

    async def receber(self, no: No, texto: str | bytes) -> tuple[list[str], int | None]:
        """Trata um frame do nó. Devolve ``(respostas, fechar)``: textos a mandar de volta e o
        código para fechar a conexão (``1008`` por abuso), ou ``None``."""
        try:
            env: Envelope | None = decode(texto)
        except EloError:
            env = None
        if env is not None and env.resp is not None:
            futuro = self._pendentes.get(env.resp)
            if futuro is not None:
                if not futuro.done():
                    futuro.set_result(env)
                    self._resolvidos.append(env.resp)
                return [], None
            if env.resp in self._resolvidos:
                return [], None  # resposta repetida (reenvio cruzado): já tratada
            if env.t is Tipo.ACAO_OK:  # atrasado: o cliente já recebeu tempo_esgotado (§1.3)
                self._resolvidos.append(env.resp)
                await self._auditar_atrasado(no, env)
                return [], None
        saida = await no.receptor.receber(texto)
        return ([saida.resposta] if saida.resposta else []), saida.fechar

    async def _trata(self, no: No, env: Envelope) -> Envelope | None:
        disp = no.disp
        if env.t is Tipo.OLA:
            await self._ola(no, env.corpo)  # type: ignore[arg-type]
        elif env.t is Tipo.BATE:
            await self._visto(no)
        elif env.t is Tipo.ESTADO and disp.tipo == "casa":
            self._casa_estado = env.corpo  # type: ignore[assignment]
            self._casa_visto = self.relogio.agora()
        r: Any = None
        for fn in self._ganchos_receber.get(env.t, []):
            r = fn(disp, env)
            if inspect.isawaitable(r):
                r = await r
            if r is not None:
                break
        if isinstance(r, Envelope):
            return r
        if r is not None:
            return responder(env, _TIPO_DO_CORPO[type(r)], r, NOME)
        if env.t in PEDE_RESPOSTA and env.resp is None:
            return responder(env, Tipo.ACK, Ack(), NOME)
        return None

    async def _ola(self, no: No, ola: Ola) -> None:
        no.ola = ola
        if no.disp.tipo == "casa":
            self._casa_ola = ola
        await self._visto(no)
        for fn in self._ganchos_ola.get(no.disp.tipo, []):
            r = fn(no.disp, ola)
            if inspect.isawaitable(r):
                await r

    async def marcar_visto(self, no: No) -> None:
        """Long-poll não manda ``bate``: cada ``GET`` conta como batida (depois do ``ola``)."""
        if no.ola is not None:
            await self._visto(no)

    async def _visto(self, no: No) -> None:
        no.visto = self.relogio.monotonico()
        agora = self.relogio.agora()
        if no.disp.tipo == "casa":
            self._casa_visto = agora
        try:
            await asyncio.to_thread(self._grava_visto, no.disp.id, agora)
        except Exception as e:  # noqa: BLE001 - visto no banco é só para a /saude
            log.warning("hub_visto_falhou (%s)", type(e).__name__)

    def _grava_visto(self, disp_id: int, agora: datetime) -> None:
        with transacao(self.db) as conn:
            conn.execute("UPDATE dispositivos SET visto = %s WHERE id = %s", (agora, disp_id))

    async def _auditar_atrasado(self, no: No, env: Envelope) -> None:
        if self._auditar is None:
            return
        ok = bool(getattr(getattr(env.corpo, "resultado", None), "ok", False))
        try:
            await asyncio.to_thread(
                self._auditar, tipo="casa", resumo=f"acao_ok atrasado resp={env.resp}", ok=ok,
                dispositivo=no.disp.id, alvo=no.disp.nome,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("hub_auditoria_falhou (%s)", type(e).__name__)

    # --- envio ---------------------------------------------------------------------------------

    def destino(self, para: str) -> No | None:
        """Conexão ativa para ``para`` (nome do dispositivo, ou o tipo ``"pc"``/``"casa"``)."""
        candidatos = [n for n in self._nos.values() if not n.fechado]
        por_nome = [n for n in candidatos if n.disp.nome == para]
        if por_nome:
            return por_nome[0]
        por_tipo = [n for n in candidatos if n.disp.tipo == para and n.ola is not None]
        por_tipo.sort(key=lambda n: n.visto or 0.0, reverse=True)
        return por_tipo[0] if por_tipo else None

    async def enviar(self, env: Envelope) -> bool:
        """Manda sem esperar resposta. ``False`` se não há conexão para ``env.para``."""
        no = self.destino(env.para)
        if no is None:
            return False
        await self._mandar(no, encode(env))
        return True

    async def _mandar(self, no: No, texto: str) -> None:
        try:
            await no.canal.enviar(texto)
        except Exception as e:  # noqa: BLE001 - conexão caiu no envio
            log.info("hub_envio_falhou (%s)", type(e).__name__)
            self.remover(no)

    async def enviar_e_esperar(self, env: Envelope, prazo: float) -> Envelope:
        """Manda ``env`` (pede resposta) e espera até ``prazo`` segundos (§1.3: reenvio a cada
        ``reenvio_s`` com o mesmo ``id``, até ``reenvios`` vezes). ``NoOffline`` se não há conexão
        no envio inicial; ``TimeoutError`` no prazo (inclusive se o nó cair no meio)."""
        no = self.destino(env.para)
        if no is None:
            raise NoOffline(env.para)
        texto = encode(env)
        futuro: asyncio.Future[Envelope] = asyncio.get_running_loop().create_future()
        self._pendentes[env.id] = futuro
        fim = self.relogio.monotonico() + prazo
        reenvios = 0
        try:
            await self._mandar(no, texto)
            while not futuro.done():
                agora = self.relogio.monotonico()
                restante = fim - agora
                if restante <= 0:
                    raise TimeoutError(f"sem resposta para {env.t} {env.id}")
                espera = asyncio.ensure_future(self.relogio.dormir(min(self.reenvio_s, restante)))
                try:
                    await asyncio.wait({futuro, espera}, return_when=asyncio.FIRST_COMPLETED)
                finally:
                    espera.cancel()
                if futuro.done():
                    break
                if fim - self.relogio.monotonico() > 0 and reenvios < self.reenvios:
                    alvo = self.destino(env.para)
                    if alvo is not None:
                        reenvios += 1
                        await self._mandar(alvo, texto)
            return futuro.result()
        finally:
            self._pendentes.pop(env.id, None)

    # --- leitura -------------------------------------------------------------------------------

    def online(self, tipo: str) -> bool:
        limite = self.relogio.monotonico() - self.offline_apos_s
        return any(
            n.disp.tipo == tipo and n.visto is not None and n.visto >= limite and not n.fechado
            for n in self._nos.values()
        )

    def estado_casa(self) -> EstadoCasa:
        ola = self._casa_ola
        est = self._casa_estado
        return EstadoCasa(
            online=self.online("casa"),
            visto=self._casa_visto,
            tvs=ola.tvs if ola else (),
            estados=est.tvs if est else (),
            apps=ola.apps if ola else (),
        )


async def esperar_com_prazo(relogio: Any, aguardavel: Awaitable[Any], prazo: float) -> Any:
    """``aguardavel`` com prazo pelo relógio injetado; ``TimeoutError`` se o prazo vence antes."""
    tarefa = asyncio.ensure_future(aguardavel)
    espera = asyncio.ensure_future(relogio.dormir(prazo))
    try:
        await asyncio.wait({tarefa, espera}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        espera.cancel()
    if tarefa.done():
        return tarefa.result()
    tarefa.cancel()
    await asyncio.gather(tarefa, return_exceptions=True)
    raise TimeoutError


def hub_de(ctx: Any) -> Hub:
    """O hub da app (``ctx.extras["hub"]``), criado na 1ª vez e ligado a ``auth.ao_revogar``."""
    hub = ctx.extras.get("hub")
    if hub is None:
        from ayanami.api import auditoria

        hub = Hub(ctx.db, ctx.relogio, offline_apos_s=ctx.cfg.rede.offline_apos_s,
                  auditar=lambda **kw: auditoria.registrar(ctx.db, **kw))
        ctx.extras["hub"] = hub
    if not getattr(hub, "_ligado_auth", False):
        ctx.auth.ao_revogar.append(hub.revogado)
        hub._ligado_auth = True
    return hub
