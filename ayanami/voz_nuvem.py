"""STT e TTS do modo nuvem (dono: Y6.3; spec §6.5, D14a).

- :class:`Fala` / :class:`Escuta`: protocolos do TTS e do STT (os adaptadores reais e os falsos
  dos testes implementam só isso).
- :class:`OpenAIFala` (``[nuvem] tts_voz`` = ``marin``) e :class:`OpenAIEscuta`
  (``[nuvem] stt_modelo``) recebem o cliente ``openai.AsyncOpenAI`` pronto (injetado; os testes
  nunca falam com a rede). :class:`KokoroFala` embrulha o ``Gerenciador`` de ``ayanami.voz.motor``.
- :class:`FalaNuvem`: OpenAI com **cache por texto**; cai para a reserva (Kokoro) quando a OpenAI
  falha 2× seguidas em 5 min (:class:`Disjuntor`, relógio injetado) ou quando o teto da nuvem
  bateu (``budget.gasto().bloqueado``). Uma falha isolada também usa a reserva naquela fala.
- :class:`EscutaNuvem`: o mesmo disjuntor para o STT (a reserva é opcional).
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any, Final, Protocol

log = logging.getLogger(__name__)

FALHAS_PARA_TROCAR: Final = 2
JANELA_FALHAS_S: Final = 300.0
CACHE_MAX: Final = 256
TTS_MODELO_PADRAO: Final = "gpt-4o-mini-tts"


class Fala(Protocol):
    formato: str

    async def sintetizar(self, texto: str) -> bytes: ...


class Escuta(Protocol):
    async def transcrever(self, audio: bytes, mime: str) -> str: ...


class VozIndisponivel(RuntimeError):
    """Nem a OpenAI nem a reserva conseguiram (ou não há reserva)."""


@dataclass(frozen=True, slots=True)
class Audio:
    dados: bytes
    formato: str  # "opus" (OpenAI) ou "pcm16" (Kokoro, 24 kHz mono)
    origem: str  # "openai" | "kokoro" | "cache"


# --------------------------------------------------------------------------- adaptadores


class OpenAIFala:
    def __init__(self, cliente: Any, *, voz: str = "marin", modelo: str = TTS_MODELO_PADRAO,
                 formato: str = "opus") -> None:
        self.cliente, self.voz, self.modelo, self.formato = cliente, voz, modelo, formato

    async def sintetizar(self, texto: str) -> bytes:
        r = await self.cliente.audio.speech.create(
            model=self.modelo, voice=self.voz, input=texto, response_format=self.formato)
        dados = getattr(r, "content", r)
        return bytes(dados)


class OpenAIEscuta:
    def __init__(self, cliente: Any, *, modelo: str = "gpt-transcribe", idioma: str = "pt") -> None:
        self.cliente, self.modelo, self.idioma = cliente, modelo, idioma

    async def transcrever(self, audio: bytes, mime: str) -> str:
        ext = "webm" if "webm" in mime else "ogg" if "ogg" in mime else "wav"
        r = await self.cliente.audio.transcriptions.create(
            model=self.modelo, file=(f"turno.{ext}", audio, mime), language=self.idioma)
        return str(getattr(r, "text", r)).strip()


class KokoroFala:
    """Reserva local: ``obter()`` devolve o ``Motor`` (``Gerenciador.obter`` em produção)."""

    formato = "pcm16"

    def __init__(self, obter: Callable[[], Awaitable[Any]], *, voz: str = "pf_dora",
                 velocidade: float = 1.0) -> None:
        self.obter, self.voz, self.velocidade = obter, voz, velocidade

    async def sintetizar(self, texto: str) -> bytes:
        motor = await self.obter()
        partes = [p async for p in motor.falar(texto, self.voz, self.velocidade)]
        return b"".join(partes)


# --------------------------------------------------------------------------- disjuntor


class Disjuntor:
    """Aberto com ``falhas`` falhas seguidas dentro de ``janela_s`` (relógio monotônico injetado)."""

    def __init__(self, relogio: Any, *, falhas: int = FALHAS_PARA_TROCAR,
                 janela_s: float = JANELA_FALHAS_S) -> None:
        self.relogio, self.falhas, self.janela_s = relogio, falhas, janela_s
        self._quando: list[float] = []

    def _podar(self) -> None:
        agora = self.relogio.monotonico()
        self._quando = [t for t in self._quando if agora - t < self.janela_s]

    def falhou(self) -> None:
        self._podar()
        self._quando.append(self.relogio.monotonico())

    def ok(self) -> None:
        self._quando.clear()

    @property
    def aberto(self) -> bool:
        self._podar()
        return len(self._quando) >= self.falhas


async def _sem_verba(budget: Any) -> bool:
    if budget is None:
        return False
    try:
        return bool((await budget.gasto()).bloqueado)
    except Exception:  # noqa: BLE001 - sem leitura do gasto: segue a OpenAI (o teto do LLM segura)
        log.exception("voz_nuvem: gasto ilegível")
        return False


# --------------------------------------------------------------------------- TTS


class FalaNuvem:
    def __init__(self, primaria: Fala | None, reserva: Fala | None, relogio: Any, *,
                 budget: Any = None, cache_max: int = CACHE_MAX,
                 disjuntor: Disjuntor | None = None) -> None:
        self.primaria, self.reserva, self.budget = primaria, reserva, budget
        self.disjuntor = disjuntor or Disjuntor(relogio)
        self.cache_max = cache_max
        self._cache: OrderedDict[str, Audio] = OrderedDict()

    async def sintetizar(self, texto: str) -> Audio:
        chave = texto.strip()
        if (hit := self._cache.get(chave)) is not None:
            self._cache.move_to_end(chave)
            return Audio(hit.dados, hit.formato, "cache")
        if self.primaria is not None and not self.disjuntor.aberto and not await _sem_verba(self.budget):
            try:
                dados = await self.primaria.sintetizar(chave)
            except Exception as e:  # noqa: BLE001 - qualquer falha da OpenAI conta para o disjuntor
                log.warning("tts_openai_falhou (%s)", type(e).__name__)
                self.disjuntor.falhou()
            else:
                self.disjuntor.ok()
                audio = Audio(dados, self.primaria.formato, "openai")
                self._guardar(chave, audio)
                return audio
        if self.reserva is None:
            raise VozIndisponivel("sem TTS")
        try:
            return Audio(await self.reserva.sintetizar(chave), self.reserva.formato, "kokoro")
        except Exception as e:
            raise VozIndisponivel("reserva falhou") from e

    def _guardar(self, chave: str, audio: Audio) -> None:
        self._cache[chave] = audio
        while len(self._cache) > self.cache_max:
            self._cache.popitem(last=False)

    async def aquecer(self, textos: Iterable[str]) -> int:
        """Gera as frases fixas uma vez (só as da OpenAI ficam no cache). Nunca levanta."""
        n = 0
        for t in textos:
            try:
                if (await self.sintetizar(t)).origem != "kokoro":
                    n += 1
            except VozIndisponivel:
                log.info("tts_aquecer_sem_voz")
        return n


# --------------------------------------------------------------------------- STT


class EscutaNuvem:
    def __init__(self, primaria: Escuta | None, reserva: Escuta | None, relogio: Any, *,
                 budget: Any = None, disjuntor: Disjuntor | None = None) -> None:
        self.primaria, self.reserva, self.budget = primaria, reserva, budget
        self.disjuntor = disjuntor or Disjuntor(relogio)

    async def transcrever(self, audio: bytes, mime: str) -> str:
        if self.primaria is not None and not self.disjuntor.aberto and not await _sem_verba(self.budget):
            try:
                texto = await self.primaria.transcrever(audio, mime)
            except Exception as e:  # noqa: BLE001
                log.warning("stt_openai_falhou (%s)", type(e).__name__)
                self.disjuntor.falhou()
            else:
                self.disjuntor.ok()
                return texto
        if self.reserva is None:
            raise VozIndisponivel("sem STT")
        try:
            return await self.reserva.transcrever(audio, mime)
        except Exception as e:
            raise VozIndisponivel("reserva falhou") from e
