"""Legenda que se escreve conforme a Condessa fala (efeito máquina de escrever, sem Qt).

O núcleo manda ``{"t":"speech","text":…,"dur":…,"i":…}`` quando cada frase começa a tocar no
satélite. Aqui fica o texto já dito (frases inteiras) e a frase atual, revelada na proporção do
tempo: ``len(frase) * clamp((agora + LEAD_S - início) / dur)`` caracteres, arredondado para
palavra inteira (a palavra aparece quando ela começa a dizê-la, nunca cortada no meio).

- Sem ``dur`` na mensagem (TTS em streaming): estima ``FALLBACK_CPS`` caracteres por segundo.
- Sem nenhum ``speech`` no turno (núcleo antigo, TTS sem aviso): revela o ``subtitle`` a
  ``FALLBACK_CPS`` desde que o áudio começou (primeiro nível de boca) ou, sem boca, desde
  ``FALLBACK_WAIT_S`` depois de entrar em ``speaking``.
- Fora de ``speaking`` (a fala acabou, foi interrompida, resposta só em texto): mostra inteiro,
  como antes.

``deadline(now)`` diz quando a legenda muda de novo (próxima palavra), no máximo
``MAX_FPS`` vezes por segundo; ``None`` = parada, nada a redesenhar.
"""

from __future__ import annotations

import re

LEAD_S = 0.08  # a palavra aparece um pouco antes do som
FALLBACK_CPS = 15.0  # velocidade estimada da fala sem duração (caracteres/s)
FALLBACK_WAIT_S = 1.0  # sem boca nem aviso de frase: espera a síntese antes de começar
MAX_FPS = 30.0
_WORD = re.compile(r"\S+")


def reveal_words(text: str, frac: float) -> str:
    """Prefixo de ``text`` com as palavras já alcançadas por ``frac`` (0..1) do texto: a palavra
    entra quando o ponteiro passa do seu começo, inteira."""
    if frac >= 1.0:
        return text
    if frac <= 0.0:
        return ""
    n = len(text) * frac
    end = 0
    for m in _WORD.finditer(text):
        if m.start() >= n:
            break
        end = m.end()
    return text[:end]


def _next_word_frac(text: str, frac: float) -> float | None:
    """Fração em que a próxima palavra (depois de ``frac``) entra; ``None`` = não há mais."""
    if not text:
        return None
    n = len(text) * frac
    for m in _WORD.finditer(text):
        if m.start() >= n:
            return min(1.0, (m.start() + 1e-6) / len(text))
    return None


class SpeechCaption:
    """Estado da legenda sincronizada. Chame os ``on_*`` com o relógio monotônico do HUD e
    leia ``text(now)``/``deadline(now)`` para desenhar."""

    def __init__(self) -> None:
        self.full = ""  # legenda do último ``subtitle`` (a fala inteira)
        self.speaking = False
        self._spoken: list[str] = []  # frases já ditas, inteiras
        self._cur: tuple[str, float, float] | None = None  # (frase, início, duração)
        self._speak_at = 0.0  # entrou em speaking
        self._mouth_at: float | None = None  # primeiro nível de boca da fala (áudio tocando)

    # -- eventos ---------------------------------------------------------------------------

    def on_state(self, expr: str, now: float) -> None:
        if expr == "speaking":
            if not self.speaking:  # fala nova: começa do zero
                self.speaking = True
                self._spoken, self._cur = [], None
                self._speak_at, self._mouth_at = now, None
            return
        self.speaking = False  # fim (ou interrupção): a legenda fica inteira

    def on_mouth(self, now: float) -> bool:
        """Nível de boca (o áudio está tocando). ``True`` = era o primeiro da fala: a estimativa
        sem aviso de frase passa a contar daqui."""
        if self.speaking and self._mouth_at is None:
            self._mouth_at = now
            return True
        return False

    def on_subtitle(self, text: str) -> None:
        self.full = text or ""
        if not self.speaking:
            self._spoken, self._cur = [], None  # resposta só em texto ou aviso: vale o subtitle

    def on_speech(self, text: str, dur: float | None, now: float) -> None:
        """A frase ``text`` começa a tocar agora. ``dur`` em segundos (``None``/negativo = sem)."""
        if not self.speaking or not text.strip():
            return  # aviso atrasado de uma fala que já acabou
        if self._cur is not None:
            self._spoken.append(self._cur[0])
        text = " ".join(text.split())
        if dur is None or dur <= 0:
            dur = len(text) / FALLBACK_CPS
        self._cur = (text, now, max(0.05, dur))

    # -- leitura ---------------------------------------------------------------------------

    def _fallback_origin(self) -> float:
        wait = self._speak_at + FALLBACK_WAIT_S
        return wait if self._mouth_at is None else min(self._mouth_at, wait)

    def _progress(self, now: float) -> tuple[str, float] | None:
        """(texto sendo revelado, fração 0..1) ou ``None`` = nada sendo revelado."""
        if not self.speaking:
            return None
        if self._cur is not None:
            text, start, dur = self._cur
            return text, (now + LEAD_S - start) / dur
        if self.full:
            origin = self._fallback_origin()
            return self.full, (now + LEAD_S - origin) * FALLBACK_CPS / max(1, len(self.full))
        return None

    def text(self, now: float) -> str:
        """Legenda a desenhar agora."""
        if not self.speaking:
            if self.full:
                return self.full
            return " ".join([*self._spoken, *([self._cur[0]] if self._cur else [])])
        prog = self._progress(now)
        if prog is None:
            return " ".join(self._spoken)
        text, frac = prog
        part = reveal_words(text, frac)
        if self._cur is None:
            return part
        return " ".join(x for x in (*self._spoken, part) if x)

    def deadline(self, now: float) -> float | None:
        """Próximo instante em que ``text`` muda (``None`` = parada)."""
        prog = self._progress(now)
        if prog is None:
            return None
        text, frac = prog
        if self._cur is None and frac <= 0:  # fallback ainda esperando o áudio
            return max(now + 1 / MAX_FPS, self._fallback_origin() - LEAD_S)
        nxt = _next_word_frac(text, max(0.0, frac))
        if nxt is None:
            return None
        if self._cur is not None:
            _, start, dur = self._cur
            at = start + nxt * dur - LEAD_S
        else:
            at = self._fallback_origin() + nxt * len(text) / FALLBACK_CPS - LEAD_S
        return max(now + 1 / MAX_FPS, at)
