"""Config da Ayanami (dono: Y0.2; spec §9.1–§9.2, [DS8]).

- ``ayanami.toml`` (montado só-leitura em ``/etc/ayanami/ayanami.toml``): tudo que não é segredo.
  :func:`ler` devolve um :class:`AyanamiConfig` (dataclasses ``frozen``). Chave desconhecida, tipo
  errado ou valor fora da faixa → :class:`ConfigError` com o caminho da chave; a API não sobe.
- ``.env`` (``0600``, fora do git): só segredos. :func:`ler_segredos` lê **por nome** e devolve
  :class:`Segredos`, cujo ``repr`` nunca mostra valores; ``faltando`` lista só os nomes das
  obrigatórias da fase ligada que não vieram (a API sobe degradada, ``/saude`` ``ok=false``).
"""

from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

CAMINHO_PADRAO = Path("/etc/ayanami/ayanami.toml")
ESCOPOS_MCP = frozenset({"ler", "tarefas", "casa", "memoria-escrever"})


class ConfigError(ValueError):
    """Erro de config com o caminho da chave (``secao.chave``)."""

    def __init__(self, caminho: str, motivo: str) -> None:
        self.caminho = caminho
        self.motivo = motivo
        super().__init__(f"{caminho}: {motivo}")


# --------------------------------------------------------------------------- seções


@dataclass(frozen=True)
class Geral:
    url_base: str
    fuso: str = "America/Sao_Paulo"


@dataclass(frozen=True)
class Rede:
    batimento_s: int = 10
    offline_apos_s: int = 30
    longpoll_s: int = 25


@dataclass(frozen=True)
class Fila:
    rapida_concorrencia: int = 8
    agendada_concorrencia: int = 2
    lenta_concorrencia: int = 1


@dataclass(frozen=True)
class Budget:
    teto_nuvem_usd: float = 2.0
    teto_geral_usd: float = 5.0


@dataclass(frozen=True)
class Nuvem:
    ligado: bool = True
    stt_modelo: str = "gpt-transcribe"
    tts_voz: str = "marin"
    kokoro_reserva: bool = True
    contexto_turnos: int = 20


@dataclass(frozen=True)
class Noticias:
    ligado: bool = True
    dim: int = 768  # = NEWS_DIM do PC (magi/memory/migrate.py)
    # demais chaves = as de [news] do config.toml do PC; passam adiante sem interpretação aqui
    fontes: tuple[str, ...] | None = None
    timeout_s: float | None = None
    embedder: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class Backup:
    ligado: bool = True
    restore_teste: bool = True
    alerta_sem_snapshot_h: int = 36


@dataclass(frozen=True)
class Push:
    max_hora: int = 10
    noticias_dia: int = 3
    silencio_padrao: str = "23:00-07:30"
    ntfy_hosts: tuple[str, ...] = ()  # hosts aceitos no endpoint ``unifiedpush`` (spec §9.6)


@dataclass(frozen=True)
class Mcp:
    escopos: tuple[str, ...] = ("ler", "tarefas")
    memoria_ler: bool = False


@dataclass(frozen=True)
class Voz:
    modelo: str = "kokoro-v1.0.int8.onnx"
    voz: str = "pf_dora"
    descarregar_apos_s: int = 600


@dataclass(frozen=True)
class Embeddings:
    ligado: bool = False


@dataclass(frozen=True)
class AyanamiConfig:
    geral: Geral
    rede: Rede = field(default_factory=Rede)
    fila: Fila = field(default_factory=Fila)
    budget: Budget = field(default_factory=Budget)
    nuvem: Nuvem = field(default_factory=Nuvem)
    noticias: Noticias = field(default_factory=Noticias)
    backup: Backup = field(default_factory=Backup)
    push: Push = field(default_factory=Push)
    mcp: Mcp = field(default_factory=Mcp)
    voz: Voz = field(default_factory=Voz)
    embeddings: Embeddings = field(default_factory=Embeddings)


# --------------------------------------------------------------------------- validação

_OBRIGATORIA = object()
_HORARIO_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d$")


def _faixa(minimo: float | None = None, maximo: float | None = None) -> Callable[[Any], str | None]:
    def checar(v: Any) -> str | None:
        if minimo is not None and v < minimo:
            return f"fora da faixa ({v} < {minimo})"
        if maximo is not None and v > maximo:
            return f"fora da faixa ({v} > {maximo})"
        return None

    return checar


def _https(v: str) -> str | None:
    return None if v.startswith("https://") and len(v) > len("https://") else "precisa começar com https://"


def _fuso(v: str) -> str | None:
    try:
        ZoneInfo(v)
    except (ZoneInfoNotFoundError, ValueError):
        return f"fuso desconhecido: {v!r}"
    return None


def _nao_vazio(v: str) -> str | None:
    return None if v.strip() else "não pode ser vazio"


def _horario(v: str) -> str | None:
    return None if _HORARIO_RE.match(v) else "formato HH:MM-HH:MM"


_HOST_PORTA = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?(?::[0-9]{1,5})?$")


def _hosts(v: tuple[str, ...]) -> str | None:
    ruins = [h for h in v if not _HOST_PORTA.match(h)]
    if ruins:
        return f"cada item é host[:porta], sem esquema nem caminho: {ruins}"
    return None


def _escopos(v: tuple[str, ...]) -> str | None:
    fora = [e for e in v if e not in ESCOPOS_MCP]
    if fora:
        return f"escopo fora da lista {sorted(ESCOPOS_MCP)}: {fora}"
    if len(set(v)) != len(v):
        return "escopo repetido"
    return None


# tipo: bool | int | float | str | "strs" (lista de str → tupla) | "tabela" (dict)
_Campo = tuple[Any, Any, Callable[[Any], str | None] | None]

_ESQUEMA: dict[str, tuple[type, dict[str, _Campo]]] = {
    "geral": (Geral, {"url_base": (str, _OBRIGATORIA, _https), "fuso": (str, "America/Sao_Paulo", _fuso)}),
    "rede": (
        Rede,
        {
            "batimento_s": (int, 10, _faixa(5, 30)),
            "offline_apos_s": (int, 30, _faixa(1)),
            "longpoll_s": (int, 25, _faixa(10, 55)),
        },
    ),
    "fila": (
        Fila,
        {
            "rapida_concorrencia": (int, 8, _faixa(1, 16)),
            "agendada_concorrencia": (int, 2, _faixa(1, 4)),
            "lenta_concorrencia": (int, 1, _faixa(1, 2)),
        },
    ),
    "budget": (
        Budget,
        {"teto_nuvem_usd": (float, 2.0, _faixa(0)), "teto_geral_usd": (float, 5.0, _faixa(0))},
    ),
    "nuvem": (
        Nuvem,
        {
            "ligado": (bool, True, None),
            "stt_modelo": (str, "gpt-transcribe", _nao_vazio),
            "tts_voz": (str, "marin", _nao_vazio),
            "kokoro_reserva": (bool, True, None),
            "contexto_turnos": (int, 20, _faixa(0, 50)),
        },
    ),
    "noticias": (
        Noticias,
        {
            "ligado": (bool, True, None),
            "dim": (int, 768, _faixa(1, 2000)),
            "fontes": ("strs", None, None),
            "timeout_s": (float, None, _faixa(0.1)),
            "embedder": ("tabela", None, None),
        },
    ),
    "backup": (
        Backup,
        {
            "ligado": (bool, True, None),
            "restore_teste": (bool, True, None),
            "alerta_sem_snapshot_h": (int, 36, _faixa(1)),
        },
    ),
    "push": (
        Push,
        {
            "max_hora": (int, 10, _faixa(1, 60)),
            "noticias_dia": (int, 3, _faixa(0, 10)),
            "silencio_padrao": (str, "23:00-07:30", _horario),
            "ntfy_hosts": ("strs", (), _hosts),
        },
    ),
    "mcp": (Mcp, {"escopos": ("strs", ("ler", "tarefas"), _escopos), "memoria_ler": (bool, False, None)}),
    "voz": (
        Voz,
        {
            "modelo": (str, "kokoro-v1.0.int8.onnx", _nao_vazio),
            "voz": (str, "pf_dora", _nao_vazio),
            "descarregar_apos_s": (int, 600, _faixa(0)),
        },
    ),
    "embeddings": (Embeddings, {"ligado": (bool, False, None)}),
}


def _converter(caminho: str, tipo: Any, v: Any) -> Any:
    if tipo is bool:
        if isinstance(v, bool):
            return v
        raise ConfigError(caminho, f"esperado bool, veio {type(v).__name__}")
    if tipo is int:
        if isinstance(v, int) and not isinstance(v, bool):
            return v
        raise ConfigError(caminho, f"esperado inteiro, veio {type(v).__name__}")
    if tipo is float:
        if isinstance(v, int | float) and not isinstance(v, bool):
            return float(v)
        raise ConfigError(caminho, f"esperado número, veio {type(v).__name__}")
    if tipo is str:
        if isinstance(v, str):
            return v
        raise ConfigError(caminho, f"esperado texto, veio {type(v).__name__}")
    if tipo == "strs":
        if isinstance(v, list) and all(isinstance(x, str) for x in v):
            return tuple(v)
        raise ConfigError(caminho, "esperada lista de textos")
    if tipo == "tabela":
        if isinstance(v, dict):
            return dict(v)
        raise ConfigError(caminho, "esperada tabela")
    raise AssertionError(tipo)  # pragma: no cover


def _secao(nome: str, dados: Any) -> Any:
    classe, campos = _ESQUEMA[nome]
    if not isinstance(dados, dict):
        raise ConfigError(nome, "esperada tabela")
    for chave in dados:
        if chave not in campos:
            raise ConfigError(f"{nome}.{chave}", "chave desconhecida")
    valores: dict[str, Any] = {}
    for chave, (tipo, padrao, checar) in campos.items():
        caminho = f"{nome}.{chave}"
        if chave not in dados:
            if padrao is _OBRIGATORIA:
                raise ConfigError(caminho, "obrigatória")
            valores[chave] = padrao
            continue
        v = _converter(caminho, tipo, dados[chave])
        if checar is not None and (erro := checar(v)):
            raise ConfigError(caminho, erro)
        valores[chave] = v
    return classe(**valores)


def de_dict(dados: Mapping[str, Any]) -> AyanamiConfig:
    """Valida um dicionário já carregado (mesmas regras de :func:`ler`)."""
    for nome in dados:
        if nome not in _ESQUEMA:
            raise ConfigError(nome, "seção desconhecida")
    if "geral" not in dados:
        raise ConfigError("geral.url_base", "obrigatória")
    secoes = {nome: _secao(nome, dados[nome]) for nome in _ESQUEMA if nome in dados}
    cfg = AyanamiConfig(**secoes)
    # regras entre chaves
    if cfg.rede.offline_apos_s < 3 * cfg.rede.batimento_s:
        raise ConfigError(
            "rede.offline_apos_s",
            f"precisa ser ≥ 3 × rede.batimento_s ({3 * cfg.rede.batimento_s})",
        )
    if cfg.budget.teto_nuvem_usd > cfg.budget.teto_geral_usd:
        raise ConfigError("budget.teto_nuvem_usd", "maior que budget.teto_geral_usd")
    return cfg


def ler(caminho: str | os.PathLike[str] = CAMINHO_PADRAO) -> AyanamiConfig:
    """Lê e valida o ``ayanami.toml``. Qualquer problema → :class:`ConfigError` (a API não sobe)."""
    p = Path(caminho)
    try:
        with p.open("rb") as f:
            dados = tomllib.load(f)
    except FileNotFoundError as e:
        raise ConfigError(str(p), "arquivo não encontrado") from e
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(str(p), f"TOML inválido: {e}") from e
    return de_dict(dados)


# --------------------------------------------------------------------------- segredos (.env)

SEGREDOS_SEMPRE = ("POSTGRES_PASSWORD", "GEMINI_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
SEGREDOS_PUSH = ("VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "VAPID_SUB")
SEGREDOS_NUVEM_LLM = ("OPENAI_API_KEY",)
SEGREDOS_BACKUP = ("B2_ACCOUNT_ID", "B2_ACCOUNT_KEY", "B2_BUCKET", "RESTIC_PASSWORD")
NOMES_SEGREDOS = SEGREDOS_SEMPRE + SEGREDOS_NUVEM_LLM + SEGREDOS_PUSH + SEGREDOS_BACKUP


def segredos_obrigatorios(cfg: AyanamiConfig) -> tuple[str, ...]:
    """Nomes obrigatórios para as fases ligadas em ``cfg`` (spec §9.1)."""
    nomes = list(SEGREDOS_SEMPRE) + list(SEGREDOS_PUSH)
    if cfg.nuvem.ligado and cfg.budget.teto_nuvem_usd > 0:
        nomes += SEGREDOS_NUVEM_LLM
    if cfg.backup.ligado:
        nomes += SEGREDOS_BACKUP
    return tuple(nomes)


@dataclass(frozen=True)
class Segredos:
    """Segredos lidos por nome. ``repr``/``str`` mostram só nomes, nunca valores."""

    _valores: Mapping[str, str] = field(repr=False)
    faltando: tuple[str, ...] = ()

    def get(self, nome: str) -> str | None:
        return self._valores.get(nome)

    def __getitem__(self, nome: str) -> str:
        return self._valores[nome]

    def __contains__(self, nome: object) -> bool:
        return nome in self._valores

    @property
    def presentes(self) -> tuple[str, ...]:
        return tuple(sorted(self._valores))

    def __repr__(self) -> str:
        return f"Segredos(presentes={list(self.presentes)}, faltando={list(self.faltando)})"

    __str__ = __repr__


def _ler_env(caminho: Path) -> dict[str, str]:
    """Formato ``NOME=valor`` (``#`` comenta; aspas simples/duplas em volta são tiradas)."""
    saida: dict[str, str] = {}
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        nome, _, valor = linha.partition("=")
        nome = nome.removeprefix("export ").strip()
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "'\"":
            valor = valor[1:-1]
        saida[nome] = valor
    return saida


def ler_segredos(
    cfg: AyanamiConfig,
    arquivo: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> Segredos:
    """Lê só os nomes de :data:`NOMES_SEGREDOS`: do ``env`` (padrão ``os.environ``; no contêiner o
    Compose passa o ``.env`` por ``env_file``) e, por cima, do ``arquivo`` se dado. Valor vazio
    conta como faltando."""
    fonte: dict[str, str] = dict(os.environ if env is None else env)
    if arquivo is not None:
        fonte.update(_ler_env(Path(arquivo)))
    valores = {n: fonte[n] for n in NOMES_SEGREDOS if fonte.get(n)}
    faltando = tuple(n for n in segredos_obrigatorios(cfg) if n not in valores)
    return Segredos(valores, faltando)
