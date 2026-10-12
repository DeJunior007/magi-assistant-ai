"""Catálogo de apps da casa (``apps.yaml``, spec §12.5; dono: C1.1).

O catálogo base mora ao lado deste arquivo; o override do usuário
(``~/.config/magi/casa-apps.yaml``, lido na hora) tem o mesmo formato e **ganha por ``id``** (a
entrada inteira é trocada; ids novos entram no fim). Driver sem entrada para o app →
``para_driver`` devolve ``None`` e o driver responde ``APP_DESCONHECIDO``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from magi.casa.config import CasaConfigErro, caminho_apps_override, normaliza
from magi.elo.mensagens import AppInfo

BASE = Path(__file__).with_name("apps.yaml")
DRIVERS_APP = ("samsung", "roku", "androidtv")


@dataclass(frozen=True)
class AppAndroidTv:
    link: str
    pacote: str = ""


@dataclass(frozen=True)
class AppEntrada:
    id: str
    nome: str
    apelidos: tuple[str, ...] = ()
    samsung: str | None = None
    roku: str | None = None
    androidtv: AppAndroidTv | None = None

    def info(self) -> AppInfo:
        return AppInfo(id=self.id, nome=self.nome, apelidos=self.apelidos)


def _entrada(d: Any, onde: str) -> AppEntrada:
    if not isinstance(d, Mapping):
        raise CasaConfigErro(f"{onde}: cada app deve ser um mapa")
    app_id, nome = d.get("id"), d.get("nome")
    if not isinstance(app_id, str) or not app_id.strip():
        raise CasaConfigErro(f"{onde}: app sem 'id'")
    if not isinstance(nome, str) or not nome.strip():
        raise CasaConfigErro(f"{onde}: app '{app_id}' sem 'nome'")
    apelidos = d.get("apelidos", [])
    if not isinstance(apelidos, list) or not all(isinstance(a, str) for a in apelidos):
        raise CasaConfigErro(f"{onde}: app '{app_id}': 'apelidos' deve ser lista de textos")
    atv = d.get("androidtv")
    atv_ok: AppAndroidTv | None = None
    if atv is not None:
        if not isinstance(atv, Mapping) or not isinstance(atv.get("link"), str):
            raise CasaConfigErro(f"{onde}: app '{app_id}': androidtv precisa de {{link, pacote}}")
        atv_ok = AppAndroidTv(link=atv["link"], pacote=str(atv.get("pacote", "")))
    for drv in ("samsung", "roku"):
        v = d.get(drv)
        if v is not None and not isinstance(v, str | int):
            raise CasaConfigErro(f"{onde}: app '{app_id}': '{drv}' deve ser texto")
    return AppEntrada(
        id=app_id.strip(),
        nome=nome.strip(),
        apelidos=tuple(a.strip() for a in apelidos if a.strip()),
        samsung=None if d.get("samsung") is None else str(d["samsung"]),
        roku=None if d.get("roku") is None else str(d["roku"]),
        androidtv=atv_ok,
    )


def _ler_arquivo(p: Path) -> list[AppEntrada]:
    try:
        dados = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise CasaConfigErro(f"{p}: YAML inválido ({e})") from None
    lista = dados.get("apps", []) if isinstance(dados, Mapping) else None
    if not isinstance(lista, list):
        raise CasaConfigErro(f"{p}: esperado 'apps:' com uma lista")
    vistos: set[str] = set()
    saida = []
    for d in lista:
        e = _entrada(d, str(p))
        if e.id in vistos:
            raise CasaConfigErro(f"{p}: app '{e.id}' repetido")
        vistos.add(e.id)
        saida.append(e)
    return saida


class AppCatalogo:
    def __init__(self, entradas: Iterable[AppEntrada]) -> None:
        self._por_id: dict[str, AppEntrada] = {}
        for e in entradas:
            self._por_id[e.id] = e
        self._por_nome: dict[str, str] = {}
        for e in self._por_id.values():
            for n in (e.id, e.nome, *e.apelidos):
                self._por_nome.setdefault(normaliza(n), e.id)

    def __len__(self) -> int:
        return len(self._por_id)

    def __contains__(self, app_id: object) -> bool:
        return app_id in self._por_id

    def ids(self) -> tuple[str, ...]:
        return tuple(self._por_id)

    def get(self, app_id: str) -> AppEntrada | None:
        return self._por_id.get(app_id)

    def resolver(self, texto: str) -> AppEntrada | None:
        """Id, nome ou apelido (normalizado) → entrada."""
        app_id = self._por_nome.get(normaliza(texto))
        return None if app_id is None else self._por_id[app_id]

    def para_driver(self, app_id: str, driver: str) -> str | AppAndroidTv | None:
        e = self._por_id.get(app_id)
        if e is None or driver not in DRIVERS_APP:
            return None
        return getattr(e, driver)

    def ids_para(self, driver: str) -> tuple[str, ...]:
        """Ids que o driver sabe abrir (Roku: todos, pois ausente = busca por nome)."""
        if driver == "roku":
            return self.ids()
        return tuple(i for i in self._por_id if self.para_driver(i, driver) is not None)

    def por_pacote(self, pacote: str) -> AppEntrada | None:
        """Android TV: pacote do app atual → entrada (``EstadoTv.app``)."""
        return next(
            (e for e in self._por_id.values() if e.androidtv and e.androidtv.pacote == pacote),
            None,
        )

    def infos(self) -> tuple[AppInfo, ...]:
        return tuple(e.info() for e in self._por_id.values())


def carregar(base: Path | None = None, override: Path | None = None) -> AppCatalogo:
    """Catálogo base + override do usuário (ausente = só o base). Erro → ``CasaConfigErro``."""
    entradas = {e.id: e for e in _ler_arquivo(base or BASE)}
    p = caminho_apps_override(override)
    if p.exists():
        for e in _ler_arquivo(p):
            entradas[e.id] = e
    return AppCatalogo(entradas.values())
