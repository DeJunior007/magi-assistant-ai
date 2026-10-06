"""``magi-clean``: faxina diária do Docker (unit ``magi-clean.service``, timer diário).

Só apaga o que é descartável e volta sozinho quando precisar:

- **cache de build** (``docker builder prune``): o com mais de ``keep_hours`` (padrão 7 dias); se
  o disco passar de ``aggressive_pct`` (padrão 90%), todo o cache;
- **imagens órfãs** (``docker image prune``, sem ``-a``): as ``<none>`` que sobraram de builds.

**Nunca** mexe em volumes (bancos e arquivos de projetos), containers ou imagens com nome.

O resultado vai para ``<data_dir>/cleanup_state.json``; o ``AlertMonitor`` do núcleo lê esse
arquivo e a Magui avisa por voz quando a faxina liberou algo que valha (``announce_min_gb``).
Sem Docker (ou com ele parado), registra e sai sem erro.

Config (``[cleanup]``, opcional)::

    [cleanup]
    enabled = true
    keep_hours = 168        # cache de build mais novo que isso fica
    aggressive_pct = 90     # disco acima disso: limpa todo o cache de build
    path = "/"              # disco medido
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from magi.common.config import Config, ConfigError, load_config

log = logging.getLogger("magi.clean")

STATE_FILE = "cleanup_state.json"
TIMEOUT_S = 600
_UNITS = {"B": 1, "KB": 10**3, "MB": 10**6, "GB": 10**9, "TB": 10**12,
          "KIB": 2**10, "MIB": 2**20, "GIB": 2**30, "TIB": 2**40}
_RECLAIMED_RE = re.compile(r"Total(?: reclaimed space)?:\s*([\d.]+)\s*([KMGT]?i?B)", re.I)


@dataclass(frozen=True, slots=True)
class CleanupConfig:
    enabled: bool = True
    keep_hours: int = 168
    aggressive_pct: float = 90.0
    path: str = "/"

    @classmethod
    def from_raw(cls, raw: Mapping[str, Any] | None) -> CleanupConfig:
        raw = dict(raw or {})
        try:
            cfg = cls(
                enabled=bool(raw.get("enabled", True)),
                keep_hours=int(raw.get("keep_hours", 168)),
                aggressive_pct=float(raw.get("aggressive_pct", 90.0)),
                path=str(raw.get("path", "/")),
            )
        except (TypeError, ValueError) as e:
            raise ConfigError(f"[cleanup] inválido: {e}") from e
        if cfg.keep_hours < 0 or not 0 < cfg.aggressive_pct <= 100:
            raise ConfigError("[cleanup]: keep_hours >= 0 e 0 < aggressive_pct <= 100")
        return cfg


@dataclass(frozen=True, slots=True)
class CleanupResult:
    at: str  # ISO 8601, UTC
    mode: str  # routine | aggressive | skipped
    freed_bytes: int
    used_pct_before: float
    free_bytes_after: int
    announced: bool = False
    note: str = ""


def parse_reclaimed(output: str) -> int:
    """Bytes do "Total reclaimed space: 1.23GB" (ou "Total: 1.2GB") do ``docker * prune``."""
    total = 0
    for value, unit in _RECLAIMED_RE.findall(output):
        total += round(float(value) * _UNITS[unit.upper()])
    return total


def plan(used_pct: float, cfg: CleanupConfig) -> tuple[str, list[list[str]]]:
    """Modo e comandos ``docker`` a rodar (nunca volumes nem imagens com nome)."""
    aggressive = used_pct >= cfg.aggressive_pct
    builder = ["docker", "builder", "prune", "-f"]
    if not aggressive and cfg.keep_hours > 0:
        builder += ["--filter", f"until={cfg.keep_hours}h"]
    return ("aggressive" if aggressive else "routine"), [builder, ["docker", "image", "prune", "-f"]]


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _run(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(cmd), capture_output=True, text=True, timeout=TIMEOUT_S, check=False)


def disk(path: str) -> tuple[float, int]:
    """(% usado, bytes livres) de ``path``."""
    u = shutil.disk_usage(path)
    return u.used / u.total * 100, u.free


def clean(cfg: CleanupConfig, *, runner: Runner = _run, usage: Callable[[str], tuple[float, int]] = disk,
          now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> CleanupResult:
    used, _free = usage(cfg.path)
    at = now().isoformat()
    mode, cmds = plan(used, cfg)
    freed = 0
    notes = []
    for cmd in cmds:
        try:
            proc = runner(cmd)
        except (OSError, subprocess.TimeoutExpired) as e:
            notes.append(f"{' '.join(cmd[1:3])}: {type(e).__name__}")
            continue
        if proc.returncode != 0:
            notes.append(f"{' '.join(cmd[1:3])}: {(proc.stderr or proc.stdout).strip()[:120]}")
            continue
        freed += parse_reclaimed(proc.stdout)
    _used_after, free_after = usage(cfg.path)
    return CleanupResult(at, mode, freed, round(used, 1), free_after, note="; ".join(notes))


def save(result: CleanupResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(result), ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def load(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config: Config | None
    try:
        config = load_config()
    except Exception as e:  # noqa: BLE001 - sem config: padrões
        log.warning("config indisponível (%s); usando os padrões", e)
        config = None
    raw = config.raw.get("cleanup") if config is not None else None
    cfg = CleanupConfig.from_raw(raw if isinstance(raw, dict) else None)
    if not cfg.enabled:
        log.info("faxina desligada em [cleanup]")
        return 0
    data_dir = config.paths.data_dir if config is not None else Path("~/.local/share/magi").expanduser()
    if shutil.which("docker") is None:
        used, free = disk(cfg.path)
        result = CleanupResult(datetime.now(UTC).isoformat(), "skipped", 0, round(used, 1), free,
                               note="docker não instalado")
    else:
        result = clean(cfg)
    save(result, data_dir / STATE_FILE)
    log.info("faxina %s: liberou %.2f GB (disco estava em %.1f%%, livres agora %.1f GB)%s", result.mode,
             result.freed_bytes / 1e9, result.used_pct_before, result.free_bytes_after / 1e9,
             f"; {result.note}" if result.note else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
