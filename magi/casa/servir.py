"""``magi-casa servir``: monta config + drivers + ``Executor`` + estado + API local (spec §10.1–§10.4;
dono: C1.1c, seguido por C1.5 e C1.6).

Sobe sem ``casa.toml`` (sem TVs: o ``ola`` lista vazio) e sem internet. Recusa subir se algum
arquivo de pareamento (``~/.local/share/magi/casa/``) ou o ``casa.token`` estiver mais aberto que
``0600`` (log ``permissao_aberta`` com o caminho, nunca o conteúdo).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import stat
from collections.abc import Callable, Mapping
from importlib import metadata
from pathlib import Path

from magi.casa import apps as apps_mod
from magi.casa import config as cfg_mod
from magi.casa import log
from magi.casa.config import CasaConfig
from magi.casa.descoberta import Descobridor, revalidar_periodicamente
from magi.casa.driver import ContextoDriver, Motivo, ResTv, TvConfig, TvDriver
from magi.casa.drivers import criar_driver
from magi.casa.estado import EstadoCasa
from magi.casa.local import ApiLocal, Executor, garantir_token
from magi.common.contracts import ActionRequest

FabricaExecutor = Callable[[CasaConfig, Mapping[str, TvDriver], apps_mod.AppCatalogo], Executor]


class PermissaoAberta(RuntimeError):
    pass


def arquivos_abertos(dir_par: Path | None = None, token: Path | None = None) -> list[Path]:
    """Arquivos de pareamento (e o ``casa.token``) com bit de grupo/outros ligado."""
    achados: list[Path] = []
    d = cfg_mod.dir_pareamento(dir_par)
    candidatos = [p for p in d.rglob("*") if p.is_file()] if d.is_dir() else []
    candidatos.append(cfg_mod.caminho_token_local(token))
    for p in candidatos:
        try:
            modo = stat.S_IMODE(p.stat().st_mode)
        except FileNotFoundError:
            continue
        if modo & 0o077:
            achados.append(p)
    return achados


class _SemExecutor:
    """Recaída enquanto ``magi.casa.emula.Executor`` (C1.1b) não existir: tudo ``NAO_SUPORTADO``."""

    async def rodar(self, req: ActionRequest) -> ResTv:
        return ResTv(False, Motivo.NAO_SUPORTADO, "executor ausente (dono: C1.1b)")


def executor_padrao(cfg: CasaConfig, drivers: Mapping[str, TvDriver], apps: apps_mod.AppCatalogo) -> Executor:
    try:
        from magi.casa.emula import Executor as ExecutorCasa
    except ImportError:
        log.evento("executor_ausente", logging.WARNING)
        return _SemExecutor()
    return ExecutorCasa(cfg, drivers)


def _ligar_estados(executor: object, estado: EstadoCasa) -> None:
    """C1.5 (sobra da C1.1b): o ``estados`` do ``Executor`` (regra 4 da §13.3) acompanha a sondagem."""
    alvo = getattr(executor, "estados", None)
    if not isinstance(alvo, dict):
        return
    alvo.update({e.id: e for e in estado.todos()})
    estado.ouvir(lambda todos: alvo.update({e.id: e for e in todos}))


def _versao() -> str:
    try:
        return metadata.version("magi-assistant")
    except metadata.PackageNotFoundError:
        return "0"


async def _conectar(tv_id: str, drv: TvDriver) -> None:
    try:
        r = await drv.conectar()
    except Exception:  # noqa: BLE001 - driver não deveria levantar
        log.evento("conectar_erro", logging.WARNING, tv=tv_id, driver=drv.nome, exc=True)
        return
    m = r.motivo.value if r.motivo is not None else None
    log.evento("conectar", tv=tv_id, driver=drv.nome, ok=r.ok, motivo=m)


async def servir_async(
    *,
    cfg: CasaConfig | None = None,
    porta: int | None = None,
    parar: asyncio.Event | None = None,
    pronto: Callable[[str, int], None] | None = None,
    fabrica_executor: FabricaExecutor = executor_padrao,
    fabrica_driver: Callable[[TvConfig, ContextoDriver], TvDriver] = criar_driver,
    descobridor: Descobridor | None = None,
) -> int:
    """Roda até ``parar`` (ou SIGTERM/SIGINT via ``servir``). ``porta=0`` = efêmera (testes)."""
    abertos = arquivos_abertos()
    if abertos:
        for p in abertos:
            log.evento("permissao_aberta", logging.ERROR, caminho=str(p), motivo="chmod 600")
        return 1
    cfg = cfg if cfg is not None else cfg_mod.ler()
    catalogo = apps_mod.carregar()
    d_par = cfg_mod.dir_pareamento()
    d_par.mkdir(parents=True, exist_ok=True, mode=0o700)
    ctx = ContextoDriver(broadcast=cfg.broadcast, apps=catalogo, dir_pareamento=d_par)
    drivers: dict[str, TvDriver] = {tv.id: fabrica_driver(tv, ctx) for tv in cfg.tvs}
    executor = fabrica_executor(cfg, drivers, catalogo)
    estado = EstadoCasa(drivers, {tv.id: (tv.nome, tv.driver) for tv in cfg.tvs})
    _ligar_estados(executor, estado)

    def _catalogo():
        tvs = tuple(
            cfg_mod.tv_info(tv, drivers[tv.id].capacidades, padrao=tv.id == cfg.padrao) for tv in cfg.tvs
        )
        return tvs, catalogo.infos()

    api = ApiLocal(garantir_token(), executor, estado, _catalogo, versao=_versao())
    host, p = await api.iniciar(cfg.escuta, cfg.porta if porta is None else porta)
    if pronto is not None:
        pronto(host, p)
    parar = parar or asyncio.Event()
    fundo = [asyncio.create_task(_conectar(i, d)) for i, d in drivers.items()]
    fundo.append(asyncio.create_task(estado.rodar()))
    if any(tv.chave for tv in cfg.tvs):  # C1.5: revalidação de IP a cada ``descoberta_min``
        fundo.append(asyncio.create_task(revalidar_periodicamente(descobridor or Descobridor())))
    try:
        await parar.wait()
    finally:
        for t in fundo:
            t.cancel()
        await asyncio.gather(*fundo, return_exceptions=True)
        await api.fechar()
        for i, d in drivers.items():
            try:
                await d.fechar()
            except Exception:  # noqa: BLE001
                log.evento("fechar_erro", logging.WARNING, tv=i, exc=True)
        log.evento("parada")
    return 0


def servir(args: list[str]) -> int:
    """Entrada do subcomando (sem argumentos): log JSON em stdout e SIGTERM/SIGINT param limpo."""
    log.configurar()
    try:
        cfg = cfg_mod.ler()
    except cfg_mod.CasaConfigErro as e:
        log.evento("config_invalida", logging.ERROR, motivo=str(e)[:200])
        return 2

    async def _rodar() -> int:
        parar = asyncio.Event()
        loop = asyncio.get_running_loop()
        for s in (signal.SIGTERM, signal.SIGINT):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(s, parar.set)
        return await servir_async(cfg=cfg, parar=parar)

    try:
        return asyncio.run(_rodar())
    except OSError as e:
        log.evento("api_local_falhou", logging.ERROR, motivo=type(e).__name__)
        return 1
