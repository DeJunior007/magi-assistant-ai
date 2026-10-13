"""Driver Samsung Tizen (spec §11.1; dono: C1.2) — ``samsungtvws[async]`` 3.0.6 + ``wakeonlan`` 4.0.0.

- **Ligação:** WS ``wss://IP:8002/api/v2/channels/samsung.remote.control`` (``name="Condessa"``);
  recaída para ``ws://IP:8001`` só se a 8002 recusar **e** ``ano < 2018`` (ou desconhecido).
- **Estado:** REST ``http://IP:8001/api/v2/`` → ``device.PowerState`` (``on``/``standby``); sem o
  campo, REST viva = ligada; sem resposta = desligada ou fora.
- **Ligar:** ``standby`` → ``KEY_POWER``; sem resposta → WOL 3× (100 ms) ao broadcast da LAN e, se a
  REST responder em ``standby`` em até 3 s, ``KEY_POWER``; confirma pela REST em até 8 s.
- **Desligar:** só com ``PowerState == "on"`` (ou REST viva sem o campo) → ``KEY_POWER``.
- **Token:** keyring (``casa.<id>.samsung``) ganha; arquivo ``<pareamentos>/<id>.samsung.token``
  ``0600`` é cópia de recaída. Nunca vai para log.

O driver nunca levanta: rede → ``OFFLINE``/``TEMPO_ESGOTADO``; "Permitir" recusado/401 →
``ACESSO_NEGADO``; inesperada → ``ERRO_DRIVER`` + log (sem segredo).
"""

from __future__ import annotations

import asyncio
import errno
import logging
import os
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiohttp
from samsungtvws import exceptions as sexc
from samsungtvws.async_remote import SamsungTVWSAsyncRemote
from samsungtvws.async_rest import SamsungTVAsyncRest
from samsungtvws.event import IGNORE_EVENTS_AT_STARTUP, MS_CHANNEL_CONNECT_EVENT, MS_CHANNEL_UNAUTHORIZED
from samsungtvws.helper import get_ssl_context, process_api_response, serialize_string
from samsungtvws.remote import ChannelEmitCommand, SendInputString, SendRemoteKey
from websockets.asyncio.client import ClientConnection
from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import ConnectionClosed, InvalidStatus
from yarl import URL

from magi.casa import log
from magi.casa.driver import (
    Cap,
    Capacidades,
    ContextoDriver,
    EstadoTv,
    Key,
    Motivo,
    ResTv,
    TvConfig,
)

# A lib loga o token (INFO "New token …") e a URL com ``token=`` (DEBUG): fica calada.
logging.getLogger("samsungtvws").setLevel(logging.WARNING)

NOME = "samsung"
NOME_CLIENTE = "Condessa"
PORTA_WSS = 8002
PORTA_WS = 8001
PORTA_REST = 8001

T_CONECTAR = 3.0
T_SONDA = 1.5
T_LIGAR = 8.0
T_WOL_REST = 3.0
PASSO_SONDA = 0.5
WOL_VEZES = 3
WOL_INTERVALO = 0.1
MAX_TECLAS = 30

TECLAS: dict[Key, str] = {
    Key.UP: "KEY_UP",
    Key.DOWN: "KEY_DOWN",
    Key.LEFT: "KEY_LEFT",
    Key.RIGHT: "KEY_RIGHT",
    Key.OK: "KEY_ENTER",
    Key.BACK: "KEY_RETURN",
    Key.HOME: "KEY_HOME",
    Key.MENU: "KEY_MENU",
    Key.PLAY_PAUSE: "KEY_PLAY",
    Key.REWIND: "KEY_REWIND",
    Key.FORWARD: "KEY_FF",
    Key.VOL_UP: "KEY_VOLUP",
    Key.VOL_DOWN: "KEY_VOLDOWN",
    Key.MUTE: "KEY_MUTE",
    Key.CH_UP: "KEY_CHUP",
    Key.CH_DOWN: "KEY_CHDOWN",
    Key.POWER: "KEY_POWER",
}
ENTRADAS: dict[str, str] = {f"hdmi{n}": f"KEY_HDMI{n}" for n in range(1, 5)}

CAPS = frozenset(
    {
        Cap.POWER_ON,
        Cap.POWER_OFF,
        Cap.VOL_STEP,
        Cap.MUTE,
        Cap.CHANNEL,
        Cap.INPUT,
        Cap.APP,
        Cap.KEY,
        Cap.TEXT,
        Cap.STATE,
    }
)
EMULA = frozenset({Cap.VOL_SET})  # zerar e subir (§10.7), no Executor

DICA_PERMITIR = (
    'TV recusou a conexão: aceite "Permitir" na TV e deixe Conexão de dispositivo externo > '
    'Notificação de acesso = "Só na primeira vez"'
)

LerSegredo = Callable[[str], "str | None"]
GravarSegredo = Callable[[str, str], None]
EnviaWol = Callable[..., Any]


def _ler_keyring(nome: str) -> str | None:
    from magi.common.secrets import get_secret

    return get_secret(nome)


def _gravar_keyring(nome: str, valor: str) -> None:
    from magi.common.secrets import set_secret

    set_secret(nome, valor)


def _wol_padrao(*macs: str, ip_address: str, port: int) -> None:
    from wakeonlan import send_magic_packet

    send_magic_packet(*macs, ip_address=ip_address, port=port)


class _Remote(SamsungTVWSAsyncRemote):
    """Remoto da lib com TLS explícito (a lib deduz pela porta 8002) e sem logar o token."""

    def __init__(self, *a: Any, tls: bool, com_token: bool, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._tls = tls
        self._com_token = com_token  # a TV só lê ``token=`` na 8002

    def _is_ssl_connection(self) -> bool:
        return self._tls

    def _format_websocket_url(self, app: str) -> str:
        query = {"name": serialize_string(self.name)}
        token = self._get_token()
        if self._com_token and token:
            query["token"] = token
        return str(
            URL.build(
                scheme="wss" if self._tls else "ws",
                host=self.host,
                port=self.port,
                path=f"/api/v2/channels/{app}",
                query=query,
            )
        )

    def _set_token(self, token: str) -> None:
        self.token = token

    async def open(self) -> ClientConnection:
        """Igual ao da lib, mas fecha o socket quando a TV recusa (a lib o deixa aberto)."""
        if self.connection:
            return self.connection
        kw: dict[str, Any] = {"ssl": get_ssl_context()} if self._tls else {}
        conn = await ws_connect(self._format_websocket_url(self.endpoint), open_timeout=self.timeout, **kw)
        try:
            event: str | None = None
            resp: dict[str, Any] = {}
            while event is None or event in IGNORE_EVENTS_AT_STARTUP:
                resp = process_api_response(await conn.recv())
                event = resp.get("event", "*")
                self._websocket_event(event, resp)
            if event == MS_CHANNEL_UNAUTHORIZED:
                raise sexc.UnauthorizedError("ms.channel.unauthorized")
            if event != MS_CHANNEL_CONNECT_EVENT:
                raise sexc.ConnectionFailure(f"evento inesperado: {event}")
            self._check_for_token(resp)
        except BaseException:
            await conn.close()
            raise
        self.connection = conn
        return conn


class SamsungDriver:
    nome = NOME

    def __init__(
        self,
        tv: TvConfig,
        ctx: ContextoDriver | None = None,
        *,
        portas: Mapping[int, int] | None = None,
        tls: bool = True,
        dormir: Callable[[float], Awaitable[None]] | None = None,
        enviar_wol: EnviaWol | None = None,
        ler_segredo: LerSegredo | None = None,
        gravar_segredo: GravarSegredo | None = None,
        sessao: aiohttp.ClientSession | None = None,
    ) -> None:
        self.tv = tv
        self.ctx = ctx or ContextoDriver()
        self._portas = dict(portas or {})
        self._tls = tls
        self._relogio = self.ctx.relogio or _monotonic
        self._dormir = dormir or asyncio.sleep
        self._wol = enviar_wol or _wol_padrao
        self._ler_segredo = ler_segredo or _ler_keyring
        self._gravar_segredo = gravar_segredo or _gravar_keyring
        self._sessao = sessao
        self._sessao_propria = False
        self._remote: _Remote | None = None
        self.porta_ws: int | None = None  # lógica (8002/8001) da conexão aberta
        apps = self.ctx.apps.ids_para(NOME) if self.ctx.apps is not None else ()
        self.capacidades = Capacidades(caps=CAPS, entradas=tuple(ENTRADAS), apps=apps, emula=EMULA)

    # --- token ----------------------------------------------------------------------------
    @property
    def nome_segredo(self) -> str:
        return f"casa.{self.tv.id}.samsung"

    @property
    def caminho_token(self) -> Path:
        from magi.casa import config

        return config.dir_pareamento(self.ctx.dir_pareamento) / f"{self.tv.id}.samsung.token"

    def _token(self) -> str | None:
        try:
            t = self._ler_segredo(self.nome_segredo)
        except Exception:  # keyring ausente/travado: recai no arquivo
            log.evento("samsung_keyring_falhou", logging.WARNING, tv=self.tv.id)
            t = None
        if t:
            return t.strip()
        try:
            t = self.caminho_token.read_text().strip()
        except OSError:
            return None
        return t or None

    def _guardar_token(self, token: str) -> None:
        try:
            self._gravar_segredo(self.nome_segredo, token)
        except Exception:
            log.evento("samsung_keyring_falhou", logging.WARNING, tv=self.tv.id)
        p = self.caminho_token
        try:
            p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            tmp = p.with_suffix(".tmp")
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(token)
            os.chmod(tmp, 0o600)
            os.replace(tmp, p)
        except OSError:
            log.evento("samsung_token_arquivo_falhou", logging.WARNING, tv=self.tv.id)
        log.evento("samsung_pareada", tv=self.tv.id)

    # --- REST -----------------------------------------------------------------------------
    def _porta(self, logica: int) -> int:
        return self._portas.get(logica, logica)

    async def _sessao_http(self) -> aiohttp.ClientSession:
        if self._sessao is None or self._sessao.closed:
            self._sessao = aiohttp.ClientSession()
            self._sessao_propria = True
        return self._sessao

    async def _rest(self) -> dict[str, Any] | None:
        """``device_info`` da REST; ``None`` = sem resposta (desligada ou fora da rede)."""
        if not self.tv.ip:
            return None
        try:
            rest = SamsungTVAsyncRest(
                self.tv.ip,
                session=await self._sessao_http(),
                port=self._porta(PORTA_REST),
                timeout=T_SONDA,
            )
            async with asyncio.timeout(T_SONDA):
                info = await rest.rest_device_info()
        except (TimeoutError, OSError, aiohttp.ClientError, sexc.HttpApiError, sexc.ResponseError):
            return None
        return info if isinstance(info, dict) else {}

    @staticmethod
    def _power_state(info: Mapping[str, Any]) -> str | None:
        dev = info.get("device")
        ps = dev.get("PowerState") if isinstance(dev, Mapping) else None
        return str(ps).lower() if ps is not None else None

    def _estado_de(self, info: Mapping[str, Any] | None) -> EstadoTv:
        base = {"id": self.tv.id, "nome": self.tv.nome, "driver": NOME}
        if info is None:
            return EstadoTv(**base, online=False, ligada=None)
        ps = self._power_state(info)
        ligada = ps != "standby" if ps is not None else True
        return EstadoTv(**base, online=True, ligada=ligada, visto=datetime.now(UTC))

    # --- WebSocket ------------------------------------------------------------------------
    def _novo_remote(self, logica: int, token: str | None) -> _Remote:
        return _Remote(
            self.tv.ip,
            token=token,
            port=self._porta(logica),
            timeout=T_CONECTAR,
            key_press_delay=0,
            name=NOME_CLIENTE,
            tls=self._tls and logica == PORTA_WSS,
            com_token=logica == PORTA_WSS,
        )

    async def _abrir(self, logica: int) -> _Remote:
        token = self._token()
        r = self._novo_remote(logica, token)
        async with asyncio.timeout(T_CONECTAR):
            await r.open()
        if r.token and r.token != token:
            self._guardar_token(r.token)
        return r

    def _pode_8001(self) -> bool:
        return self.tv.ano is None or self.tv.ano < 2018

    async def conectar(self) -> ResTv:
        if self._remote is not None and self._remote.is_alive():
            return ResTv(True)
        self._remote = None
        if not self.tv.ip:
            return ResTv(False, Motivo.OFFLINE, "TV sem IP no casa.toml")
        try:
            try:
                self._remote = await self._abrir(PORTA_WSS)
                self.porta_ws = PORTA_WSS
            except OSError as e:
                if not (_recusada(e) and self._pode_8001()):
                    raise
                log.evento("samsung_recaida_8001", tv=self.tv.id, ano=self.tv.ano)
                self._remote = await self._abrir(PORTA_WS)
                self.porta_ws = PORTA_WS
        except Exception as e:  # noqa: BLE001 — o driver nunca levanta
            return self._res_erro(e, "conectar")
        log.evento("samsung_conectada", tv=self.tv.id, porta=self.porta_ws)
        return ResTv(True)

    def _res_erro(self, e: BaseException, etapa: str) -> ResTv:
        if isinstance(e, sexc.UnauthorizedError):
            return ResTv(False, Motivo.ACESSO_NEGADO, DICA_PERMITIR)
        if isinstance(e, InvalidStatus) and e.response.status_code in (401, 403):
            return ResTv(False, Motivo.ACESSO_NEGADO, DICA_PERMITIR)
        if isinstance(e, TimeoutError):
            return ResTv(False, Motivo.TEMPO_ESGOTADO, f"{etapa}: tempo esgotado")
        if isinstance(e, OSError | ConnectionClosed | sexc.ConnectionFailure | InvalidStatus):
            return ResTv(False, Motivo.OFFLINE, f"{etapa}: {type(e).__name__}")
        log.evento("samsung_erro", logging.ERROR, exc=True, tv=self.tv.id, etapa=etapa)
        return ResTv(False, Motivo.ERRO_DRIVER, f"{etapa}: {type(e).__name__}")

    async def _descartar(self) -> None:
        r, self._remote = self._remote, None
        if r is not None:
            try:
                await r.close()
            except Exception:  # noqa: BLE001
                pass

    async def _enviar(self, comandos: Sequence[Any], etapa: str) -> ResTv:
        """Manda os frames; reabre a conexão uma vez se ela tinha caído."""
        for tentativa in range(2):
            res = await self.conectar()
            if not res.ok:
                return res
            assert self._remote is not None
            try:
                async with asyncio.timeout(T_CONECTAR):
                    await self._remote.send_commands(list(comandos), key_press_delay=0)
                return ResTv(True)
            except ConnectionClosed as e:
                await self._descartar()
                if tentativa:
                    return self._res_erro(e, etapa)
            except Exception as e:  # noqa: BLE001
                await self._descartar()
                return self._res_erro(e, etapa)
        return ResTv(False, Motivo.OFFLINE, etapa)  # pragma: no cover

    async def _teclas(self, tecla: str, n: int = 1) -> ResTv:
        return await self._enviar([SendRemoteKey.click(tecla)] * n, tecla)

    async def fechar(self) -> None:
        await self._descartar()
        if self._sessao_propria and self._sessao is not None:
            await self._sessao.close()
            self._sessao = None
            self._sessao_propria = False

    # --- power ----------------------------------------------------------------------------
    async def _esperar(self, alvo: bool, ate: float) -> tuple[EstadoTv | None, bool]:
        """Sonda a REST a cada 500 ms até ``ate`` (relógio); devolve (estado, alguma_resposta)."""
        respondeu = False
        while True:
            info = await self._rest()
            est = self._estado_de(info)
            respondeu = respondeu or info is not None
            if alvo and est.ligada is True:
                return est, respondeu
            if not alvo and est.ligada is not True:
                return est, respondeu
            if self._relogio() >= ate:
                return None, respondeu
            await self._dormir(PASSO_SONDA)

    async def power(self, on: bool) -> ResTv:
        try:
            return await (self._ligar() if on else self._desligar())
        except Exception as e:  # noqa: BLE001
            return self._res_erro(e, "power")

    async def _ligar(self) -> ResTv:
        t0 = self._relogio()
        info = await self._rest()
        if info is not None:
            est = self._estado_de(info)
            if est.ligada:
                return ResTv(True, detalhe="já estava ligada", estado=est)
            res = await self._teclas("KEY_POWER")
            if not res.ok:
                return res
            est2, _ = await self._esperar(True, t0 + T_LIGAR)
            if est2 is None:
                return ResTv(False, Motivo.STANDBY_PROFUNDO, "KEY_POWER sem efeito em 8 s")
            return ResTv(True, estado=est2)
        if not self.tv.mac:
            return ResTv(False, Motivo.SEM_MAC, "sem resposta e sem MAC no casa.toml para WOL")
        for i in range(WOL_VEZES):
            self._wol(self.tv.mac, ip_address=self.ctx.broadcast, port=9)
            if i < WOL_VEZES - 1:
                await self._dormir(WOL_INTERVALO)
        log.evento("samsung_wol", tv=self.tv.id, vezes=WOL_VEZES)
        respondeu = False
        limite_rest = self._relogio() + T_WOL_REST
        while True:
            info = await self._rest()
            if info is not None:
                respondeu = True
                est = self._estado_de(info)
                if est.ligada:
                    return ResTv(True, estado=est)
                res = await self._teclas("KEY_POWER")
                if not res.ok:
                    return res
                break
            if self._relogio() >= limite_rest:
                break
            await self._dormir(PASSO_SONDA)
        est2, r2 = await self._esperar(True, t0 + T_LIGAR)
        if est2 is not None:
            return ResTv(True, estado=est2)
        if respondeu or r2:
            return ResTv(False, Motivo.STANDBY_PROFUNDO, "respondeu ao WOL mas não ligou em 8 s")
        return ResTv(False, Motivo.REDE_DESLIGADA, "sem resposta de rede antes e depois do WOL")

    async def _desligar(self) -> ResTv:
        t0 = self._relogio()
        info = await self._rest()
        if info is None:
            return ResTv(False, Motivo.OFFLINE, "sem resposta da REST: estado desconhecido")
        est = self._estado_de(info)
        if not est.ligada:
            return ResTv(True, detalhe="já estava em standby", estado=est)
        res = await self._teclas("KEY_POWER")
        if not res.ok:
            return res
        est2, _ = await self._esperar(False, t0 + T_LIGAR)
        if est2 is None:
            return ResTv(False, Motivo.TEMPO_ESGOTADO, "continua ligada após KEY_POWER")
        return ResTv(True, estado=est2)

    # --- comandos simples -----------------------------------------------------------------
    async def volume(self, step: int | None = None, set_to: int | None = None) -> ResTv:
        if set_to is not None:
            return ResTv(False, Motivo.NAO_SUPORTADO, "samsung: sem volume absoluto")
        if not step:
            return ResTv(True)
        n = min(abs(step), MAX_TECLAS)
        return await self._teclas("KEY_VOLUP" if step > 0 else "KEY_VOLDOWN", n)

    async def mute(self, on: bool | None) -> ResTv:
        if on is not None:
            return ResTv(False, Motivo.NAO_SUPORTADO, "samsung: mudo só alterna (estado desconhecido)")
        return await self._teclas("KEY_MUTE")

    async def channel(self, step: int) -> ResTv:
        if not step:
            return ResTv(True)
        n = min(abs(step), MAX_TECLAS)
        return await self._teclas("KEY_CHUP" if step > 0 else "KEY_CHDOWN", n)

    async def input(self, nome: str) -> ResTv:
        tecla = ENTRADAS.get(nome)
        if tecla is None:
            return ResTv(False, Motivo.ENTRADA_DESCONHECIDA, f"samsung: entrada {nome!r}")
        return await self._teclas(tecla)

    async def app(self, app_id: str) -> ResTv:
        alvo = self.ctx.apps.para_driver(app_id, NOME) if self.ctx.apps is not None else None
        if not isinstance(alvo, str) or not alvo:
            return ResTv(False, Motivo.APP_DESCONHECIDO, f"samsung: app {app_id!r} sem id")
        return await self._enviar([ChannelEmitCommand.launch_app(alvo)], "run_app")

    async def key(self, key: Key) -> ResTv:
        tecla = TECLAS.get(Key(key))
        if tecla is None:  # pragma: no cover — todas mapeadas
            return ResTv(False, Motivo.NAO_SUPORTADO, f"samsung: tecla {key}")
        return await self._teclas(tecla)

    async def text(self, s: str) -> ResTv:
        if not s:
            return ResTv(True)
        log.evento("samsung_texto", tv=self.tv.id, tamanho=len(s))
        return await self._enviar([ChannelEmitCommand.text_received(), SendInputString.send(s)], "send_text")

    async def state(self) -> EstadoTv:
        try:
            return self._estado_de(await self._rest())
        except Exception:  # noqa: BLE001
            log.evento("samsung_erro", logging.ERROR, exc=True, tv=self.tv.id, etapa="state")
            return self._estado_de(None)


def _recusada(e: OSError) -> bool:
    return isinstance(e, ConnectionRefusedError) or e.errno == errno.ECONNREFUSED


def _monotonic() -> float:
    import time

    return time.monotonic()


def criar(tv: TvConfig, ctx: ContextoDriver) -> SamsungDriver:
    return SamsungDriver(tv, ctx)
