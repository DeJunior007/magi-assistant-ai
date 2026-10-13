"""Credenciais do PC para falar com a Ayanami (helper único: news-sync, backup, ``RemoteLink``).

- ``url_ayanami(cfg)``: ``[ayanami] url`` do ``config.toml`` (sem barra final) ou ``None``.
  ``cfg`` pode ser o dicionário cru do TOML ou um ``magi.common.config.Config`` (usa ``.raw``).
- ``token_pc()``: token do PC no keyring (serviço ``magi``, nome ``ayanami_pc``); recaída no
  arquivo ``ayanami.token`` ao lado do ``config.toml`` (``0600``, fora do git). Nunca vai a log.

Só biblioteca padrão no topo (o ``keyring`` é importado na chamada).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

KEYRING_SERVICO = "magi"
KEYRING_NOME = "ayanami_pc"
TOKEN_FILE = "ayanami.token"


def url_ayanami(cfg: Any) -> str | None:
    raw = cfg if isinstance(cfg, Mapping) else getattr(cfg, "raw", None)
    if not isinstance(raw, Mapping):
        return None
    ay = raw.get("ayanami")
    url = ay.get("url") if isinstance(ay, Mapping) else None
    return url.strip().rstrip("/") if isinstance(url, str) and url.strip() else None


def _keyring_get(servico: str, nome: str) -> str | None:
    import keyring

    return keyring.get_password(servico, nome)


def _dir_config() -> Path:
    from magi.common.config import config_path

    return config_path().parent


def token_pc(
    config_dir: Path | None = None,
    *,
    keyring_get: Callable[[str, str], str | None] | None = None,
) -> str | None:
    """Keyring ``magi``/``ayanami_pc`` primeiro; depois ``<config_dir>/ayanami.token``."""
    try:
        tok = (keyring_get or _keyring_get)(KEYRING_SERVICO, KEYRING_NOME)
        if tok and tok.strip():
            return tok.strip()
    except Exception as e:  # noqa: BLE001 - keyring sem backend, D-Bus fora etc.
        log.debug("keyring indisponível: %s", type(e).__name__)
    arq = (config_dir or _dir_config()) / TOKEN_FILE
    try:
        modo = arq.stat().st_mode & 0o777
        tok = arq.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except OSError as e:
        log.warning("%s ilegível: %s", arq, type(e).__name__)
        return None
    if modo & 0o077:
        log.warning("%s com permissão %o; use chmod 600", arq, modo)
    return tok or None


__all__ = ["KEYRING_NOME", "KEYRING_SERVICO", "TOKEN_FILE", "token_pc", "url_ayanami"]
