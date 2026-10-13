"""``magi-backup``: backup diário do PC empurrado à Ayanami (ayanami-central spec §7.1, R4.1, R4.2).

Disparado por ``magi-backup.timer`` (03:30, ``Persistent=true``, ``OnStartupSec=10min``)::

    docker exec magi-pg pg_dump -Fc -U magi -d magi            > $TMP/magi-pg.dump   (só leitura)
    docker exec magi-pg psql -U magi -d magi -Atc "SELECT count(*) FROM <t>"  → manifesto.json
    tar de ~/.config/magi sem *.token / *key* / *secret*        → $TMP/config.tar
    tar magi-pg.dump manifesto.json config.tar | zstd -10      → $TMP/magi-AAAA-MM-DD.tar.zst
    PUT /v1/backup/pc (X-Sha256, X-Data, X-Manifesto)           → apaga $TMP no fim, sempre

Contra o ``magi-pg`` só ``pg_dump`` (dump e ``--version``) e ``psql -Atc "SELECT count(*) …"``
(spec §7.3); nada de ``DROP``/``TRUNCATE``/``--clean``. ``409`` (mesma data já recebida e íntegra)
→ sai 0. Rede fora, ``5xx`` ou sha256 recusado (``400``) → até 3 novas tentativas depois de 1, 5 e
15 min (``dormir`` injetado). ``401``/``403``/``413`` não adiantam repetir.

Config (``config.toml``)::

    [ayanami]
    url = "https://ayanami.<tailnet>.ts.net"
    # token do PC (escopo ``backup``): ``ayanami.token`` ao lado do config.toml (0600, fora do git)

Sem ``[ayanami] url`` ou sem o token o backup fica desligado (sai 0, só registra). O resultado vai
para ``<data_dir>/backup_state.json`` (``resultado``: ``ok``, ``ja_recebido``, ``falhou`` ou
``desligado``) — o mesmo canal do ``magi-clean``: o núcleo lê o arquivo e põe o card "backup não
subiu" no HUD.
"""

from __future__ import annotations

import argparse
import base64
import fnmatch
import hashlib
import json
import logging
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import httpx

log = logging.getLogger("magi.elo.backup")

CONTAINER = "magi-pg"
PG_USUARIO = "magi"
PG_BASE = "magi"
TABELAS = ("turns", "memories", "costs", "news_items", "taste", "learning_sessions")
EXCLUIR = ("*.token", "*key*", "*secret*")
ESPERAS_S = (60.0, 300.0, 900.0)  # 1, 5 e 15 min entre as tentativas
STATE_FILE = "backup_state.json"
TOKEN_FILE = "ayanami.token"
ROTA = "/v1/backup/pc"
_REPETE = {400, 408, 425, 429}  # além de 5xx e erro de rede


@dataclass(frozen=True)
class Resultado:
    codigo: int
    texto: str = ""


class Executor(Protocol):
    """Roda ``cmd``; com ``saida``, o stdout vai para esse arquivo (binário) em vez de ``texto``."""

    def __call__(self, cmd: Sequence[str], saida: Path | None = None) -> Resultado: ...


def executor_real(cmd: Sequence[str], saida: Path | None = None) -> Resultado:
    if saida is not None:
        with saida.open("wb") as f:
            p = subprocess.run(list(cmd), stdout=f, stderr=subprocess.PIPE, check=False)
        return Resultado(p.returncode, p.stderr.decode("utf-8", "replace").strip())
    p = subprocess.run(list(cmd), capture_output=True, text=True, check=False)
    return Resultado(p.returncode, p.stdout if p.returncode == 0 else p.stderr.strip())


class BackupErro(Exception):
    pass


@dataclass(frozen=True)
class BackupConfig:
    url: str | None
    token: str | None
    config_dir: Path
    data_dir: Path
    tmp_base: Path | None = None  # None: ~/.cache/magi (o /tmp do Fedora é tmpfs)
    timeout_s: float = 600.0


@dataclass
class Estado:
    quando: str
    resultado: str
    data: str | None = None
    tamanho: int | None = None
    sha256: str | None = None
    tentativas: int = 0
    erro: str | None = None
    tabelas: dict[str, int | None] = field(default_factory=dict)


# --- montagem -------------------------------------------------------------------------------------


def _docker_pg(*args: str) -> list[str]:
    return ["docker", "exec", CONTAINER, *args]


def cmd_dump() -> list[str]:
    return _docker_pg("pg_dump", "-Fc", "-U", PG_USUARIO, "-d", PG_BASE)


def cmd_versao() -> list[str]:
    return _docker_pg("pg_dump", "--version")


def cmd_contagem(tabela: str) -> list[str]:
    if tabela not in TABELAS:  # nunca SQL montado com nome de fora
        raise ValueError(tabela)
    return _docker_pg("psql", "-U", PG_USUARIO, "-d", PG_BASE, "-Atc", f"SELECT count(*) FROM {tabela}")


def excluido(nome: str) -> bool:
    """Igual ao ``tar --exclude``: o padrão casa com qualquer componente do caminho."""
    return any(fnmatch.fnmatch(parte, pad) for parte in Path(nome).parts for pad in EXCLUIR)


def tar_config(config_dir: Path, destino: Path) -> list[str]:
    """``tar -C ~/.config … -cf - magi`` em Python; devolve os nomes que entraram."""
    nomes: list[str] = []

    def filtro(ti: tarfile.TarInfo) -> tarfile.TarInfo | None:
        if excluido(ti.name) or not (ti.isfile() or ti.isdir()):
            return None
        nomes.append(ti.name)
        return ti

    with tarfile.open(destino, "w") as tar:
        if config_dir.is_dir():
            tar.add(config_dir, arcname="magi", filter=filtro)
    return nomes


def manifesto(executor: Executor, data: str) -> dict[str, Any]:
    r = executor(cmd_versao())
    versao = r.texto.strip().rsplit(" ", 1)[-1] if r.codigo == 0 and r.texto.strip() else None
    tabelas: dict[str, int | None] = {}
    for t in TABELAS:
        r = executor(cmd_contagem(t))
        try:
            tabelas[t] = int(r.texto.strip()) if r.codigo == 0 else None
        except ValueError:
            tabelas[t] = None
        if tabelas[t] is None:
            log.warning("contagem de %s indisponível", t)
    return {"data": data, "pg_versao": versao, "tabelas": tabelas}


def montar(executor: Executor, tmp: Path, config_dir: Path, data: str) -> tuple[Path, dict[str, Any]]:
    """Monta ``magi-<data>.tar.zst`` em ``tmp``; devolve o caminho e o manifesto."""
    dump = tmp / "magi-pg.dump"
    r = executor(cmd_dump(), dump)
    if r.codigo != 0 or not dump.exists() or dump.stat().st_size == 0:
        raise BackupErro(f"pg_dump falhou ({r.codigo}): {r.texto[:200]}")
    man = manifesto(executor, data)
    (tmp / "manifesto.json").write_text(json.dumps(man, ensure_ascii=False), encoding="utf-8")
    tar_config(config_dir, tmp / "config.tar")
    pacote = tmp / f"magi-{data}.tar"
    with tarfile.open(pacote, "w") as tar:
        for nome in ("magi-pg.dump", "manifesto.json", "config.tar"):
            tar.add(tmp / nome, arcname=nome)
    for nome in ("magi-pg.dump", "config.tar"):
        (tmp / nome).unlink()
    zst = tmp / f"magi-{data}.tar.zst"
    r = executor(["zstd", "-10", "-q", "-f", "-o", str(zst), str(pacote)])
    if r.codigo != 0 or not zst.exists():
        raise BackupErro(f"zstd falhou ({r.codigo}): {r.texto[:200]}")
    pacote.unlink()
    return zst, man


def sha256_arquivo(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


# --- envio ----------------------------------------------------------------------------------------


def enviar(
    cliente: httpx.Client,
    cfg: BackupConfig,
    arquivo: Path,
    data: str,
    man: dict[str, Any],
    sha: str,
    dormir: Callable[[float], None],
) -> tuple[str, int, str | None]:
    """``PUT /v1/backup/pc`` com até 3 repetições. Devolve ``(resultado, tentativas, erro)``."""
    assert cfg.url and cfg.token
    cab = {
        "Authorization": f"Bearer {cfg.token}",
        "Content-Type": "application/zstd",
        "Content-Length": str(arquivo.stat().st_size),
        "X-Sha256": sha,
        "X-Data": data,
        "X-Manifesto": base64.b64encode(json.dumps(man, ensure_ascii=False).encode()).decode("ascii"),
    }
    url = cfg.url.rstrip("/") + ROTA
    erro: str | None = None
    for i in range(len(ESPERAS_S) + 1):
        if i:
            log.info("nova tentativa em %.0f s", ESPERAS_S[i - 1])
            dormir(ESPERAS_S[i - 1])
        try:
            with arquivo.open("rb") as f:
                resp = cliente.put(url, content=f, headers=cab, timeout=cfg.timeout_s)
        except httpx.HTTPError as e:
            erro = f"rede: {type(e).__name__}"
            log.warning("envio falhou (%s)", erro)
            continue
        if resp.status_code in (200, 201):
            return "ok", i + 1, None
        if resp.status_code == 409:
            log.info("backup de %s já estava na Ayanami", data)
            return "ja_recebido", i + 1, None
        erro = f"HTTP {resp.status_code}"
        log.warning("Ayanami respondeu %s", resp.status_code)
        if resp.status_code < 500 and resp.status_code not in _REPETE:
            return "falhou", i + 1, erro
    return "falhou", len(ESPERAS_S) + 1, erro


def salvar_estado(est: Estado, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(est), ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def executar(
    cfg: BackupConfig,
    *,
    executor: Executor = executor_real,
    cliente: httpx.Client | None = None,
    dormir: Callable[[float], None] = time.sleep,
    agora: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    """Roda um backup; grava ``backup_state.json``. 0 = ok/já recebido/desligado, 1 = falhou."""
    momento = agora()
    est = Estado(quando=momento.isoformat(), resultado="desligado")
    estado_path = cfg.data_dir / STATE_FILE
    if not cfg.url or not cfg.token:
        est.erro = "sem [ayanami] url" if not cfg.url else f"sem {TOKEN_FILE}"
        log.info("backup desligado: %s", est.erro)
        salvar_estado(est, estado_path)
        return 0
    data = momento.astimezone().date().isoformat()
    est.data = data
    base = cfg.tmp_base or Path(os.environ.get("XDG_CACHE_HOME", "~/.cache")).expanduser() / "magi"
    base.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="magi-backup-", dir=base))
    proprio = cliente is None
    http = cliente or httpx.Client()
    try:
        zst, man = montar(executor, tmp, cfg.config_dir, data)
        est.tabelas = man["tabelas"]
        est.tamanho = zst.stat().st_size
        est.sha256 = sha256_arquivo(zst)
        est.resultado, est.tentativas, est.erro = enviar(http, cfg, zst, data, man, est.sha256, dormir)
    except Exception as e:  # noqa: BLE001 - qualquer falha vira card, nunca traceback com segredo
        est.resultado, est.erro = "falhou", f"{type(e).__name__}: {e}"[:300]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        if proprio:
            http.close()
    salvar_estado(est, estado_path)
    if est.resultado == "falhou":
        log.error("backup não subiu: %s", est.erro)
        return 1
    log.info("backup %s: %s (%s bytes)", data, est.resultado, est.tamanho)
    return 0


# --- linha de comando -----------------------------------------------------------------------------


def config_de(raw: dict[str, Any], config_dir: Path, data_dir: Path) -> BackupConfig:
    ay = raw.get("ayanami")
    ay = ay if isinstance(ay, dict) else {}
    url = ay.get("url") if isinstance(ay.get("url"), str) and ay.get("url") else None
    token: str | None = None
    try:
        token = (config_dir / TOKEN_FILE).read_text(encoding="utf-8").strip() or None
    except OSError:
        token = None
    return BackupConfig(url=url, token=token, config_dir=config_dir, data_dir=data_dir)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="magi-backup", description="Backup do PC para a Ayanami (spec §7.1).")
    ap.add_argument("--config", help="caminho do config.toml")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # a URL não leva token, mas fica quieto
    from magi.common.config import ConfigError, config_path, load_config

    raw: dict[str, Any] = {}
    data_dir = Path("~/.local/share/magi").expanduser()
    caminho = Path(a.config).expanduser() if a.config else config_path()
    try:
        c = load_config(caminho)
        raw, data_dir = c.raw, c.paths.data_dir
    except ConfigError as e:
        log.warning("config indisponível (%s); backup desligado", e)
    return executar(config_de(raw, caminho.parent, data_dir))


if __name__ == "__main__":
    raise SystemExit(main())
