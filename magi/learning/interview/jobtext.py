"""Texto colado da vaga: normalizar, identificar e checar (tarefa LI0.1; spec §1, R1.5). Puro.

``check`` é usado no HUD (recusa local de vazio/curto) e no núcleo (corte em ``JOB_MAX``).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from magi.learning.interview.contracts import JOB_MAX, JOB_MIN, PASTE_ASK

#: Linhas que são só ruído de site de vagas (comparação sem caixa e sem pontuação nas pontas).
NOISE = frozenset(
    {"apply now", "candidatar-se", "show more", "ver mais", "save", "salvar"}
)
BULLETS = "•·–*○"
TOO_SHORT = "too short to be a job post"
TRIMMED = "job post too long — trimmed to 12k"

_BULLET_RE = re.compile(rf"^[{re.escape(BULLETS)}]\s*")
_BLANKS_RE = re.compile(r"\n{4,}")  # 3+ linhas vazias seguidas = 4+ quebras


def _clean_line(line: str) -> str | None:
    line = line.strip()
    if line.strip(" .:!").lower() in NOISE:
        return None
    return _BULLET_RE.sub("- ", line)


def _cut(text: str, limit: int = JOB_MAX) -> str:
    if len(text) <= limit:
        return text
    head = text[:limit]
    nl = head.rfind("\n")
    return (head[:nl] if nl > 0 else head).rstrip()


def _normalize_full(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [c for c in (_clean_line(x) for x in text.split("\n")) if c is not None]
    return _BLANKS_RE.sub("\n\n", "\n".join(lines)).strip()


def normalize(text: str) -> str:
    """CRLF → LF; pontas das linhas sem espaço; 3+ linhas vazias → 1; bullets → ``- ``; tira as
    linhas de ``NOISE``; corta em ``JOB_MAX`` na última quebra de linha antes do limite."""
    return _cut(_normalize_full(text))


def job_id(normalized: str) -> str:
    """``JOB-`` + 8 hex do sha256 do texto normalizado (mesma vaga → mesmo id, R2.6)."""
    return "JOB-" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:8]


@dataclass(frozen=True, slots=True)
class Checked:
    """Resultado do ``check``: ``ok`` falso → ``line`` é a recusa; ``trimmed`` → ``line`` avisa
    o corte e ``text`` já vem cortado."""

    text: str
    ok: bool
    trimmed: bool
    line: str | None


def check(raw: str | None) -> Checked:
    """Recusa vazio/curto (< ``JOB_MIN``); acima de ``JOB_MAX`` corta, não recusa (R1.5)."""
    full = _normalize_full(raw or "")
    if len(full) < JOB_MIN:
        return Checked(full, False, False, TOO_SHORT)
    if len(full) > JOB_MAX:
        return Checked(_cut(full), True, True, TRIMMED)
    return Checked(full, True, False, None)


def is_long_paste(text: str | None) -> bool:
    """Colagem no campo que vira a pergunta ``use as job description?`` (R1.2)."""
    return bool(text) and (len(text) > PASTE_ASK or "\n" in text)  # type: ignore[arg-type]
