"""Fase do turno da Condessa para o chip de estado e a legenda (sem Qt).

O núcleo manda ``{"t":"state","v":<expressão>}`` e a expressão nem sempre é o estado do turno:
a resposta com ``result.expression`` entra em ``speaking`` mandando ``happy``/``confused``/
``alert`` em vez de ``speaking``; o ``confirming`` (pergunta sim/não depois da fala) também
manda ``alert``; o "dispensada" manda ``happy`` saindo de ``listening``. Aqui a sequência de
eventos vira uma fase estável:

    idle → listening → thinking → speaking → (listening da continuação | idle)

- ``speaking`` só aparece no chip quando o áudio começa (primeiro nível de boca ou aviso de
  frase ``speech``) ou depois de ``AUDIO_WAIT_S``: enquanto a voz é sintetizada o chip segue
  em ``thinking`` (sem o "falando" mudo do começo).
- Cada fase mostrada fica pelo menos ``MIN_DWELL_S`` no chip (sem piscar ``thinking`` por um
  quadro); a troca atrasada vem em ``deadline``.
- ``happy``/``confused``/``alert`` durante a fala com a boca mexendo (``MOUTH_HOLD_S``) seguem
  ``speaking``; ``alert`` depois da fala = confirmação = ``listening``.
"""

from __future__ import annotations

IDLE, LISTENING, THINKING, SPEAKING = "idle", "listening", "thinking", "speaking"
FACES = ("happy", "confused", "alert")  # expressões que não dizem a fase sozinhas
AUDIO_WAIT_S = 1.0  # sem boca nem frase: depois disso o chip mostra "falando" assim mesmo
MIN_DWELL_S = 0.35  # tempo mínimo de cada fase no chip
MOUTH_HOLD_S = 0.6  # boca mexeu há menos que isso: ainda falando
MOUTH_MIN = 0.02  # nível de boca que conta como som


class TurnPhase:
    """Chame ``on_state``/``on_mouth``/``on_speech`` com o relógio monotônico; leia ``speaking``
    (para a legenda), ``chip(now)`` e ``deadline(now)`` (próxima troca do chip)."""

    def __init__(self) -> None:
        self.phase = IDLE
        self._speak_at = 0.0
        self._audio = False
        self._wait_from = IDLE  # fase mostrada enquanto a voz não começa
        self._last_mouth: float | None = None
        self._shown = IDLE
        self._shown_at = -1e9

    # -- eventos ---------------------------------------------------------------------------

    @property
    def speaking(self) -> bool:
        return self.phase == SPEAKING

    def _set(self, phase: str, now: float) -> None:
        if phase == SPEAKING and self.phase != SPEAKING:
            self._speak_at, self._audio = now, False
            self._wait_from = THINKING if self.phase == THINKING else SPEAKING
        self.phase = phase

    def on_state(self, expr: str, now: float) -> None:
        self.chip(now)  # fixa o que estava no chip antes da troca (para o tempo mínimo)
        if expr == "sleeping":
            self._set(IDLE, now)
        elif expr in (LISTENING, THINKING, SPEAKING):
            self._set(expr, now)
        elif expr in FACES:
            if self.phase == SPEAKING:
                mouth = self._last_mouth is not None and now - self._last_mouth < MOUTH_HOLD_S
                if expr == "alert" and not mouth:
                    self._set(LISTENING, now)  # confirmação: espera o "sim"/"não"
            elif self.phase in (IDLE, THINKING):
                self._set(SPEAKING, now)  # resposta (ou aviso) falada com expressão
            elif self.phase == LISTENING and expr == "happy":
                self._set(IDLE, now)  # dispensada
        self.chip(now)

    def on_mouth(self, level: float, now: float) -> None:
        if level > MOUTH_MIN:
            self._last_mouth = now
            if self.phase == SPEAKING:
                self._audio = True

    def on_speech(self, now: float) -> None:
        if self.phase == SPEAKING:
            self._audio = True

    # -- leitura ---------------------------------------------------------------------------

    def target(self, now: float) -> str:
        """Fase que o chip deveria mostrar agora (sem o tempo mínimo)."""
        if self.phase == SPEAKING and not self._audio and now < self._speak_at + AUDIO_WAIT_S:
            return self._wait_from
        return self.phase

    def chip(self, now: float) -> str:
        """Fase mostrada no chip agora (com o tempo mínimo de cada uma)."""
        tgt = self.target(now)
        if tgt != self._shown and now >= self._shown_at + MIN_DWELL_S:
            self._shown, self._shown_at = tgt, now
        return self._shown

    def deadline(self, now: float) -> float | None:
        """Próximo instante em que ``chip`` pode mudar sozinho (``None`` = parado)."""
        tgt = self.target(now)
        if tgt != self._shown:
            return max(now, self._shown_at + MIN_DWELL_S)
        if self.phase == SPEAKING and not self._audio and now < self._speak_at + AUDIO_WAIT_S:
            return self._speak_at + AUDIO_WAIT_S
        return None
