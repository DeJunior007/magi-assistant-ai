"""``casa.toml`` (spec §12.4) e os caminhos da casa (§10.1); dono: C1.1.

Os caminhos são resolvidos **na hora da chamada** (parâmetro ``None`` = padrão), como no overlay,
para os testes trocarem com ``monkeypatch`` (``HOME``/``XDG_*``).

Validação (CA-Y50): arquivo ausente → casa sem TVs; ``id``/``nome``/apelidos únicos entre TVs com
comparação normalizada (sem acento, sem caixa, como no roteador); ``padrao`` aponta para TV
existente; driver desconhecido → só aquela TV é ignorada (log ``tv_ignorada``); ``escuta`` nunca
``0.0.0.0``. Erro → ``CasaConfigErro`` com mensagem clara.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import tomllib
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from magi.casa import log
from magi.casa.driver import ENTRADAS_CANONICAS, Capacidades, TvConfig
from magi.casa.drivers import conhecido
from magi.elo.mensagens import TvInfo

PORTA_PADRAO = 10760
_ID = re.compile(r"^[a-z0-9_-]+$")


class CasaConfigErro(ValueError):
    pass


# --- caminhos (lidos na hora) ---------------------------------------------------------------
def _xdg(var: str, padrao: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / padrao)


def dir_config(base: Path | None = None) -> Path:
    return base if base is not None else _xdg("XDG_CONFIG_HOME", ".config") / "magi"


def caminho_casa(caminho: Path | None = None) -> Path:
    return caminho if caminho is not None else dir_config() / "casa.toml"


def caminho_apps_override(caminho: Path | None = None) -> Path:
    return caminho if caminho is not None else dir_config() / "casa-apps.yaml"


def caminho_token_local(caminho: Path | None = None) -> Path:
    return caminho if caminho is not None else dir_config() / "casa.token"


def caminho_token_ayanami(caminho: Path | None = None) -> Path:
    return caminho if caminho is not None else dir_config() / "ayanami-casa.token"


def dir_pareamento(caminho: Path | None = None) -> Path:
    if caminho is not None:
        return caminho
    return _xdg("XDG_DATA_HOME", ".local/share") / "magi" / "casa"


def caminho_estado(caminho: Path | None = None) -> Path:
    if caminho is not None:
        return caminho
    return _xdg("XDG_STATE_HOME", ".local/state") / "magi" / "casa-estado.json"


# --- modelo ---------------------------------------------------------------------------------
@dataclass(frozen=True)
class CasaConfig:
    escuta: str = "127.0.0.1"
    porta: int = PORTA_PADRAO
    ayanami: str = ""  # vazio = só local
    padrao: str = ""  # id da TV padrão
    broadcast: str = "192.168.0.255"
    descoberta_min: int = 10
    tvs: tuple[TvConfig, ...] = ()
    ignoradas: tuple[TvConfig, ...] = field(default=(), compare=False)  # driver desconhecido

    def tv(self, tv_id: str) -> TvConfig | None:
        return next((t for t in self.tvs if t.id == tv_id), None)


def normaliza(texto: str) -> str:
    """Sem acento, minúsculo, espaços colapsados (mesma ideia do ``normalize_text`` do roteador)."""
    t = unicodedata.normalize("NFKD", texto)
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return " ".join(re.sub(r"[^\w\s-]", " ", t).split())


def tv_info(tv: TvConfig, caps: Capacidades, padrao: bool = False) -> TvInfo:
    """Parte fixa da TV para o ``ola`` (§1.2 [DS19])."""
    return TvInfo(
        id=tv.id,
        nome=tv.nome,
        driver=tv.driver,
        apelidos=tv.apelidos,
        caps=caps.anunciadas(),
        entradas=caps.entradas,
        apps=caps.apps,
        padrao=padrao,
    )


# --- leitura e validação --------------------------------------------------------------------
def _str(d: Mapping[str, Any], k: str, onde: str, padrao: str | None = None) -> str:
    v = d.get(k, padrao)
    if v is None:
        raise CasaConfigErro(f"{onde}: falta '{k}'")
    if not isinstance(v, str):
        raise CasaConfigErro(f"{onde}: '{k}' deve ser texto")
    return v.strip()


def _int(d: Mapping[str, Any], k: str, onde: str, padrao: int | None) -> int | None:
    v = d.get(k, padrao)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, int):
        raise CasaConfigErro(f"{onde}: '{k}' deve ser inteiro")
    return v


def _tv(d: Any, i: int) -> TvConfig:
    onde = f"casa.toml [[tv]] nº {i + 1}"
    if not isinstance(d, Mapping):
        raise CasaConfigErro(f"{onde}: deve ser uma tabela")
    tv_id = _str(d, "id", onde)
    onde = f"casa.toml [[tv]] '{tv_id}'"
    if not _ID.match(tv_id):
        raise CasaConfigErro(f"{onde}: id só aceita [a-z0-9_-]")
    apelidos = d.get("apelidos", [])
    if not isinstance(apelidos, list) or not all(isinstance(a, str) for a in apelidos):
        raise CasaConfigErro(f"{onde}: 'apelidos' deve ser lista de textos")
    entradas = d.get("entradas", {})
    if not isinstance(entradas, Mapping):
        raise CasaConfigErro(f"{onde}: 'entradas' deve ser tabela apelido = canônica")
    for apelido, canonica in entradas.items():
        if canonica not in ENTRADAS_CANONICAS:
            raise CasaConfigErro(
                f"{onde}: entrada '{apelido}' = '{canonica}' não é canônica ({', '.join(ENTRADAS_CANONICAS)})"
            )
    adb = d.get("adb", False)
    if not isinstance(adb, bool):
        raise CasaConfigErro(f"{onde}: 'adb' deve ser true/false")
    zerar = _int(d, "zerar_passos", onde, 50)
    return TvConfig(
        id=tv_id,
        nome=_str(d, "nome", onde),
        driver=_str(d, "driver", onde),
        apelidos=tuple(a.strip() for a in apelidos if a.strip()),
        chave=_str(d, "chave", onde, ""),
        ip=_str(d, "ip", onde, ""),
        mac=_str(d, "mac", onde, "").lower(),
        ano=_int(d, "ano", onde, None),
        zerar_passos=50 if zerar is None else zerar,
        entradas={str(k): str(v) for k, v in entradas.items()},
        adb=adb,
    )


def validar(dados: Mapping[str, Any], *, logar: bool = True) -> CasaConfig:
    """Monta e valida a ``CasaConfig`` a partir do TOML já lido."""
    casa = dados.get("casa", {})
    if not isinstance(casa, Mapping):
        raise CasaConfigErro("casa.toml: [casa] deve ser uma tabela")
    escuta = _str(casa, "escuta", "casa.toml [casa]", "127.0.0.1")
    if escuta in ("0.0.0.0", "::", "", "*"):
        raise CasaConfigErro(
            f"casa.toml [casa]: escuta = '{escuta}' não é aceito; use 127.0.0.1 ou o IP do tailnet"
        )
    porta = _int(casa, "porta", "casa.toml [casa]", PORTA_PADRAO) or PORTA_PADRAO
    if not 1 <= porta <= 65535:
        raise CasaConfigErro(f"casa.toml [casa]: porta {porta} fora de 1..65535")
    descoberta = _int(casa, "descoberta_min", "casa.toml [casa]", 10) or 10
    if descoberta < 1:
        raise CasaConfigErro("casa.toml [casa]: descoberta_min deve ser ≥ 1")

    brutas = dados.get("tv", [])
    if not isinstance(brutas, list):
        raise CasaConfigErro("casa.toml: use [[tv]] (lista de tabelas)")
    todas = [_tv(d, i) for i, d in enumerate(brutas)]

    # nomes únicos entre TVs (id, nome e apelidos, normalizados)
    dono: dict[str, str] = {}
    ids: set[str] = set()
    for tv in todas:
        if tv.id in ids:
            raise CasaConfigErro(f"casa.toml: id '{tv.id}' repetido")
        ids.add(tv.id)
        for nome in {normaliza(n) for n in (tv.id, tv.nome, *tv.apelidos)} - {""}:
            outro = dono.get(nome)
            if outro is not None and outro != tv.id:
                raise CasaConfigErro(
                    f"casa.toml: apelido '{nome}' repetido nas TVs '{outro}' e '{tv.id}' "
                    "(a comparação ignora acento e maiúsculas)"
                )
            dono[nome] = tv.id

    tvs: list[TvConfig] = []
    ignoradas: list[TvConfig] = []
    for tv in todas:
        if conhecido(tv.driver):
            tvs.append(tv)
        else:
            ignoradas.append(tv)
            if logar:
                log.evento(
                    "tv_ignorada",
                    logging.WARNING,
                    tv=tv.id,
                    driver=tv.driver,
                    motivo="driver_desconhecido",
                )

    padrao = _str(casa, "padrao", "casa.toml [casa]", "")
    if padrao:
        if padrao not in ids:
            raise CasaConfigErro(f"casa.toml [casa]: padrao = '{padrao}' não é o id de nenhuma TV")
        if padrao not in {t.id for t in tvs}:
            if logar:
                log.evento("padrao_ignorado", logging.WARNING, tv=padrao, motivo="driver_desconhecido")
            padrao = ""

    return CasaConfig(
        escuta=escuta,
        porta=porta,
        ayanami=_str(casa, "ayanami", "casa.toml [casa]", "").rstrip("/"),
        padrao=padrao,
        broadcast=_str(casa, "broadcast", "casa.toml [casa]", "192.168.0.255"),
        descoberta_min=descoberta,
        tvs=tuple(tvs),
        ignoradas=tuple(ignoradas),
    )


def ler(caminho: Path | None = None) -> CasaConfig:
    """Lê o ``casa.toml``; ausente → ``CasaConfig()`` (sobe sem TVs)."""
    p = caminho_casa(caminho)
    try:
        with p.open("rb") as f:
            dados = tomllib.load(f)
    except FileNotFoundError:
        return CasaConfig()
    except tomllib.TOMLDecodeError as e:
        raise CasaConfigErro(f"{p}: TOML inválido ({e})") from None
    return validar(dados)


# --- escrita atômica ------------------------------------------------------------------------
def _toml_valor(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        esc = v.replace("\\", "\\\\").replace('"', '\\"')
        esc = "".join(c if ord(c) >= 0x20 and c != "\x7f" else f"\\u{ord(c):04x}" for c in esc)
        return f'"{esc}"'
    if isinstance(v, list | tuple):
        return "[" + ", ".join(_toml_valor(x) for x in v) + "]"
    if isinstance(v, Mapping):
        return "{ " + ", ".join(f"{_toml_chave(k)} = {_toml_valor(x)}" for k, x in v.items()) + " }"
    raise TypeError(f"valor sem formato TOML: {type(v).__name__}")


def _toml_chave(k: str) -> str:
    return k if re.fullmatch(r"[A-Za-z0-9_-]+", k) else _toml_valor(k)


def para_toml(cfg: CasaConfig) -> str:
    linhas = ["[casa]"]
    for k in ("escuta", "porta", "ayanami", "padrao", "broadcast", "descoberta_min"):
        linhas.append(f"{k} = {_toml_valor(getattr(cfg, k))}")
    for tv in (*cfg.tvs, *cfg.ignoradas):
        linhas += ["", "[[tv]]"]
        campos: dict[str, Any] = {
            "id": tv.id,
            "nome": tv.nome,
            "apelidos": list(tv.apelidos),
            "driver": tv.driver,
            "chave": tv.chave,
            "ip": tv.ip,
            "mac": tv.mac,
            "ano": tv.ano,
            "zerar_passos": tv.zerar_passos,
            "entradas": dict(tv.entradas),
            "adb": tv.adb,
        }
        for k, v in campos.items():
            if v is None or (k in ("chave", "ip", "mac") and v == ""):
                continue
            if k == "entradas" and not v:
                continue
            linhas.append(f"{k} = {_toml_valor(v)}")
    return "\n".join(linhas) + "\n"


def salvar(cfg: CasaConfig, caminho: Path | None = None) -> Path:
    """Grava o ``casa.toml`` de forma atômica (temporário no mesmo diretório + ``os.replace``).

    Mantém as TVs ignoradas (driver desconhecido) para não apagar o que o Pedro escreveu.
    """
    p = caminho_casa(caminho)
    p.parent.mkdir(parents=True, exist_ok=True)
    texto = para_toml(cfg)
    validar(tomllib.loads(texto), logar=False)  # nunca grava um arquivo que a própria casa recusaria
    try:
        modo = p.stat().st_mode & 0o777
    except FileNotFoundError:
        modo = 0o644
    fd, tmp = tempfile.mkstemp(prefix=".casa.", suffix=".toml.tmp", dir=p.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(texto)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, modo)
        os.replace(tmp, p)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return p
