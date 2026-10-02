"""Provedores por tarefa (tarefa 3.1): registro, rodízio de chaves e adaptadores."""

from magi.providers.keypool import FreeQuotaExhausted, KeyRejected, RotatingKeyPool
from magi.providers.registry import BACKENDS, Registry

__all__ = ["BACKENDS", "FreeQuotaExhausted", "KeyRejected", "Registry", "RotatingKeyPool"]
