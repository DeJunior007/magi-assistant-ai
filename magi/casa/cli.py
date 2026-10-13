"""Subcomandos de manutenção do ``magi-casa`` (spec §10.1, §12.1–§12.3; dono: C1.5).

Cada função recebe a lista crua de argumentos depois do subcomando e devolve o código de saída.
As dependências com rede/TV (``Descobridor``, pareador, fábrica de driver, leitura do código) são
parâmetros nomeados para os testes injetarem falsos; o ``__main__`` chama só ``fn(args)``.

``descobrir`` grava a última lista em ``~/.local/state/magi/casa-descobertas.json`` (sem segredo)
para o ``nomear`` achar a TV pela ``chave``, pelo número da linha ou pelo IP.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import dataclasses
import getpass
import sys
import time
from collections.abc import Callable
from typing import Any

from magi.casa import config as cfg_mod
from magi.casa import descoberta, pareamento
from magi.casa.config import CasaConfig, CasaConfigErro, normaliza
from magi.casa.driver import ContextoDriver, TvConfig, TvDriver

DONO = "C1.5"


def _parser(prog: str, descricao: str) -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog=f"magi-casa {prog}", description=descricao)


def _ler_cfg() -> CasaConfig | None:
    try:
        return cfg_mod.ler()
    except CasaConfigErro as e:
        print(f"casa.toml inválido: {e}", file=sys.stderr)
        return None


def _ctx(cfg: CasaConfig) -> ContextoDriver:
    from magi.casa import apps as apps_mod

    return ContextoDriver(
        broadcast=cfg.broadcast, apps=apps_mod.carregar(), dir_pareamento=cfg_mod.dir_pareamento()
    )


def achar_tv(cfg: CasaConfig, nome: str) -> TvConfig | None:
    """Por id, nome ou apelido (comparação normalizada)."""
    alvo = normaliza(nome)
    for tv in cfg.tvs:
        if tv.id == nome or alvo in {normaliza(x) for x in (tv.id, tv.nome, *tv.apelidos)}:
            return tv
    return None


# --- descobrir ---------------------------------------------------------------------------------
def _tabela(cands: list[descoberta.Candidato]) -> str:
    cab = ("nº", "chave", "driver", "IP", "modelo", "nome anunciado", "já nomeada?")
    linhas = [cab] + [
        (str(i), c.chave, c.driver, c.ip, c.modelo or "-", c.nome or "-", c.nomeada or "não")
        for i, c in enumerate(cands, 1)
    ]
    larg = [max(len(linha[j]) for linha in linhas) for j in range(len(cab))]
    return "\n".join("  ".join(v.ljust(larg[j]) for j, v in enumerate(linha)).rstrip() for linha in linhas)


def descobrir(args: list[str], *, descobridor: descoberta.Descobridor | None = None) -> int | None:
    """SSDP + mDNS, confirma por HTTP e lista as TVs achadas com a ``chave`` estável."""
    p = _parser("descobrir", "procura TVs na rede local (SSDP + mDNS)")
    p.add_argument("--segundos", type=float, default=5.0)
    a = p.parse_args(args)
    cfg = _ler_cfg()
    if cfg is None:
        return 2
    cands = asyncio.run((descobridor or descoberta.Descobridor()).descobrir(a.segundos, cfg))
    descoberta.gravar_descobertas(cands)
    if not cands:
        print("Nenhuma TV achada. A TV está ligada e na mesma rede deste computador?")
        return 1
    print(_tabela(cands))
    if any(not c.nomeada for c in cands):
        print('\nPróximo passo: magi-casa nomear <nº|chave|IP> <id> "Nome da TV" [--padrao]')
    return 0


# --- nomear ------------------------------------------------------------------------------------
def nomear(args: list[str]) -> int | None:
    """``nomear <nº|chave|IP> <id> [nome] [--apelido A]… [--padrao] [--driver D]``: grava a TV
    achada no ``casa.toml`` (atualiza se a ``chave`` já estiver lá)."""
    p = _parser("nomear", "grava uma TV achada pelo 'descobrir' no casa.toml")
    p.add_argument("alvo", help="número da linha, chave ou IP do 'descobrir'")
    p.add_argument("id", help="id estável [a-z0-9_-], ex.: sala")
    p.add_argument("nome", nargs="?", help='nome falado, ex.: "TV da sala"')
    p.add_argument("--apelido", action="append", default=[])
    p.add_argument("--padrao", action="store_true", help="vira a TV padrão (slot tv vazio)")
    p.add_argument("--driver", choices=("samsung", "roku", "androidtv"), help="força o driver (TCL)")
    a = p.parse_args(args)
    cfg = _ler_cfg()
    if cfg is None:
        return 2
    cands = descoberta.ler_descobertas()
    cand = None
    if a.alvo.isdigit() and 1 <= int(a.alvo) <= len(cands):
        cand = cands[int(a.alvo) - 1]
    else:
        cand = next((c for c in cands if a.alvo in (c.chave, c.ip)), None)
    if cand is None:
        print(f"'{a.alvo}' não está na última descoberta; rode 'magi-casa descobrir' antes.", file=sys.stderr)
        return 2
    antiga = next((t for t in cfg.tvs if t.chave == cand.chave or t.id == a.id), None)
    nome = a.nome or (antiga.nome if antiga else a.id)
    apelidos = tuple(dict.fromkeys((*(antiga.apelidos if antiga else ()), *a.apelido)))
    base = antiga or TvConfig(id=a.id, nome=nome, driver=cand.driver)
    tv = dataclasses.replace(
        base,
        id=a.id,
        nome=nome,
        apelidos=apelidos,
        driver=a.driver or cand.driver,
        chave=cand.chave,
        ip=cand.ip,
        mac=cand.mac or base.mac,
    )
    tvs = [tv if t is antiga else t for t in cfg.tvs] if antiga else [*cfg.tvs, tv]
    novo = dataclasses.replace(cfg, tvs=tuple(tvs), padrao=a.id if a.padrao else cfg.padrao)
    if antiga is not None and antiga.id != a.id and cfg.padrao == antiga.id:
        novo = dataclasses.replace(novo, padrao=a.id)
    try:
        cfg_mod.salvar(novo)
    except CasaConfigErro as e:
        print(f"Não gravei: {e}", file=sys.stderr)
        return 2
    print(f"TV '{tv.id}' ({tv.driver}, {tv.ip}) gravada. Próximo passo: magi-casa parear {tv.id}")
    return 0


# --- parear ------------------------------------------------------------------------------------
Pareador = Callable[..., Any]
DICAS = {
    "samsung": 'Aceite "Permitir" na TV (até 60 s)…',
    "androidtv": "A TV vai mostrar um código de 6 letras/números (até 120 s, 3 tentativas)…",
    "roku": "Roku não pareia: só confiro se a TV responde.",
}


def parear(
    args: list[str],
    *,
    pareador: Pareador = pareamento.parear,
    ler_codigo: Callable[[str], str] = getpass.getpass,
) -> int | None:
    """``parear <tv>``: Samsung 60 s, Android TV 120 s com código (eco desligado), Roku ``device-info``."""
    p = _parser("parear", "pareia uma TV do casa.toml")
    p.add_argument("tv", help="id, nome ou apelido")
    a = p.parse_args(args)
    cfg = _ler_cfg()
    if cfg is None:
        return 2
    tv = achar_tv(cfg, a.tv)
    if tv is None:
        print(f"Nenhuma TV '{a.tv}' no casa.toml (use 'magi-casa nomear').", file=sys.stderr)
        return 2
    print(DICAS.get(tv.driver, ""), flush=True)

    async def pedir_codigo() -> str:
        return await asyncio.to_thread(ler_codigo, "Código mostrado na TV: ")

    res = asyncio.run(pareador(tv, _ctx(cfg), pedir_codigo))
    if res.ok:
        print(f"TV '{tv.id}' pareada.")
        return 0
    motivo = res.motivo.value if res.motivo else "erro"
    print(f"Não pareou ({motivo}): {res.detalhe}", file=sys.stderr)
    return 1


# --- esquecer ----------------------------------------------------------------------------------
def esquecer(args: list[str], *, apagar_segredo: Callable[[str], Any] | None = None) -> int | None:
    """``esquecer <tv> [--manter-config]``: apaga token/cert (arquivo e keyring) e a entrada do
    ``casa.toml``."""
    p = _parser("esquecer", "apaga o pareamento (e a entrada do casa.toml) de uma TV")
    p.add_argument("tv", help="id, nome ou apelido")
    p.add_argument("--manter-config", action="store_true", help="só apaga token/cert")
    a = p.parse_args(args)
    cfg = _ler_cfg()
    if cfg is None:
        return 2
    tv = achar_tv(cfg, a.tv)
    tv_id = tv.id if tv else a.tv
    saiu = pareamento.esquecer(
        tv_id, cfg=cfg, apagar_segredo=apagar_segredo, tirar_do_toml=not a.manter_config
    )
    print(f"TV '{tv_id}': " + (", ".join(saiu) + " apagados." if saiu else "nada guardado."))
    return 0


# --- estado ------------------------------------------------------------------------------------
FabricaDriver = Callable[[TvConfig, ContextoDriver], TvDriver]


def _linha_estado(tv: TvConfig, e: Any) -> str:
    if e is None:
        return f"{tv.id:<12} {tv.driver:<10} sem dados (a casa ainda não sondou)"
    lig = {True: "ligada", False: "desligada", None: "?"}[e.ligada]
    partes = [f"{tv.id:<12} {tv.driver:<10} {'online' if e.online else 'offline':<8} {lig}"]
    if e.app:
        partes.append(f"app={e.app}")
    if e.entrada:
        partes.append(f"entrada={e.entrada}")
    if e.volume is not None:
        partes.append(f"vol={e.volume}")
    return " ".join(partes)


def estado(args: list[str], *, fabrica_driver: FabricaDriver | None = None) -> int | None:
    """Mostra o ``EstadoTv`` de cada TV (do ``casa-estado.json``; ``--sondar`` pergunta às TVs)."""
    p = _parser("estado", "mostra o estado de cada TV")
    p.add_argument("--sondar", action="store_true", help="pergunta a cada TV agora")
    a = p.parse_args(args)
    cfg = _ler_cfg()
    if cfg is None:
        return 2
    if not cfg.tvs:
        print("Nenhuma TV no casa.toml.")
        return 0
    if a.sondar:
        estados = asyncio.run(_sondar(cfg, fabrica_driver))
    else:
        from magi.casa import estado as estado_mod

        estados = {e.id: e for e in estado_mod.carregar()}
    for tv in cfg.tvs:
        print(_linha_estado(tv, estados.get(tv.id)))
    return 0


def _fabrica(f: FabricaDriver | None) -> FabricaDriver:
    if f is not None:
        return f
    from magi.casa.drivers import criar_driver

    return criar_driver


async def _sondar(cfg: CasaConfig, fabrica: FabricaDriver | None) -> dict[str, Any]:
    ctx = _ctx(cfg)
    drivers = {tv.id: _fabrica(fabrica)(tv, ctx) for tv in cfg.tvs}
    try:
        lidos = await asyncio.gather(*(d.state() for d in drivers.values()), return_exceptions=True)
    finally:
        for d in drivers.values():
            with contextlib.suppress(Exception):
                await d.fechar()
    return {i: e for i, e in zip(drivers, lidos, strict=True) if not isinstance(e, BaseException)}


# --- testar ------------------------------------------------------------------------------------
def montar_pedido(tv_id: str, acao: str, extras: list[str]) -> Any:
    from datetime import UTC, datetime

    from magi.common.contracts import ActionRequest, Intent, Slot, TurnContext, WakeSource

    intent = acao if acao.startswith("tv.") else f"tv.{acao}"
    kv: dict[str, Any] = {}
    for x in extras:
        k, sep, v = x.partition("=")
        if not sep:
            raise ValueError(f"argumento '{x}' não é chave=valor")
        kv[k] = v
    ctx = TurnContext(satellite="cli", source=WakeSource.WAKE, started_at=datetime.now(UTC))
    return ActionRequest(
        intent=Intent(id=intent, slots=(Slot(name="tv", value=tv_id),)), ctx=ctx, confirmed=True, args=kv
    )


def testar(
    args: list[str],
    *,
    fabrica_driver: FabricaDriver | None = None,
    relogio: Callable[[], float] | None = None,
    dormir: Callable[[float], Any] | None = None,
) -> int | None:
    """``testar <tv> <acao> [chave=valor…]``: roda uma ação pelo ``Executor`` e mostra
    ``ok``/``motivo``/``ms`` (ex.: ``testar sala volume volume=+2``, ``testar sala text texto=oi``)."""
    p = _parser("testar", "roda uma ação numa TV e mostra o resultado")
    p.add_argument("tv")
    p.add_argument("acao", help="power_on, power_off, volume, mute, app, input, key, text, state…")
    p.add_argument("extras", nargs="*", help="chave=valor (ex.: volume=+2, app=netflix, key=ok, step=1)")
    a = p.parse_args(args)
    cfg = _ler_cfg()
    if cfg is None:
        return 2
    tv = achar_tv(cfg, a.tv)
    if tv is None:
        print(f"Nenhuma TV '{a.tv}' no casa.toml.", file=sys.stderr)
        return 2
    try:
        req = montar_pedido(tv.id, a.acao, a.extras)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    rel = relogio or time.monotonic
    res, ms = asyncio.run(_rodar(cfg, req, _fabrica(fabrica_driver), rel, dormir))
    motivo = res.motivo.value if res.motivo else "-"
    extra = f" emulado={res.emulado}" if res.emulado else ""
    print(f"ok={res.ok} motivo={motivo} ms={ms}{extra}" + (f" detalhe={res.detalhe}" if res.detalhe else ""))
    return 0 if res.ok else 1


async def _rodar(
    cfg: CasaConfig, req: Any, fabrica: FabricaDriver, relogio: Callable[[], float], dormir: Any
) -> tuple[Any, int]:
    from magi.casa.emula import Executor

    ctx = _ctx(cfg)
    drivers = {t.id: fabrica(t, ctx) for t in cfg.tvs}
    ex = Executor(cfg, drivers, relogio=relogio, dormir=dormir)
    t0 = relogio()
    try:
        res = await ex.rodar(req, origem="local")
    finally:
        for d in drivers.values():
            with contextlib.suppress(Exception):
                await d.fechar()
    return res, round((relogio() - t0) * 1000)
