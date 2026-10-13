"""Conexão de saída da casa à Ayanami (spec §10.3; R1.7, R6.7; dono: C1.6).

Só existe se ``[casa] ayanami`` estiver preenchido (vazio = casa só local). Rede, reconexão
(1 → 2 → 4 … → 60 s, jitter ±20%), ``bate`` a cada 10 s, recaída ``/v1/longpoll`` após 3 falhas de
WS e o ``401`` (para de vez) são do ``EloCliente`` (``magi/elo/cliente.py``, Y2.4). Aqui só o que é
da casa:

- token ``casa``: ``~/.config/magi/ayanami-casa.token`` (``0600``) ou keyring ``casa.ayanami``;
- ``ola`` com ``tvs``/``apps`` (como a API local, §10.2, sem ``token``), remontado a cada conexão;
- ``estado`` a cada mudança (ouvinte do ``EstadoCasa``) e a cada ``periodo_estado_s`` (60 s);
  ``estado`` vazio vindo da Ayanami → responde com as ``EstadoTv``;
- ``acao`` remota → o mesmo ``Executor`` (mesma fila por TV da API local) com ``origem=ayanami``
  no log → ``acao_ok``. ``tv.power_off`` sem ``confirmed`` vira ``precisa_confirmar`` no Executor;
- token revogado → loga ``ayanami_token_revogado`` e volta; a API local segue servindo.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import stat
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from magi.casa import config as cfg_mod
from magi.casa import log
from magi.casa.driver import Motivo, ResTv
from magi.casa.estado import EstadoCasa
from magi.casa.local import CAPS_CASA, Executor, prazo_s, resultado_de_res
from magi.common.contracts import TurnContext, WakeSource
from magi.elo.cliente import ConexaoFechada, EloCliente
from magi.elo.converte import request_de_pedido
from magi.elo.mensagens import (
    Acao,
    AcaoOk,
    AcaoResultado,
    AppInfo,
    EloError,
    Envelope,
    Estado,
    EstadoTv,
    Ola,
    Tipo,
    TipoDispositivo,
    TvInfo,
    agora_utc,
)

NOME: Final = "casa"
PERIODO_ESTADO_S: Final = 60.0
SEGREDO: Final = "casa.ayanami"  # keyring (serviço magi-assistant); sem "/" (ver Sobras C1.2)
ORIGEM: Final = "ayanami"

Catalogo = Callable[[], tuple[tuple[TvInfo, ...], tuple[AppInfo, ...]]]


def ler_token(
    caminho: Path | None = None, *, keyring_get: Callable[[str], str | None] | None = None
) -> str | None:
    """Token ``casa`` da Ayanami: arquivo (recusado se mais aberto que ``0600``) e depois keyring."""
    p = cfg_mod.caminho_token_ayanami(caminho)
    try:
        if stat.S_IMODE(p.stat().st_mode) & 0o077:
            log.evento("permissao_aberta", logging.ERROR, caminho=str(p), motivo="chmod 600")
            return None
        token = p.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        token = ""
    if token:
        return token
    if keyring_get is None:
        from magi.common.secrets import get_secret

        keyring_get = get_secret
    try:
        return keyring_get(SEGREDO) or None
    except Exception:  # noqa: BLE001 - keyring indisponível = sem token
        log.evento("keyring_falhou", logging.WARNING)
        return None


async def executar_acao(
    executor: Executor,
    estado: EstadoCasa,
    acao: Acao,
    *,
    origem: str,
    agora: Callable[[], datetime] = agora_utc,
) -> AcaoResultado:
    """``acao`` → ``Executor`` (mesma fila por TV) → ``AcaoResultado``; nunca levanta."""
    pedido = acao.pedido
    tv = dict(pedido.slots).get("tv")
    ctx = TurnContext(satellite=acao.origem, source=WakeSource.PTT, started_at=agora())
    t0 = time.monotonic()
    try:
        req = request_de_pedido(pedido, ctx)
        rodar = executor.rodar
        aceita_origem = "origem" in inspect.signature(rodar).parameters
        coro = rodar(req, origem=origem) if aceita_origem else rodar(req)  # type: ignore[call-arg]
        res = await asyncio.wait_for(coro, prazo_s(acao))
    except TimeoutError:
        res = ResTv(False, Motivo.TEMPO_ESGOTADO, "prazo da acao")
    except Exception:  # noqa: BLE001 - executor não deveria levantar
        log.evento("acao_erro", logging.ERROR, acao=pedido.intent, tv=tv, origem=origem, exc=True)
        res = ResTv(False, Motivo.ERRO_DRIVER, "erro interno")
    ms = int((time.monotonic() - t0) * 1000)
    motivo = res.motivo.value if res.motivo is not None else None
    log.evento("acao", acao=pedido.intent, tv=tv, ok=res.ok, motivo=motivo, ms=ms, origem=origem)
    if res.estado is not None:
        await estado.atualizar(res.estado)
    return resultado_de_res(res, tv)


class SaidaAyanami:
    """Liga a casa à Ayanami por um ``EloCliente``. ``elo_kw`` vai direto ao ``EloCliente``
    (``rng``, ``conectar``, ``http``, ``batimento_s``…; testes)."""

    def __init__(
        self,
        url: str,
        token: str,
        executor: Executor,
        estado: EstadoCasa,
        catalogo: Catalogo,
        *,
        versao: str = "0",
        nome: str = NOME,
        periodo_estado_s: float = PERIODO_ESTADO_S,
        relogio: Callable[[], float] = time.monotonic,
        dormir: Callable[[float], Awaitable[Any]] = asyncio.sleep,
        agora: Callable[[], datetime] = agora_utc,
        **elo_kw: Any,
    ) -> None:
        self.executor = executor
        self.estado = estado
        self._catalogo = catalogo
        self._versao = versao
        self._periodo = periodo_estado_s
        self._relogio = relogio
        self._dormir = dormir
        self._agora = agora
        self.cliente = EloCliente(url, token, nome, self._ola, relogio=relogio, dormir=dormir, **elo_kw)
        self.cliente.on(Tipo.ACAO, self._acao)
        self.cliente.on(Tipo.ESTADO, self._estado_pedido)

    def _ola(self) -> Ola:
        tvs, apps = self._catalogo()
        return Ola(tipo=TipoDispositivo.CASA, versao=self._versao, caps=CAPS_CASA, tvs=tvs, apps=apps)

    async def _acao(self, env: Envelope) -> AcaoOk | None:
        if not isinstance(env.corpo, Acao):
            return None
        r = await executar_acao(self.executor, self.estado, env.corpo, origem=ORIGEM, agora=self._agora)
        return AcaoOk(r)

    def _estado_pedido(self, env: Envelope) -> Estado | None:
        if isinstance(env.corpo, Estado) and not env.corpo.tvs:
            return Estado(tvs=self.estado.todos())
        return None

    async def mandar_estado(self, tvs: tuple[EstadoTv, ...] | None = None) -> bool:
        """Empurra ``estado`` se conectado; ``False`` se não deu (sem conexão ou queda)."""
        if self.cliente.modo is None:
            return False
        corpo = Estado(tvs=self.estado.todos() if tvs is None else tvs)
        try:
            await self.cliente.enviar(Tipo.ESTADO, corpo)
        except (ConexaoFechada, ConnectionError, EloError, OSError):
            return False
        return True

    async def _periodico(self) -> None:
        proximo = self._relogio() + self._periodo
        while True:
            await self._dormir(max(0.0, min(1.0, proximo - self._relogio())))
            if self._relogio() >= proximo:
                proximo = self._relogio() + self._periodo
                await self.mandar_estado()

    async def rodar(self) -> None:
        """Até ``parar()`` ou token revogado (aí loga e volta; a API local não depende disto)."""
        tira = self.estado.ouvir(self.mandar_estado)
        periodico = asyncio.create_task(self._periodico())
        log.evento("ayanami_saida", url=self.cliente.base_url)
        try:
            await self.cliente.rodar()
        finally:
            tira()
            periodico.cancel()
            await asyncio.gather(periodico, return_exceptions=True)
        if self.cliente.revogado:
            log.evento("ayanami_token_revogado", logging.WARNING, origem=ORIGEM)

    def parar(self) -> None:
        self.cliente.parar()
