"""Quadros binários do elo: áudio do turno (spec §1.4).

Cabeçalho de 18 bytes — ``versao:u8`` (=1), ``tipo:u8`` (1 AUDIO_IN, 2 AUDIO_OUT, 3 AUDIO_FIM),
``turno:16 bytes`` (ULID binário) — seguido da carga PCM s16le mono (16 kHz na entrada, 24 kHz na
saída). AUDIO_FIM tem carga vazia. Carga acima de ``MAX_CARGA`` → ``EloError("tamanho")``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Final

from magi.elo.ids import de_bytes, para_bytes, valido
from magi.elo.mensagens import MAX_BINARIO_BYTES, EloError

VERSAO_QUADRO: Final = 1
CABECALHO: Final = 18
MAX_CARGA: Final = MAX_BINARIO_BYTES - CABECALHO  # 8174


class QuadroTipo(IntEnum):
    AUDIO_IN = 1
    AUDIO_OUT = 2
    AUDIO_FIM = 3


@dataclass(frozen=True, slots=True)
class Quadro:
    tipo: QuadroTipo
    turno: str  # ULID do turno
    pcm: bytes = b""


def _checa(tipo: QuadroTipo, pcm: bytes) -> None:
    if len(pcm) > MAX_CARGA:
        raise EloError("tamanho", f"carga {len(pcm)} > {MAX_CARGA} bytes")
    if tipo is QuadroTipo.AUDIO_FIM and pcm:
        raise EloError("campo", "AUDIO_FIM tem carga vazia")
    if len(pcm) % 2:
        raise EloError("campo", "PCM s16le precisa de número par de bytes")


def encode_quadro(q: Quadro) -> bytes:
    """``Quadro`` → bytes (cabeçalho + carga)."""
    tipo = QuadroTipo(q.tipo)
    if not valido(q.turno):
        raise EloError("campo", "turno não é ULID")
    _checa(tipo, q.pcm)
    return bytes((VERSAO_QUADRO, tipo)) + para_bytes(q.turno) + q.pcm


def decode_quadro(raw: bytes) -> Quadro:
    """Bytes → ``Quadro``. Versão ≠ 1 → ``"versao"``; tipo desconhecido → ``"tipo"``."""
    if len(raw) < CABECALHO:
        raise EloError("campo", "quadro menor que o cabeçalho")
    if raw[0] != VERSAO_QUADRO:
        raise EloError("versao", f"versão do quadro {raw[0]}")
    try:
        tipo = QuadroTipo(raw[1])
    except ValueError as e:
        raise EloError("tipo", f"tipo de quadro {raw[1]}") from e
    pcm = bytes(raw[CABECALHO:])
    _checa(tipo, pcm)
    turno = de_bytes(bytes(raw[2:CABECALHO]))
    if not valido(turno):
        raise EloError("campo", "turno não é ULID")
    return Quadro(tipo=tipo, turno=turno, pcm=pcm)
