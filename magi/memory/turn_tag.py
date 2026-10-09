"""Tag do turno do Pedro para as reações da Condessa (spec §6 B, tarefa R2.B).

Só sinais LOCAIS, sem LLM, com as mesmas regras de palavras do ``mood.py``:

- ``correcao``: "eu falei", "não foi isso" (``_CORRECTION``) ou "para de zoar", "sem graça"
  (``_STOP_TEASE``) — a Condessa pede desculpa (86);
- ``elogio``: "valeu", "mandou bem", "perfeito"… (``_THANKS``) e elogio direto a ela
  ("linda", "fofa", "inteligente"…) — tsundere (74) ou gaguejando (87);
- ``zoeira``: risada ("kkk", "haha", "rsrs", ``_LAUGH``) — ela ri junto (76);
- ``sussurro``: reservado para a R2.F (voz baixa, ``ToneMetadata``).

Ordem: correção > elogio > zoeira (bronca vale mais que riso; "kkk mandou bem" é elogio). Sem
sinal: ``None`` (turno neutro, nada vai ao HUD). O ``MoodTracker.observe`` manda a tag como
``TurnTagMsg`` pelo mesmo canal do ``MoodMsg``.
"""

from __future__ import annotations

import re

from magi.common.contracts import ToneMetadata
from magi.memory.mood import _CORRECTION, _LAUGH, _STOP_TEASE, _THANKS, normalize

# elogio direto à Condessa, além dos agradecimentos do mood.py
_PRAISE = re.compile(
    r"\b(linda|lindinha|fofa|fofinha|gata|inteligente|genia|incrivel|maravilhosa|"
    r"te amo|amo voce|melhor assistente)\b"
)
# "boa noite" não é elogio (o ``boa`` do _THANKS pegaria)
_GREETING = re.compile(r"\bboa (noite|tarde|madrugada|sorte)\b")


def classify(text: str, tone: ToneMetadata | None = None) -> str | None:
    """Tag do turno (``elogio``, ``zoeira``, ``correcao``) ou ``None``. ``tone`` fica para a R2.F."""
    del tone  # sussurro: R2.F
    norm = normalize(text)
    if not norm:
        return None
    if _CORRECTION.search(norm) or _STOP_TEASE.search(norm):
        return "correcao"
    sem_saudacao = _GREETING.sub(" ", norm)
    if _THANKS.search(sem_saudacao) or _PRAISE.search(sem_saudacao):
        return "elogio"
    if _LAUGH.search(norm):
        return "zoeira"
    return None
