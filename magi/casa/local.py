"""API local da casa para o ``magi-core``: elo em JSON-lines sobre TCP (spec §10.2; dono: C1.1c).

Uma mensagem do elo (§1) por linha UTF-8 terminada em ``\\n``, ≤ 64 KiB. Fluxo:

1. cliente → ``ola`` (``tipo="pc"``, ``token`` = conteúdo de ``casa.token``). Primeira linha que não
   é esse ``ola`` com o token certo → ``erro`` ``nao_autorizado`` e a casa fecha;
2. casa → ``ola`` (``tipo="casa"``) com ``tvs`` (``TvInfo``) e ``apps`` (``AppInfo``);
3. ``acao`` → ``acao_ok`` (``resp`` = id da ``acao``) com o ``AcaoResultado`` montado do ``ResTv``;
4. ``estado`` com ``tvs=()`` → ``estado`` com as ``EstadoTv``; mudança no estado é empurrada sem
   pedido a todo cliente autenticado;
5. sem ``bate``; ociosa por ``OCIOSO_S`` (10 min) → a casa fecha.

Depois do ``ola``, cada linha passa por um ``Receptor`` (idempotência por ``id``: ``acao`` reenviada
não roda 2×; 10 inválidas em 60 s fecham). A ``acao`` chega ao executor pela interface
``Executor`` (``rodar(ActionRequest) -> ResTv``, spec §10.6), que a C1.1b implementa.
Escuta só ``127.0.0.1`` ou o IP do tailnet; nunca ``0.0.0.0``.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
import secrets
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Final, Protocol

from magi.casa import log
from magi.casa.config import caminho_token_local
from magi.casa.driver import Motivo, ResTv
from magi.casa.emula import candidatos
from magi.casa.estado import EstadoCasa
from magi.common.contracts import ActionRequest, TurnContext, WakeSource
from magi.elo.converte import request_de_pedido
from magi.elo.mensagens import (
    MAX_ERRO_MSG,
    Acao,
    AcaoOk,
    AcaoResultado,
    AppInfo,
    EloError,
    Envelope,
    Erro,
    Estado,
    EstadoTv,
    Ola,
    Tipo,
    TipoDispositivo,
    TvInfo,
    agora_utc,
    decode,
    encode,
    responder,
)
from magi.elo.receptor import Receptor

MAX_LINHA: Final = 65_536
OCIOSO_S: Final = 600.0
NOME: Final = "casa"
PROIBIDOS: Final = frozenset({"0.0.0.0", "::", "", "*"})
CAPS_CASA: Final = ("acao", "estado")


class Executor(Protocol):
    """O que a API local precisa do executor (C1.1b, ``magi/casa/emula.py``)."""

    async def rodar(self, req: ActionRequest) -> ResTv: ...


# --- token ------------------------------------------------------------------------------------
def garantir_token(caminho: Path | None = None) -> str:
    """Lê o ``casa.token``; na 1ª subida cria com ``secrets.token_urlsafe(32)`` já em ``0600``."""
    p = caminho_token_local(caminho)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        token = p.read_text(encoding="utf-8").strip()
        if token:
            return token
        p.unlink()
        return garantir_token(caminho)
    token = secrets.token_urlsafe(32)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(token + "\n")
    log.evento("token_local_criado")
    return token


def prazo_s(acao: Acao) -> float:
    """Prazo da ``acao`` em segundos (rede de segurança acima dos timeouts do ``Executor``)."""
    return acao.prazo_ms / 1000


# --- montagem das respostas --------------------------------------------------------------------
def resultado_de_res(res: ResTv, tv: str | None) -> AcaoResultado:
    """``ResTv`` → ``AcaoResultado`` (§10.2 passo 3): ``fala`` vazia, ``dados`` com tv/emulado/…"""
    tv_id = res.estado.id if res.estado is not None else tv
    dados: dict[str, object] = {
        "tv": tv_id,
        "emulado": res.emulado,
        "detalhe": res.detalhe[:MAX_ERRO_MSG],
        "estado": res.estado,
    }
    if cands := candidatos(res):  # C1.6 (sobra da C1.1b): a pergunta lista só as candidatas
        dados["candidatos"] = list(cands)
    return AcaoResultado(
        ok=res.ok,
        motivo=res.motivo.value if res.motivo is not None else None,
        precisa_confirmar=res.motivo == Motivo.PRECISA_CONFIRMAR,
        dados=dados,
    )


class _Conexao:
    def __init__(self, writer: asyncio.StreamWriter) -> None:
        self.writer = writer
        self.trava = asyncio.Lock()
        self.de = "pc"

    async def mandar(self, texto: str) -> None:
        async with self.trava:
            self.writer.write(texto.encode("utf-8") + b"\n")
            await self.writer.drain()


class ApiLocal:
    """Servidor TCP do elo local. ``catalogo()`` → ``(tvs, apps)`` do ``ola`` (lido a cada ``ola``).

    ``relogio``: monotônico para o ``Receptor``; ``agora``: parede (``started_at`` do turno).
    """

    def __init__(
        self,
        token: str,
        executor: Executor,
        estado: EstadoCasa,
        catalogo: Callable[[], tuple[tuple[TvInfo, ...], tuple[AppInfo, ...]]],
        *,
        versao: str = "0",
        ocioso_s: float = OCIOSO_S,
        relogio: Callable[[], float] = time.monotonic,
        agora: Callable[[], datetime] = agora_utc,
    ) -> None:
        self._token = token
        self.executor = executor
        self.estado = estado
        self._catalogo = catalogo
        self._versao = versao
        self._ocioso = ocioso_s
        self._agora = agora
        self._receptor = Receptor(NOME, self._tratar, relogio)
        self._conexoes: set[_Conexao] = set()
        self._tarefas: set[asyncio.Task] = set()
        self._servidor: asyncio.Server | None = None
        self._tira_ouvinte = estado.ouvir(self._empurrar)

    # --- ciclo de vida ------------------------------------------------------------------
    async def iniciar(self, host: str = "127.0.0.1", porta: int = 10760) -> tuple[str, int]:
        if host in PROIBIDOS:
            raise ValueError(f"escuta '{host}' recusada: use 127.0.0.1 ou o IP do tailnet")
        self._servidor = await asyncio.start_server(self._cliente, host, porta, limit=MAX_LINHA + 1)
        h, p = self._servidor.sockets[0].getsockname()[:2]
        log.evento("api_local", ok=True, escuta=h, porta=p)
        return h, p

    async def fechar(self) -> None:
        self._tira_ouvinte()
        if self._servidor is not None:
            self._servidor.close()
        for c in list(self._conexoes):
            c.writer.close()
        for t in list(self._tarefas):
            t.cancel()
        if self._tarefas:
            await asyncio.gather(*self._tarefas, return_exceptions=True)
        if self._servidor is not None:
            await self._servidor.wait_closed()

    # --- conexão ------------------------------------------------------------------------
    async def _ler(self, reader: asyncio.StreamReader) -> bytes | None:
        """Uma linha; ``None`` = fechar (EOF, ociosa ou linha acima do limite)."""
        try:
            linha = await asyncio.wait_for(reader.readline(), self._ocioso)
        except TimeoutError:
            log.evento("conexao_ociosa", logging.DEBUG)
            return None
        except (ValueError, asyncio.LimitOverrunError):
            log.evento("linha_grande", logging.WARNING, motivo="tamanho")
            return None
        if not linha or len(linha) > MAX_LINHA:
            return None
        return linha

    async def _cliente(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        conn = _Conexao(writer)
        try:
            if not await self._autenticar(conn, await self._ler(reader)):
                return
            self._conexoes.add(conn)
            while (linha := await self._ler(reader)) is not None:
                if not linha.strip():
                    continue
                t = asyncio.create_task(self._linha(conn, linha))
                self._tarefas.add(t)
                t.add_done_callback(self._tarefas.discard)
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            self._conexoes.discard(conn)
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, asyncio.CancelledError):
                pass

    async def _autenticar(self, conn: _Conexao, linha: bytes | None) -> bool:
        if linha is None:
            return False
        try:
            env = decode(linha)
        except EloError:
            env = None
        ok = (
            env is not None
            and env.t == Tipo.OLA
            and isinstance(env.corpo, Ola)
            and env.corpo.tipo == TipoDispositivo.PC
            and isinstance(env.corpo.token, str)
            and hmac.compare_digest(env.corpo.token.encode(), self._token.encode())
        )
        if not ok:
            para = env.de if env is not None else "pc"
            erro = Envelope(
                t=Tipo.ERRO,
                corpo=Erro(codigo="nao_autorizado"),
                de=NOME,
                para=para,
                resp=env.id if env is not None else None,
            )
            log.evento("nao_autorizado", logging.WARNING, origem="local")
            try:
                await conn.mandar(encode(erro))
            except ConnectionError:
                pass
            return False
        assert env is not None
        conn.de = env.de
        await conn.mandar(encode(self._ola(env)))
        log.evento("cliente_local", ok=True, origem="local")
        return True

    async def _linha(self, conn: _Conexao, linha: bytes) -> None:
        saida = await self._receptor.receber(linha)
        try:
            if saida.resposta is not None:
                await conn.mandar(saida.resposta)
            if saida.fechar is not None:
                conn.writer.close()
        except ConnectionError:
            pass

    # --- mensagens ----------------------------------------------------------------------
    def _ola(self, env: Envelope) -> Envelope:
        tvs, apps = self._catalogo()
        corpo = Ola(tipo=TipoDispositivo.CASA, versao=self._versao, caps=CAPS_CASA, tvs=tvs, apps=apps)
        return responder(env, Tipo.OLA, corpo, NOME)

    async def _tratar(self, env: Envelope) -> Envelope | None:
        if env.t == Tipo.ACAO and isinstance(env.corpo, Acao):
            return responder(env, Tipo.ACAO_OK, AcaoOk(await self._acao(env.corpo)), NOME)
        if env.t == Tipo.ESTADO:
            return responder(env, Tipo.ESTADO, Estado(tvs=self.estado.todos()), NOME)
        if env.t == Tipo.OLA:  # re-ola na mesma conexão: só reapresenta (já autenticada)
            return self._ola(env)
        return responder(env, Tipo.ERRO, Erro(codigo="invalido", msg=f"tipo {env.t.value}"), NOME)

    async def _acao(self, acao: Acao) -> AcaoResultado:
        pedido = acao.pedido
        tv = dict(pedido.slots).get("tv")
        ctx = TurnContext(satellite=acao.origem, source=WakeSource.PTT, started_at=self._agora())
        t0 = time.monotonic()
        try:
            req = request_de_pedido(pedido, ctx)
            res = await asyncio.wait_for(self.executor.rodar(req), prazo_s(acao))
        except TimeoutError:
            res = ResTv(False, Motivo.TEMPO_ESGOTADO, "prazo da acao")
        except Exception:  # noqa: BLE001 - executor não deveria levantar; nunca derruba a conexão
            log.evento("acao_erro", logging.ERROR, acao=pedido.intent, tv=tv, origem="local", exc=True)
            res = ResTv(False, Motivo.ERRO_DRIVER, "erro interno")
        ms = int((time.monotonic() - t0) * 1000)
        motivo = res.motivo.value if res.motivo is not None else None
        log.evento("acao", acao=pedido.intent, tv=tv, ok=res.ok, motivo=motivo, ms=ms, origem="local")
        if res.estado is not None:
            await self.estado.atualizar(res.estado)
        return resultado_de_res(res, tv)

    async def _empurrar(self, tvs: tuple[EstadoTv, ...]) -> None:
        for c in list(self._conexoes):
            env = Envelope(t=Tipo.ESTADO, corpo=Estado(tvs=tvs), de=NOME, para=c.de)
            try:
                await c.mandar(encode(env))
            except (ConnectionError, EloError):
                self._conexoes.discard(c)
