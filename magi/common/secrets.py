"""Chaves de API no chaveiro do sistema (keyring / Secret Service do KDE) — Req. 21.4.

O config só cita nomes (ex.: ``openai-1``); o valor fica no keyring sob o serviço
``magi-assistant``. Nada aqui grava segredos em arquivo.
"""

from __future__ import annotations

import re

import keyring
from keyring.errors import PasswordDeleteError

SERVICE = "magi-assistant"
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class SecretError(RuntimeError):
    pass


def _check(name: str) -> str:
    if not _NAME_RE.match(name or ""):
        raise SecretError(f"nome de chave inválido: {name!r} (use letras, números, '.', '_' ou '-')")
    return name


def set_secret(name: str, value: str) -> None:
    value = value.strip()
    if not value:
        raise SecretError("valor vazio")
    keyring.set_password(SERVICE, _check(name), value)


def get_secret(name: str) -> str | None:
    return keyring.get_password(SERVICE, _check(name))


def require_secret(name: str) -> str:
    value = get_secret(name)
    if not value:
        raise SecretError(f"chave '{name}' não está no keyring; rode `magi-keys add {name}`")
    return value


def has_secret(name: str) -> bool:
    return bool(get_secret(name))


def delete_secret(name: str) -> bool:
    """Remove a chave. Retorna False se ela não existia."""
    try:
        keyring.delete_password(SERVICE, _check(name))
    except PasswordDeleteError:
        return False
    return True
