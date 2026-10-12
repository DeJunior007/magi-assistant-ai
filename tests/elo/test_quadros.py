"""Quadros binários do elo: CA-Y3."""

from __future__ import annotations

import pytest

from magi.elo import ids
from magi.elo.mensagens import EloError
from magi.elo.quadros import CABECALHO, MAX_CARGA, Quadro, QuadroTipo, decode_quadro, encode_quadro

TURNO = ids.novo_id(agora_ms=lambda: 1_760_000_000_000, rng=lambda k: b"\x5a" * k)


@pytest.mark.parametrize(
    "q",
    [
        Quadro(QuadroTipo.AUDIO_IN, TURNO, b"\x01\x02" * 1280),  # 80 ms a 16 kHz
        Quadro(QuadroTipo.AUDIO_OUT, TURNO, b"\x00\xff" * (MAX_CARGA // 2)),
        Quadro(QuadroTipo.AUDIO_FIM, TURNO),
    ],
)
def test_ca_y3_ida_e_volta(q: Quadro) -> None:
    raw = encode_quadro(q)
    assert len(raw) == CABECALHO + len(q.pcm)
    assert raw[0] == 1 and raw[1] == q.tipo
    assert raw[2:18] == ids.para_bytes(TURNO)
    assert decode_quadro(raw) == q


def _codigo(raw: bytes) -> str:
    with pytest.raises(EloError) as e:
        decode_quadro(raw)
    return e.value.codigo


def test_ca_y3_carga_grande_recusada() -> None:
    assert MAX_CARGA == 8174
    with pytest.raises(EloError) as e:
        encode_quadro(Quadro(QuadroTipo.AUDIO_IN, TURNO, b"\x00" * 8175))
    assert e.value.codigo == "tamanho"
    cabeca = bytes((1, 1)) + ids.para_bytes(TURNO)
    assert _codigo(cabeca + b"\x00" * 8175) == "tamanho"


def test_ca_y3_versao_2_recusada() -> None:
    raw = bytearray(encode_quadro(Quadro(QuadroTipo.AUDIO_IN, TURNO, b"\x00\x00")))
    raw[0] = 2
    assert _codigo(bytes(raw)) == "versao"


def test_quadro_malformado() -> None:
    ok = encode_quadro(Quadro(QuadroTipo.AUDIO_FIM, TURNO))
    assert _codigo(ok[:10]) == "campo"
    assert _codigo(bytes((1, 9)) + ok[2:]) == "tipo"
    assert _codigo(ok + b"\x00\x00") == "campo"  # AUDIO_FIM com carga
    with pytest.raises(EloError):
        encode_quadro(Quadro(QuadroTipo.AUDIO_IN, "x", b""))
