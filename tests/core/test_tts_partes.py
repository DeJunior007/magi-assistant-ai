"""A2.1: ``GuardedTts.com_opcoes``, ``PhraseSpeaker.say_parts`` e o TTS Kokoro do livro (CA-A8)."""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator
from pathlib import Path

import pytest

from magi.audiolivro.contratos import OpcoesVoz
from magi.common.config import parse_config
from magi.common.contracts import PcmFormat, SatelliteHello
from magi.core.tts import PhraseCache, Phrases, PhraseSpeaker
from magi.providers.registry import GuardedTts, Registry

FMT = PcmFormat(rate=24_000)


class FakeKokoro:
    """Backend falso: guarda as opções de cada síntese; frase inteira de uma vez."""

    whole_sentence = True

    def __init__(self, cfg: object, log: list[tuple[str, dict]]) -> None:
        self.log = log

    def tts_format(self, ctx: object) -> PcmFormat:
        return FMT

    async def synthesize(self, key: object, ctx, text: str) -> AsyncIterator[bytes]:
        self.log.append((text, dict(ctx.options)))
        yield f"<{text}>".encode() * 2  # tamanho par (16 bits)

    async def warm(self, key: object) -> bool:  # pragma: no cover - não usado
        return False


class Budget:
    def __init__(self) -> None:
        self.allowed: list[object] = []

    async def ensure_allowed(self, task: object) -> None:
        self.allowed.append(task)

    async def record(self, usage: object) -> None:
        pass


class FakeLink:
    def __init__(self) -> None:
        self.hello = SatelliteHello("pc")
        self.plays: list[tuple[list[bytes], PcmFormat]] = []

    async def send(self, msg: object) -> None:  # pragma: no cover
        pass

    async def play(self, audio: AsyncIterable[bytes], fmt: PcmFormat) -> None:
        self.plays.append(([pcm async for pcm in audio], fmt))


def config(tts: dict) -> object:
    return parse_config(
        {
            "providers": {"openai": {"keys": ["openai-1"]}, "kokoro": {"keys": [], "local": True}},
            "tasks": {"stt": {"provider": "openai", "model": "stt-x"}, "tts": tts,
                      "agent": {"provider": "openai", "model": "chat-x"}},
            "speech": {"language": "pt-br"},
        }
    )


def registry(cfg: object, log: list) -> Registry:
    backends = {"kokoro": lambda c: FakeKokoro(c, log), "openai": lambda c: FakeKokoro(c, log)}
    return Registry(cfg, Budget(), backends=backends, get_secret=lambda name: "sk-teste")


def speaker(tmp_path: Path, provider: object) -> PhraseSpeaker:
    phrases = Phrases.build(["Era uma vez."], [])
    return PhraseSpeaker(provider, phrases=phrases, cache=PhraseCache(tmp_path / "tts"), auto_warm=False)


KOKORO = {"provider": "kokoro", "model": "kokoro-v1.0", "voice": "pf_dora", "lang": "pt-br"}


def test_com_opcoes_mescla_e_preserva(tmp_path: Path) -> None:
    log: list = []
    base = registry(config(KOKORO), log).tts()
    copia = base.com_opcoes(voice="pm_alex", speed=1.2, lang=None)
    assert isinstance(copia, GuardedTts) and copia is not base
    assert copia._ctx.options == {"voice": "pm_alex", "lang": "pt-br", "speed": 1.2}
    assert base._ctx.options == {"voice": "pf_dora", "lang": "pt-br"}  # original intacto
    assert copia._pool is base._pool and copia._budget is base._budget
    assert copia.whole_sentence and copia.output_format == base.output_format
    assert copia.voice == "pm_alex"
    assert base.com_opcoes() is base


async def test_say_parts_opcoes_por_parte_e_pausa(tmp_path: Path) -> None:
    log: list = []
    tts = registry(config(KOKORO), log).tts()
    sp = speaker(tmp_path, tts)
    link = FakeLink()
    partes = [
        ("Era uma vez.", OpcoesVoz(pausa_ms=250)),
        ("— Quem está aí?", OpcoesVoz(voice="pm_alex", speed=1.1, pausa_ms=100)),
        ("   ", OpcoesVoz(pausa_ms=40)),
        ("Ninguém respondeu.", OpcoesVoz(voice="pf_dora", lang="pt-br")),
    ]
    await sp.say_parts(partes, link, personal=False)

    assert log == [
        ("Era uma vez.", {"voice": "pf_dora", "lang": "pt-br"}),
        ("— Quem está aí?", {"voice": "pm_alex", "lang": "pt-br", "speed": 1.1}),
        ("Ninguém respondeu.", {"voice": "pf_dora", "lang": "pt-br"}),
    ]
    (chunks, fmt), = link.plays
    assert fmt == FMT
    audio = b"".join(chunks)
    a, b, c = (f"<{t}>".encode() * 2 for t in ("Era uma vez.", "— Quem está aí?", "Ninguém respondeu."))
    pausa = lambda ms: b"\x00" * (FMT.rate * ms // 1000 * FMT.width * FMT.channels)  # noqa: E731
    assert audio == a + pausa(250) + b + pausa(100) + pausa(40) + c
    assert len(pausa(250)) == 12_000  # 24 kHz, 16 bits, mono
    assert not list((tmp_path / "tts").glob("*"))  # frase conhecida não foi ao cache


async def test_say_parts_fluxo_assincrono_e_provedor_explicito(tmp_path: Path) -> None:
    log: list = []
    reg = registry(config(KOKORO), log)
    sp = speaker(tmp_path, lambda: pytest.fail("não deve usar o TTS da fala"))

    async def partes() -> AsyncIterator[tuple[str, OpcoesVoz]]:
        yield "Um.", OpcoesVoz(speed=0.9)
        yield "Dois.", OpcoesVoz(speed=0.9)

    await sp.say_parts(partes(), FakeLink(), personal=True, provider=reg.tts_livro())
    assert [o for _, o in log] == [{"voice": "pf_dora", "lang": "pt-br", "speed": 0.9}] * 2


async def test_say_e_say_stream_continuam_iguais(tmp_path: Path) -> None:
    log: list = []
    sp = speaker(tmp_path, registry(config(KOKORO), log).tts())
    link = FakeLink()
    await sp.say("Era uma vez.", link, personal=False)
    await sp.say("Era uma vez.", link, personal=False)  # do cache
    assert len(log) == 1 and len(link.plays) == 2
    assert link.plays[0][0] and b"".join(link.plays[0][0]) == b"".join(link.plays[1][0])


def test_tts_livro_e_kokoro_mesmo_com_openai() -> None:
    log: list = []
    reg = registry(config({"provider": "openai", "model": "tts-x", "voice": "nova"}), log)
    livro = reg.tts_livro()
    assert reg.tts().name == "openai"
    assert livro.name == "kokoro"
    assert livro._ctx.options == {"voice": "pf_dora", "lang": "pt-br"}
    assert reg.tts_livro() is livro


def test_tts_livro_reusa_o_kokoro_ativo() -> None:
    reg = registry(config(KOKORO), [])
    assert reg.tts_livro() is reg.tts()


def test_tts_livro_sem_kokoro_no_providers() -> None:
    cfg = parse_config(
        {
            "providers": {"openai": {"keys": ["openai-1"]}},
            "tasks": {"tts": {"provider": "openai", "model": "tts-x"}},
        }
    )
    reg = Registry(cfg, Budget(), backends={"kokoro": lambda c: FakeKokoro(c, []),
                                            "openai": lambda c: FakeKokoro(c, [])},
                   get_secret=lambda name: "sk-teste")
    livro = reg.tts_livro()
    assert livro.name == "kokoro" and livro.free_tier


def test_tts_livro_refeito_quando_tts_muda() -> None:
    reg = registry(config({"provider": "openai", "model": "tts-x"}), [])
    antes = reg.tts_livro()
    reg.reload(config({"provider": "openai", "model": "tts-y", "voice": "alloy"}))
    assert reg.tts_livro() is not antes


async def test_say_parts_on_sentence_indice_continuo(tmp_path: Path) -> None:
    sp = speaker(tmp_path, registry(config(KOKORO), []).tts())
    avisos: list[tuple[str, int]] = []
    partes = [("Um.", OpcoesVoz()), ("", OpcoesVoz()), ("Dois.", OpcoesVoz(voice="pm_alex")),
              ("Três.", OpcoesVoz())]
    await sp.say_parts(partes, FakeLink(), personal=False, on_sentence=lambda t, d, i: avisos.append((t, i)))
    # sem pausa, cada frase dura < 5 ms: os avisos saem na hora (sem relógio real)
    assert avisos == [("Um.", 0), ("Dois.", 1), ("Três.", 2)]


async def test_say_parts_on_done_espera_o_audio_tocar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``on_done`` sai quando o áudio enviado acaba de tocar (relógio da reprodução), não quando o
    envio acaba; relógio do loop falso (sem sleep real)."""
    import asyncio

    loop = asyncio.get_running_loop()
    agora = [loop.time()]
    monkeypatch.setattr(loop, "time", lambda: agora[0])
    sp = speaker(tmp_path, registry(config(KOKORO), []).tts())
    feitos: list[str] = []
    partes = [("Um.", OpcoesVoz(pausa_ms=500)), ("Dois.", OpcoesVoz(pausa_ms=500))]
    await sp.say_parts(partes, FakeLink(), personal=False, on_done=lambda: feitos.append("fim"))
    await asyncio.sleep(0)
    assert feitos == []  # ~1 s de áudio ainda na fila do satélite
    agora[0] += 0.9
    await asyncio.sleep(0)
    assert feitos == []
    agora[0] += 0.2
    for _ in range(3):
        await asyncio.sleep(0)
    assert feitos == ["fim"]


async def test_say_parts_on_done_vem_das_partes_e_nao_sai_se_interrompido(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    loop = asyncio.get_running_loop()
    agora = [loop.time()]
    monkeypatch.setattr(loop, "time", lambda: agora[0])
    sp = speaker(tmp_path, registry(config(KOKORO), []).tts())
    feitos: list[str] = []

    class Partes:
        def __init__(self, itens: list) -> None:
            self._it = iter(itens)
            self.on_done = lambda: feitos.append("fim")

        def __aiter__(self) -> Partes:
            return self

        async def __anext__(self) -> tuple[str, OpcoesVoz]:
            try:
                return next(self._it)
            except StopIteration:
                raise StopAsyncIteration from None

    await sp.say_parts(Partes([("Um.", OpcoesVoz())]), FakeLink(), personal=False)
    agora[0] += 1.0
    for _ in range(3):
        await asyncio.sleep(0)
    assert feitos == ["fim"]

    class LinkQueCorta(FakeLink):
        async def play(self, audio: AsyncIterable[bytes], fmt: PcmFormat) -> None:
            async for _ in audio:
                raise asyncio.CancelledError  # ativação no meio da leitura

    feitos.clear()
    with pytest.raises(asyncio.CancelledError):
        await sp.say_parts(Partes([("Um.", OpcoesVoz()), ("Dois.", OpcoesVoz())]), LinkQueCorta(),
                           personal=False)
    agora[0] += 1.0
    for _ in range(3):
        await asyncio.sleep(0)
    assert feitos == []
