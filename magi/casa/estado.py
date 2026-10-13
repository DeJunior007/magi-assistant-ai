"""Estado vivo das TVs (spec §10.4 *Estado*; dono: C1.1c).

``EstadoCasa`` guarda a ``EstadoTv`` de cada TV em memória e grava só o último retrato em
``casa-estado.json`` (escrita atômica: temporário no mesmo diretório + ``os.replace``) para o ``ola``
depois de um reinício. Mudança real (ignorando ``visto``) avisa os ouvintes (a API local empurra
``estado`` sem pedido).

Sondagem por driver: ``driver.state()`` a cada ``INTERVALO_S`` (30 s); a Android TV lê o estado que
os callbacks da TV já mantêm, então pode ser lida mais amiúde (``INTERVALOS``). Sem resposta (exceção
ou ``online=False``) em ``FALHAS_OFFLINE`` sondagens seguidas → ``online=False`` (o resto do último
estado conhecido fica). Relógio e ``dormir`` injetados; nada de ``sleep`` real nos testes.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import os
import tempfile
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from magi.casa import log
from magi.casa.config import caminho_estado
from magi.casa.driver import TvDriver
from magi.elo.mensagens import EstadoTv, agora_utc, formata_ts, le_ts

INTERVALO_S = 30.0
INTERVALOS: Mapping[str, float] = {"androidtv": 5.0}  # push da TV: ler o cache é barato
FALHAS_OFFLINE = 2

Ouvinte = Callable[[tuple[EstadoTv, ...]], "None | Awaitable[None]"]


def _sem_visto(e: EstadoTv) -> EstadoTv:
    return dataclasses.replace(e, visto=None)


def para_dict(e: EstadoTv) -> dict[str, Any]:
    d = dataclasses.asdict(e)
    d["visto"] = formata_ts(e.visto) if e.visto is not None else None
    return d


def de_dict(d: Mapping[str, Any]) -> EstadoTv:
    campos = {f.name for f in dataclasses.fields(EstadoTv)}
    kw = {k: v for k, v in d.items() if k in campos}
    if kw.get("visto") is not None:
        kw["visto"] = le_ts(kw["visto"], "visto")
    return EstadoTv(**kw)


def gravar(estados: tuple[EstadoTv, ...], caminho: Path | None = None) -> Path:
    """Grava o retrato em ``casa-estado.json`` de forma atômica."""
    p = caminho_estado(caminho)
    p.parent.mkdir(parents=True, exist_ok=True)
    texto = json.dumps({"tvs": [para_dict(e) for e in estados]}, ensure_ascii=False, indent=1)
    fd, tmp = tempfile.mkstemp(prefix=".casa-estado.", suffix=".json.tmp", dir=p.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(texto + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return p


def carregar(caminho: Path | None = None) -> tuple[EstadoTv, ...]:
    """Lê o último retrato; ausente ou corrompido → ``()`` (com log, sem derrubar a casa)."""
    p = caminho_estado(caminho)
    try:
        dados = json.loads(p.read_text(encoding="utf-8"))
        return tuple(de_dict(d) for d in dados.get("tvs", ()))
    except FileNotFoundError:
        return ()
    except (ValueError, TypeError, AttributeError) as e:
        log.evento("estado_ilegivel", logging.WARNING, motivo=type(e).__name__)
        return ()


class EstadoCasa:
    """Estado em memória das TVs de ``drivers`` (``id`` → ``TvDriver``).

    ``nomes``: ``id`` → ``(nome, driver)`` para montar a ``EstadoTv`` de quem nunca respondeu.
    ``agora``: relógio de parede (``visto``). ``caminho``: ``casa-estado.json`` (``None`` = padrão).
    """

    def __init__(
        self,
        drivers: Mapping[str, TvDriver],
        nomes: Mapping[str, tuple[str, str]],
        *,
        agora: Callable[[], datetime] = agora_utc,
        caminho: Path | None = None,
        gravar_arquivo: bool = True,
    ) -> None:
        self.drivers = dict(drivers)
        self._agora = agora
        self._caminho = caminho
        self._gravar = gravar_arquivo
        self._falhas: dict[str, int] = dict.fromkeys(self.drivers, 0)
        self._ouvintes: list[Ouvinte] = []
        self._estados: dict[str, EstadoTv] = {
            tv_id: EstadoTv(id=tv_id, nome=nome, driver=drv, online=False)
            for tv_id, (nome, drv) in nomes.items()
            if tv_id in self.drivers
        }
        for e in carregar(caminho) if gravar_arquivo else ():
            if e.id in self._estados:  # TV que saiu do casa.toml não volta
                base = self._estados[e.id]
                self._estados[e.id] = dataclasses.replace(e, nome=base.nome, driver=base.driver)

    # --- leitura ------------------------------------------------------------------------
    def todos(self) -> tuple[EstadoTv, ...]:
        return tuple(self._estados.values())

    def get(self, tv_id: str) -> EstadoTv | None:
        return self._estados.get(tv_id)

    def ouvir(self, f: Ouvinte) -> Callable[[], None]:
        """Registra um ouvinte de mudança; devolve a função que o remove."""
        self._ouvintes.append(f)
        return lambda: self._ouvintes.remove(f) if f in self._ouvintes else None

    # --- escrita ------------------------------------------------------------------------
    async def atualizar(self, novo: EstadoTv) -> bool:
        """Troca o estado da TV; devolve ``True`` (e avisa/grava) se mudou algo além de ``visto``."""
        if novo.id not in self._estados:
            return False
        antigo = self._estados[novo.id]
        self._estados[novo.id] = novo
        if _sem_visto(antigo) == _sem_visto(novo):
            return False
        log.evento("estado", logging.DEBUG, tv=novo.id, driver=novo.driver, ok=novo.online)
        if self._gravar:
            try:
                gravar(self.todos(), self._caminho)
            except OSError as e:
                log.evento("estado_nao_gravado", logging.WARNING, motivo=type(e).__name__)
        retrato = self.todos()
        for f in list(self._ouvintes):
            try:
                r = f(retrato)
                if asyncio.iscoroutine(r):
                    await r
            except Exception:  # noqa: BLE001 - ouvinte com defeito não para a sondagem
                log.evento("ouvinte_falhou", logging.WARNING, exc=True)
        return True

    async def sondar(self, tv_id: str) -> EstadoTv | None:
        """Uma sondagem da TV (``driver.state()``); conta falhas e marca ``online=False`` na 2ª."""
        drv = self.drivers.get(tv_id)
        atual = self._estados.get(tv_id)
        if drv is None or atual is None:
            return None
        try:
            lido: EstadoTv | None = await drv.state()
        except Exception:  # noqa: BLE001 - driver não deveria levantar; conta como falha
            log.evento("sondagem_erro", logging.DEBUG, tv=tv_id, driver=atual.driver, exc=True)
            lido = None
        if lido is not None and lido.online:
            self._falhas[tv_id] = 0
            novo = dataclasses.replace(
                lido, id=tv_id, nome=atual.nome, driver=atual.driver, visto=lido.visto or self._agora()
            )
        else:
            self._falhas[tv_id] = self._falhas.get(tv_id, 0) + 1
            if self._falhas[tv_id] < FALHAS_OFFLINE or not atual.online:
                log.evento("sondagem", logging.DEBUG, tv=tv_id, ok=False, motivo="sem_resposta")
                return atual
            novo = dataclasses.replace(atual, online=False)
        log.evento("sondagem", logging.DEBUG, tv=tv_id, driver=atual.driver, ok=novo.online)
        await self.atualizar(novo)
        return self._estados[tv_id]

    async def rodar(
        self,
        dormir: Callable[[float], Awaitable[Any]] = asyncio.sleep,
        relogio: Callable[[], float] | None = None,
        voltas: int | None = None,
    ) -> None:
        """Laço de sondagem: cada TV no seu intervalo (por driver). ``voltas`` limita (testes)."""
        relogio = relogio or asyncio.get_running_loop().time
        proxima = dict.fromkeys(self.drivers, relogio())
        n = 0
        while voltas is None or n < voltas:
            agora = relogio()
            for tv_id in self.drivers:
                if proxima[tv_id] <= agora:
                    await self.sondar(tv_id)
                    drv = self._estados[tv_id].driver
                    proxima[tv_id] = agora + INTERVALOS.get(drv, INTERVALO_S)
            n += 1
            if not proxima:
                await dormir(INTERVALO_S)
                continue
            await dormir(max(0.0, min(proxima.values()) - relogio()))
