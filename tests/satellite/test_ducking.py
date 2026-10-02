"""Ducking com pulsectl falso: nunca toca no volume real."""

import json
from types import SimpleNamespace

from magi.satellite.ducking import Ducker, is_game, restore_file_path, should_duck


class PulseIndexError(Exception):
    """Mesmo nome da exceção do pulsectl (o Ducker reconhece pelo nome)."""


def si(index, name="", binary="", pid=None, vol=(1.0, 1.0), **extra):
    props = {"application.name": name, "application.process.binary": binary, **extra}
    if pid is not None:
        props["application.process.id"] = str(pid)
    return SimpleNamespace(index=index, proplist=props, volume=SimpleNamespace(values=list(vol)))


class FakePulse:
    def __init__(self, streams, path=None):
        self.streams = {s.index: s for s in streams}
        self.path = path
        self.closed = False
        self.file_before_set = []
        self.fail = None

    def sink_input_list(self):
        if self.fail:
            raise self.fail
        return list(self.streams.values())

    def volume_set_all_chans(self, obj, vol):
        if obj.index not in self.streams:
            raise PulseIndexError(obj.index)
        if self.path is not None:  # o original já tem que estar no arquivo
            data = json.loads(self.path.read_text())
            self.file_before_set.append(any(e["index"] == obj.index for e in data["streams"]))
        s = self.streams[obj.index]
        s.volume.values = [vol] * len(s.volume.values)

    def sink_input_volume_set(self, index, vol):
        if index not in self.streams:
            raise PulseIndexError(index)
        self.streams[index].volume.values = list(vol.values)

    def close(self):
        self.closed = True


def environ(pid):
    return {7: b"HOME=/x\0SteamAppId=870780\0", 8: b"SteamAppId=0\0", 9: b"PATH=/bin\0"}[pid]


def make(pulse, path):
    return Ducker(path=path, pulse_factory=lambda: pulse,
                  volume_factory=lambda v: SimpleNamespace(values=list(v)), read_environ=environ)


def vols(pulse):
    return {i: s.volume.values for i, s in pulse.streams.items()}


def test_restore_file_path():
    assert str(restore_file_path({"XDG_RUNTIME_DIR": "/run/user/5"})) == "/run/user/5/magi/duck-restore.json"


def test_quem_sofre_ducking():
    assert should_duck(si(1, "spotify"), environ)
    assert should_duck(si(1, "x", **{"pipewire.access.portal.app_id": "com.spotify.Client"}),
                       environ)
    assert should_duck(si(1, " ", "wine64-preloader"), environ)
    assert is_game(si(1, "Game", "game.bin", pid=7), environ)
    assert not is_game(si(1, "steamwebhelper", pid=8), environ)  # SteamAppId=0
    assert not should_duck(si(1, "Firefox", "firefox", pid=9), environ)
    assert not should_duck(si(1, "WEBRTC VoiceEngine", "Discord"), environ)
    assert not should_duck(si(1, "magi", "spotify"), environ)  # nosso próprio fluxo


async def test_duck_grava_antes_e_restaura(tmp_path):
    path = tmp_path / "magi" / "duck-restore.json"
    pulse = FakePulse([
        si(1, "spotify", vol=(0.4, 0.4)),
        si(2, " ", "wine64-preloader", vol=(1.0, 0.8)),
        si(3, "Firefox", "firefox", pid=9),
        si(4, "magi"),
        si(5, "spotify", vol=(0.2, 0.2)),  # já abaixo de 0,30: nunca aumenta
    ], path)
    d = make(pulse, path)
    assert await d.duck() == 2
    assert pulse.file_before_set == [True, True]
    assert vols(pulse) == {1: [0.3, 0.3], 2: [0.3, 0.3], 3: [1.0, 1.0], 4: [1.0, 1.0], 5: [0.2, 0.2]}
    assert await d.duck() == 0  # idempotente: não regrava 0,30 como "original"
    assert await d.restore() == 2
    assert vols(pulse)[1] == [0.4, 0.4] and vols(pulse)[2] == [1.0, 0.8]
    assert not path.exists()
    await d.close()


async def test_fluxo_novo_durante_a_fala(tmp_path):
    path = tmp_path / "duck.json"
    pulse = FakePulse([si(1, "spotify")])
    d = make(pulse, path)
    await d.duck()
    pulse.streams[2] = si(2, "Game", pid=7)
    assert await d.duck() == 1
    await d.restore()
    assert vols(pulse) == {1: [1.0, 1.0], 2: [1.0, 1.0]}


async def test_recupera_apos_queda(tmp_path):
    path = tmp_path / "duck.json"
    pulse = FakePulse([si(1, "spotify", vol=(0.7, 0.7))])
    await make(pulse, path).duck()  # "cai" sem restaurar
    assert path.exists() and vols(pulse)[1] == [0.3, 0.3]
    assert await make(pulse, path).recover() == 1
    assert vols(pulse)[1] == [0.7, 0.7] and not path.exists()


async def test_fluxo_sumiu_aplica_no_proximo_do_mesmo_app(tmp_path):
    path = tmp_path / "duck.json"
    pulse = FakePulse([si(1, "spotify", vol=(0.7, 0.7))])
    await make(pulse, path).duck()
    del pulse.streams[1]  # Spotify fechou durante a queda
    d = make(pulse, path)
    assert await d.recover() == 0
    assert json.loads(path.read_text())["streams"][0]["pending"] is True
    # o WirePlumber reabre o Spotify com o 0,30 salvo; a próxima operação corrige
    pulse.streams[9] = si(9, "spotify", vol=(0.3, 0.3))
    await d.duck()  # aplica o original pendente e então abaixa de novo, guardando 0,7
    assert vols(pulse)[9] == [0.3, 0.3]
    await d.restore()
    assert vols(pulse)[9] == [0.7, 0.7] and not path.exists()


async def test_erro_do_pipewire_nao_derruba(tmp_path):
    pulse = FakePulse([si(1, "spotify")])
    pulse.fail = OSError("sem pipewire")
    d = make(pulse, tmp_path / "duck.json")
    assert await d.duck() == 0
    assert pulse.closed
    assert await d.recover() == 0  # sem arquivo: nada a fazer
