"""Driver Android/Google TV — ``androidtvremote2`` 0.3.2 (spec §11.3; dono: C1.4).

- Ligação: ``AndroidTVRemote(client_name="Condessa", certfile, keyfile, host)`` (TLS ``:6466``
  controle, ``:6467`` pareamento); ``async_connect()`` e depois ``keep_reconnecting()``, que a lib
  roda numa tarefa própria. Comando durante a reconexão espera até 1,5 s pela volta da conexão.
- Estado por push (callbacks ``is_on``, ``current_app``, ``volume_info``, ``is_available``): o
  ``state()`` não faz I/O. ``current_app`` (pacote) → id do ``apps.yaml`` pelo ``pacote:``;
  ``volume_info`` → ``EstadoTv.volume`` 0–100 (``round(level*100/max)``).
- ``POWER`` é alterna: só sai quando o estado contradiz o pedido; estado desconhecido → não envia.
- Apps por deep link do catálogo; HDMI por keycode 243–246 com confirmação pela troca de
  ``current_app`` (sem troca → ``NAO_SUPORTADO``).
- Pareamento por código (``parear``, §12.3): cert/key em ``pareamentos/<id>.atv.crt|.key`` ``0600``,
  gravados só depois do código certo; 3 códigos errados ou 120 s → aborta sem gravar.
- Recaída ADB (``adb = true``): só gancho ``NAO_SUPORTADO`` (TODO, opcional, fora do padrão).

Nos testes o cliente da lib é um objeto falso passado em ``fabrica``; nada de rede.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from androidtvremote2.exceptions import CannotConnect, ConnectionClosed, InvalidAuth

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

NOME = "androidtv"
CLIENTE = "Condessa"
ESPERA_RECONEXAO_S = 1.5  # §11.3: comando durante reconexão espera ≤ 1,5 s
ESPERA_POWER_S = 8.0  # §11.5: ligar até confirmar
ESPERA_ENTRADA_S = 2.0  # §11.5: comando simples; confirmação da entrada pelo current_app
PASSO_S = 0.05
MAX_TECLAS = 30
PRAZO_PAREAMENTO_S = 120.0
TENTATIVAS_CODIGO = 3

ENTRADAS_HDMI = {"hdmi1": 243, "hdmi2": 244, "hdmi3": 245, "hdmi4": 246}  # KEYCODE_TV_INPUT_HDMI_n

TECLAS: dict[Key, str] = {
    Key.UP: "DPAD_UP",
    Key.DOWN: "DPAD_DOWN",
    Key.LEFT: "DPAD_LEFT",
    Key.RIGHT: "DPAD_RIGHT",
    Key.OK: "DPAD_CENTER",
    Key.BACK: "BACK",
    Key.HOME: "HOME",
    Key.MENU: "MENU",
    Key.PLAY_PAUSE: "MEDIA_PLAY_PAUSE",
    Key.REWIND: "MEDIA_REWIND",
    Key.FORWARD: "MEDIA_FAST_FORWARD",
    Key.VOL_UP: "VOLUME_UP",
    Key.VOL_DOWN: "VOLUME_DOWN",
    Key.MUTE: "VOLUME_MUTE",
    Key.CH_UP: "CHANNEL_UP",
    Key.CH_DOWN: "CHANNEL_DOWN",
    Key.POWER: "POWER",
}

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

# (certfile, keyfile, host) → cliente com a API do ``AndroidTVRemote``
Fabrica = Callable[[str, str, str], Any]
Dormir = Callable[[float], Awaitable[None]]


def _fabrica_real(certfile: str, keyfile: str, host: str) -> Any:
    from androidtvremote2 import AndroidTVRemote

    return AndroidTVRemote(client_name=CLIENTE, certfile=certfile, keyfile=keyfile, host=host)


def caminhos_cert(tv_id: str, dir_pareamento: Path | None = None) -> tuple[Path, Path]:
    """``pareamentos/<id>.atv.crt`` e ``.key`` (§11.3)."""
    if dir_pareamento is None:
        from magi.casa import config

        dir_pareamento = config.dir_pareamento()
    return dir_pareamento / f"{tv_id}.atv.crt", dir_pareamento / f"{tv_id}.atv.key"


def _gravar_0600(p: Path, dados: bytes) -> None:
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, dados)
    finally:
        os.close(fd)


def _apagar(*ps: Path) -> None:
    for p in ps:
        with contextlib.suppress(FileNotFoundError):
            p.unlink()


class DriverAndroidTv:
    nome = NOME

    def __init__(
        self,
        tv: TvConfig,
        ctx: ContextoDriver,
        *,
        fabrica: Fabrica | None = None,
        dormir: Dormir | None = None,
        agora: Callable[[], datetime] | None = None,
    ) -> None:
        self._tv = tv
        self._ctx = ctx
        self._fabrica = fabrica or _fabrica_real
        self._dormir = dormir or asyncio.sleep
        self._relogio = ctx.relogio or time.monotonic
        self._agora = agora or (lambda: datetime.now(UTC))
        self._crt, self._key = caminhos_cert(tv.id, ctx.dir_pareamento)
        apps = ctx.apps.ids_para(NOME) if ctx.apps is not None else ()
        self.capacidades = Capacidades(
            caps=CAPS,
            entradas=tuple(ENTRADAS_HDMI),
            apps=apps,
            emula=frozenset({Cap.VOL_SET}),  # §10.7: com volume_info, caminho de 60 teclas
        )
        self._remote: Any = None
        self._conectado = False
        self._nao_pareado = False
        self._ligada: bool | None = None
        self._pacote: str | None = None
        self._vol: dict[str, Any] | None = None
        self._entrada: str | None = None
        self._visto: datetime | None = None

    # ── callbacks (push da TV) ──────────────────────────────────────────────
    def _ver(self) -> None:
        self._visto = self._agora()

    def _cb_is_on(self, is_on: bool) -> None:
        self._ligada = bool(is_on)
        self._ver()

    def _cb_app(self, pacote: str) -> None:
        if pacote != self._pacote:
            self._entrada = None
        self._pacote = pacote
        self._ver()

    def _cb_volume(self, info: Any) -> None:
        self._vol = dict(info)
        mx = int(self._vol.get("max") or 0)
        if mx > 0 and mx != self.capacidades.vol_max:
            caps = self.capacidades
            self.capacidades = Capacidades(
                caps=caps.caps, entradas=caps.entradas, apps=caps.apps, vol_max=mx, emula=caps.emula
            )
        self._ver()

    def _cb_disponivel(self, ok: bool) -> None:
        self._conectado = bool(ok)
        if ok:
            self._ver()
        log.evento("androidtv_conexao", tv=self._tv.id, online=bool(ok))

    def _cb_auth_invalida(self) -> None:
        self._conectado = False
        self._nao_pareado = True
        log.evento("androidtv_nao_pareado", tv=self._tv.id)

    def _ler_remoto(self) -> None:
        r = self._remote
        if r is None:
            return
        if getattr(r, "is_on", None) is not None:
            self._ligada = bool(r.is_on)
        if getattr(r, "current_app", None):
            self._cb_app(r.current_app)
        if getattr(r, "volume_info", None):
            self._cb_volume(r.volume_info)

    # ── conexão ──────────────────────────────────────────────────────────────
    async def conectar(self) -> ResTv:
        if self._remote is not None and self._conectado:
            return ResTv(True, estado=await self.state())
        if not (self._crt.is_file() and self._key.is_file()):
            return ResTv(False, Motivo.NAO_PAREADO, "sem cert/key do pareamento")
        if self._remote is not None:
            await self.fechar()
        try:
            r = self._fabrica(str(self._crt), str(self._key), self._tv.ip)
            r.add_is_on_updated_callback(self._cb_is_on)
            r.add_current_app_updated_callback(self._cb_app)
            r.add_volume_info_updated_callback(self._cb_volume)
            r.add_is_available_updated_callback(self._cb_disponivel)
            self._remote = r
            await r.async_connect()
        except InvalidAuth:
            await self.fechar()
            self._nao_pareado = True
            return ResTv(False, Motivo.NAO_PAREADO, "TV pediu novo pareamento")
        except (CannotConnect, ConnectionClosed, OSError) as e:
            await self.fechar()
            return ResTv(False, Motivo.OFFLINE, f"sem conexão em :6466 ({type(e).__name__})")
        except TimeoutError:
            await self.fechar()
            return ResTv(False, Motivo.TEMPO_ESGOTADO, "conectar")
        except Exception:
            log.evento("androidtv_erro", logging.ERROR, exc=True, tv=self._tv.id, metodo="conectar")
            await self.fechar()
            return ResTv(False, Motivo.ERRO_DRIVER, "conectar")
        self._nao_pareado = False
        self._conectado = True
        self._ver()
        self._ler_remoto()
        r.keep_reconnecting(self._cb_auth_invalida)  # a lib cria a tarefa de reconexão
        log.evento("androidtv_conectada", tv=self._tv.id)
        return ResTv(True, estado=await self.state())

    async def fechar(self) -> None:
        r, self._remote = self._remote, None
        self._conectado = False
        if r is None:
            return
        for nome, cb in (
            ("remove_is_on_updated_callback", self._cb_is_on),
            ("remove_current_app_updated_callback", self._cb_app),
            ("remove_volume_info_updated_callback", self._cb_volume),
            ("remove_is_available_updated_callback", self._cb_disponivel),
        ):
            with contextlib.suppress(Exception):
                getattr(r, nome)(cb)
        with contextlib.suppress(Exception):
            r.disconnect()

    async def _esperar(self, cond: Callable[[], bool], limite: float) -> bool:
        t0 = self._relogio()
        while not cond():
            if self._relogio() - t0 >= limite:
                return False
            await self._dormir(PASSO_S)
        return True

    async def _pronto(self) -> ResTv | None:
        """``None`` = conectado e pronto; senão o ``ResTv`` de falha."""
        if self._nao_pareado:
            return ResTv(False, Motivo.NAO_PAREADO, "TV pediu novo pareamento")
        if self._remote is None:
            res = await self.conectar()
            return None if res.ok else res
        if self._conectado:
            return None
        # reconectando (tarefa da lib): espera até 1,5 s
        if await self._esperar(lambda: self._conectado or self._nao_pareado, ESPERA_RECONEXAO_S):
            if self._nao_pareado:
                return ResTv(False, Motivo.NAO_PAREADO, "TV pediu novo pareamento")
            return None
        return ResTv(False, Motivo.OFFLINE, "reconectando")

    async def _enviar(self, metodo: str, fn: Callable[[Any], None]) -> ResTv | None:
        """Envia um frame; ``None`` = ok, senão a falha (nunca levanta)."""
        falha = await self._pronto()
        if falha is not None:
            return falha
        try:
            fn(self._remote)
        except ConnectionClosed:
            self._conectado = False
            return ResTv(False, Motivo.OFFLINE, "conexão fechou")
        except (CannotConnect, OSError):
            self._conectado = False
            return ResTv(False, Motivo.OFFLINE, metodo)
        except Exception:
            log.evento("androidtv_erro", logging.ERROR, exc=True, tv=self._tv.id, metodo=metodo)
            return ResTv(False, Motivo.ERRO_DRIVER, metodo)
        return None

    async def _teclas(self, metodo: str, tecla: str, n: int = 1) -> ResTv:
        for _ in range(n):
            falha = await self._enviar(metodo, lambda r: r.send_key_command(tecla))
            if falha is not None:
                return falha
        return ResTv(True, estado=await self.state())

    # ── TvDriver ─────────────────────────────────────────────────────────────
    async def power(self, on: bool) -> ResTv:
        falha = await self._pronto()
        if falha is not None:
            return falha
        if self._ligada is None:
            return ResTv(False, Motivo.NAO_SUPORTADO, "estado desconhecido")
        if self._ligada == on:
            return ResTv(True, estado=await self.state())
        falha = await self._enviar("power", lambda r: r.send_key_command("POWER"))
        if falha is not None:
            return falha
        if await self._esperar(lambda: self._ligada == on, ESPERA_POWER_S):
            return ResTv(True, estado=await self.state())
        if on:
            if self._tv.adb:
                return self._adb("power_on")
            return ResTv(False, Motivo.STANDBY_PROFUNDO, "POWER enviado e a TV não ligou")
        return ResTv(False, Motivo.TEMPO_ESGOTADO, "POWER enviado e a TV não desligou")

    async def volume(self, step: int | None = None, set_to: int | None = None) -> ResTv:
        if set_to is not None:
            return ResTv(False, Motivo.NAO_SUPORTADO, "volume absoluto é emulado no Executor")
        if not step:
            return ResTv(False, Motivo.NAO_SUPORTADO, "passo zero")
        tecla = "VOLUME_UP" if step > 0 else "VOLUME_DOWN"
        return await self._teclas("volume", tecla, min(abs(step), MAX_TECLAS))

    async def mute(self, on: bool | None) -> ResTv:
        mudo = None if self._vol is None else bool(self._vol.get("muted"))
        if on is not None and mudo is not None and mudo == on:
            falha = await self._pronto()
            return falha or ResTv(True, estado=await self.state())
        res = await self._teclas("mute", "VOLUME_MUTE")
        if res.ok and on is not None and mudo is None:
            return ResTv(True, emulado=True, detalhe="alternado", estado=res.estado)
        return res

    async def channel(self, step: int) -> ResTv:
        if not step:
            return ResTv(False, Motivo.NAO_SUPORTADO, "passo zero")
        tecla = "CHANNEL_UP" if step > 0 else "CHANNEL_DOWN"
        return await self._teclas("channel", tecla, min(abs(step), MAX_TECLAS))

    async def input(self, nome: str) -> ResTv:
        code = ENTRADAS_HDMI.get(nome)
        if code is None:
            if nome in ("tv", "av"):
                return ResTv(False, Motivo.NAO_SUPORTADO, f"entrada {nome} sem keycode")
            return ResTv(False, Motivo.ENTRADA_DESCONHECIDA, nome)
        falha = await self._pronto()
        if falha is not None:
            return falha
        antes = self._pacote
        falha = await self._enviar("input", lambda r: r.send_key_command(code))
        if falha is not None:
            return falha
        if await self._esperar(lambda: self._pacote != antes, ESPERA_ENTRADA_S):
            self._entrada = nome
            return ResTv(True, estado=await self.state())
        if self._tv.adb:
            return self._adb("input")
        return ResTv(False, Motivo.NAO_SUPORTADO, "keycode HDMI sem efeito neste modelo")

    async def app(self, app_id: str) -> ResTv:
        alvo = self._ctx.apps.para_driver(app_id, NOME) if self._ctx.apps is not None else None
        link = getattr(alvo, "link", "") if alvo is not None else ""
        if not link:
            return ResTv(False, Motivo.APP_DESCONHECIDO, app_id)
        falha = await self._enviar("app", lambda r: r.send_launch_app_command(link))
        return falha or ResTv(True, estado=await self.state())

    async def key(self, key: Key) -> ResTv:
        tecla = TECLAS.get(Key(key))
        if tecla is None:
            return ResTv(False, Motivo.NAO_SUPORTADO, str(key))
        return await self._teclas("key", tecla)

    async def text(self, s: str) -> ResTv:
        falha = await self._enviar("text", lambda r: r.send_text(s))
        if falha is None:
            log.evento("androidtv_texto", logging.DEBUG, tv=self._tv.id, texto=s)  # só texto_len
        return falha or ResTv(True, estado=await self.state())

    async def state(self) -> EstadoTv:
        app: str | None = None
        if self._pacote:
            e = self._ctx.apps.por_pacote(self._pacote) if self._ctx.apps is not None else None
            app = e.id if e is not None else self._pacote
        volume = mudo = None
        if self._vol is not None:
            mx = int(self._vol.get("max") or 0)
            if mx > 0:
                volume = max(0, min(100, round(int(self._vol.get("level") or 0) * 100 / mx)))
            mudo = bool(self._vol.get("muted"))
        return EstadoTv(
            id=self._tv.id,
            nome=self._tv.nome,
            driver=NOME,
            online=self._remote is not None and self._conectado,
            ligada=self._ligada,
            app=app,
            volume=volume,
            mudo=mudo,
            entrada=self._entrada,
            visto=self._visto,
        )

    def _adb(self, acao: str) -> ResTv:
        # TODO(adb, opcional): recaída `androidtv` 0.0.75 / `adb-shell` 0.4.4 em :5555 (§11.3),
        # só com `adb = true` e a depuração por rede ligada; fora do padrão da A2.
        log.evento("androidtv_adb_gancho", tv=self._tv.id, acao=acao)
        return ResTv(False, Motivo.NAO_SUPORTADO, f"recaída ADB ({acao}) não implementada")


def criar(tv: TvConfig, ctx: ContextoDriver) -> DriverAndroidTv:
    return DriverAndroidTv(tv, ctx)


async def parear(
    tv: TvConfig,
    ctx: ContextoDriver,
    pedir_codigo: Callable[[], Awaitable[str]],
    *,
    fabrica: Fabrica | None = None,
    gerar_cert: Callable[[str], tuple[bytes, bytes]] | None = None,
    prazo_s: float = PRAZO_PAREAMENTO_S,
    tentativas: int = TENTATIVAS_CODIGO,
) -> ResTv:
    """Pareamento por código (§12.3): gera cert/key ``0600`` em nomes provisórios, inicia o
    pareamento (a TV mostra 6 hex), pede o código (até ``tentativas``), e só com o código certo
    grava ``<id>.atv.crt|.key``. Errou todas, a TV fechou ou passou do prazo → apaga tudo e
    devolve falha. O código nunca vai para log nem para o ``detalhe``."""
    if gerar_cert is None:
        from androidtvremote2.certificate_generator import generate_selfsigned_cert

        gerar_cert = generate_selfsigned_cert
    crt, key = caminhos_cert(tv.id, ctx.dir_pareamento)
    crt.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp_crt, tmp_key = crt.with_name(crt.name + ".novo"), key.with_name(key.name + ".novo")
    cert_pem, key_pem = gerar_cert(CLIENTE)
    _gravar_0600(tmp_crt, cert_pem)
    _gravar_0600(tmp_key, key_pem)
    r = (fabrica or _fabrica_real)(str(tmp_crt), str(tmp_key), tv.ip)

    async def _fluxo() -> ResTv:
        for n in range(1, tentativas + 1):
            await r.async_start_pairing()
            codigo = (await pedir_codigo()).strip()
            try:
                await r.async_finish_pairing(codigo)
            except InvalidAuth:
                log.evento("androidtv_codigo_errado", tv=tv.id, tentativa=n)
                continue
            return ResTv(True)
        return ResTv(False, Motivo.ACESSO_NEGADO, f"{tentativas} códigos errados")

    try:
        res = await asyncio.wait_for(_fluxo(), prazo_s)
    except TimeoutError:
        res = ResTv(False, Motivo.TEMPO_ESGOTADO, "pareamento expirou")
    except ConnectionClosed:
        res = ResTv(False, Motivo.ACESSO_NEGADO, "pareamento cancelado na TV")
    except (CannotConnect, OSError):
        res = ResTv(False, Motivo.OFFLINE, "sem conexão em :6467")
    except Exception:
        log.evento("androidtv_erro", logging.ERROR, exc=True, tv=tv.id, metodo="parear")
        res = ResTv(False, Motivo.ERRO_DRIVER, "parear")
    finally:
        with contextlib.suppress(Exception):
            r.disconnect()
    if not res.ok:
        _apagar(tmp_crt, tmp_key)
        log.evento("androidtv_pareamento_falhou", tv=tv.id, motivo=str(res.motivo))
        return res
    os.replace(tmp_crt, crt)
    os.replace(tmp_key, key)
    log.evento("androidtv_pareada", tv=tv.id)
    return res
