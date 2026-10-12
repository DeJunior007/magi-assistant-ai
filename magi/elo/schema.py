"""JSON Schema do elo, gerado dos dataclasses de ``mensagens.py`` (spec §1).

``python -m magi.elo.schema > ayanami/app/elo.schema.json`` — saída determinística (chaves
ordenadas), usada pelo PWA. Os campos desconhecidos são permitidos (compatibilidade para frente).
"""

from __future__ import annotations

import dataclasses
import json
import sys
import types
import typing
from collections.abc import Mapping
from datetime import datetime
from enum import Enum
from typing import Any

from magi.elo import mensagens as m
from magi.elo.ids import ULID_RE
from magi.elo.quadros import CABECALHO, MAX_CARGA


def _ref(nome: str) -> dict[str, Any]:
    return {"$ref": f"#/$defs/{nome}"}


def _tipo(tp: Any, defs: dict[str, Any]) -> dict[str, Any]:  # noqa: PLR0911
    if tp is Any:
        return {}
    origem = typing.get_origin(tp)
    if origem is typing.Union or origem is types.UnionType:
        return {"anyOf": [_tipo(a, defs) for a in typing.get_args(tp)]}
    if tp is type(None):
        return {"type": "null"}
    if origem is tuple:
        args = typing.get_args(tp)
        if len(args) == 2 and args[1] is Ellipsis:
            return {"type": "array", "items": _tipo(args[0], defs)}
        return {
            "type": "array",
            "prefixItems": [_tipo(a, defs) for a in args],
            "minItems": len(args),
            "maxItems": len(args),
        }
    if origem is Mapping or origem is dict:
        return {"type": "object", "additionalProperties": _tipo(typing.get_args(tp)[1], defs)}
    if tp is bool:
        return {"type": "boolean"}
    if tp is int:
        return {"type": "integer"}
    if tp is float:
        return {"type": "number"}
    if tp is str:
        return {"type": "string"}
    if tp is datetime:
        return {"type": "string", "format": "date-time"}
    if isinstance(tp, type) and issubclass(tp, Enum):
        defs.setdefault(tp.__name__, {"enum": [e.value for e in tp]})
        return _ref(tp.__name__)
    if isinstance(tp, type) and dataclasses.is_dataclass(tp):
        if tp.__name__ not in defs:
            defs[tp.__name__] = {}  # reserva (recursão)
            dicas = typing.get_type_hints(tp)
            campos = dataclasses.fields(tp)
            props = {f.name: _tipo(dicas[f.name], defs) for f in campos}
            obrig = [
                f.name
                for f in campos
                if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING
            ]
            d: dict[str, Any] = {"type": "object", "properties": props}
            if obrig:
                d["required"] = obrig
            defs[tp.__name__] = d
        return _ref(tp.__name__)
    raise TypeError(f"tipo sem schema: {tp!r}")  # pragma: no cover


def gerar() -> dict[str, Any]:
    """O JSON Schema (2020-12) do envelope do elo."""
    defs: dict[str, Any] = {}
    nome = {"type": "string", "pattern": m.NOME_RE.pattern}
    ulid = {"type": "string", "pattern": ULID_RE.pattern}
    ramos = []
    for t, cls in m.CORPOS.items():
        ramos.append(
            {
                "if": {"properties": {"t": {"const": t.value}}, "required": ["t"]},
                "then": {"properties": {"corpo": _tipo(cls, defs)}},
            }
        )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "magi-elo-v1",
        "title": "Envelope do elo (magi/elo, spec §1)",
        "description": (
            f"Uma mensagem por frame de texto, ≤ {m.MAX_TEXTO_BYTES} bytes. Quadros binários de áudio: "
            f"cabeçalho de {CABECALHO} bytes (versao u8=1, tipo u8 1=AUDIO_IN 2=AUDIO_OUT 3=AUDIO_FIM, "
            f"turno ULID 16 bytes) + carga PCM s16le ≤ {MAX_CARGA} bytes."
        ),
        "type": "object",
        "required": ["v", "t", "id", "de", "para", "ts", "corpo"],
        "properties": {
            "v": {"const": m.VERSAO},
            "t": {"enum": [t.value for t in m.Tipo]},
            "id": ulid,
            "de": nome,
            "para": nome,
            "ts": {"type": "string", "format": "date-time"},
            "resp": {"anyOf": [ulid, {"type": "null"}]},
            "corpo": {"type": "object"},
        },
        "allOf": ramos,
        "$defs": defs,
    }


def texto() -> str:
    """Schema serializado (determinístico, com ``\\n`` no fim)."""
    return json.dumps(gerar(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> None:
    sys.stdout.write(texto())


if __name__ == "__main__":
    main()
