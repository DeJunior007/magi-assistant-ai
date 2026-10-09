"""R2.D: volume do PipeWire (``data.Volume``, ``wpctl`` falso) e reação 31 no ``det_volume``."""

from __future__ import annotations

import threading

from wired import integration
from wired.data import Volume
from wired.main_screen import Snapshot
from wired.reacoes import det_volume
from wired.reacoes.catalogo import ATIVAS


def test_parse_da_saida_do_wpctl() -> None:
    assert Volume.parse("Volume: 0.45\n") == (45.0, False)
    assert Volume.parse("Volume: 0.30 [MUTED]\n") == (30.0, True)
    assert Volume.parse("Volume: 1.20") == (120.0, False)
    assert Volume.parse("Volume: abc") is None
    assert Volume.parse("Error: no default sink") is None
    assert Volume.parse("") is None
    assert Volume.parse(None) is None


def test_ler_com_wpctl_falso_ausente_e_quebrado() -> None:
    v = Volume(run=lambda: "Volume: 0.45")
    assert v.ler() == (45.0, False) and v.atual == (45.0, False)
    v.run = lambda: None  # wpctl ausente / rc != 0
    assert v.ler() is None and v.atual is None

    def quebra():
        raise OSError("sem wpctl")

    v.run = quebra
    assert v.ler() is None


def test_thread_le_e_para() -> None:
    lido = threading.Event()

    def run():
        lido.set()
        return "Volume: 0.50 [MUTED]"

    v = Volume(run=run, intervalo=60.0).start()
    try:
        assert lido.wait(5.0)
    finally:
        v.stop()
    v._thread.join(5.0)
    assert not v._thread.is_alive()
    assert v.atual == (50.0, True)


def tick(ctx: dict, vol, agora: float) -> list[str]:
    ctx["agora"] = agora
    return [d.chave for d in det_volume.detectar(Snapshot(), Snapshot(volume=vol), ctx)]


def test_salto_de_20pp_em_2s_dispara_31() -> None:
    ctx: dict = {}
    assert tick(ctx, (30.0, False), 10.0) == []
    assert tick(ctx, (40.0, False), 11.0) == []
    assert tick(ctx, (50.0, False), 12.0) == ["volume_alto"]  # 30 → 50 em 2 s
    assert tick(ctx, (55.0, False), 13.0) == []  # um disparo por salto


def test_subida_lenta_nao_dispara() -> None:
    ctx: dict = {}
    for i, pct in enumerate((30.0, 38.0, 46.0, 54.0, 62.0)):
        assert tick(ctx, (pct, False), 10.0 + i) == []  # 8 pp/s: nunca 20 pp em 2 s
    assert tick(ctx, (70.0, False), 20.0) == []  # 62 → 70 depois de um buraco


def test_mudo_e_sem_wpctl_nao_disparam() -> None:
    ctx: dict = {}
    assert tick(ctx, (20.0, False), 10.0) == []
    assert tick(ctx, (80.0, True), 11.0) == []  # mudo
    assert tick(ctx, (80.0, False), 12.0) == []  # desmutar não é salto
    ctx = {}
    assert tick(ctx, None, 10.0) == []
    assert tick(ctx, (90.0, False), 11.0) == []


def test_31_ativa() -> None:
    assert "volume_alto" in ATIVAS


class _SemPlayer:
    active = False


class _RedeFalsa:
    down = up = 0.0
    down_series = ()

    def poll(self, now=None):
        pass


class _GitFalso:
    head = None

    def poll(self, mono=None):
        return {"branch": "main", "added": 0, "removed": 0}


def test_integration_poe_volume_no_snapshot() -> None:
    v = Volume(run=lambda: "Volume: 0.45")
    ui = integration.WiredUI(now_playing=_SemPlayer(), net=_RedeFalsa(), git=_GitFalso(), volume=v)
    assert ui.build({}).volume is None  # thread não ligada, nada lido ainda
    v.ler()
    assert ui.build({}).volume == (45.0, False)


def test_testes_nao_ligam_a_thread() -> None:
    ui = integration.WiredUI(now_playing=_SemPlayer(), net=_RedeFalsa(), git=_GitFalso())
    assert ui.volume is None  # MAGI_NO_VOLUME=1 no conftest
    assert ui.build({}).volume is None
