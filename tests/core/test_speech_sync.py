"""Legenda sincronizada com a fala: aviso de frase (``speech``) com a duração do áudio."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from magi.common.contracts import SpeechMsg, TurnState
from magi.core.tts import _Playhead

from .test_stream_speech import CTX, FMT, FakeLink, PcmTts, StreamChat, machine, pcm, speaker

SENTENCE_S = len(pcm(0)) / (FMT.rate * FMT.width * FMT.channels)  # 0,1 s depois do corte


class WholeTts(PcmTts):
    """Como o Kokoro: a frase sai inteira de uma vez, duração conhecida antes de tocar."""

    whole_sentence = True


def recorder() -> tuple[list[tuple[str, float | None, int, float]], object]:
    seen: list[tuple[str, float | None, int, float]] = []

    def on_sentence(text: str, dur: float | None, i: int) -> None:
        seen.append((text, dur, i, asyncio.get_running_loop().time()))

    return seen, on_sentence


async def two() -> AsyncIterator[str]:
    yield "Primeira frase."
    yield "Segunda frase."


async def test_uma_aviso_por_frase_com_duracao_e_no_tempo_do_audio(tmp_path):
    spk = speaker(tmp_path, WholeTts())
    link = FakeLink()
    seen, on_sentence = recorder()
    await spk.say_stream(two(), link, personal=True, on_sentence=on_sentence)
    assert [s[:3] for s in seen] == [("Primeira frase.", pytest.approx(SENTENCE_S), 0)]
    await asyncio.sleep(SENTENCE_S + 0.05)  # a 2ª só "começa" quando a 1ª acaba de tocar
    assert [s[:3] for s in seen] == [
        ("Primeira frase.", pytest.approx(SENTENCE_S), 0),
        ("Segunda frase.", pytest.approx(SENTENCE_S), 1),
    ]
    assert seen[1][3] - seen[0][3] == pytest.approx(SENTENCE_S, abs=0.03)
    assert b"".join(link.plays[0]) == pcm(0) * 2  # o áudio não muda


async def test_tts_em_streaming_avisa_sem_duracao(tmp_path):
    spk = speaker(tmp_path, PcmTts())
    seen, on_sentence = recorder()
    await spk.say_stream(two(), FakeLink(), personal=True, on_sentence=on_sentence)
    await asyncio.sleep(SENTENCE_S + 0.05)
    assert [s[:3] for s in seen] == [("Primeira frase.", None, 0), ("Segunda frase.", None, 1)]


async def test_frase_do_cache_tem_duracao_mesmo_sem_provedor_inteiro(tmp_path):
    spk = speaker(tmp_path, PcmTts(), ["Pronto."])
    await spk.say("Pronto.", FakeLink(), personal=False)  # vai para o cache
    seen, on_sentence = recorder()
    await spk.say("Pronto.", FakeLink(), personal=False, on_sentence=on_sentence)
    assert [s[:3] for s in seen] == [("Pronto.", pytest.approx(SENTENCE_S), 0)]


async def test_sem_on_sentence_nada_muda(tmp_path):
    spk = speaker(tmp_path, WholeTts())
    link = FakeLink()
    await spk.say("Uma frase só.", link, personal=True)
    assert b"".join(link.plays[0]) == pcm(0)


async def test_playhead_cancela_avisos_agendados():
    seen, on_sentence = recorder()
    clock = _Playhead(FMT, on_sentence)
    clock.start("a", 4800)
    clock.advance(4800)
    clock.start("b", 4800)  # só daqui a 0,1 s
    clock.cancel()
    await asyncio.sleep(0.15)
    assert [s[0] for s in seen] == ["a"]


async def test_turno_manda_speech_ao_hud_por_frase(tmp_path):
    chat = StreamChat([(["Uma aranha tem oito ", "patas. ", "Elas têm ", "quatro pares."], ())])
    m, link, hud, _ = machine(tmp_path, chat)
    m.pipeline.deps.speaker._provider = WholeTts()
    m._start(m._think(b"\0\0", FMT, CTX))
    await asyncio.wait_for(m._task, 1)
    await asyncio.sleep(SENTENCE_S + 0.05)
    speech = [x for x in hud.msgs if isinstance(x, SpeechMsg)]
    said = [(x.text, x.i) for x in speech]
    assert said == [("Uma aranha tem oito patas.", 0), ("Elas têm quatro pares.", 1)]
    assert all(x.dur == pytest.approx(SENTENCE_S) for x in speech)
    assert m.state is TurnState.SPEAKING  # até o playback-done


async def test_aviso_de_fala_interrompida_nao_chega_ao_hud(tmp_path):
    m, _, hud, _ = machine(tmp_path, StreamChat([]))
    on_sentence = m._captions(m.pipeline.deps.speaker.say)["on_sentence"]
    await m._cancel_work()  # nova ativação no meio da fala
    on_sentence("velha.", 1.0, 1)
    await asyncio.sleep(0)
    assert not [x for x in hud.msgs if isinstance(x, SpeechMsg)]


async def test_speaker_sem_on_sentence_continua_funcionando(tmp_path):
    m, _, _, _ = machine(tmp_path, StreamChat([]))

    async def say(text, link, *, personal):  # speaker antigo/fake
        pass

    assert m._captions(say) == {}
