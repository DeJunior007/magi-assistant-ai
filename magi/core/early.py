"""Fala por frase em streaming (1.24, RNF-05).

O turno (``TurnMachine._think``) abre um ``EarlySpeech`` e o deixa em ``EARLY_SPEECH`` enquanto
espera a resposta. O agente, ao receber o texto final do modelo em streaming, entrega cada frase
fechada com ``say``: a primeira já começa a tocar (``play`` do turno, que entra em ``speaking`` e
abre um único envio de áudio ao satélite) e as seguintes entram na fila do mesmo envio. No fim,
``_deliver`` chama ``finish`` com as frases da fala final que ainda não saíram (``missing``) e o
envio termina com ``audio-stop``. Sem ``EARLY_SPEECH`` (avisos, confirmações, testes antigos) o
caminho é o de antes: fala só depois da resposta inteira.

Frases de espera: o texto que o modelo escreve antes de chamar uma ferramenta ("deixa eu ver as
conquistas…", ou a parte do pedido que ele já sabe responder) também é falado na hora, e o agente
o marca com ``mark_interim``. Essas frases têm cota própria (``INTERIM_MAX``) e não contam no
limite da resposta final, que continua com até ``max_sentences`` frases.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from contextvars import ContextVar

from magi.core.compose import SPEECH_MAX_SENTENCES, sentences, speech_key

#: Fala antecipada do turno em curso (``None`` = falar só no fim).
EARLY_SPEECH: ContextVar[EarlySpeech | None] = ContextVar("magi_early_speech", default=None)

Play = Callable[[AsyncIterator[str]], Awaitable[None]]
INTERIM_MAX = 2  # frases de espera por turno (antes das ferramentas)


class EarlySpeech:
    """Fila de frases faladas antes do fim da resposta. ``play`` recebe o fluxo de frases."""

    def __init__(self, play: Play, max_sentences: int = SPEECH_MAX_SENTENCES) -> None:
        self._play = play
        self.max_sentences = max_sentences
        self.spoken: list[str] = []
        self.interim: list[str] = []  # das faladas, as de espera (não contam no limite)
        self.skipped: list[str] = []  # cortadas pelo filtro de referências: não voltam no fim
        self._queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._closed = False

    @property
    def started(self) -> bool:
        return self._task is not None

    def say(self, sentence: str) -> None:
        """Fala ``sentence`` (a primeira abre o envio). Depois de ``finish``/``cancel``, ignora."""
        final = len(self.spoken) - len(self.interim)
        if self._closed or final >= self.max_sentences or not sentence.strip():
            return
        self.spoken.append(sentence)
        self._queue.put_nowait(sentence)
        if self._task is None:
            loop = asyncio.get_running_loop()
            self._task = loop.create_task(self._play(self._sentences()), name="early-speech")

    def mark_interim(self, said: Iterable[str]) -> None:
        """As frases ``said`` (já faladas) eram de espera: saem do limite da resposta final."""
        for sentence in said:
            if sentence in self.spoken and len(self.interim) < INTERIM_MAX:
                self.interim.append(sentence)

    def missing(self, speech: str) -> list[str]:
        """Frases de ``speech`` que ainda não foram faladas."""
        said = {speech_key(s) for s in (*self.spoken, *self.skipped)}
        return [s for s in sentences(speech) if speech_key(s) not in said]

    async def finish(self, rest: Iterable[str] = ()) -> None:
        """Fecha a fila com ``rest`` no fim e espera o envio terminar (``audio-stop``)."""
        self._closed = True
        if self._task is None:
            return
        for sentence in rest:
            self._queue.put_nowait(sentence)
        self._queue.put_nowait(None)
        await self._task

    def cancel(self) -> None:
        """Interrupção (ativação durante a fala) ou erro: para o envio na hora."""
        self._closed = True
        if self._task is not None and not self._task.done():
            self._task.cancel()

    async def _sentences(self) -> AsyncIterator[str]:
        while (sentence := await self._queue.get()) is not None:
            yield sentence
