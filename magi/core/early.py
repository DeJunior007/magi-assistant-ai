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

Lotes (E3.1, design §5, spec §6): numa resposta de várias partes, o texto que o modelo diz antes de
uma ferramenta numa volta que já tem resultado de ferramenta (ou com 2+ frases na 1ª volta) é um
**lote**: parte da resposta, falada na hora. ``open_lote``/``close_lote`` delimitam cada um; até
``lotes_max`` lotes de até ``max_sentences`` frases, e lotes + resposta final nunca passam de
``lotes_frases_max`` frases (a frase de espera local e as interinas ficam fora dessa conta).
``lotes_max = 0`` (padrão, ``[espera] lotes = false`` ou desabafo) = sem lotes, como antes.
"""

from __future__ import annotations

import asyncio
import logging
import time
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

    def __init__(
        self,
        play: Play,
        max_sentences: int = SPEECH_MAX_SENTENCES,
        *,
        lotes_max: int = 0,
        lotes_frases_max: int = 6,
    ) -> None:
        self._play = play
        self.max_sentences = max_sentences
        self.lotes_max = lotes_max  # 0 = sem lotes (padrão; o turno liga pelo ``[espera]``)
        self.lotes_frases_max = lotes_frases_max
        self.lotes: list[list[str]] = []  # frases de cada lote, em ordem (E3.1)
        self._lote_open = False
        self._t0 = time.monotonic()  # só para o log do lote (spec §8)
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

    def _counted(self) -> int:
        """Frases do turno na conta de ``lotes_frases_max``: lotes + resposta final."""
        return len(self.spoken) - len(self.interim)

    def _in_lotes(self) -> int:
        return sum(len(lote) for lote in self.lotes)

    def say(self, sentence: str, lote: bool = False) -> bool:
        """Fala ``sentence`` (a primeira abre o envio). Depois de ``finish``/``cancel``, ignora.
        ``lote=True``: entra no lote aberto (até ``max_sentences`` por lote). Recusa a frase que
        passaria de ``lotes_frases_max`` no turno. Devolve se falou."""
        if self._closed or not sentence.strip() or self._counted() >= self.lotes_frases_max:
            return False
        if lote:
            if not self._lote_open or len(self.lotes[-1]) >= self.max_sentences:
                return False
            self.lotes[-1].append(sentence)
        elif self._counted() - self._in_lotes() >= self.max_sentences:
            return False
        self.spoken.append(sentence)
        self._queue.put_nowait(sentence)
        if self._task is None:
            loop = asyncio.get_running_loop()
            self._task = loop.create_task(self._play(self._sentences()), name="early-speech")
        return True

    def open_lote(self, said: Iterable[str] = ()) -> bool:
        """Abre um lote; as frases ``said`` (já faladas como resposta) passam a ser dele. Recusa
        sem lotes, com o teto ``lotes_max`` atingido ou com o turno já fechado."""
        if self._closed or self._lote_open or len(self.lotes) >= self.lotes_max:
            return False
        taken = {s for lote in self.lotes for s in lote}
        cur = [s for s in said if s in self.spoken and s not in self.interim and s not in taken]
        self.lotes.append(cur[: self.max_sentences])
        self._lote_open = True
        return True

    def close_lote(self) -> int:
        """Fecha o lote aberto: devolve o número dele (1..) ou 0 se ficou vazio (é descartado)."""
        if not self._lote_open:
            return 0
        self._lote_open = False
        if not self.lotes[-1]:
            self.lotes.pop()
            return 0
        n, ms = len(self.lotes), (time.monotonic() - self._t0) * 1000
        log.info("espera: lote %d (%d frases) em %d ms", n, len(self.lotes[-1]), ms)
        return n

    def full_text(self, final: str) -> str:
        """Resposta completa da legenda (R5.4): lotes + ``final``, sem repetir frase do lote que
        já está no ``final``."""
        keys = {speech_key(s) for s in sentences(final)}
        before = [s for lote in self.lotes for s in lote if speech_key(s) not in keys]
        return " ".join([*before, final]) if final else " ".join(before)

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
        """Frases de ``speech`` que ainda não foram faladas (nem as de espera local nem lotes)."""
        said = {speech_key(s) for s in (*self.spoken, *self.skipped, *self.waits)}
        return [s for s in sentences(speech) if speech_key(s) not in said]

    async def finish(self, rest: Iterable[str] = ()) -> None:
        """Fecha a fila com ``rest`` no fim e espera o envio terminar (``audio-stop``)."""
        self._closed = True
        if self._task is None:
            return
        rest = list(rest)
        if self.lotes:  # lotes + resposta final ≤ ``lotes_frases_max`` (D3)
            rest = rest[: max(0, self.lotes_frases_max - self._counted())]
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
