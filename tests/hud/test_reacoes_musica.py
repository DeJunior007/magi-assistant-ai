"""R1.2: detector de música (spec §5, acordo §1 24–33/78–89, §2 I3/I7–I15)."""

from __future__ import annotations

import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from hud.wired.reacoes import catalogo, det_musica
from hud.wired.reacoes.contratos import EFEITO
from hud.wired.reactions import Verdict

GOSTO = tomllib.loads((Path(__file__).parents[2] / "persona" / "condessa-gosto.toml").read_text("utf-8"))


class _Taste:
    def section(self, nome: str) -> dict:
        return dict(GOSTO.get(nome, {}))


class Sim:
    """Player falso: cada ``tick`` monta o Snapshot e o ``ctx`` e roda o detector."""

    def __init__(self, **ctx):
        self.ctx = {
            "defs": {k: catalogo.DEFS[k] for k in catalogo.ATIVAS}, "agora": 0.0, "relogio": 1.7e9,
            "hora": 15, "jogo": False, "fps_estavel": True, "favorita_dia": "", "taste": _Taste(),
            "musica_nota": 0, "veredito": None, "ado": False,
        } | ctx
        self.snap = None
        self.t = 0.0
        self.tick(0.0, None)

    def tick(self, t: float, faixa: tuple[str, str] | None, nota: int = 0, playing: bool = True,
             pos: float | None = None, length: float | None = None, genres: tuple = (),
             artist_key: str = "", **ctx) -> list:
        self.t = t
        tr = SimpleNamespace(title=faixa[0], artist=faixa[1], position=pos, length=length,
                             playing=playing) if faixa else None
        snap = SimpleNamespace(track=tr)
        v = Verdict(nota, artist_key, genres, artist_key == "ado") if faixa else None
        self.ctx.update(agora=t, musica_nota=nota if faixa else 0, veredito=v,
                        ado=artist_key == "ado", **ctx)
        out = det_musica.detectar(self.snap, snap, self.ctx)
        self.snap = snap
        return out

    def chaves(self, *a, **kw) -> list:
        return [(d.chave, d.variante) for d in self.tick(*a, **kw)]

    def tocar(self, t0: float, t1: float, faixa, passo: float = 1.0, **kw) -> list:
        out, t = [], t0
        while t <= t1:
            out += self.chaves(t, faixa, **kw)
            t += passo
        return out


A = ("Song A", "Banda A")
B = ("Song B", "Banda B")
C = ("Song C", "Banda C")


def _todas_ativas(out):
    for k in out:
        assert (k[0] if k[1] is None else k) in catalogo.ATIVAS, k


# ------------------------------------------------------------ uma por linha (CA-04)

def test_24_comecou_a_tocar():
    s = Sim()
    assert ("colocando_fone", None) in s.chaves(1, A)


def test_25_parou():
    s = Sim()
    s.chaves(1, A, pos=30, length=200)
    out = s.chaves(2, A, playing=False, pos=31, length=200)
    assert ("tirando_fone", None) not in out
    assert ("tirando_fone", None) in s.chaves(12.5, A, playing=False, pos=31, length=200)


def test_32_acabou_a_fila():
    s = Sim()
    s.chaves(1, A, pos=198, length=200)
    s.chaves(2, A, playing=False, pos=199, length=200)
    out = s.chaves(13, None)
    assert ("acabou_fila", None) in out and ("tirando_fone", None) not in out


def test_32_nao_dispara_se_outra_comecou():
    s = Sim()
    s.chaves(1, A, pos=198, length=200)
    s.chaves(2, A, playing=False, pos=199, length=200)
    out = s.chaves(5, B) + s.chaves(14, B)
    assert ("acabou_fila", None) not in out


def test_26_nunca_antes_de_60s():
    s = Sim()
    s.chaves(1, A, nota=2)
    antes = s.tocar(2, 60.5, A, passo=0.5, nota=2)
    assert ("refrao", None) not in antes
    depois = s.tocar(61, 120, A, nota=2)
    assert depois.count(("refrao", None)) == 1


def test_27_cantando_junto_nota_2_apos_40s():
    s = Sim()
    s.chaves(1, A, nota=2)
    assert ("cantando_junto", None) not in s.tocar(2, 40, A, nota=2)
    assert ("cantando_junto", None) in s.tocar(41, 42, A, nota=2)


def test_27_cantando_junto_quinta_vez():
    s = Sim()
    t = 0.0
    for _ in range(4):
        t += 300
        s.chaves(t, A, pos=100, length=100)
        t += 300
        s.chaves(t, B, pos=100, length=100)
    s.chaves(t + 300, A)
    assert ("cantando_junto", None) in s.tocar(t + 341, t + 342, A)


def test_28_terceira_vez_no_dia():
    s = Sim()
    out = []
    for i in range(3):
        out += s.chaves(100 + i * 400, A, pos=100, length=100)
        s.chaves(300 + i * 400, B, pos=100, length=100)
    assert out.count(("musica_repetida", None)) == 1


def test_29_melancolica_por_artista_e_titulo():
    s = Sim()
    assert ("musica_triste", None) in s.chaves(1, ("Fragile", "Arvo Pärt"))
    assert ("musica_triste", None) in s.chaves(2, ("Requiem pra mim", "Fulano"))


def test_I12_chopin_de_madrugada_vira_variante():
    s = Sim(hora=2)
    out = s.chaves(1, ("Nocturne op. 9", "Frédéric Chopin"))
    assert ("musica_triste", "chopin") in out and ("musica_triste", None) not in out
    s.ctx["hora"] = 15
    assert ("musica_triste", None) in s.chaves(2, ("Nocturne op. 27", "Chopin"))


def test_30_dancante_nota_1():
    s = Sim()
    assert ("musica_dancante", None) in s.chaves(1, A, nota=1, genres=("k-pop",))
    assert ("musica_dancante", None) not in s.chaves(2, B, nota=0, genres=("rock",))


def test_33_artista_novo_que_amou():
    s = Sim()
    assert ("music_new", "amou") in s.chaves(1, A, nota=1)
    s.chaves(2, B, nota=1)
    assert ("music_new", "amou") not in s.chaves(3, ("Outra", "Banda A"), nota=1)


def test_78_desconfiada():
    s = Sim()
    assert ("desconfiada", None) in s.chaves(1, ("Song (Slowed + Reverb)", "X"))
    assert ("desconfiada", None) in s.chaves(2, ("Song - Sped Up", "Y"))


def test_81_virada():
    s = Sim()
    s.chaves(1, A, nota=-1)
    assert ("surpresa_boa", None) in s.chaves(100, B, nota=2)


def test_83_parou_de_pular_numa_nota_2():
    s = Sim()
    s.chaves(1, A)
    s.chaves(3, B)
    s.chaves(5, C, nota=2)
    assert ("piscadinha", None) in s.tocar(6, 25, C, nota=2)


def test_85_mesmo_botao():
    s = Sim()
    s.chaves(1, A)
    out = s.chaves(2, A, playing=False) + s.chaves(3, A) + s.chaves(4, A, playing=False)
    assert ("indiferente", None) in out


def test_89_anterior_proxima_alternados():
    s = Sim()
    s.chaves(1, A)
    out = s.chaves(3, B) + s.chaves(5, A) + s.chaves(7, B)
    assert ("indecisa", None) in out


def test_I3_tontura_cinco_pulos():
    s = Sim()
    out = []
    for i, f in enumerate([A, B, C, A, B, C]):
        out += s.chaves(1 + i * 5, f)
    assert ("skips", "tontura") in out


def test_I7_favorita_do_dia_uma_vez():
    s = Sim(favorita_dia="banda a")
    assert ("favorita_dia", None) in s.chaves(1, A, artist_key="banda a")
    s.chaves(200, B, pos=100, length=100)
    assert ("favorita_dia", None) not in s.chaves(400, A, artist_key="banda a")


def test_I8_duelo_ado():
    s = Sim()
    assert ("duelo_ado", None) in s.chaves(1, ("Usseewa", "Ado"), nota=2, artist_key="ado")


def test_I9_conta_anonima():
    s = Sim()
    s.chaves(1, ("Lemon", "Kenshi Yonezu"))
    assert ("conta_anonima", None) in s.tocar(2, 42, ("Lemon", "Kenshi Yonezu"))
    s.chaves(100, B, genres=("vocaloid",))
    assert ("conta_anonima", None) in s.tocar(101, 141, B, genres=("vocaloid",))


def test_I10_diva_contra_diva():
    s = Sim()
    assert ("diva_diva", None) in s.chaves(1, ("Bad Romance", "Lady Gaga"))


def test_I11_tema_agua():
    s = Sim()
    assert ("tema_agua", None) in s.chaves(1, ("Reflets dans l'eau", "Debussy"))
    assert ("tema_agua", None) not in s.chaves(2, ("Marte", "X"))


def test_I13_modo_chefe():
    s = Sim(jogo=True)
    s.chaves(1, A, nota=2, genres=("trilha",))
    assert ("music_love", "chefe") not in s.tocar(2, 100, A, nota=2, genres=("trilha",))
    assert ("music_love", "chefe") in s.tocar(101, 125, A, nota=2, genres=("trilha",))


def test_I13_fps_instavel_zera():
    s = Sim(jogo=True)
    s.chaves(1, A, nota=2, genres=("trilha",))
    s.tocar(2, 100, A, nota=2, genres=("trilha",))
    s.chaves(101, A, nota=2, genres=("trilha",), fps_estavel=False)
    assert ("music_love", "chefe") not in s.tocar(102, 200, A, nota=2, genres=("trilha",), fps_estavel=True)


def test_I14_elevador():
    s = Sim()
    s.chaves(1, A, nota=-1)
    assert ("elevador", None) in s.tocar(2, 62, A, nota=-1)


def test_I15_pulou_essa():
    s = Sim()
    s.chaves(1, A, nota=2)
    assert ("pulou_essa", None) in s.chaves(10, B, pos=9, length=200)
    s.chaves(100, C, nota=2)
    assert ("pulou_essa", None) not in s.chaves(150, A, pos=50, length=200)


# ------------------------------------------------------------ regras

def _tem_blush_ou_love(k) -> bool:
    d = catalogo.DEFS[k[0] if k[1] is None else k]
    return d.mood == "love" or any(e in (EFEITO["D1"], "D1") for p in d.passos for e in p.efeitos)


@pytest.mark.parametrize("jogo", [False, True])
def test_ado_nunca_recebe_blush_nem_love(jogo):
    s = Sim(jogo=jogo, favorita_dia="ado")
    ado = ("Usseewa (Slowed)", "Ado")
    kw = {"nota": 2, "artist_key": "ado", "genres": ("trilha", "j-rock", "vocaloid")}
    out = s.chaves(1, A, nota=-1)
    out += s.chaves(5, B) + s.chaves(8, C)
    for i in range(4):
        out += s.tocar(10 + i * 400, 300 + i * 400, ado, passo=2, pos=10, length=200, **kw)
        out += s.chaves(305 + i * 400, A, nota=-1, pos=1, length=200)
    ado_out = [k for k in out if k[0] not in ("elevador", "pulou_essa")]
    assert ("duelo_ado", None) in ado_out
    assert not [k for k in ado_out if _tem_blush_ou_love(k)]
    assert ("surpresa_boa", None) not in out and ("music_love", "chefe") not in out


def test_chaves_existem_no_catalogo():
    s = Sim(hora=2, jogo=True, favorita_dia="banda a")
    out = s.chaves(1, A, nota=-1)
    out += s.tocar(2, 200, ("Nocturne (Slowed) water", "Chopin"), nota=2, genres=("trilha", "pop"))
    out += s.chaves(201, A, nota=2, artist_key="banda a")
    _todas_ativas(out)
    assert len(out) >= 5


def test_primeiro_tick_so_aprende():
    s = SimpleNamespace(track=SimpleNamespace(title="X", artist="Y", position=1, length=9, playing=True))
    assert det_musica.detectar(None, s, {"agora": 0.0}) == []


def test_sem_gosto_usa_listas_padrao():
    s = Sim(taste=None)
    assert ("musica_triste", None) in s.chaves(1, ("Fragile", "Laufey"))
