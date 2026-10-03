"""Mudo só do Discord no atalho (5.2, R2.3, R2.4) com ``pulsectl`` falso (regra 8)."""

import asyncio
import json
from types import SimpleNamespace

from magi.satellite.discord import DiscordPttMuter, mute_file_path
from magi.satellite.ptt import PttSource, PushToTalk


class PulseIndexError(Exception):
    pass


def so(index, name="WEBRTC VoiceEngine", binary="Discord", mute=False):
    props = {"application.name": name, "application.process.binary": binary}
    return SimpleNamespace(index=index, proplist=props, corked=False, mute=mute)


MIC_MAGUI = so(5, "magi-satellite", "python3")  # nosso fluxo de captura: nunca mexer


class FakePulse:
    def __init__(self, streams):
        self.streams = {s.index: s for s in streams}
        self.calls: list[tuple[int, bool]] = []
        self.closed = False

    def source_output_list(self):
        return list(self.streams.values())

    def source_output_mute(self, index, mute):
        if index not in self.streams:
            raise PulseIndexError(index)
        self.calls.append((index, mute))
        s = self.streams[index]
        self.streams[index] = SimpleNamespace(**{**vars(s), "mute": mute})

    def close(self):
        self.closed = True

    def muted(self, index):
        return self.streams[index].mute


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def make(pulse, tmp_path, in_call=True, clock=None):
    flag = {"in_call": in_call}
    m = DiscordPttMuter(lambda: flag["in_call"], pulse_factory=lambda: pulse,
                        path=tmp_path / "magi" / "discord-muted", clock=clock or Clock())
    return m, flag


def test_caminho_padrao_do_arquivo():
    assert str(mute_file_path({"XDG_RUNTIME_DIR": "/run/user/7"})) == "/run/user/7/magi/discord-muted"


def test_aperto_muta_so_discord_e_soltura_restaura_depois_da_folga(tmp_path):
    pulse = FakePulse([so(10), MIC_MAGUI])
    clock = Clock()
    m, _ = make(pulse, tmp_path, clock=clock)

    async def go():
        m.on_ptt(True)
        assert await m.step() == m.poll_s
        assert pulse.muted(10) and not pulse.muted(5)
        saved = json.loads(m.path.read_text())["streams"]
        assert saved == [{"index": 10, "app": "WEBRTC VoiceEngine", "was_muted": False}]
        clock.t = 1.0
        m.on_ptt(False)
        left = await m.step()  # ainda na folga: continua mutado
        assert 0 < left <= m.grace_s and pulse.muted(10)
        clock.t = 1.0 + m.grace_s + 0.01
        assert await m.step() is None
        assert not pulse.muted(10)
        assert not m.path.exists()
        await m.close()

    asyncio.run(go())
    assert pulse.calls == [(10, True), (10, False)]


def test_ligacao_com_push_to_talk(tmp_path):
    pulse = FakePulse([so(10)])
    m, _ = make(pulse, tmp_path)
    ptt = PushToTalk()
    ptt.subscribe(m.on_ptt)
    ptt.set(PttSource.DUALSENSE, True)
    assert m._pressed and m._wake.is_set()
    ptt.set(PttSource.DUALSENSE, False)
    assert not m._pressed


def test_ja_mutado_pelo_usuario_continua_mutado(tmp_path):
    pulse = FakePulse([so(10, mute=True)])
    m, _ = make(pulse, tmp_path, clock=Clock())

    async def go():
        m.on_ptt(True)
        await m.step()
        m.on_ptt(False)
        m.clock.t = 10
        await m.step()
        await m.close()

    asyncio.run(go())
    assert pulse.calls == []
    assert pulse.muted(10)
    assert not m.path.exists()


def test_fora_de_call_nao_mexe(tmp_path):
    pulse = FakePulse([so(10)])
    m, _ = make(pulse, tmp_path, in_call=False)

    async def go():
        m.on_ptt(True)
        assert await m.step() is None
        m.on_ptt(False)
        await m.step()
        await m.close()

    asyncio.run(go())
    assert pulse.calls == []
    assert not m.path.exists()


def test_troca_de_stream_no_meio_aplica_ao_novo(tmp_path):
    pulse = FakePulse([so(10)])
    m, _ = make(pulse, tmp_path, clock=Clock())

    async def go():
        m.on_ptt(True)
        await m.step()
        # Discord fecha o fluxo 10 e abre o 11; o WirePlumber o reabre já mutado (S1)
        del pulse.streams[10]
        pulse.streams[11] = so(11, mute=True)
        await m.step()
        pulse.streams[12] = so(12)  # outro fluxo novo, desmutado: muta também
        await m.step()
        assert pulse.muted(12)
        m.on_ptt(False)
        m.clock.t = 10
        await m.step()
        await m.close()

    asyncio.run(go())
    assert not pulse.muted(11) and not pulse.muted(12)  # herdou "não estava mutado"
    assert not m.path.exists()


def test_recuperacao_apos_queda(tmp_path):
    pulse = FakePulse([so(10)])
    m, _ = make(pulse, tmp_path)

    async def crash():
        m.on_ptt(True)
        await m.step()  # mutou e gravou o arquivo; o processo "morre" aqui (kill -9)

    asyncio.run(crash())
    assert pulse.muted(10) and m.path.exists()

    m2, _ = make(pulse, tmp_path)

    async def restart():
        assert await m2.recover() == 1
        await m2.close()

    asyncio.run(restart())
    assert not pulse.muted(10)
    assert not m2.path.exists()


def test_recuperacao_com_fluxo_novo_reaberto_mutado(tmp_path):
    path = tmp_path / "magi" / "discord-muted"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"streams": [{"index": 10, "app": "WEBRTC VoiceEngine", "was_muted": False}]}))
    pulse = FakePulse([])  # Discord fechado: fica pendente
    m, _ = make(pulse, tmp_path)

    async def go():
        assert await m.recover() == 0
        assert path.exists()
        pulse.streams[20] = so(20, mute=True)  # Discord volta; WirePlumber reabre mutado
        assert await m.step() is None
        await m.close()

    asyncio.run(go())
    assert not pulse.muted(20)
    assert not path.exists()


def test_recuperacao_respeita_quem_ja_estava_mutado(tmp_path):
    path = tmp_path / "magi" / "discord-muted"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"streams": [{"index": 10, "app": "WEBRTC VoiceEngine", "was_muted": True}]}))
    pulse = FakePulse([so(10, mute=True)])
    m, _ = make(pulse, tmp_path)

    async def go():
        await m.recover()
        await m.close()

    asyncio.run(go())
    assert pulse.calls == [] and pulse.muted(10)
    assert not path.exists()


def test_run_completo_e_sair_mutado_desmuta(tmp_path):
    pulse = FakePulse([so(10)])
    m, _ = make(pulse, tmp_path)
    m.poll_s = 0.01

    async def go():
        task = asyncio.create_task(m.run())
        m.on_ptt(True)
        for _ in range(50):
            await asyncio.sleep(0.005)
            if pulse.calls:
                break
        assert pulse.muted(10)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(go())
    assert not pulse.muted(10) and pulse.closed
    assert not m.path.exists()
