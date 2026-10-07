"""Voz no núcleo (tarefa 1.12; R12.1, R12.2; §4.1 ``tts``).

``PhraseSpeaker`` implementa ``Speaker``: fala um texto no satélite pelo ``SatelliteLink.play``.

- Frase curta frequente (``phrases.yaml``) já em cache → toca o PCM do disco, sem rede (R12.2).
- Senão → sintetiza em streaming pelo ``TtsProvider`` e repassa os blocos ao satélite conforme
  chegam (R12.1). Se o texto é uma frase conhecida (fixa ou molde com placeholder preenchido),
  o áudio completo vai para o cache ao fim.
- As fixas são pré-geradas no primeiro uso (``warm``, disparado em segundo plano no primeiro
  ``say``). Chave = hash de texto normalizado + provedor + modelo + voz + formato: trocar a voz
  invalida. Cache em ``~/.cache/magi/tts/`` com limite de tamanho (LRU por mtime).
- Silêncio inicial (1.24, S3: a voz "nova" abre com 0,2–0,5 s mudos): amostras abaixo de
  ``SILENCE_DBFS`` no começo de cada frase são descartadas até a primeira fala, nunca mais que
  ``MAX_TRIM_MS``. Vale no streaming, ao gravar no cache e ao ler dele (entradas antigas são
  regravadas cortadas na primeira leitura).
- ``say_stream`` (1.24): frases que vão chegando (fala por frase do agente) num único envio
  ``audio-start`` … ``audio-stop``, uma atrás da outra.
- Legenda sincronizada: com ``on_sentence`` (``say``/``say_stream``), cada frase avisa quando começa
  a tocar no satélite, com a duração do áudio (``_Playhead``). O envio vai mais rápido que o tempo
  real, então o "começa a tocar" é estimado: fim das frases anteriores ou agora, o que vier depois.
  Duração conhecida antes de tocar = frase do cache ou provedor que sintetiza a frase inteira de uma
  vez (``whole_sentence``, ex.: Kokoro); TTS em streaming avisa sem duração (``None``).
- Erro do TTS não trava o turno: o envio termina (``audio-stop``) com o que saiu até ali, para o
  satélite responder ``playback-done``; a legenda já foi para o HUD.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import os
import re
from collections.abc import AsyncIterable, AsyncIterator, Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import yaml

from magi.common.contracts import CHUNK_MS, PcmFormat, SatelliteLink, TtsProvider

log = logging.getLogger(__name__)

PHRASES_FILE = Path(__file__).with_name("phrases.yaml")
DEFAULT_CACHE_MAX_BYTES = 64 * 1024 * 1024
#: Aviso de frase começando a tocar: (texto, duração em s ou ``None``, índice no envio).
OnSentence = Callable[[str, float | None, int], None]
_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_SPACES = re.compile(r"\s+")
#: Limiar do silêncio inicial (1.24): |amostra| abaixo de -50 dBFS (16 bits: ~104) é silêncio.
SILENCE_DBFS = -50.0
#: Nunca corta mais que isto do começo de uma frase.
MAX_TRIM_MS = 600


def _silence_level(width: int) -> int:
    return round((1 << (8 * width - 1)) * 10 ** (SILENCE_DBFS / 20))


def _first_sound(pcm: bytes, fmt: PcmFormat) -> int | None:
    """Byte (alinhado ao quadro) da primeira amostra acima do limiar; ``None`` = tudo mudo.
    Só PCM de 16 bits; outro formato conta como som desde o início."""
    if fmt.width != 2:
        return 0
    frame = fmt.width * fmt.channels
    usable = len(pcm) - len(pcm) % frame
    samples = np.frombuffer(pcm[:usable], dtype="<i2")
    loud = np.flatnonzero(np.abs(samples.astype(np.int32)) >= _silence_level(2))
    if not loud.size:
        return None
    return int(loud[0]) * 2 // frame * frame


def trim_silence(pcm: bytes, fmt: PcmFormat) -> bytes:
    """``pcm`` sem o silêncio inicial (no máximo ``MAX_TRIM_MS``). Áudio curto e todo abaixo do
    limiar fica como está (não é silêncio "antes da fala", é a fala inteira baixa)."""
    limit = fmt.bytes_for_ms(MAX_TRIM_MS)
    start = _first_sound(pcm[:limit], fmt)
    if start is None:
        return pcm[limit:] if len(pcm) > limit else pcm
    return pcm[start:]


async def trim_lead(chunks: AsyncIterable[bytes], fmt: PcmFormat) -> AsyncIterator[bytes]:
    """Versão em streaming de ``trim_silence``: segura até ``MAX_TRIM_MS`` do começo enquanto só
    há silêncio e repassa o resto como chega (a fala sai assim que aparece)."""
    limit = fmt.bytes_for_ms(MAX_TRIM_MS)
    head: bytes | None = b""
    async for pcm in chunks:
        if head is None:
            yield pcm
            continue
        head += pcm
        start = _first_sound(head[:limit], fmt)
        if start is None and len(head) <= limit:
            continue
        out, head = head[limit if start is None else start :], None
        if out:
            yield out
    if head:
        yield head


def default_cache_dir(env: dict[str, str] | None = None) -> Path:
    env = dict(os.environ) if env is None else env
    base = env.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "magi" / "tts"


def normalize(text: str) -> str:
    """Forma usada na comparação e na chave: sem espaços extras, sem caixa."""
    return _SPACES.sub(" ", text).strip().casefold()


@dataclass(frozen=True, slots=True)
class Phrases:
    """Frases fixas e moldes com placeholder (``{game}``).

    ``fixed`` são pré-geradas por ``warm``; ``lazy`` (1.23) são fixas também, mas só vão para o
    cache na primeira vez que são faladas (respostas raras, sem custo de pré-geração).
    """

    fixed: tuple[str, ...] = ()
    templates: tuple[str, ...] = ()
    lazy: tuple[str, ...] = ()
    _patterns: tuple[re.Pattern[str], ...] = field(default=(), repr=False, compare=False)
    _fixed_norm: frozenset[str] = field(default=frozenset(), repr=False, compare=False)

    @classmethod
    def build(
        cls, fixed: Iterable[str] = (), templates: Iterable[str] = (), lazy: Iterable[str] = ()
    ) -> Phrases:
        fixed_t = tuple(s.strip() for s in fixed if s and s.strip())
        tpl_t = tuple(s.strip() for s in templates if s and s.strip())
        lazy_t = tuple(s.strip() for s in lazy if s and s.strip())
        return cls(
            fixed_t,
            tpl_t,
            lazy_t,
            tuple(_compile(t) for t in tpl_t),
            frozenset(normalize(s) for s in fixed_t + lazy_t),
        )

    @classmethod
    def load(cls, path: Path = PHRASES_FILE) -> Phrases:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls.build(data.get("fixed") or (), data.get("templates") or (), data.get("lazy") or ())

    def cacheable(self, text: str) -> bool:
        """Frase fixa ou molde preenchido."""
        norm = normalize(text)
        return norm in self._fixed_norm or any(p.fullmatch(norm) for p in self._patterns)


def _compile(template: str) -> re.Pattern[str]:
    parts: list[str] = []
    pos = 0
    norm = normalize(template)
    for m in _PLACEHOLDER.finditer(norm):
        parts.append(re.escape(norm[pos : m.start()]))
        parts.append(r".+?")
        pos = m.end()
    parts.append(re.escape(norm[pos:]))
    return re.compile("".join(parts))


class PhraseCache:
    """PCM por chave em disco, com limite de bytes (sai o menos usado: menor mtime)."""

    def __init__(self, root: Path | None = None, max_bytes: int = DEFAULT_CACHE_MAX_BYTES) -> None:
        self.root = root if root is not None else default_cache_dir()
        self.max_bytes = max_bytes

    def _path(self, key: str) -> Path:
        return self.root / f"{key}.pcm"

    def get(self, key: str) -> bytes | None:
        path = self._path(key)
        try:
            data = path.read_bytes()
            os.utime(path)  # marca como usado (LRU)
        except OSError:
            return None
        return data or None

    def __contains__(self, key: str) -> bool:
        return self._path(key).is_file()

    def put(self, key: str, pcm: bytes) -> None:
        if not pcm or len(pcm) > self.max_bytes:
            return
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            tmp = self.root / f".{key}.{os.getpid()}.tmp"
            tmp.write_bytes(pcm)
            tmp.replace(self._path(key))
            self._evict()
        except OSError as e:
            log.warning("cache de TTS: não gravou %s: %s", key, e)

    def size(self) -> int:
        return sum(p.stat().st_size for p in self.root.glob("*.pcm"))

    def _evict(self) -> None:
        entries = []
        for p in self.root.glob("*.pcm"):
            with contextlib.suppress(OSError):
                st = p.stat()
                entries.append((st.st_mtime_ns, st.st_size, p))
        total = sum(e[1] for e in entries)
        for _, sz, p in sorted(entries, key=lambda e: e[0]):
            if total <= self.max_bytes:
                break
            with contextlib.suppress(OSError):
                p.unlink()
                total -= sz


ProviderSource = TtsProvider | Callable[[], TtsProvider]


class PhraseSpeaker:
    """``Speaker`` com cache de frases curtas e TTS em streaming (R12.1, R12.2).

    ``provider``: o ``TtsProvider`` ou uma função que o devolve (ex.: ``registry.tts``, para
    acompanhar releituras da config). ``voice``: voz configurada (``[tasks].tts.voice``) ou
    função que a devolve; sem ela, usa ``provider.voice`` se existir. Entra na chave do cache.
    """

    def __init__(
        self,
        provider: ProviderSource,
        *,
        voice: str | Callable[[], str] | None = None,
        phrases: Phrases | None = None,
        cache: PhraseCache | None = None,
        auto_warm: bool = True,
    ) -> None:
        self._provider = provider
        self._voice = voice
        self.phrases = phrases if phrases is not None else Phrases.load()
        self.cache = cache if cache is not None else PhraseCache()
        self._auto_warm = auto_warm
        self._warm_task: asyncio.Task[int] | None = None

    # -- chave -------------------------------------------------------------------------------

    def provider(self) -> TtsProvider:
        p = self._provider
        return p if isinstance(p, TtsProvider) or not callable(p) else p()

    def voice(self, provider: TtsProvider) -> str:
        v = self._voice
        if v is None:
            return str(getattr(provider, "voice", "") or "")
        return v() if callable(v) else v

    def key(self, text: str, provider: TtsProvider | None = None) -> str:
        p = provider if provider is not None else self.provider()
        fmt = p.output_format
        raw = "\x1f".join(
            (
                normalize(text),
                p.name,
                p.model,
                self.voice(p),
                f"{fmt.rate}/{fmt.width}/{fmt.channels}",
            )
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    # -- Speaker -----------------------------------------------------------------------------

    async def say(
        self, text: str, link: SatelliteLink, *, personal: bool, on_sentence: OnSentence | None = None
    ) -> None:
        text = _SPACES.sub(" ", text).strip()
        if not text:
            return
        self._start_warm()
        provider = self.provider()
        await link.play(self._speak_all(provider, _one(text), personal, on_sentence), provider.output_format)

    async def say_stream(
        self,
        texts: AsyncIterable[str],
        link: SatelliteLink,
        *,
        personal: bool,
        on_sentence: OnSentence | None = None,
    ) -> None:
        """Fala as frases de ``texts`` conforme chegam, num único envio ao satélite (1.24)."""
        self._start_warm()
        provider = self.provider()
        await link.play(self._speak_all(provider, texts, personal, on_sentence), provider.output_format)

    async def _speak_all(
        self,
        provider: TtsProvider,
        texts: AsyncIterable[str],
        personal: bool,
        on_sentence: OnSentence | None = None,
    ) -> AsyncIterator[bytes]:
        clock = _Playhead(provider.output_format, on_sentence) if on_sentence is not None else None
        whole = bool(getattr(provider, "whole_sentence", False))
        try:
            async for raw in texts:
                text = _SPACES.sub(" ", raw).strip()
                if not text:
                    continue
                audio = self._speak(provider, text, personal)
                if clock is None:
                    async for pcm in audio:
                        yield pcm
                    continue
                known: int | None = None
                if whole or self._in_cache(provider, text):
                    # o áudio da frase sai inteiro de uma vez: junta para saber a duração antes de tocar
                    parts = [pcm async for pcm in audio]
                    known = sum(map(len, parts))
                    audio = _replay(parts)
                first = True
                async for pcm in audio:
                    if first:
                        clock.start(text, known)
                        first = False
                    clock.advance(len(pcm))
                    yield pcm
        except BaseException:
            if clock is not None:
                clock.cancel()  # interrompida: as frases que ainda iam "começar" não avisam mais
            raise

    def _in_cache(self, provider: TtsProvider, text: str) -> bool:
        return self.phrases.cacheable(text) and self.key(text, provider) in self.cache

    async def _speak(self, provider: TtsProvider, text: str, personal: bool) -> AsyncIterator[bytes]:
        """PCM de uma frase: do cache se houver; senão do TTS (e vai para o cache se for frase
        conhecida). Sem o silêncio inicial."""
        fmt = provider.output_format
        cacheable = self.phrases.cacheable(text)
        key = self.key(text, provider) if cacheable else ""
        if cacheable and (pcm := self._cached(key, fmt)) is not None:
            async for chunk in _chunks(pcm, fmt):
                yield chunk
            return
        sink: list[bytes] | None = [] if cacheable else None
        stream = _SafeStream(provider, text, personal, sink)
        async for chunk in stream:
            yield chunk
        if sink is not None and stream.ok and sink:
            self.cache.put(key, b"".join(sink))

    def _cached(self, key: str, fmt: PcmFormat) -> bytes | None:
        """PCM do cache sem o silêncio inicial; entrada antiga (anterior à 1.24) é regravada cortada."""
        pcm = self.cache.get(key)
        if pcm is None:
            return None
        trimmed = trim_silence(pcm, fmt)
        if len(trimmed) != len(pcm) and trimmed:
            self.cache.put(key, trimmed)
        return trimmed or pcm

    # -- pré-geração -------------------------------------------------------------------------

    async def warm(self) -> int:
        """Gera as frases fixas que faltam no cache. Devolve quantas gerou."""
        made = 0
        provider = self.provider()
        for text in self.phrases.fixed:
            key = self.key(text, provider)
            if key in self.cache:
                continue
            sink: list[bytes] = []
            stream = _SafeStream(provider, text, False, sink)  # texto fixo, sem dado pessoal
            async for _ in stream:
                pass
            if not stream.ok:
                break  # sem rede/chave: tenta de novo noutro uso
            if sink:
                self.cache.put(key, b"".join(sink))
                made += 1
        return made

    def _start_warm(self) -> None:
        if not self._auto_warm or self._warm_task is not None:
            return
        self._warm_task = asyncio.get_running_loop().create_task(self.warm(), name="tts-warm")

    def invalidate(self) -> None:
        """Voz/modelo do TTS mudou (recarga a quente, 1.22): as chaves antigas deixam de casar (a
        voz entra na chave) e a pré-geração roda de novo no próximo ``say``, com a voz nova. As
        frases da voz anterior ficam no disco até o LRU tirá-las (voltar a ela não gasta de novo)."""
        task, self._warm_task = self._warm_task, None
        if task is not None and not task.done():
            task.cancel()

    async def aclose(self) -> None:
        task, self._warm_task = self._warm_task, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


class _SafeStream:
    """Fluxo do provedor que nunca levanta: erro vira fim do áudio e ``ok = False``."""

    def __init__(self, provider: TtsProvider, text: str, personal: bool, sink: list[bytes] | None) -> None:
        self._provider = provider
        self._text = text
        self._personal = personal
        self._sink = sink
        self.ok = False

    def __aiter__(self) -> AsyncIterator[bytes]:
        return self._run()

    async def _run(self) -> AsyncIterator[bytes]:
        try:
            raw = self._provider.synthesize(self._text, personal=self._personal)
            async for pcm in trim_lead(raw, self._provider.output_format):
                if not pcm:
                    continue
                if self._sink is not None:
                    self._sink.append(pcm)
                yield pcm
        except Exception as e:  # noqa: BLE001 - erro do TTS não trava o turno
            log.warning("TTS falhou (%s): %s", type(e).__name__, e)
            return
        self.ok = True


async def _chunks(pcm: bytes, fmt: PcmFormat) -> AsyncIterator[bytes]:
    step = max(fmt.bytes_for_ms(CHUNK_MS), fmt.width * fmt.channels)
    for i in range(0, len(pcm), step):
        yield pcm[i : i + step]


async def _one(text: str) -> AsyncIterator[str]:
    yield text


async def _replay(parts: list[bytes]) -> AsyncIterator[bytes]:
    for pcm in parts:
        yield pcm


class _Playhead:
    """Relógio da reprodução no satélite para a legenda sincronizada.

    O envio ao satélite vai mais rápido que o tempo real (ele enfileira), então a frase ``n``
    começa a tocar quando as anteriores acabam ou agora, se o satélite já esvaziou a fila. Nesse
    instante (``call_later``) avisa ``on_sentence(texto, duração, índice)``. ``advance`` soma o
    áudio enviado; ``cancel`` descarta os avisos ainda agendados (interrupção)."""

    def __init__(self, fmt: PcmFormat, on_sentence: OnSentence) -> None:
        self._bps = max(1, fmt.rate * fmt.width * fmt.channels)
        self._on = on_sentence
        self._end = 0.0  # loop.time() em que o áudio já enviado termina de tocar
        self._index = 0
        self._handles: list[asyncio.TimerHandle] = []

    def start(self, text: str, nbytes: int | None) -> None:
        loop = asyncio.get_running_loop()
        now = loop.time()
        begin = max(now, self._end)
        self._end = begin
        dur = None if nbytes is None else nbytes / self._bps
        index, self._index = self._index, self._index + 1
        if begin - now < 0.005:
            self._fire(text, dur, index)
        else:
            self._handles.append(loop.call_later(begin - now, self._fire, text, dur, index))

    def advance(self, nbytes: int) -> None:
        self._end += nbytes / self._bps

    def cancel(self) -> None:
        for handle in self._handles:
            handle.cancel()
        self._handles.clear()

    def _fire(self, text: str, dur: float | None, index: int) -> None:
        try:
            self._on(text, dur, index)
        except Exception as e:  # noqa: BLE001 - legenda nunca trava a fala
            log.warning("aviso de frase falhou (%s): %s", type(e).__name__, e)
