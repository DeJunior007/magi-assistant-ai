"""Voz no núcleo (tarefa 1.12; R12.1, R12.2; §4.1 ``tts``).

``PhraseSpeaker`` implementa ``Speaker``: fala um texto no satélite pelo ``SatelliteLink.play``.

- Frase curta frequente (``phrases.yaml``) já em cache → toca o PCM do disco, sem rede (R12.2).
- Senão → sintetiza em streaming pelo ``TtsProvider`` e repassa os blocos ao satélite conforme
  chegam (R12.1). Se o texto é uma frase conhecida (fixa ou molde com placeholder preenchido),
  o áudio completo vai para o cache ao fim.
- As fixas são pré-geradas no primeiro uso (``warm``, disparado em segundo plano no primeiro
  ``say``). Chave = hash de texto normalizado + provedor + modelo + voz + formato: trocar a voz
  invalida. Cache em ``~/.cache/magi/tts/`` com limite de tamanho (LRU por mtime).
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
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from magi.common.contracts import CHUNK_MS, PcmFormat, SatelliteLink, TtsProvider

log = logging.getLogger(__name__)

PHRASES_FILE = Path(__file__).with_name("phrases.yaml")
DEFAULT_CACHE_MAX_BYTES = 64 * 1024 * 1024
_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_SPACES = re.compile(r"\s+")


def default_cache_dir(env: dict[str, str] | None = None) -> Path:
    env = dict(os.environ) if env is None else env
    base = env.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "magi" / "tts"


def normalize(text: str) -> str:
    """Forma usada na comparação e na chave: sem espaços extras, sem caixa."""
    return _SPACES.sub(" ", text).strip().casefold()


@dataclass(frozen=True, slots=True)
class Phrases:
    """Frases fixas e moldes com placeholder (``{game}``)."""

    fixed: tuple[str, ...] = ()
    templates: tuple[str, ...] = ()
    _patterns: tuple[re.Pattern[str], ...] = field(default=(), repr=False, compare=False)
    _fixed_norm: frozenset[str] = field(default=frozenset(), repr=False, compare=False)

    @classmethod
    def build(cls, fixed: Iterable[str] = (), templates: Iterable[str] = ()) -> Phrases:
        fixed_t = tuple(s.strip() for s in fixed if s and s.strip())
        tpl_t = tuple(s.strip() for s in templates if s and s.strip())
        return cls(
            fixed_t,
            tpl_t,
            tuple(_compile(t) for t in tpl_t),
            frozenset(normalize(s) for s in fixed_t),
        )

    @classmethod
    def load(cls, path: Path = PHRASES_FILE) -> Phrases:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls.build(data.get("fixed") or (), data.get("templates") or ())

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

    async def say(self, text: str, link: SatelliteLink, *, personal: bool) -> None:
        text = _SPACES.sub(" ", text).strip()
        if not text:
            return
        self._start_warm()
        provider = self.provider()
        fmt = provider.output_format
        cacheable = self.phrases.cacheable(text)
        key = self.key(text, provider) if cacheable else ""
        if cacheable and (pcm := self.cache.get(key)) is not None:
            await link.play(_chunks(pcm, fmt), fmt)
            return
        sink: list[bytes] | None = [] if cacheable else None
        stream = _SafeStream(provider, text, personal, sink)
        await link.play(stream, fmt)
        if sink is not None and stream.ok and sink:
            self.cache.put(key, b"".join(sink))

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
            async for pcm in self._provider.synthesize(self._text, personal=self._personal):
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
