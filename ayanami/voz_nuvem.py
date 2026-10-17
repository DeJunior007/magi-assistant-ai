"""STT e TTS do modo nuvem (dono: Y6.3; spec §6.5; design §7.3; D14a).

- **TTS** (:class:`VozNuvem`): frase fixa com ``<sha1>.ogg`` no cache do ``voz.cache_frases``
  (:func:`ayanami.workers.voz.chave`, mesma chave) → toca o arquivo, sem TTS. Senão OpenAI
  (``[nuvem] tts_voz``, padrão ``marin``) com cache por texto; **Kokoro** (``ayanami-voz``) quando
  a OpenAI falhou 2× seguidas em 5 min (fica no Kokoro até 5 min depois da 2ª falha) ou o teto da
  nuvem bateu (``BudgetNuvem.gasto().bloqueado``). Áudio sempre Opus em OGG.
- **STT** (:class:`SttNuvem`): OpenAI ``[nuvem] stt_modelo`` (turno ao vivo); grava o ``Usage``.

Motores atrás de protocolos (:class:`Tts`, :class:`Stt`); os de produção falam HTTP com a OpenAI e o
``ayanami-voz``. Testes usam falsos e relógio falso (nada pago, nada de rede).
"""

from __future__ import annotations

import logging
import os
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Final, Protocol

from ayanami.workers.voz import chave
from magi.common.contracts import ProviderTask, Usage

log = logging.getLogger("ayanami.voz_nuvem")

FALHAS_PARA_KOKORO: Final = 2
JANELA_S: Final = 300.0
CACHE_MAX_ARQUIVOS: Final = 500
OPENAI_URL: Final = "https://api.openai.com/v1"
TTS_MODELO_OPENAI: Final = "gpt-4o-mini-tts"


class Tts(Protocol):
    async def sintetizar(self, texto: str) -> bytes:
        """Áudio Opus/OGG do texto."""
        ...


class Stt(Protocol):
    async def transcrever(self, audio: bytes, mime: str) -> tuple[str, float]:
        """``(texto, segundos de áudio)``."""
        ...


class VozNuvem:
    """TTS da nuvem com cache por texto e troca para o Kokoro (spec §6.5)."""

    def __init__(self, openai: Tts | None, kokoro: Tts, relogio: Any, *, cache_frases: Path,
                 cache: Path, budget: Any = None, modelo: str = TTS_MODELO_OPENAI,
                 falhas_para_kokoro: int = FALHAS_PARA_KOKORO, janela_s: float = JANELA_S,
                 cache_max: int = CACHE_MAX_ARQUIVOS) -> None:
        self.openai, self.kokoro, self.relogio, self.budget = openai, kokoro, relogio, budget
        self.cache_frases, self.cache, self.modelo = cache_frases, cache, modelo
        self.falhas_para_kokoro, self.janela_s, self.cache_max = falhas_para_kokoro, janela_s, cache_max
        self._falhas: list[float] = []  # instantes (monotônico) das falhas seguidas da OpenAI
        self._kokoro_ate: float | None = None
        self.ultimo_motor = ""

    # -- estado ------------------------------------------------------------

    def em_kokoro(self) -> bool:
        return self._kokoro_ate is not None and self.relogio.monotonico() < self._kokoro_ate

    def _falhou(self) -> None:
        agora = self.relogio.monotonico()
        self._falhas = [t for t in self._falhas if agora - t <= self.janela_s] + [agora]
        if len(self._falhas) >= self.falhas_para_kokoro:
            self._kokoro_ate = agora + self.janela_s
            self._falhas.clear()
            log.warning("tts_openai_caiu: Kokoro por %.0f s", self.janela_s)

    async def _teto(self) -> bool:
        if self.budget is None:
            return False
        try:
            return bool((await self.budget.gasto()).bloqueado)
        except Exception as e:  # noqa: BLE001 - sem leitura do gasto: segue a OpenAI
            log.warning("tts_gasto_ilegivel (%s)", type(e).__name__)
            return False

    # -- cache -------------------------------------------------------------

    def _em_cache(self, texto: str) -> bytes | None:
        k = chave(texto)
        for d in (self.cache_frases, self.cache):
            f = d / f"{k}.ogg"
            if f.is_file():
                return f.read_bytes()
        return None

    def _guardar(self, texto: str, audio: bytes) -> None:
        try:
            self.cache.mkdir(parents=True, exist_ok=True)
            final = self.cache / f"{chave(texto)}.ogg"
            tmp = final.with_name(f".{final.name}.tmp")
            tmp.write_bytes(audio)
            tmp.replace(final)
            arquivos = sorted(self.cache.glob("*.ogg"), key=lambda p: p.stat().st_mtime)
            for velho in arquivos[: max(0, len(arquivos) - self.cache_max)]:
                velho.unlink(missing_ok=True)
        except OSError as e:
            log.warning("tts_cache_falhou (%s)", type(e).__name__)

    # -- fala --------------------------------------------------------------

    async def falar(self, texto: str) -> bytes:
        """OGG/Opus de ``texto``: cache → OpenAI → Kokoro (ver o módulo)."""
        if (audio := self._em_cache(texto)) is not None:
            self.ultimo_motor = "cache"
            return audio
        if self.openai is not None and not self.em_kokoro() and not await self._teto():
            try:
                audio = await self.openai.sintetizar(texto)
            except Exception as e:  # noqa: BLE001 - provedor fora: conta a falha e cai no Kokoro
                log.warning("tts_openai_falhou (%s)", type(e).__name__)
                self._falhou()
            else:
                self._falhas.clear()
                await self._registrar(texto)
                self._guardar(texto, audio)
                self.ultimo_motor = "openai"
                return audio
        self.ultimo_motor = "kokoro"
        return await self.kokoro.sintetizar(texto)

    async def _registrar(self, texto: str) -> None:
        if self.budget is None:
            return
        try:
            await self.budget.record(Usage(provider="openai", task=ProviderTask.TTS, model=self.modelo,
                                           input_units=float(len(texto))))
        except Exception as e:  # noqa: BLE001
            log.warning("tts_custo_nao_gravado (%s)", type(e).__name__)


class SttNuvem:
    """STT do turno ao vivo (OpenAI ``[nuvem] stt_modelo``) com o ``Usage`` no ``BudgetNuvem``."""

    def __init__(self, motor: Stt, *, modelo: str, budget: Any = None) -> None:
        self.motor, self.modelo, self.budget = motor, modelo, budget

    async def transcrever(self, audio: bytes, mime: str) -> str:
        texto, segundos = await self.motor.transcrever(audio, mime)
        if self.budget is not None:
            try:
                await self.budget.record(Usage(provider="openai", task=ProviderTask.STT, model=self.modelo,
                                               input_units=float(segundos)))
            except Exception as e:  # noqa: BLE001
                log.warning("stt_custo_nao_gravado (%s)", type(e).__name__)
        return texto


# --------------------------------------------------------------------------- motores de produção


def _chave_openai(chave_api: str | None) -> str:
    v = chave_api or os.environ.get("OPENAI_API_KEY")
    if not v:
        raise RuntimeError("OPENAI_API_KEY ausente")
    return v


class TtsOpenAI:
    """``POST /v1/audio/speech`` (``response_format=opus``). ``cliente``: ``httpx.AsyncClient``."""

    def __init__(self, *, voz: str = "marin", modelo: str = TTS_MODELO_OPENAI, chave_api: str | None = None,
                 cliente: Any = None, timeout_s: float = 15.0) -> None:
        self.voz, self.modelo, self._chave = voz, modelo, chave_api
        self._cliente, self.timeout_s = cliente, timeout_s

    async def sintetizar(self, texto: str) -> bytes:
        import httpx

        cab = {"Authorization": f"Bearer {_chave_openai(self._chave)}"}
        corpo = {"model": self.modelo, "voice": self.voz, "input": texto, "response_format": "opus"}
        if self._cliente is not None:
            r = await self._cliente.post(f"{OPENAI_URL}/audio/speech", json=corpo, headers=cab)
        else:
            async with httpx.AsyncClient(timeout=self.timeout_s) as c:
                r = await c.post(f"{OPENAI_URL}/audio/speech", json=corpo, headers=cab)
        r.raise_for_status()
        return r.content


class SttOpenAI:
    """``POST /v1/audio/transcriptions`` com o ``[nuvem] stt_modelo``."""

    def __init__(self, *, modelo: str, chave_api: str | None = None, cliente: Any = None,
                 timeout_s: float = 30.0, idioma: str = "pt") -> None:
        self.modelo, self._chave, self._cliente, self.timeout_s, self.idioma = (
            modelo, chave_api, cliente, timeout_s, idioma)

    async def transcrever(self, audio: bytes, mime: str) -> tuple[str, float]:
        import httpx

        cab = {"Authorization": f"Bearer {_chave_openai(self._chave)}"}
        ext = "webm" if "webm" in mime else "ogg" if "ogg" in mime else "wav"
        files = {"file": (f"turno.{ext}", audio, mime)}
        data = {"model": self.modelo, "language": self.idioma, "response_format": "json"}
        url = f"{OPENAI_URL}/audio/transcriptions"
        if self._cliente is not None:
            r = await self._cliente.post(url, files=files, data=data, headers=cab)
        else:
            async with httpx.AsyncClient(timeout=self.timeout_s) as c:
                r = await c.post(url, files=files, data=data, headers=cab)
        r.raise_for_status()
        j = r.json()
        return str(j.get("text") or ""), float(j.get("duration") or 0.0)


class TtsKokoro:
    """Kokoro pelo ``ayanami-voz`` (PCM) + ``ffmpeg`` → OGG/Opus; os dois injetáveis (Y3.5)."""

    def __init__(self, voz: str, *,
                 sintetizar: Callable[[str, str], Awaitable[tuple[bytes, int]]] | None = None,
                 ffmpeg: Callable[[bytes, int, Path], Awaitable[None]] | None = None) -> None:
        from ayanami.workers.voz import ffmpeg_ogg, sintetizar_http

        self.voz = voz
        self._sintetizar = sintetizar or sintetizar_http
        self._ffmpeg = ffmpeg or ffmpeg_ogg

    async def sintetizar(self, texto: str) -> bytes:
        pcm, taxa = await self._sintetizar(texto, self.voz)
        with tempfile.TemporaryDirectory(prefix="ayanami-tts-") as d:
            destino = Path(d) / "fala.ogg"
            await self._ffmpeg(pcm, taxa, destino)
            return destino.read_bytes()


def montar(cfg: Any, dados: Path, relogio: Any, *, budget: Any = None,
           chave_api: str | None = None) -> tuple[VozNuvem, SttNuvem]:
    """Produção: ``cfg`` = ``AyanamiConfig`` (``[nuvem]``, ``[voz]``), cache em ``<dados>/``."""
    kokoro = TtsKokoro(cfg.voz.voz)
    openai = TtsOpenAI(voz=cfg.nuvem.tts_voz, chave_api=chave_api) if cfg.nuvem.ligado else None
    tts = VozNuvem(openai, kokoro, relogio, cache_frases=dados / "modelos" / "cache-voz",
                   cache=dados / "cache-tts", budget=budget)
    stt = SttNuvem(SttOpenAI(modelo=cfg.nuvem.stt_modelo, chave_api=chave_api), modelo=cfg.nuvem.stt_modelo,
                   budget=budget)
    return tts, stt
