"""``EloCliente``: conexão de saída do PC/casa à Ayanami (spec §1.3, §1.4, §2.2, §10.3; R1.7).

WS ``wss://<ayanami>/ws`` com ``Authorization: Bearer`` → ``ola`` → ``ack`` → ``bate`` a cada
``batimento_s``. Queda → reconexão com esperas 1 → 2 → 4 … → 60 s, jitter ±20% (``rng``
injetado). Três falhas seguidas de WS → recaída em ``/v1/longpoll`` (GET puxa, POST manda). ``401``
(ou WS fechada com ``4001``) → para de vez e loga ``ayanami_token_revogado``.

Envelopes que pedem resposta (``PEDE_RESPOSTA``) são reenviados com o **mesmo** ``id`` a cada
``reenvio_s`` sem resposta, até ``reenvios`` vezes; depois o ``enviar`` levanta ``TimeoutError``.
Recebidos passam pelo ``Receptor`` (cache de ids, ``erro`` em inválido, 1008) e vão ao handler
registrado com ``on(tipo, fn)``. Quadros binários (§1.4) vão a ``on_quadro(fn)``.

Relógio (``relogio``: segundos monotônicos), ``dormir`` e ``rng`` são injetados. A rede também:
``conectar(url, cabecalhos) -> Conexao`` (padrão: ``websockets``) e ``http`` (``httpx.AsyncClient``).
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import random
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

import httpx

from magi.elo.mensagens import (
    CORPOS,
    PEDE_RESPOSTA,
    Ack,
    Bate,
    Corpo,
    EloError,
    Envelope,
    Ola,
    Tipo,
    decode,
    encode,
    responder,
)
from magi.elo.quadros import Quadro, decode_quadro, encode_quadro
from magi.elo.receptor import Receptor

log = logging.getLogger(__name__)

ESPERA_MIN_S: Final = 1.0
ESPERA_MAX_S: Final = 60.0
JITTER: Final = 0.2
FALHAS_PARA_LONGPOLL: Final = 3
BATIMENTO_S: Final = 10.0
REENVIO_S: Final = 10.0
REENVIOS: Final = 3
LONGPOLL_ESPERA_S: Final = 25
LONGPOLL_MAX_ENVIO: Final = 20
LONGPOLL_JANELA_S: Final = 300.0  # depois disso tenta a WS de novo
FECHA_REVOGADO: Final = 4001
PASSO_MAX_S: Final = 1.0

_TIPO_DO_CORPO: Final[Mapping[type, Tipo]] = {cls: t for t, cls in CORPOS.items()}


class TokenRevogado(Exception):
    """A Ayanami recusou o token (``401`` ou WS fechada com ``4001``)."""


class ConexaoFechada(Exception):
    """A conexão caiu; ``codigo`` é o código de fechamento WS, se houver."""

    def __init__(self, codigo: int | None = None) -> None:
        super().__init__(f"conexão fechada ({codigo})")
        self.codigo = codigo


class Conexao(Protocol):
    async def enviar(self, dado: str | bytes) -> None: ...
    async def receber(self) -> str | bytes: ...  # levanta ConexaoFechada
    async def fechar(self) -> None: ...


Conectar = Callable[[str, Mapping[str, str]], Awaitable[Conexao]]
Handler = Callable[[Envelope], "Envelope | Corpo | None | Awaitable[Envelope | Corpo | None]"]
HandlerQuadro = Callable[[Quadro], "None | Awaitable[None]"]


def espera_reconexao(falhas: int, rng: random.Random) -> float:
    """Espera antes da tentativa após ``falhas`` falhas seguidas (≥ 1): 1, 2, 4 … 60 s ± 20%."""
    base = min(ESPERA_MAX_S, ESPERA_MIN_S * 2 ** max(0, falhas - 1))
    return base * (1.0 + rng.uniform(-JITTER, JITTER))


def url_ws(base: str) -> str:
    base = base.rstrip("/")
    if base.startswith("https://"):
        base = "wss://" + base[len("https://") :]
    elif base.startswith("http://"):
        base = "ws://" + base[len("http://") :]
    return base + "/ws"


class _ConexaoWebsockets:
    """Adaptador de ``websockets`` (import tardio: só quem conecta de verdade precisa)."""

    def __init__(self, ws: Any) -> None:
        self._ws = ws

    async def enviar(self, dado: str | bytes) -> None:
        from websockets.exceptions import ConnectionClosed

        try:
            await self._ws.send(dado)
        except ConnectionClosed as e:
            raise ConexaoFechada(e.rcvd.code if e.rcvd else None) from e

    async def receber(self) -> str | bytes:
        from websockets.exceptions import ConnectionClosed

        try:
            return await self._ws.recv()
        except ConnectionClosed as e:
            raise ConexaoFechada(e.rcvd.code if e.rcvd else None) from e

    async def fechar(self) -> None:
        await self._ws.close()


async def conectar_websockets(url: str, cabecalhos: Mapping[str, str]) -> Conexao:
    from websockets.asyncio.client import connect
    from websockets.exceptions import InvalidStatus

    try:
        ws = await connect(url, additional_headers=dict(cabecalhos), open_timeout=10, ping_interval=None)
    except InvalidStatus as e:
        if e.response.status_code == 401:
            raise TokenRevogado from e
        raise
    return _ConexaoWebsockets(ws)


@dataclass(slots=True)
class _Pendente:
    env: Envelope
    texto: str
    prazo: float
    futuro: asyncio.Future[Envelope]
    reenvios: int = 0


@dataclass(slots=True)
class _Canal:
    modo: str  # "ws" | "longpoll"
    mandar: Callable[[str | bytes], Awaitable[None]]
    bate: bool
    proxima_bate: float = 0.0
    seq: int = 0
    tarefas: list[asyncio.Task[Any]] = field(default_factory=list)


class EloCliente:
    """Cliente do elo. ``ola()`` monta o corpo do ``ola`` a cada conexão (a casa manda tvs/apps).

    ``custos()`` (só o PC) entra no ``bate``. ``rodar()`` só volta com ``parar()`` ou token revogado.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        nome: str,
        ola: Callable[[], Ola],
        *,
        batimento_s: float = BATIMENTO_S,
        reenvio_s: float = REENVIO_S,
        reenvios: int = REENVIOS,
        longpoll_janela_s: float = LONGPOLL_JANELA_S,
        custos: Callable[[], float | None] | None = None,
        relogio: Callable[[], float] = time.monotonic,
        dormir: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rng: random.Random | None = None,
        conectar: Conectar = conectar_websockets,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.nome = nome
        self._token = token
        self._ola = ola
        self._batimento = batimento_s
        self._reenvio = reenvio_s
        self._reenvios = reenvios
        self._janela_lp = longpoll_janela_s
        self._custos = custos
        self._relogio = relogio
        self._dormir = dormir
        self._rng = rng or random.Random()
        self._conectar = conectar
        self._http = http
        self._handlers: dict[Tipo, Handler] = {}
        self._handlers_quadro: list[HandlerQuadro] = []
        self._pendentes: dict[str, _Pendente] = {}
        self._receptor = Receptor(nome, self._despacha, relogio)
        self._canal: _Canal | None = None
        self._parado = False
        self._fim_sessao: asyncio.Event | None = None
        self._erro_sessao: BaseException | None = None
        self._lp_desde = 0
        self.falhas = 0
        self.revogado = False

    # --- registro -------------------------------------------------------------------------------

    def on(self, tipo: Tipo | str, fn: Handler) -> None:
        self._handlers[Tipo(tipo)] = fn

    def on_quadro(self, fn: HandlerQuadro) -> None:
        self._handlers_quadro.append(fn)

    @property
    def modo(self) -> str | None:
        """``"ws"``, ``"longpoll"`` ou ``None`` (desconectado)."""
        return self._canal.modo if self._canal else None

    @property
    def _cabecalhos(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    # --- envio ----------------------------------------------------------------------------------

    async def enviar(
        self, t: Tipo, corpo: Corpo, para: str = "ayanami", *, resp: str | None = None
    ) -> Envelope | None:
        """Manda um envelope. Se ``t`` pede resposta, espera e devolve a resposta (``TimeoutError``
        após os reenvios); senão devolve ``None``. Sem conexão → ``ConexaoFechada``."""
        return await self.enviar_env(Envelope(t=t, corpo=corpo, de=self.nome, para=para, resp=resp))

    async def enviar_env(self, env: Envelope) -> Envelope | None:
        canal = self._canal
        if canal is None:
            raise ConexaoFechada
        texto = encode(env)
        if env.t not in PEDE_RESPOSTA or env.resp is not None:
            await canal.mandar(texto)
            return None
        futuro: asyncio.Future[Envelope] = asyncio.get_running_loop().create_future()
        self._pendentes[env.id] = _Pendente(env, texto, self._relogio() + self._reenvio, futuro)
        try:
            await canal.mandar(texto)
            return await futuro
        finally:
            self._pendentes.pop(env.id, None)

    async def enviar_quadro(self, q: Quadro) -> None:
        canal = self._canal
        if canal is None or canal.modo != "ws":
            raise ConexaoFechada
        await canal.mandar(encode_quadro(q))

    def parar(self) -> None:
        self._parado = True
        if self._fim_sessao is not None:
            self._fim_sessao.set()

    # --- laço principal -------------------------------------------------------------------------

    async def rodar(self) -> None:
        tentar_ws = False
        while not self._parado:
            longpoll = self.falhas >= FALHAS_PARA_LONGPOLL and self._http is not None and not tentar_ws
            tentar_ws = False
            try:
                ok = await (self._sessao_longpoll() if longpoll else self._sessao_ws())
            except TokenRevogado:
                self.revogado = True
                self._parado = True
                log.warning("ayanami_token_revogado")
                return
            if self._parado:
                return
            if longpoll:
                # janela do long-poll cumprida: tenta a WS já; se falhar de novo, volta ao long-poll
                tentar_ws = ok
                if ok:
                    continue
            self.falhas = 0 if ok else self.falhas + 1
            espera = espera_reconexao(max(1, self.falhas), self._rng)
            log.info("elo_reconecta", extra={"falhas": self.falhas, "espera_s": round(espera, 2)})
            await self._dormir(espera)

    async def _sessao_ws(self) -> bool:
        """Uma conexão WS. ``True`` se chegou ao ``ack`` do ``ola`` (a próxima espera volta a 1 s)."""
        try:
            con = await self._conectar(url_ws(self.base_url), self._cabecalhos)
        except TokenRevogado:
            raise
        except Exception as e:  # noqa: BLE001 - qualquer falha de rede conta como tentativa falha
            log.info("elo_ws_falhou", extra={"erro": type(e).__name__})
            return False
        canal = _Canal("ws", con.enviar, bate=True)
        try:
            return await self._sessao(canal, self._le_ws(con))
        finally:
            try:
                await con.fechar()
            except Exception:  # noqa: BLE001
                pass

    async def _le_ws(self, con: Conexao) -> None:
        while True:
            try:
                dado = await con.receber()
            except ConexaoFechada as e:
                if e.codigo == FECHA_REVOGADO:
                    raise TokenRevogado from e
                raise
            await self._recebe(dado)

    async def _sessao_longpoll(self) -> bool:
        http = self._http
        assert http is not None
        url = self.base_url + "/v1/longpoll"

        async def mandar(dado: str | bytes) -> None:
            if isinstance(dado, bytes):
                raise ConexaoFechada
            r = await http.post(url, json={"envelopes": [json.loads(dado)]}, headers=self._cabecalhos)
            _checa_http(r)
            for env in r.json().get("respostas", []):
                await self._recebe(json.dumps(env, ensure_ascii=False))

        async def puxa() -> None:
            fim = self._relogio() + self._janela_lp
            while self._relogio() < fim:
                r = await http.get(
                    url,
                    params={"desde": self._lp_desde, "espera": LONGPOLL_ESPERA_S},
                    headers=self._cabecalhos,
                    timeout=LONGPOLL_ESPERA_S + 10,
                )
                _checa_http(r)
                d = r.json()
                self._lp_desde = int(d.get("ate", self._lp_desde))
                for env in d.get("envelopes", []):
                    await self._recebe(json.dumps(env, ensure_ascii=False))
                await asyncio.sleep(0)
            raise ConexaoFechada  # janela acabou: volta a tentar a WS

        canal = _Canal("longpoll", mandar, bate=False)
        try:
            return await self._sessao(canal, puxa())
        except httpx.HTTPError as e:
            log.info("elo_longpoll_falhou", extra={"erro": type(e).__name__})
            return False

    async def _sessao(self, canal: _Canal, leitura: Awaitable[None]) -> bool:
        """Roda leitura + pulso (``bate``/reenvios) + ``ola``. Volta quando a conexão cai."""
        self._fim_sessao = asyncio.Event()
        if self._parado:
            self._fim_sessao.set()
        self._erro_sessao = None
        self._canal = canal
        canal.proxima_bate = self._relogio() + self._batimento
        ok = False
        fim_evt = self._fim_sessao
        ola = asyncio.ensure_future(self.enviar(Tipo.OLA, self._ola()))  # 1º frame
        ola.add_done_callback(self._tarefa_acabou_ola)
        tarefas = [asyncio.ensure_future(leitura), asyncio.ensure_future(self._pulso(canal))]
        for t in tarefas:
            t.add_done_callback(self._tarefa_acabou)
        fim = asyncio.ensure_future(fim_evt.wait())
        try:
            await asyncio.wait({ola, fim}, return_when=asyncio.FIRST_COMPLETED)
            if ola.done() and not ola.cancelled() and ola.exception() is None:
                resposta = ola.result()
                ok = resposta is not None and resposta.t is Tipo.ACK
                if ok:
                    log.info("elo_conectado", extra={"modo": canal.modo})
                else:
                    fim_evt.set()
            await fim
        finally:
            self._canal = None
            todas = [*tarefas, ola, fim]
            for t in todas:
                t.cancel()
            await asyncio.gather(*todas, return_exceptions=True)
            for p in list(self._pendentes.values()):
                if not p.futuro.done():
                    p.futuro.set_exception(ConexaoFechada())
        if isinstance(self._erro_sessao, TokenRevogado):
            raise self._erro_sessao
        if isinstance(self._erro_sessao, httpx.HTTPError):
            raise self._erro_sessao
        return ok

    def _tarefa_acabou(self, t: asyncio.Task[Any] | asyncio.Future[Any]) -> None:
        if not t.cancelled() and t.exception() is not None and self._erro_sessao is None:
            self._erro_sessao = t.exception()
        if self._fim_sessao is not None:
            self._fim_sessao.set()

    def _tarefa_acabou_ola(self, t: asyncio.Future[Any]) -> None:
        if t.cancelled() or t.exception() is not None:
            if self._fim_sessao is not None:
                self._fim_sessao.set()

    async def _pulso(self, canal: _Canal) -> None:
        """Único dono do ``dormir`` na sessão: manda ``bate`` e reenvia pendentes no prazo."""
        while True:
            agora = self._relogio()
            if canal.bate and agora >= canal.proxima_bate:
                custos = self._custos() if self._custos else None
                env = Envelope(
                    t=Tipo.BATE,
                    corpo=Bate(seq=canal.seq, custos_mes_usd=custos),
                    de=self.nome,
                    para="ayanami",
                )
                canal.seq += 1
                canal.proxima_bate = agora + self._batimento
                await canal.mandar(encode(env))
            for p in list(self._pendentes.values()):
                if p.futuro.done() or agora < p.prazo:
                    continue
                if p.reenvios >= self._reenvios:
                    p.futuro.set_exception(TimeoutError(f"sem resposta para {p.env.t} {p.env.id}"))
                    continue
                p.reenvios += 1
                p.prazo = agora + self._reenvio
                await canal.mandar(p.texto)
            alvos = [p.prazo for p in self._pendentes.values() if not p.futuro.done()]
            if canal.bate:
                alvos.append(canal.proxima_bate)
            proximo = min(alvos, default=agora + PASSO_MAX_S)
            await self._dormir(min(PASSO_MAX_S, max(0.0, proximo - self._relogio())))

    # --- recepção -------------------------------------------------------------------------------

    async def _recebe(self, dado: str | bytes) -> None:
        if isinstance(dado, bytes):
            try:
                q = decode_quadro(dado)
            except EloError as e:
                log.info("elo_quadro_invalido", extra={"codigo": e.codigo})
                return
            for fn in self._handlers_quadro:
                r = fn(q)
                if inspect.isawaitable(r):
                    await r
            return
        try:
            env = decode(dado)
        except EloError:
            env = None
        if env is not None and env.resp is not None and env.resp in self._pendentes:
            p = self._pendentes[env.resp]
            if not p.futuro.done():
                p.futuro.set_result(env)
            return
        saida = await self._receptor.receber(dado)
        canal = self._canal
        if saida.resposta is not None and canal is not None:
            await canal.mandar(saida.resposta)
        if saida.fechar is not None:
            raise ConexaoFechada(saida.fechar)

    async def _despacha(self, env: Envelope) -> Envelope | None:
        fn = self._handlers.get(env.t)
        r: Any = None
        if fn is not None:
            r = fn(env)
            if inspect.isawaitable(r):
                r = await r
        if r is None:
            if env.t in PEDE_RESPOSTA and env.resp is None:
                return responder(env, Tipo.ACK, Ack(), self.nome)
            return None
        if isinstance(r, Envelope):
            return r
        return responder(env, _TIPO_DO_CORPO[type(r)], r, self.nome)


def _checa_http(r: httpx.Response) -> None:
    if r.status_code == 401:
        raise TokenRevogado
    r.raise_for_status()
