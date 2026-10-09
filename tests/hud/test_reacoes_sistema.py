"""R1.3: detector de sistema (spec §5, acordo §1 34–48/80/84, §2 I4–I6)."""

from __future__ import annotations

from hud.wired.main_screen import Snapshot
from hud.wired.reacoes import catalogo, det_sistema


class Sim:
    """Cada ``tick`` monta um Snapshot e roda o detector com o mesmo ``ctx``."""

    def __init__(self, **base):
        self.ctx: dict = {"agora": 0.0, "jogo": False}
        self.base = {"net_ip": "192.168.0.2", "cpu": 10.0, "ram": 40.0} | base
        self.ant = None
        self.tick(0.0)  # 48 sai aqui

    def tick(self, t: float, **campos) -> list[tuple[str, str | None]]:
        snap = Snapshot(**(self.base | campos))
        self.ctx.update(agora=t, jogo=snap.gaming)
        out = det_sistema.detectar(self.ant, snap, self.ctx)
        self.ant = snap
        for d in out:  # toda chave emitida existe no catálogo
            assert (d.chave, d.variante) in catalogo.DEFS or d.chave in catalogo.DEFS
        return [(d.chave, d.variante) for d in out]

    def rodar(self, t0: float, t1: float, passo: float = 1.0, **campos) -> list:
        out, t = [], t0
        while t <= t1:
            out += self.tick(t, **campos)
            t += passo
        return out


def test_48_hud_acordou_so_no_primeiro_snapshot():
    ctx: dict = {"agora": 0.0}
    assert [d.chave for d in det_sistema.detectar(None, Snapshot(), ctx)] == ["hud_acordou"]
    assert det_sistema.detectar(Snapshot(), Snapshot(), ctx) == []
    assert det_sistema.detectar(None, Snapshot(gaming=True), {"agora": 0.0}) == []  # palco do game_on
    assert det_sistema.detectar(None, None, {}) == []


def test_35_alivio_e_histerese_sem_duplicar_hot():
    s = Sim()
    out = s.tick(1, cpu_temp=86.0)
    assert out == []  # o 34 (`hot`) sai pelo fire antigo
    assert s.ctx["_sistema_quente"]
    assert s.tick(2, cpu_temp=80.0) == []  # ainda acima de 78
    assert s.tick(61, gpu_temp=77.0, cpu_temp=60.0) == [("hot", "alivio")]
    s.tick(100, cpu_temp=90.0)
    assert s.tick(110, cpu_temp=60.0) == []  # pico de 10 s não vira alívio


def test_oscilacao_84_86_por_10_min_gera_no_maximo_um_hot():
    s = Sim()
    entradas, out = 0, []
    for i in range(600):
        era = s.ctx.get("_sistema_quente", False)
        out += s.tick(i + 1, cpu_temp=86.0 if i % 2 else 84.0)
        entradas += s.ctx["_sistema_quente"] and not era
    assert entradas <= 1
    assert out == []  # nem alívio, nem eu avisei


def _fps_queda(s: Sim, t: float) -> list:
    kw = {"gaming": True, "fps": 20.0, "fps_avg": 100.0}
    return s.tick(t, **kw) + s.tick(t + 1, **kw)


def _fps_bom(s: Sim, t: float) -> list:
    kw = {"gaming": True, "fps": 95.0, "fps_avg": 100.0}
    return s.tick(t, **kw) + s.tick(t + 1, **kw)


def test_37_fps_recuperou():
    s = Sim()
    assert _fps_queda(s, 1) == []  # 36 é o fire antigo
    assert _fps_bom(s, 3) == [("fps_drop", "recuperou")]
    assert _fps_bom(s, 5) == []


def test_I4_vergonha_na_terceira_queda_da_sessao():
    s = Sim()
    out = []
    for k in range(3):
        out += _fps_queda(s, 10 * k + 1) + _fps_bom(s, 10 * k + 3)
    assert out.count(("fps_drop", "vergonha")) == 1
    assert out.count(("fps_drop", "recuperou")) == 3
    s.tick(100, gaming=False)  # sessão nova zera a contagem
    out = []
    for k in range(2):
        out += _fps_queda(s, 200 + 10 * k)
    assert ("fps_drop", "vergonha") not in out


def test_I6_partida_sem_tropeco_uma_vez_por_sessao():
    s = Sim()
    out = s.rodar(1, 1801 + 120, 30.0, gaming=True, fps=100.0, fps_avg=100.0)
    assert out == [("sem_tropeco", None)]
    s2 = Sim()
    _fps_queda(s2, 1)
    assert ("sem_tropeco", None) not in s2.rodar(3, 2000, 30.0, gaming=True, fps=100.0, fps_avg=100.0)


def test_84_eu_avisei_queda_de_fps_ate_10_min_depois_do_calor():
    s = Sim()
    s.tick(1, cpu_temp=90.0)
    s.tick(2, cpu_temp=70.0)
    assert ("eu_avisei", None) in _fps_queda(s, 300)
    assert ("eu_avisei", None) not in _fps_queda(s, 320)  # 1× por 34
    s2 = Sim()
    s2.tick(1, cpu_temp=90.0)
    assert ("eu_avisei", None) not in _fps_queda(s2, 700)  # passou de 10 min


def test_84_eu_avisei_quando_esquenta_de_novo():
    s = Sim()
    s.tick(1, cpu_temp=90.0)
    s.tick(2, cpu_temp=70.0)
    assert s.tick(100, cpu_temp=88.0) == [("eu_avisei", None)]


def test_38_39_rede_caiu_e_voltou():
    s = Sim()
    assert s.rodar(1, 10, net_ip=None) == []  # 9 s sem IP
    assert s.tick(11, net_ip=None) == [("rede_caiu", None)]
    assert s.rodar(12, 30, net_ip=None) == []
    assert s.tick(31) == [("rede_voltou", None)]


def test_38_sem_ip_desde_o_inicio_nao_e_queda():
    s = Sim(net_ip=None)
    assert s.rodar(1, 60) == []


def test_40_transferencia_pesada_acabou():
    s = Sim()
    assert s.rodar(1, 61, net_down=6e6) == []
    assert s.tick(62, net_down=50_000.0) == [("transferencia_acabou", None)]
    s2 = Sim()
    s2.rodar(1, 30, net_down=6e6)  # só 30 s de pico
    assert s2.tick(31, net_down=50_000.0) == []


def test_41_disco_quase_cheio_com_histerese():
    s = Sim()
    assert s.tick(1, disk_pct=91.0) == [("disco_cheio", None)]
    assert s.tick(2, disk_pct=89.0) == []
    assert s.tick(3, disk_pct=92.0) == []
    s.tick(4, disk_pct=80.0)
    assert s.tick(5, disk_pct=91.0) == [("disco_cheio", None)]


def test_80_impaciente_cpu_alta_60s_sem_jogo():
    s = Sim()
    assert s.rodar(1, 60, cpu=95.0) == []
    assert s.tick(61, cpu=95.0) == [("impaciente", None)]
    assert s.rodar(62, 200, cpu=95.0) == []
    j = Sim()
    assert j.rodar(1, 200, cpu=95.0, gaming=True) == []


def test_I5_sufocando_ram_ou_swap():
    s = Sim()
    assert s.tick(1, ram=92.0) == [("sufocando", None)]
    assert s.rodar(2, 30, ram=92.0) == []
    s.tick(31, ram=50.0)
    w = Sim(swap_used_gb=1.0)
    assert w.tick(10, swap_used_gb=1.5) == []
    assert w.tick(40, swap_used_gb=2.1) == [("sufocando", None)]
    lento = Sim(swap_used_gb=1.0)
    assert lento.rodar(1, 300, 30.0, swap_used_gb=None) == []
    assert lento.tick(400, swap_used_gb=1.9) == []


def test_chaves_antigas_sem_variante_nunca_saem_daqui():
    s = Sim()
    out = s.tick(1, cpu_temp=90.0, gaming=True, fps=10.0, fps_avg=100.0)
    out += s.tick(2, cpu_temp=90.0, gaming=False)
    for chave, var in out:
        assert not (chave in {"hot", "fps_drop", "game_on", "game_off", "cleanup"} and var is None)
