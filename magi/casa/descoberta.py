"""Descoberta e identificação das TVs (spec §12.1–§12.2, design §5.3; dono: C1.5).

``Descobridor`` junta anúncios de duas **fontes injetáveis** (SSDP pelo ``async-upnp-client`` e
mDNS pelo ``zeroconf``; nos testes, listas falsas — nenhum socket multicast) e confirma cada IP por
**sondas injetáveis** (HTTP ``:8060/query/device-info`` do Roku, ``:8001/api/v2/`` da Samsung, TCP
``:6466`` do Android TV, MAC de ``/proc/net/arp``). Cada TV confirmada vira um ``Candidato`` com a
``chave`` estável (``roku:<serial>``, ``samsung:<device.id>``, ``androidtv:<MAC>``).

TCL (D9, §12.2): no mesmo IP, ``:8060`` responde → ``roku``; anuncia ``_androidtvremote2._tcp`` ou
abre ``:6466`` → ``androidtv``; os dois → ``androidtv`` e log ``tcl_dois_protocolos``. O modelo
não decide.

Revalidação (§10.4): ``revalidar(cfg, candidatos)`` troca o IP (e preenche MAC vazio) das TVs do
``casa.toml`` achadas com a mesma ``chave`` em outro IP e grava o arquivo de forma atômica;
``revalidar_periodicamente`` é o laço que o ``servir`` liga a cada ``descoberta_min``.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import logging
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from magi.casa import config as cfg_mod
from magi.casa import log
from magi.casa.config import CasaConfig

ST_ROKU = "roku:ecp"
ST_SAMSUNG = (
    "urn:samsung.com:device:RemoteControlReceiver:1",
    "urn:schemas-upnp-org:device:MediaRenderer:1",
)
MDNS_ATV = "_androidtvremote2._tcp.local."
PORTA_ROKU = 8060
PORTA_SAMSUNG = 8001
PORTA_ATV = 6466
T_SONDA = 2.0
ARP = Path("/proc/net/arp")
_MAC = re.compile(r"^([0-9a-f]{2}:){5}[0-9a-f]{2}$")


@dataclass(frozen=True)
class Anuncio:
    """Uma resposta crua de uma fonte: ``fonte`` ``ssdp``|``mdns``; ``tipo`` = ST do SSDP ou o
    serviço mDNS; ``nome`` = nome mDNS (sem o sufixo do serviço)."""

    fonte: str
    ip: str
    tipo: str
    nome: str = ""


@dataclass(frozen=True)
class Candidato:
    chave: str
    driver: str
    ip: str
    mac: str = ""
    modelo: str = ""
    nome: str = ""  # anunciado pela TV
    nomeada: str = ""  # id no casa.toml, se já estiver lá

    def para_dict(self) -> dict[str, str]:
        return dataclasses.asdict(self)


Fonte = Callable[[float], Awaitable[Iterable[Anuncio]]]


class Sondas(Protocol):
    async def roku(self, ip: str) -> Mapping[str, str] | None: ...
    async def samsung(self, ip: str) -> Mapping[str, Any] | None: ...
    async def abre_atv(self, ip: str) -> bool: ...
    def mac(self, ip: str) -> str: ...


def normaliza_mac(v: str | None) -> str:
    m = (v or "").strip().lower().replace("-", ":")
    return m if _MAC.match(m) and m != "00:00:00:00:00:00" else ""


def mac_de_arp(ip: str, caminho: Path = ARP) -> str:
    """MAC do IP na tabela ARP do kernel (vazio se não houver)."""
    try:
        linhas = caminho.read_text().splitlines()[1:]
    except OSError:
        return ""
    for linha in linhas:
        cols = linha.split()
        if len(cols) >= 4 and cols[0] == ip:
            return normaliza_mac(cols[3])
    return ""


def xml_device_info(texto: str) -> dict[str, str]:
    raiz = ET.fromstring(texto)
    return {el.tag: (el.text or "").strip() for el in raiz}


class SondasHttp:
    """Sondas reais (aiohttp/TCP). ``portas`` troca a porta lógica pela real (testes com servidor
    falso em ``127.0.0.1:0``); ``arp`` troca o ``/proc/net/arp``."""

    def __init__(self, *, portas: Mapping[int, int] | None = None, arp: Path = ARP, timeout: float = T_SONDA):
        self._portas = dict(portas or {})
        self._arp = arp
        self._t = timeout

    def _p(self, logica: int) -> int:
        return self._portas.get(logica, logica)

    async def _get(self, ip: str, porta: int, caminho: str) -> tuple[int, str] | None:
        import aiohttp

        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self._t)) as s:
                async with s.get(f"http://{ip}:{self._p(porta)}{caminho}") as r:
                    return r.status, await r.text()
        except (TimeoutError, OSError, aiohttp.ClientError):
            return None

    async def roku(self, ip: str) -> Mapping[str, str] | None:
        r = await self._get(ip, PORTA_ROKU, "/query/device-info")
        if r is None or r[0] != 200:
            return None
        try:
            return xml_device_info(r[1])
        except ET.ParseError:
            return None

    async def samsung(self, ip: str) -> Mapping[str, Any] | None:
        r = await self._get(ip, PORTA_SAMSUNG, "/api/v2/")
        if r is None or r[0] != 200:
            return None
        try:
            d = json.loads(r[1])
        except ValueError:
            return None
        return d if isinstance(d, dict) else None

    async def abre_atv(self, ip: str) -> bool:
        try:
            async with asyncio.timeout(self._t):
                _, w = await asyncio.open_connection(ip, self._p(PORTA_ATV))
        except (TimeoutError, OSError):
            return False
        w.close()
        with contextlib.suppress(Exception):
            await w.wait_closed()
        return True

    def mac(self, ip: str) -> str:
        return mac_de_arp(ip, self._arp)


# --- fontes reais (nunca rodam nos testes) ---------------------------------------------------
async def ssdp_real(segundos: float) -> list[Anuncio]:  # pragma: no cover - multicast real
    from async_upnp_client.search import async_search

    achados: list[Anuncio] = []

    for st in (ST_ROKU, *ST_SAMSUNG):

        async def _cb(headers: Any, st: str = st) -> None:
            loc = str(headers.get("location", ""))
            m = re.match(r"https?://\[?([^\]/:]+)", loc)
            ip = m.group(1) if m else str(headers.get("_host", ""))
            if ip:
                achados.append(Anuncio("ssdp", ip, st))

        await async_search(_cb, timeout=max(1, int(segundos)), search_target=st)
    return achados


async def mdns_real(segundos: float) -> list[Anuncio]:  # pragma: no cover - multicast real
    from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

    nomes: set[str] = set()

    def _ao_mudar(zeroconf: Any, service_type: str, name: str, state_change: Any) -> None:
        nomes.add(name)

    azc = AsyncZeroconf()
    try:
        browser = AsyncServiceBrowser(azc.zeroconf, MDNS_ATV, handlers=[_ao_mudar])
        await asyncio.sleep(segundos)
        await browser.async_cancel()
        achados: list[Anuncio] = []
        for nome in nomes:
            info = AsyncServiceInfo(MDNS_ATV, nome)
            if await info.async_request(azc.zeroconf, 2000):
                curto = nome.removesuffix("." + MDNS_ATV)
                achados += [Anuncio("mdns", ip, MDNS_ATV, curto) for ip in info.parsed_addresses()]
        return achados
    finally:
        await azc.async_close()


# --- identificação ---------------------------------------------------------------------------
class Descobridor:
    def __init__(
        self,
        *,
        ssdp: Fonte | None = None,
        mdns: Fonte | None = None,
        sondas: Sondas | None = None,
    ) -> None:
        self._ssdp = ssdp or ssdp_real
        self._mdns = mdns or mdns_real
        self._sondas = sondas or SondasHttp()

    async def _fonte(self, nome: str, f: Fonte, segundos: float) -> list[Anuncio]:
        try:
            return list(await f(segundos))
        except Exception:  # noqa: BLE001 - uma fonte com defeito não derruba a outra
            log.evento("descoberta_fonte_falhou", logging.WARNING, fonte=nome, exc=True)
            return []

    async def descobrir(self, segundos: float = 5.0, cfg: CasaConfig | None = None) -> list[Candidato]:
        ssdp, mdns = await asyncio.gather(
            self._fonte("ssdp", self._ssdp, segundos), self._fonte("mdns", self._mdns, segundos)
        )
        por_ip: dict[str, list[Anuncio]] = {}
        for a in (*ssdp, *mdns):
            por_ip.setdefault(a.ip, []).append(a)
        achados = await asyncio.gather(*(self._identificar(ip, an) for ip, an in por_ip.items()))
        nomeadas = {t.chave: t.id for t in (cfg.tvs if cfg else ()) if t.chave}
        saida: dict[str, Candidato] = {}
        for c in achados:
            if c is not None and c.chave not in saida:
                saida[c.chave] = dataclasses.replace(c, nomeada=nomeadas.get(c.chave, ""))
        log.evento("descoberta", ok=True, achadas=len(saida), anuncios=len(ssdp) + len(mdns))
        return sorted(saida.values(), key=lambda c: (c.driver, c.ip))

    async def _identificar(self, ip: str, anuncios: list[Anuncio]) -> Candidato | None:
        tipos = {a.tipo for a in anuncios}
        nome_mdns = next((a.nome for a in anuncios if a.fonte == "mdns" and a.nome), "")
        anunciou_atv = MDNS_ATV in tipos
        s = self._sondas
        if tipos & set(ST_SAMSUNG) and not (ST_ROKU in tipos or anunciou_atv):
            info = await s.samsung(ip)
            dev = info.get("device") if isinstance(info, Mapping) else None
            if not isinstance(dev, Mapping) or dev.get("type") != "Samsung SmartTV":
                log.evento("descoberta_sem_confirmacao", logging.DEBUG, ip=ip, driver="samsung")
                return None
            mac = normaliza_mac(dev.get("wifiMac")) or s.mac(ip)
            ident = str(dev.get("id") or info.get("id") or "") or mac
            if not ident:
                return None
            return Candidato(
                chave=f"samsung:{ident}",
                driver="samsung",
                ip=ip,
                mac=mac,
                modelo=str(dev.get("modelName") or ""),
                nome=str(dev.get("name") or info.get("name") or ""),
            )
        roku = await s.roku(ip)
        atv = await s.abre_atv(ip) if (anunciou_atv or roku is not None) else False
        if anunciou_atv and not atv and roku is None:
            log.evento("descoberta_sem_confirmacao", logging.DEBUG, ip=ip, driver="androidtv")
            return None
        if roku is not None and (atv or anunciou_atv):
            log.evento("tcl_dois_protocolos", ip=ip, driver="androidtv")
        mac_roku = normaliza_mac(roku.get("wifi-mac") or roku.get("ethernet-mac")) if roku else ""
        modelo_roku = (roku.get("model-name") or roku.get("model-number") or "") if roku else ""
        nome_roku = (roku.get("user-device-name") or roku.get("friendly-device-name") or "") if roku else ""
        if atv or (anunciou_atv and roku is not None):
            mac = mac_roku or s.mac(ip)
            ident = mac or nome_mdns or ip
            return Candidato(
                chave=f"androidtv:{ident}",
                driver="androidtv",
                ip=ip,
                mac=mac,
                modelo=modelo_roku,
                nome=nome_mdns or nome_roku,
            )
        if roku is not None:
            serial = roku.get("serial-number") or ""
            if not serial:
                return None
            return Candidato(
                chave=f"roku:{serial}",
                driver="roku",
                ip=ip,
                mac=mac_roku or s.mac(ip),
                modelo=modelo_roku,
                nome=nome_roku,
            )
        return None


# --- cache da última descoberta (para o ``nomear``) ----------------------------------------
def caminho_descobertas(caminho: Path | None = None) -> Path:
    return caminho if caminho is not None else cfg_mod.caminho_estado().parent / "casa-descobertas.json"


def gravar_descobertas(cands: Iterable[Candidato], caminho: Path | None = None) -> Path:
    p = caminho_descobertas(caminho)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".descobertas.", dir=p.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump([c.para_dict() for c in cands], f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return p


def ler_descobertas(caminho: Path | None = None) -> list[Candidato]:
    try:
        dados = json.loads(caminho_descobertas(caminho).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    campos = {f.name for f in dataclasses.fields(Candidato)}
    return [
        Candidato(**{k: str(v) for k, v in d.items() if k in campos}) for d in dados if isinstance(d, dict)
    ]


# --- revalidação de IP (§10.4) --------------------------------------------------------------
def revalidar(
    cfg: CasaConfig, cands: Iterable[Candidato], *, caminho: Path | None = None, gravar: bool = True
) -> CasaConfig:
    """TV do ``casa.toml`` achada com a mesma ``chave`` em outro IP → IP novo (e MAC, se faltava),
    ``casa.toml`` gravado de forma atômica e log ``ip_atualizado``. Sem mudança → mesmo ``cfg``."""
    por_chave = {c.chave: c for c in cands}
    novas = []
    mudou = False
    for tv in cfg.tvs:
        c = por_chave.get(tv.chave) if tv.chave else None
        if c is not None and c.ip and (c.ip != tv.ip or (c.mac and not tv.mac)):
            log.evento("ip_atualizado", tv=tv.id, driver=tv.driver, ip=c.ip, ip_antes=tv.ip)
            tv = dataclasses.replace(tv, ip=c.ip, mac=tv.mac or c.mac)
            mudou = True
        novas.append(tv)
    if not mudou:
        return cfg
    novo = dataclasses.replace(cfg, tvs=tuple(novas))
    if gravar:
        cfg_mod.salvar(novo, caminho)
    return novo


async def revalidar_periodicamente(
    descobridor: Descobridor,
    *,
    ler_cfg: Callable[[], CasaConfig] = cfg_mod.ler,
    ao_mudar: Callable[[CasaConfig], Any] | None = None,
    dormir: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    segundos: float = 5.0,
    voltas: int | None = None,
) -> None:
    """Laço do ``servir``: dorme ``descoberta_min``, descobre e revalida. ``voltas`` limita (testes).

    Relê o ``casa.toml`` a cada volta (o Pedro pode ter editado); erro numa volta só loga."""
    n = 0
    while voltas is None or n < voltas:
        n += 1
        try:
            cfg = ler_cfg()
        except cfg_mod.CasaConfigErro:
            log.evento("revalidacao_config_invalida", logging.WARNING)
            await dormir(600.0)
            continue
        await dormir(cfg.descoberta_min * 60.0)
        if not any(t.chave for t in cfg.tvs):
            continue
        try:
            cands = await descobridor.descobrir(segundos, cfg)
            novo = revalidar(cfg, cands)
        except Exception:  # noqa: BLE001 - revalidação nunca derruba a casa
            log.evento("revalidacao_falhou", logging.WARNING, exc=True)
            continue
        if novo is not cfg and ao_mudar is not None:
            r = ao_mudar(novo)
            if asyncio.iscoroutine(r):
                await r
