"""Leitura do ``config.toml`` com recarga ao salvar (design §2, §4.7; Req. 21.1, 21.4).

O arquivo guarda só *nomes* de chaves (que apontam para o keyring), nunca as chaves.
Caminho: ``$MAGI_CONFIG`` ou ``$XDG_CONFIG_HOME/magi/config.toml`` (padrão ``~/.config``).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import tomllib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

ENV_VAR = "MAGI_CONFIG"
DEFAULT_DSN = "postgresql://magi:magi@127.0.0.1:54329/magi"
TASK_NAMES = ("stt", "tts", "agent", "vision", "embeddings", "search", "news")

# Nome de chave no keyring: curto, sem espaços. Algo com cara de chave de API é recusado.
_KEY_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SECRET_LIKE_RE = re.compile(r"^(sk-|sk_|AIza|xai-|gsk_|ya29\.)|^[A-Za-z0-9_-]{32,}$")
_FORBIDDEN_FIELDS = {"api_key", "apikey", "key", "secret", "token", "password", "client_secret"}


class ConfigError(ValueError):
    """Configuração inválida ou com segredo em texto puro."""


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    keys: tuple[str, ...]
    free_tier: bool = False
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskConfig:
    name: str
    provider: str
    model: str
    options: dict[str, Any] = field(default_factory=dict)  # ex.: voice do TTS


@dataclass(frozen=True)
class BudgetConfig:
    monthly_usd: float = 5.0


@dataclass(frozen=True)
class DatabaseConfig:
    dsn: str = DEFAULT_DSN


@dataclass(frozen=True)
class PathsConfig:
    data_dir: Path = Path("~/.local/share/magi").expanduser()
    cache_dir: Path = Path("~/.cache/magi").expanduser()


@dataclass(frozen=True)
class Config:
    providers: dict[str, ProviderConfig]
    tasks: dict[str, TaskConfig]
    budget: BudgetConfig = BudgetConfig()
    database: DatabaseConfig = DatabaseConfig()
    paths: PathsConfig = PathsConfig()
    source: Path | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def task(self, name: str) -> TaskConfig:
        try:
            return self.tasks[name]
        except KeyError:
            raise ConfigError(f"tarefa '{name}' não configurada em [tasks]") from None

    def provider_for(self, task: str) -> ProviderConfig:
        return self.providers[self.task(task).provider]

    def key_names(self) -> list[str]:
        """Todos os nomes de chave citados em [providers.*], sem repetição."""
        seen: dict[str, None] = {}
        for p in self.providers.values():
            for k in p.keys:
                seen.setdefault(k, None)
        return list(seen)


def config_path() -> Path:
    env = os.environ.get(ENV_VAR)
    if env:
        return Path(env).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or "~/.config"
    return Path(base).expanduser() / "magi" / "config.toml"


def _check_key_name(provider: str, name: Any) -> str:
    if not isinstance(name, str) or not _KEY_NAME_RE.match(name):
        raise ConfigError(f"providers.{provider}.keys: nome de chave inválido: {name!r}")
    if _SECRET_LIKE_RE.search(name):
        raise ConfigError(
            f"providers.{provider}.keys parece conter uma chave de API; guarde-a com "
            f"`magi-keys add <nome>` e use só o nome aqui"
        )
    return name


def _reject_secrets(section: str, data: dict[str, Any]) -> None:
    for k in data:
        if k.lower() in _FORBIDDEN_FIELDS:
            raise ConfigError(f"{section}.{k}: segredos não vão no config; use `magi-keys add <nome>`")


def parse_config(data: dict[str, Any], source: Path | None = None) -> Config:
    providers: dict[str, ProviderConfig] = {}
    for name, p in (data.get("providers") or {}).items():
        if not isinstance(p, dict):
            raise ConfigError(f"providers.{name} deve ser uma tabela")
        _reject_secrets(f"providers.{name}", p)
        keys = p.get("keys", [])
        if not isinstance(keys, list):
            raise ConfigError(f"providers.{name}.keys deve ser uma lista de nomes")
        opts = {k: v for k, v in p.items() if k not in ("keys", "free_tier")}
        providers[name] = ProviderConfig(
            name=name,
            keys=tuple(_check_key_name(name, k) for k in keys),
            free_tier=bool(p.get("free_tier", False)),
            options=opts,
        )

    tasks: dict[str, TaskConfig] = {}
    for name, t in (data.get("tasks") or {}).items():
        if not isinstance(t, dict) or "provider" not in t or "model" not in t:
            raise ConfigError(f"tasks.{name} precisa de provider e model")
        _reject_secrets(f"tasks.{name}", t)
        if t["provider"] not in providers:
            raise ConfigError(f"tasks.{name}: provedor '{t['provider']}' não está em [providers]")
        opts = {k: v for k, v in t.items() if k not in ("provider", "model")}
        tasks[name] = TaskConfig(name=name, provider=t["provider"], model=str(t["model"]), options=opts)

    b = data.get("budget") or {}
    budget = BudgetConfig(monthly_usd=float(b.get("monthly_usd", BudgetConfig.monthly_usd)))
    if budget.monthly_usd < 0:
        raise ConfigError("budget.monthly_usd não pode ser negativo")

    db = data.get("database") or {}
    _reject_secrets("database", db)
    database = DatabaseConfig(dsn=str(db.get("dsn", DEFAULT_DSN)))

    pa = data.get("paths") or {}
    defaults = PathsConfig()
    paths = PathsConfig(
        data_dir=Path(pa["data_dir"]).expanduser() if "data_dir" in pa else defaults.data_dir,
        cache_dir=Path(pa["cache_dir"]).expanduser() if "cache_dir" in pa else defaults.cache_dir,
    )

    return Config(
        providers=providers,
        tasks=tasks,
        budget=budget,
        database=database,
        paths=paths,
        source=source,
        raw=data,
    )


def load_config(path: str | os.PathLike[str] | None = None) -> Config:
    p = Path(path).expanduser() if path is not None else config_path()
    try:
        with p.open("rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        raise ConfigError(f"config não encontrado: {p} (copie config.example.toml)") from None
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{p}: TOML inválido: {e}") from e
    return parse_config(data, source=p)


ReloadCallback = Callable[[Config], Awaitable[None] | None]


class ConfigWatcher:
    """Mantém a config atual e recarrega quando o arquivo é salvo.

    Observa o diretório (editores salvam por rename) e filtra pelo nome do arquivo.
    Se a nova versão for inválida, registra o erro e mantém a anterior.
    """

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(path).expanduser() if path is not None else config_path()
        self.current: Config = load_config(self.path)
        self._callbacks: list[ReloadCallback] = []

    def on_reload(self, cb: ReloadCallback) -> ReloadCallback:
        self._callbacks.append(cb)
        return cb

    async def reload(self) -> bool:
        try:
            new = load_config(self.path)
        except ConfigError as e:
            log.error("recarga do config ignorada: %s", e)
            return False
        self.current = new
        log.info("config recarregado de %s", self.path)
        for cb in list(self._callbacks):
            try:
                res = cb(new)
                if asyncio.iscoroutine(res):
                    await res
            except Exception:
                log.exception("callback de recarga do config falhou")
        return True

    async def run(self, stop_event: asyncio.Event | None = None) -> None:
        from watchfiles import awatch

        target = self.path.resolve()
        async for changes in awatch(target.parent, stop_event=stop_event, debounce=200):
            if any(Path(p).resolve() == target for _, p in changes) and target.exists():
                await self.reload()
