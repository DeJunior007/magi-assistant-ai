"""Contrato do elo (spec §1): ids, mensagens, quadros binários, ponte com ``contracts`` e receptor.

Núcleo puro, sem I/O de rede. Cliente (``cliente.py``) e ``RemoteLink`` (``remote.py``) ficam fora.
"""

from magi.elo.ids import novo_id, valido
from magi.elo.mensagens import (
    VERSAO,
    Corpo,
    EloError,
    Envelope,
    Tipo,
    decode,
    encode,
    responder,
)
from magi.elo.quadros import Quadro, QuadroTipo, decode_quadro, encode_quadro

__all__ = [
    "VERSAO",
    "Corpo",
    "EloError",
    "Envelope",
    "Quadro",
    "QuadroTipo",
    "Tipo",
    "decode",
    "decode_quadro",
    "encode",
    "encode_quadro",
    "novo_id",
    "responder",
    "valido",
]
