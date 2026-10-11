"""Cenários do tema Roleplay (tarefa LI4.1; D5; design imersivo §9; spec imersivo §12).

Um arquivo de dados por cenário em ``prompts/scenarios/<id>.md``: cabeçalho ``key: value``
(``title``, ``role``, ``setting``, ``goal``, ``twist``) até a primeira linha vazia, depois o texto
livre para a Condessa (≤ ``BODY_MAX`` caracteres). Puro: só lê arquivo, nada de LLM nem rede.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

__all__ = ["BODY_MAX", "FILE_MAX", "KEYS", "SCENARIOS_DIR", "Scenario", "load", "scenarios"]

SCENARIOS_DIR = Path(__file__).parent / "prompts" / "scenarios"
KEYS = ("title", "role", "setting", "goal", "twist")
FILE_MAX = 4096
BODY_MAX = 900
_ID = re.compile(r"[a-z_]+")


@dataclass(frozen=True)
class Scenario:
    id: str
    title: str
    role: str
    setting: str
    goal: str
    twist: str
    body: str


def load(id: str, dir: Path = SCENARIOS_DIR) -> Scenario:  # noqa: A002 (assinatura da spec §12)
    """Lê e valida ``<dir>/<id>.md``; ``ValueError`` se o id, o tamanho ou o cabeçalho falharem."""
    if not isinstance(id, str) or not _ID.fullmatch(id):
        raise ValueError(f"scenario id inválido: {id!r}")
    path = Path(dir) / f"{id}.md"
    if not path.is_file():
        raise ValueError(f"scenario inexistente: {id}")
    raw = path.read_bytes()
    if len(raw) > FILE_MAX:
        raise ValueError(f"scenario {id}: arquivo > {FILE_MAX} bytes")
    text = raw.decode("utf-8").replace("\r\n", "\n").strip("\n")
    head, _, body = text.partition("\n\n")
    fields: dict[str, str] = {}
    for line in head.splitlines():
        key, sep, value = line.partition(":")
        key = key.strip().lower()
        if not sep or key not in KEYS:
            raise ValueError(f"scenario {id}: linha de cabeçalho inválida: {line!r}")
        fields[key] = " ".join(value.split())
    missing = [k for k in KEYS if not fields.get(k)]
    if missing:
        raise ValueError(f"scenario {id}: faltam {', '.join(missing)}")
    body = body.strip()
    if not body:
        raise ValueError(f"scenario {id}: texto vazio")
    if len(body) > BODY_MAX:
        raise ValueError(f"scenario {id}: texto > {BODY_MAX} caracteres")
    return Scenario(id=id, body=body, **fields)


def scenarios(dir: Path = SCENARIOS_DIR) -> tuple[Scenario, ...]:  # noqa: A002
    """Todos os cenários válidos de ``dir``, ordenados por id (arquivo inválido levanta)."""
    ids = sorted(p.stem for p in Path(dir).glob("*.md") if _ID.fullmatch(p.stem))
    return tuple(load(i, dir) for i in ids)
