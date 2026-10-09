"""R2.G: sinais menores (hwmon falso, ``dnf`` falso, pasta de capturas em ``tmp_path``) e ``det_extras``."""

from __future__ import annotations

import os
from datetime import datetime

from wired import integration
from wired.data import Capturas, Reinicio, Ventoinha
from wired.main_screen import Snapshot
from wired.reacoes import det_extras
from wired.reacoes.catalogo import ATIVAS, DEFS


def _chaves(disparos) -> list[str]:
    return [d.chave for d in disparos]


def _hwmon(raiz, rpms: dict[str, int]) -> None:
    for nome, rpm in rpms.items():
        hw, fan = nome.split("/")
        (raiz / hw).mkdir(parents=True, exist_ok=True)
        (raiz / hw / f"{fan}_input").write_text(f"{rpm}\n")


# --- ventoinha (43) ---

def test_ventoinha_le_o_maior_fan_e_faz_media(tmp_path) -> None:
    _hwmon(tmp_path, {"hwmon0/fan1": 800, "hwmon1/fan2": 1000})
    (tmp_path / "hwmon2").mkdir()
    (tmp_path / "hwmon2" / "fan3_input").write_text("lixo")
    t = [0.0]
    v = Ventoinha(raiz=tmp_path, clock=lambda: t[0])
    assert v.ler() == (1000.0, 1000.0)
    t[0] = 10.0
    _hwmon(tmp_path, {"hwmon1/fan2": 2000})
    assert v.ler() == (2000.0, 1500.0)
    t[0] = 400.0  # leituras de > 5 min saem da média
    assert v.ler() == (2000.0, 2000.0)


def test_ventoinha_sem_hwmon_e_none(tmp_path) -> None:
    assert Ventoinha(raiz=tmp_path).ler() is None
    assert Ventoinha(raiz=tmp_path / "nao_existe").ler() is None


def test_43_dispara_uma_vez_por_episodio() -> None:
    ctx: dict = {}
    snap = Snapshot()
    snap.fan = (1000.0, 1000.0)
    assert det_extras.detectar(None, snap, ctx) == []
    snap.fan = (1400.0, 1050.0)  # 33% acima
    assert _chaves(det_extras.detectar(None, snap, ctx)) == ["ventoinha"]
    snap.fan = (1500.0, 1100.0)
    assert det_extras.detectar(None, snap, ctx) == []  # mesmo episódio
    snap.fan = (1150.0, 1100.0)  # rearma
    assert det_extras.detectar(None, snap, ctx) == []
    snap.fan = (1600.0, 1150.0)
    assert _chaves(det_extras.detectar(None, snap, ctx)) == ["ventoinha"]


def test_43_ignora_ventoinha_quase_parada() -> None:
    snap = Snapshot()
    snap.fan = (200.0, 50.0)
    assert det_extras.detectar(None, snap, {}) == []


# --- reinício (50) ---

def test_reinicio_rc_0_1_e_erro() -> None:
    assert Reinicio(run=lambda: 1).ler() is True
    assert Reinicio(run=lambda: 0).ler() is False
    assert Reinicio(run=lambda: None).ler() is None  # sem dnf / timeout
    assert Reinicio(run=lambda: 2).ler() is None  # opção desconhecida etc.

    def quebra():
        raise OSError("dnf sumiu")

    assert Reinicio(run=quebra).ler() is None


def test_reinicio_roda_no_maximo_a_cada_6h() -> None:
    assert Reinicio(run=lambda: 0).intervalo >= 6 * 3600


def test_50_dispara_na_subida() -> None:
    ctx: dict = {}
    snap = Snapshot()
    snap.reinicio = False
    assert det_extras.detectar(None, snap, ctx) == []
    snap.reinicio = True
    assert _chaves(det_extras.detectar(None, snap, ctx)) == ["pede_reinicio"]
    assert det_extras.detectar(None, snap, ctx) == []
    snap.reinicio = None
    assert det_extras.detectar(None, snap, ctx) == []
    snap.reinicio = True
    assert _chaves(det_extras.detectar(None, snap, ctx)) == ["pede_reinicio"]


# --- capturas (51) ---

def test_capturas_mtime_da_mais_nova(tmp_path) -> None:
    pasta = tmp_path / "Capturas de tela"
    c = Capturas(pasta=pasta)
    assert c.ler() is None  # sem pasta
    pasta.mkdir()
    assert c.ler() == 0.0
    a = pasta / "a.png"
    a.write_bytes(b"x")
    os.utime(a, (1000.0, 1000.0))
    b = pasta / "b.png"
    b.write_bytes(b"x")
    os.utime(b, (2000.0, 2000.0))
    assert c.ler() == 2000.0


def test_51_captura_nova_e_so_nova() -> None:
    ctx: dict = {"relogio": 5000.0}
    snap = Snapshot()
    snap.captura = 1000.0
    assert det_extras.detectar(None, snap, ctx) == []  # 1ª leitura só marca
    snap.captura = 4990.0
    assert _chaves(det_extras.detectar(None, snap, ctx)) == ["posando_print"]
    assert det_extras.detectar(None, snap, ctx) == []
    snap.captura = 4000.0  # nova, mas velha demais (> 120 s)
    ctx["_extras_captura"] = 3000.0
    assert det_extras.detectar(None, snap, ctx) == []
    snap.captura = None
    assert det_extras.detectar(None, snap, ctx) == []


# --- datas (63) ---

class _Gosto:
    def __init__(self, datas: dict) -> None:
        self.datas = datas

    def section(self, nome: str) -> dict:
        return dict(self.datas) if nome == "datas" else {}


def test_63_dispara_uma_vez_no_dia_cadastrado() -> None:
    dia = datetime(2026, 10, 9, 14, 0).timestamp()
    ctx: dict = {"relogio": dia, "taste": _Gosto({"10-09": "aniversário do Pedro"})}
    snap = Snapshot()
    ds = det_extras.detectar(None, snap, ctx)
    assert _chaves(ds) == ["data_especial"] and ds[0].fmt["nome"] == "aniversário do Pedro"
    ctx["relogio"] = dia + 3600
    assert det_extras.detectar(None, snap, ctx) == []  # 1× por dia
    ctx["relogio"] = dia + 86400  # 10-10 não está cadastrado
    assert det_extras.detectar(None, snap, ctx) == []


def test_63_sem_datas_nao_dispara() -> None:
    dia = datetime(2026, 10, 9, 14, 0).timestamp()
    assert det_extras.detectar(None, Snapshot(), {"relogio": dia, "taste": _Gosto({})}) == []
    assert det_extras.detectar(None, Snapshot(), {"relogio": dia}) == []


# --- catálogo e integração ---

def test_43_50_51_63_ativas_e_i20_nao() -> None:
    assert {"ventoinha", "pede_reinicio", "posando_print", "data_especial"} <= ATIVAS
    assert "bracos_cruzados" not in ATIVAS and DEFS["bracos_cruzados"].sinal == "P13"


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


def test_integration_poe_extras_no_snapshot(tmp_path) -> None:
    _hwmon(tmp_path / "hw", {"hwmon0/fan1": 900})
    v, r, c = Ventoinha(raiz=tmp_path / "hw"), Reinicio(run=lambda: 1), Capturas(pasta=tmp_path)
    ui = integration.WiredUI(now_playing=_SemPlayer(), net=_RedeFalsa(), git=_GitFalso(),
                             ventoinha=v, reinicio=r, capturas=c)
    s = ui.build({})
    assert s.fan is None and s.reinicio is None and s.captura is None  # threads não ligadas
    v.ler(), r.ler(), c.ler()
    s = ui.build({})
    assert s.fan == (900.0, 900.0) and s.reinicio is True and s.captura is not None


def test_testes_nao_ligam_as_threads() -> None:
    assert os.environ.get("MAGI_NO_EXTRAS") == "1"
    ui = integration.WiredUI(now_playing=_SemPlayer(), net=_RedeFalsa(), git=_GitFalso())
    assert ui.ventoinha is None and ui.reinicio is None and ui.capturas is None


def test_thread_le_com_dnf_falso_e_para() -> None:
    import threading

    leu = threading.Event()

    def dnf():
        leu.set()
        return 1

    r = Reinicio(run=dnf).start()
    try:
        assert leu.wait(2.0) and r._thread is not None
    finally:
        r.stop()
    r._thread.join(2.0)
    assert not r._thread.is_alive() and r.atual is True
