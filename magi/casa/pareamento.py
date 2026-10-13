"""Pareamento por driver e ``esquecer`` (spec §12.3, design §5.4; dono: C1.5).

- Samsung: WS sem token → TV mostra "Permitir" → token no 1º frame (60 s); guarda no keyring
  ``casa.<id>.samsung`` e em ``<id>.samsung.token`` ``0600`` (pelo próprio driver, C1.2).
- Roku: só ``GET :8060/query/device-info`` (nenhuma tecla); nada a guardar.
- Android TV: ``magi.casa.drivers.androidtv.parear`` (120 s, 3 códigos); ``<id>.atv.crt/.key`` ``0600``.

Diretório de pareamento ``0700``; arquivos ``0600`` (os drivers gravam com ``os.open``). Token,
cert e código nunca vão para log nem para o ``detalhe``.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from magi.casa import config as cfg_mod
from magi.casa import log
from magi.casa.config import CasaConfig
from magi.casa.driver import ContextoDriver, Motivo, ResTv, TvConfig

PRAZO_SAMSUNG_S = 60.0
PedirCodigo = Callable[[], Awaitable[str]]


def nome_segredo_samsung(tv_id: str) -> str:
    """Nome no keyring (o ``_NAME_RE`` de ``magi.common.secrets`` não aceita ``/``; C1.2)."""
    return f"casa.{tv_id}.samsung"


def preparar_dir(dir_par: Path | None = None) -> Path:
    d = cfg_mod.dir_pareamento(dir_par)
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(d, 0o700)
    return d


async def parear_samsung(
    tv: TvConfig, ctx: ContextoDriver, *, driver: Any = None, prazo_s: float = PRAZO_SAMSUNG_S
) -> ResTv:
    """Abre a WS **sem token** e espera o "Permitir" até ``prazo_s``; o token do 1º frame vai ao
    keyring e ao arquivo ``0600`` (pelo próprio driver). Recusou → ``ACESSO_NEGADO``."""
    from magi.casa.drivers import samsung

    drv = driver if driver is not None else samsung.SamsungDriver(tv, ctx)
    if not tv.ip:
        return ResTv(False, Motivo.OFFLINE, "TV sem IP no casa.toml")
    remote = None
    try:
        for logica in (samsung.PORTA_WSS, samsung.PORTA_WS):
            remote = drv._novo_remote(logica, None)
            remote.timeout = prazo_s
            try:
                async with asyncio.timeout(prazo_s):
                    await remote.open()
                break
            except OSError as e:
                remote = None
                if logica == samsung.PORTA_WS or not (samsung._recusada(e) and drv._pode_8001()):
                    raise
        assert remote is not None
        if remote.token:
            drv._guardar_token(remote.token)
        res = ResTv(True, detalhe="pareada" if remote.token else "aceita (sem token na 8001)")
    except Exception as e:  # noqa: BLE001
        res = drv._res_erro(e, "parear")
    finally:
        if remote is not None:
            with contextlib.suppress(Exception):
                await remote.close()
        with contextlib.suppress(Exception):
            await drv.fechar()
    log.evento("pareamento", tv=tv.id, driver="samsung", ok=res.ok, motivo=_m(res))
    return res


async def parear_roku(tv: TvConfig, ctx: ContextoDriver, *, sondas: Any = None) -> ResTv:
    """Roku não pareia: só confere o ``device-info`` (nenhuma tecla, para não mexer na TV)."""
    from magi.casa.descoberta import SondasHttp

    info = await (sondas or SondasHttp()).roku(tv.ip) if tv.ip else None
    res = (
        ResTv(True, detalhe="Roku não precisa parear")
        if info is not None
        else ResTv(False, Motivo.OFFLINE, "sem resposta em :8060/query/device-info")
    )
    log.evento("pareamento", tv=tv.id, driver="roku", ok=res.ok, motivo=_m(res))
    return res


async def parear(
    tv: TvConfig,
    ctx: ContextoDriver,
    pedir_codigo: PedirCodigo,
    *,
    driver_samsung: Any = None,
    sondas: Any = None,
    fabrica_atv: Any = None,
    gerar_cert: Any = None,
    prazo_s: float | None = None,
) -> ResTv:
    """Despacha pelo driver da TV. O ``pedir_codigo`` só é usado no Android TV."""
    preparar_dir(ctx.dir_pareamento)
    if tv.driver == "samsung":
        return await parear_samsung(
            tv, ctx, driver=driver_samsung, prazo_s=PRAZO_SAMSUNG_S if prazo_s is None else prazo_s
        )
    if tv.driver == "roku":
        return await parear_roku(tv, ctx, sondas=sondas)
    if tv.driver == "androidtv":
        from magi.casa.drivers import androidtv

        kw: dict[str, Any] = {"fabrica": fabrica_atv, "gerar_cert": gerar_cert}
        if prazo_s is not None:
            kw["prazo_s"] = prazo_s
        res = await androidtv.parear(tv, ctx, pedir_codigo, **kw)
        log.evento("pareamento", tv=tv.id, driver="androidtv", ok=res.ok, motivo=_m(res))
        return res
    return ResTv(False, Motivo.NAO_SUPORTADO, f"driver {tv.driver}")


def arquivos_da_tv(tv_id: str, dir_par: Path | None = None) -> list[Path]:
    d = cfg_mod.dir_pareamento(dir_par)
    nomes = (f"{tv_id}.samsung.token", f"{tv_id}.atv.crt", f"{tv_id}.atv.key")
    return [d / n for n in nomes] + [d / (n + ".novo") for n in nomes[1:]]


def esquecer(
    tv_id: str,
    *,
    cfg: CasaConfig | None = None,
    caminho: Path | None = None,
    dir_par: Path | None = None,
    apagar_segredo: Callable[[str], Any] | None = None,
    tirar_do_toml: bool = True,
) -> list[str]:
    """Apaga token/cert (arquivo e keyring) e a entrada do ``casa.toml``. Devolve o que saiu."""
    if apagar_segredo is None:
        from magi.common.secrets import delete_secret as apagar_segredo
    saiu: list[str] = []
    for p in arquivos_da_tv(tv_id, dir_par):
        with contextlib.suppress(FileNotFoundError):
            p.unlink()
            saiu.append(p.name)
    try:
        if apagar_segredo(nome_segredo_samsung(tv_id)):
            saiu.append("keyring")
    except Exception:  # noqa: BLE001 - keyring ausente/travado não impede o resto
        log.evento("keyring_falhou", logging.WARNING, tv=tv_id)
    if tirar_do_toml:
        cfg = cfg if cfg is not None else cfg_mod.ler(caminho)
        if any(t.id == tv_id for t in (*cfg.tvs, *cfg.ignoradas)):
            novo = dataclasses.replace(
                cfg,
                tvs=tuple(t for t in cfg.tvs if t.id != tv_id),
                ignoradas=tuple(t for t in cfg.ignoradas if t.id != tv_id),
                padrao="" if cfg.padrao == tv_id else cfg.padrao,
            )
            cfg_mod.salvar(novo, caminho)
            saiu.append("casa.toml")
    log.evento("esquecida", tv=tv_id, itens=len(saiu))
    return saiu


def _m(res: ResTv) -> str | None:
    return res.motivo.value if res.motivo is not None else None
