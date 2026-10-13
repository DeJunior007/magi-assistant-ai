"""Driver Roku por ECP (HTTP ``:8060``, ``rokuecp`` 0.19.5; spec §11.2; dono: C1.3).

- Caps vêm do ``/query/device-info``: player (``is-tv=false``) → ``KEY APP TEXT STATE`` (+
  ``POWER_*`` só com ``supports-tv-power-control``); Roku TV → + ``POWER_ON POWER_OFF VOL_STEP MUTE
  CHANNEL INPUT`` (``VOL_SET`` fica para a emulação do ``Executor``, §10.7).
- Ligar: ``POST /keypress/PowerOn`` (exige *Início rápido da TV*); sem resposta e com MAC → WOL e
  repete ``PowerOn``; ``ok`` só com ``power-mode == PowerOn`` relido.
- Apps: ``POST /launch/<id>`` com o id do ``apps.yaml``; sem id Roku → busca por nome em
  ``/query/apps`` (cache 24 h no relógio injetado).
- Texto: ``Lit_<char>`` URL-encoded, 30 ms entre teclas, ≤ 100 caracteres; o log leva só o tamanho.
- 403 (OS 14.1.4+ com *Acesso à rede* "Limitado") → ``ACESSO_NEGADO`` com a dica do menu.

O driver nunca levanta para o chamador (contrato §10.5).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from magi.casa.config import normaliza
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
from magi.casa.log import evento

PORTA = 8060
TEXTO_MAX = 100
TEXTO_PAUSA_S = 0.03
CACHE_APPS_S = 24 * 3600.0
PASSOS_MAX = 30
LIGAR_CONFIRMA_S = 7.0  # < 8 s do Executor (§11.5), para o motivo chegar antes do timeout dele
WOL_ESPERA_S = 3.0
SONDA_S = 0.5
DICA_ACESSO = 'Controle por apps móveis > Acesso à rede = Ativado (vem "Limitado" no OS 14.1.4+)'
DICA_LIGAR = "Configurações > Sistema > Energia > Início rápido da TV"

CAPS_BASE = frozenset({Cap.KEY, Cap.APP, Cap.TEXT, Cap.STATE})
CAPS_POWER = frozenset({Cap.POWER_ON, Cap.POWER_OFF})
CAPS_TV = CAPS_BASE | CAPS_POWER | {Cap.VOL_STEP, Cap.MUTE, Cap.CHANNEL, Cap.INPUT}
ENTRADAS_TV = ("hdmi1", "hdmi2", "hdmi3", "hdmi4", "tv", "av")
ENTRADA_TECLA = {
    "hdmi1": "InputHDMI1",
    "hdmi2": "InputHDMI2",
    "hdmi3": "InputHDMI3",
    "hdmi4": "InputHDMI4",
    "tv": "InputTuner",
    "av": "InputAV1",
}
TECLA = {
    Key.UP: "Up",
    Key.DOWN: "Down",
    Key.LEFT: "Left",
    Key.RIGHT: "Right",
    Key.OK: "Select",
    Key.BACK: "Back",
    Key.HOME: "Home",
    Key.MENU: "Info",
    Key.PLAY_PAUSE: "Play",
    Key.REWIND: "Rev",
    Key.FORWARD: "Fwd",
    Key.VOL_UP: "VolumeUp",
    Key.VOL_DOWN: "VolumeDown",
    Key.MUTE: "VolumeMute",
    Key.CH_UP: "ChannelUp",
    Key.CH_DOWN: "ChannelDown",
    Key.POWER: "Power",
}

Wol = Callable[..., None]
Dormir = Callable[[float], Awaitable[None]]


def _verdade(v: Any) -> bool:
    return str(v).strip().lower() == "true"


def _caps(info: dict[str, Any], apps: tuple[str, ...]) -> Capacidades:
    if _verdade(info.get("is-tv")):
        return Capacidades(CAPS_TV, ENTRADAS_TV, apps, emula=frozenset({Cap.VOL_SET}))
    caps = CAPS_BASE | CAPS_POWER if _verdade(info.get("supports-tv-power-control")) else CAPS_BASE
    return Capacidades(frozenset(caps), (), apps)


class _Falha(Exception):  # noqa: N818 - uso interno: carrega o ResTv de erro
    def __init__(self, res: ResTv) -> None:
        super().__init__(res.detalhe)
        self.res = res


def _wol_padrao(*macs: str, ip_address: str, port: int) -> None:
    from wakeonlan import send_magic_packet

    send_magic_packet(*macs, ip_address=ip_address, port=port)


class RokuDriver:
    nome = "roku"

    def __init__(
        self,
        tv: TvConfig,
        ctx: ContextoDriver | None = None,
        *,
        porta: int = PORTA,
        session: Any = None,
        dormir: Dormir | None = None,
        wol: Wol | None = None,
        request_timeout: float = 2.0,
    ) -> None:
        self.tv = tv
        self.ctx = ctx or ContextoDriver()
        self._porta = porta
        self._session = session
        self._dormir: Dormir = dormir or asyncio.sleep
        self._wol: Wol = wol or _wol_padrao
        self._relogio = self.ctx.relogio or _monotonic
        self._timeout = request_timeout
        self._roku: Any = None
        self._apps_cache: tuple[float, list[dict[str, Any]]] | None = None
        apps = self.ctx.apps.ids_para("roku") if self.ctx.apps is not None else ()
        self._apps_ids = apps
        self.capacidades = Capacidades(CAPS_BASE, (), apps)

    # --- HTTP ---------------------------------------------------------------------------------
    def _cliente(self) -> Any:
        if self._roku is None:
            from rokuecp import Roku

            self._roku = Roku(
                self.tv.ip,
                port=self._porta,
                session=self._session,
                request_timeout=self._timeout,  # type: ignore[arg-type]
            )
        return self._roku

    async def _req(self, uri: str, method: str = "GET") -> Any:
        """Uma chamada ECP; erro vira ``_Falha`` com o motivo do contrato."""
        from rokuecp import RokuConnectionError, RokuConnectionTimeoutError, RokuError

        if not self.tv.ip:
            raise _Falha(ResTv(False, Motivo.OFFLINE, "sem ip no casa.toml"))
        try:
            return await self._cliente()._request(uri, method=method, encoded=True)
        except RokuConnectionTimeoutError as e:
            raise _Falha(ResTv(False, Motivo.TEMPO_ESGOTADO, "roku não respondeu a tempo")) from e
        except RokuConnectionError as e:
            raise _Falha(ResTv(False, Motivo.OFFLINE, "roku fora da rede")) from e
        except RokuError as e:
            info = e.args[1] if len(e.args) > 1 and isinstance(e.args[1], dict) else {}
            status = info.get("status-code")
            if status == 403:
                raise _Falha(ResTv(False, Motivo.ACESSO_NEGADO, DICA_ACESSO)) from e
            raise _Falha(ResTv(False, Motivo.ERRO_DRIVER, f"HTTP {status}" if status else "ECP")) from e
        except TimeoutError as e:
            raise _Falha(ResTv(False, Motivo.TEMPO_ESGOTADO, "roku não respondeu a tempo")) from e
        except OSError as e:
            raise _Falha(ResTv(False, Motivo.OFFLINE, "roku fora da rede")) from e

    async def _tecla(self, nome: str) -> None:
        await self._req(f"keypress/{nome}", method="POST")

    async def _device_info(self) -> dict[str, Any]:
        res = await self._req("query/device-info")
        if not isinstance(res, dict) or not isinstance(res.get("device-info"), dict):
            raise _Falha(ResTv(False, Motivo.ERRO_DRIVER, "device-info malformado"))
        return res["device-info"]

    async def _protegido(self, acao: str, fn: Callable[[], Awaitable[ResTv]]) -> ResTv:
        try:
            return await fn()
        except _Falha as f:
            return f.res
        except asyncio.CancelledError:
            raise
        except Exception:
            evento("driver_erro", logging.ERROR, exc=True, tv=self.tv.id, driver=self.nome, acao=acao)
            return ResTv(False, Motivo.ERRO_DRIVER, f"erro inesperado em {acao}")

    def _sem(self, cap: Cap) -> ResTv | None:
        if cap in self.capacidades.caps:
            return None
        return ResTv(False, Motivo.NAO_SUPORTADO, f"roku sem {cap.value}")

    # --- contrato -----------------------------------------------------------------------------
    async def conectar(self) -> ResTv:
        async def _f() -> ResTv:
            info = await self._device_info()
            self.capacidades = _caps(info, self._apps_ids)
            return ResTv(True, estado=self._estado(info, None))

        return await self._protegido("conectar", _f)

    async def fechar(self) -> None:
        roku, self._roku = self._roku, None
        if roku is not None and self._session is None:
            try:
                await roku.close_session()
            except Exception:  # pragma: no cover - fechar nunca levanta
                pass

    async def power(self, on: bool) -> ResTv:
        if (r := self._sem(Cap.POWER_ON if on else Cap.POWER_OFF)) is not None:
            return r
        return await self._protegido("power", lambda: self._ligar() if on else self._desligar())

    async def _ligar(self) -> ResTv:
        respondeu = True
        try:
            await self._tecla("PowerOn")
        except _Falha as f:
            if f.res.motivo not in (Motivo.OFFLINE, Motivo.TEMPO_ESGOTADO):
                raise
            respondeu = False
        if not respondeu:
            if not self.tv.mac:
                return ResTv(False, Motivo.SEM_MAC, "roku não respondeu e não há MAC para WOL")
            self._wol(self.tv.mac, ip_address=self.ctx.broadcast, port=9)
            evento("roku_wol", tv=self.tv.id, driver=self.nome)
            fim = self._relogio() + WOL_ESPERA_S
            while True:
                await self._dormir(SONDA_S)
                try:
                    await self._tecla("PowerOn")
                    break
                except _Falha as f:
                    if f.res.motivo not in (Motivo.OFFLINE, Motivo.TEMPO_ESGOTADO):
                        raise
                if self._relogio() >= fim:
                    return ResTv(False, Motivo.REDE_DESLIGADA, "nenhuma resposta depois do WOL")
        return await self._confirmar(True)

    async def _desligar(self) -> ResTv:
        await self._tecla("PowerOff")
        return await self._confirmar(False)

    async def _confirmar(self, on: bool) -> ResTv:
        fim = self._relogio() + LIGAR_CONFIRMA_S
        while True:
            try:
                info = await self._device_info()
                estado = self._estado(info, None)
                if estado.ligada is on:
                    return ResTv(True, estado=estado)
            except _Falha as f:
                if f.res.motivo is Motivo.ACESSO_NEGADO:
                    raise
            if self._relogio() >= fim:
                detalhe = f"não ligou; confira {DICA_LIGAR}" if on else "não desligou"
                return ResTv(False, Motivo.STANDBY_PROFUNDO if on else Motivo.TEMPO_ESGOTADO, detalhe)
            await self._dormir(SONDA_S)

    async def _repetir(self, tecla: str, n: int) -> ResTv:
        async def _f() -> ResTv:
            for _ in range(n):
                await self._tecla(tecla)
            return ResTv(True)

        return await self._protegido(tecla, _f)

    async def volume(self, step: int | None = None, set_to: int | None = None) -> ResTv:
        if set_to is not None:
            return ResTv(False, Motivo.NAO_SUPORTADO, "roku sem volume absoluto")
        if (r := self._sem(Cap.VOL_STEP)) is not None:
            return r
        if not step:
            return ResTv(True)
        n = max(1, min(PASSOS_MAX, abs(step)))
        return await self._repetir("VolumeUp" if step > 0 else "VolumeDown", n)

    async def mute(self, on: bool | None) -> ResTv:
        if (r := self._sem(Cap.MUTE)) is not None:
            return r
        if on is not None:  # o Roku não informa o mudo; explícito é emulação do Executor
            return ResTv(False, Motivo.NAO_SUPORTADO, "roku só alterna o mudo (estado desconhecido)")
        return await self._repetir("VolumeMute", 1)

    async def channel(self, step: int) -> ResTv:
        if (r := self._sem(Cap.CHANNEL)) is not None:
            return r
        if not step:
            return ResTv(True)
        n = max(1, min(PASSOS_MAX, abs(step)))
        return await self._repetir("ChannelUp" if step > 0 else "ChannelDown", n)

    async def input(self, nome: str) -> ResTv:
        if (r := self._sem(Cap.INPUT)) is not None:
            return r
        tecla = ENTRADA_TECLA.get(nome)
        if tecla is None:
            return ResTv(False, Motivo.ENTRADA_DESCONHECIDA, f"entrada {nome!r}")
        return await self._repetir(tecla, 1)

    async def key(self, key: Key) -> ResTv:
        if (r := self._sem(Cap.KEY)) is not None:
            return r
        tecla = TECLA.get(key)
        if tecla is None:  # pragma: no cover - TECLA cobre a Key toda
            return ResTv(False, Motivo.NAO_SUPORTADO, f"tecla {key}")
        return await self._repetir(tecla, 1)

    async def app(self, app_id: str) -> ResTv:
        if (r := self._sem(Cap.APP)) is not None:
            return r

        async def _f() -> ResTv:
            roku_id = await self._resolver_app(app_id)
            if roku_id is None:
                return ResTv(False, Motivo.APP_DESCONHECIDO, f"app {app_id!r} não achado no roku")
            await self._req(f"launch/{quote(roku_id, safe='')}", method="POST")
            return ResTv(True)

        return await self._protegido("app", _f)

    async def _resolver_app(self, app_id: str) -> str | None:
        entrada = self.ctx.apps.get(app_id) if self.ctx.apps is not None else None
        if entrada is not None and entrada.roku:
            return entrada.roku
        nomes = {normaliza(app_id)}
        if entrada is not None:
            nomes |= {normaliza(n) for n in (entrada.nome, *entrada.apelidos)}
        for a in await self._apps_tv():
            if isinstance(a, dict) and normaliza(str(a.get("#text", ""))) in nomes and a.get("@id"):
                return str(a["@id"])
        return None

    async def _apps_tv(self) -> list[dict[str, Any]]:
        agora = self._relogio()
        if self._apps_cache is not None and agora - self._apps_cache[0] < CACHE_APPS_S:
            return self._apps_cache[1]
        res = await self._req("query/apps")
        bruto = res.get("apps") if isinstance(res, dict) else None
        lista = bruto.get("app", []) if isinstance(bruto, dict) else []
        if isinstance(lista, dict):
            lista = [lista]
        self._apps_cache = (agora, list(lista))
        return self._apps_cache[1]

    async def text(self, s: str) -> ResTv:
        if (r := self._sem(Cap.TEXT)) is not None:
            return r
        if len(s) > TEXTO_MAX:
            evento(
                "roku_texto_cortado",
                logging.WARNING,
                tv=self.tv.id,
                driver=self.nome,
                tamanho=len(s),
                max=TEXTO_MAX,
            )
            s = s[:TEXTO_MAX]

        async def _f() -> ResTv:
            for i, c in enumerate(s):
                if i:
                    await self._dormir(TEXTO_PAUSA_S)
                await self._tecla(f"Lit_{quote(c, safe='')}")
            return ResTv(True, detalhe=f"{len(s)} caracteres")

        return await self._protegido("text", _f)

    async def state(self) -> EstadoTv:
        try:
            info = await self._device_info()
        except _Falha:
            return EstadoTv(id=self.tv.id, nome=self.tv.nome, driver=self.nome, online=False)
        except Exception:
            evento("driver_erro", logging.ERROR, exc=True, tv=self.tv.id, driver=self.nome, acao="state")
            return EstadoTv(id=self.tv.id, nome=self.tv.nome, driver=self.nome, online=False)
        app: str | None = None
        try:
            res = await self._req("query/active-app")
            app = self._app_ativo(res)
        except Exception:  # app é extra; ligada já basta
            app = None
        return self._estado(info, app)

    def _app_ativo(self, res: Any) -> str | None:
        ativo = res.get("active-app") if isinstance(res, dict) else None
        bruto = ativo.get("app") if isinstance(ativo, dict) else None
        if not isinstance(bruto, dict):
            return None  # "Roku" = tela inicial
        roku_id = str(bruto.get("@id", ""))
        if self.ctx.apps is not None:
            for i in self.ctx.apps.ids():
                if self.ctx.apps.para_driver(i, "roku") == roku_id:
                    return i
        return str(bruto.get("#text", "")) or roku_id or None

    def _estado(self, info: dict[str, Any], app: str | None) -> EstadoTv:
        modo = str(info.get("power-mode", ""))
        return EstadoTv(
            id=self.tv.id,
            nome=self.tv.nome,
            driver=self.nome,
            online=True,
            ligada=(modo == "PowerOn") if modo else None,
            app=app,
            visto=datetime.now(UTC),
        )


def _monotonic() -> float:
    import time

    return time.monotonic()


def criar(tv: TvConfig, ctx: ContextoDriver) -> RokuDriver:
    return RokuDriver(tv, ctx)
