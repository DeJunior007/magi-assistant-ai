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

Espera viva (E0.1): ``THINK_HUD`` é o gancho do turno para avisar o HUD do que ela está fazendo
(``ThinkMsg``). ``notify_wait``/``notify_tool``/``notify_lote`` mandam pelo gancho aberto e não
fazem nada sem ele (testes antigos, avisos).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from contextvars import ContextVar

from magi.common.contracts import ThinkMsg
from magi.core.compose import SPEECH_MAX_SENTENCES, sentences, speech_key
from magi.core.espera import mesma_espera

#: Fala antecipada do turno em curso (``None`` = falar só no fim).
EARLY_SPEECH: ContextVar[EarlySpeech | None] = ContextVar("magi_early_speech", default=None)

#: Aviso de espera ao HUD do turno em curso (``None`` = ninguém ouvindo; espera viva, design §4).
THINK_HUD: ContextVar[Callable[[ThinkMsg], None] | None] = ContextVar("magi_think_hud", default=None)

log = logging.getLogger(__name__)

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
        self.waits: list[str] = []  # frases de espera locais faladas (espera viva, fora das cotas)
        self._echo_dropped = False
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

    def say_wait(self, sentence: str) -> bool:
        """Frase de espera local (R3): fala só se nada começou; abre o envio como ``say`` e fica
        fora de todas as cotas. Avisa o HUD (``notify_wait``). Devolve se falou."""
        if self._closed or self.started or not sentence.strip():
            return False
        self.waits.append(sentence)
        self._queue.put_nowait(sentence)
        loop = asyncio.get_running_loop()
        self._task = loop.create_task(self._play(self._sentences()), name="early-speech")
        notify_wait()
        return True

    def drop_wait_echo(self, sentence: str) -> bool:
        """R3.4: com a frase local já tocada, a 1ª frase do modelo que é só "espera vazia" é
        descartada (vai para ``skipped``, não volta no fim). Só vale antes de o modelo falar."""
        if not self.waits or self._echo_dropped or self.spoken or not mesma_espera(sentence):
            return False
        self._echo_dropped = True
        self.skipped.append(sentence)
        return True

    def mark_interim(self, said: Iterable[str]) -> None:
        """As frases ``said`` (já faladas) eram de espera: saem do limite da resposta final."""
        for sentence in said:
            if sentence in self.spoken and len(self.interim) < INTERIM_MAX:
                self.interim.append(sentence)

    def missing(self, speech: str) -> list[str]:
        """Frases de ``speech`` que ainda não foram faladas (nem as de espera local)."""
        said = {speech_key(s) for s in (*self.spoken, *self.skipped, *self.waits)}
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


def _notify(msg: ThinkMsg) -> None:
    hook = THINK_HUD.get()
    if hook is None:
        return
    try:
        hook(msg)
    except Exception:  # noqa: BLE001 - aviso ao HUD nunca derruba o turno
        log.exception("espera: aviso ao HUD falhou")


def notify_wait() -> None:
    """A frase de espera local começou a tocar (R3): ``{"t":"think","v":"wait"}``."""
    _notify(ThinkMsg("wait"))


def notify_tool(nome: str) -> None:
    """O agente vai rodar a ferramenta ``nome`` (R2); nome fora de ``THINK_TOOLS`` vira ``other``."""
    _notify(ThinkMsg("tool", tool=nome))


def notify_lote(n: int) -> None:
    """O lote ``n`` (1..) acabou de ser falado e o modelo segue (R5.3)."""
    _notify(ThinkMsg("lote", n=n))
