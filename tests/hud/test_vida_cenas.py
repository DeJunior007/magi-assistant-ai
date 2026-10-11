"""V1.2: cenas novas e a passiva ``torcida`` (acordo placar-e-jogo §1–§2)."""

from __future__ import annotations

import pytest
from PySide6.QtGui import QColor, QImage
from wired.reacoes import catalogo
from wired.reacoes.contratos import EFEITO, Classe
from wired.reacoes.momento import GRUPOS, Momento, _cabe
from wired.reacoes.vida import VIDA_PADRAO

C = catalogo.CENAS


def _seq(passos) -> list[tuple]:
    return [(p.eyes, p.mouth, p.look, p.efeitos, p.corpo, p.ms) for p in passos]


@pytest.mark.parametrize(("chave", "ms"), [
    (("episodio", "cobranca"), 2100), (("episodio", "recuperou"), 2000), (("truque", "fone"), 3000),
    (("truque", "fone_inverso"), 3000), (("truque", "piscadinha"), 3500), (("truque", None), 3500),
    (("pedro_voltou", "orgulhosa"), 3000), (("truque", "aplaudido"), 1000), (("truque", "ignorado"), 800),
    (("pedro_voltou", "orgulhosa_2"), 1400),
])
def test_duracoes_do_acordo(chave, ms):
    assert C[chave].ms == ms


def test_episodio_tres_passos_de_frente_no_fim_sem_desconfiada():
    d = C[("episodio", "cobranca")]
    assert len(d.passos) == 3 and d.passos[0].look == "fps"
    assert d.passos[1].efeitos == ("sweat", "bang")
    fim = d.passos[-1]
    assert fim.corpo == ("iris:B1",) and fim.look is None and (fim.eyes, fim.mouth) == ("B7", "C12")
    assert all((p.eyes, p.mouth) != ("B7", "C8") for p in d.passos)


def test_recuperou_punho_e_c5_de_frente():
    fim = C[("episodio", "recuperou")].passos[-1]
    assert fim.mouth == "C5" and set(fim.corpo) == {"iris:B1", "braco:P12"}


def test_truque_fone_e_caminho_inverso():
    fone = [p.corpo for p in C[("truque", "fone")].passos]
    inv = [p.corpo for p in C[("truque", "fone_inverso")].passos]
    assert [c for cs in fone for c in cs if c.startswith("fone")] == ["fone_off", "fone_on"]
    assert [c for cs in inv for c in cs if c.startswith("fone")] == ["fone_on", "fone_off"]
    for k in ("fone", "fone_inverso", "piscadinha"):  # o aceno no fim é o "pode bater palma"
        assert "braco:P9" in C[("truque", k)].passos[-1].corpo
    assert _seq(C[("truque", None)].passos) == _seq(C[("truque", "piscadinha")].passos)


def test_aplaudido_e_ignorado():
    ap = C[("truque", "aplaudido")].passos
    assert len(ap) == 1 and (ap[0].eyes, ap[0].mouth, ap[0].efeitos) == ("B4", "C6", ("blush",))
    ig = C[("truque", "ignorado")].passos
    assert len(ig) == 1 and (ig[0].eyes, ig[0].mouth) == ("F1", "C12")
    assert all(p.mouth != "C9" for p in ig)  # sem beicinho
    assert catalogo.NIVEL_CENA["truque"] == 2


def test_volta_orgulhosa_passo_extra_e_habituacao():
    d = C[("pedro_voltou", "orgulhosa")]
    assert "braco:P13" in d.passos[0].corpo and "blush" in d.passos[2].efeitos
    assert (d.passos[-1].eyes, d.passos[-1].mouth, d.passos[-1].ms) == ("F1", "C10", 400)
    longa = catalogo.VOLTA_LONGA
    assert longa.ms == 3700 and len(longa.passos) == 5
    assert (longa.passos[3].eyes, longa.passos[3].mouth, longa.passos[3].corpo) == ("B5", "C6", ("tails",))
    assert _seq(longa.passos[-1:]) == _seq(d.passos[-1:])  # o disfarce continua no fim
    assert len(C[("pedro_voltou", "orgulhosa_2")].passos) == 2
    assert catalogo.VOLTA_ATENCAO[0].corpo == ("iris:B1",)  # 3ª volta: só olhar nele


def test_torcida_variantes_positiva_e_so_em_jogando():
    tela, punho = (catalogo.DEFS[k] for k in catalogo.TORCIDA)
    assert tela.ms == 1500 and punho.ms == 1500
    assert all(k in catalogo.ATIVAS for k in catalogo.TORCIDA)
    assert tela.passos[0].look == "fps" and "braco:P12" in punho.passos[0].corpo
    assert Classe.PASSIVA in tela.classes and not (tela.classes & {Classe.ZOEIRA, Classe.COBRANCA})
    assert [m for m, g in GRUPOS.items() if "torcida" in g] == [Momento.JOGANDO]
    g = GRUPOS[Momento.JOGANDO]
    assert "cabeca_ritmo" in g and _cabe("torcida", Momento.JOGANDO, {})  # mesmo peso (base 1)
    assert VIDA_PADRAO["torcida"]["delta_animo"] == 0.03


def test_torcida_com_episodio_aberto_tem_d2_em_todos_os_passos():
    for k in catalogo.TORCIDA:
        d = catalogo.com_suor(catalogo.DEFS[k])
        assert all(EFEITO["D2"] in p.efeitos for p in d.passos)
        assert d.ms == catalogo.DEFS[k].ms and catalogo.com_suor(d) == d  # sem D2 duplicado
        assert all(EFEITO["D2"] not in p.efeitos for p in catalogo.DEFS[k].passos)


def _assets(tmp_path):
    for rel in ("parts/head.png", "parts/body.png", "parts/back.png", "eyes/B1.png", "eyes/B7.png",
                "eyes/B14.png", "eyes/B15.png", "mouth/C1.png", "mouth/C12.png",
                "parts/iris.png", "parts/eye_open.png", "eyes/O1.png"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        img = QImage(16, 16, QImage.Format.Format_ARGB32)
        img.fill(QColor(120, 100, 200))
        assert img.save(str(tmp_path / rel))
    (tmp_path / "portrait.toml").write_text(
        'mode = "parts"\n[states]\n'
        'listening = { eyes = "B1", mouth = "C1", blink = ["B1", "B1"] }\n'
        'sleeping = { eyes = "B14", mouth = "C1", blink = ["B15", "B15"] }\n'
    )
    return tmp_path


@pytest.mark.parametrize("cena", [("episodio", "cobranca"), ("episodio", "recuperou")])
def test_o1_funciona_num_passo_de_cena(tmp_path, cena):
    """Nota da Kurisu: o retrato aceita ``O1`` (íris de frente) num passo de cena."""
    from wired.portrait import PartsAssets, PartsPortrait
    from wired.reactions import Reaction

    p = C[cena].passos[-1]
    m = PartsPortrait(PartsAssets(_assets(tmp_path)), "sleeping", now=0.0)
    m.hour = lambda: 14
    # como ``reactions._passo`` monta o rosto de um passo da sequência
    m.react(Reaction(cena[0], p.eyes, p.mouth, p.look, "calm", p.efeitos[0] if p.efeitos else None,
                     5.0, False, 1, None, p.efeitos, p.corpo), 9.0)  # até 9 s
    assert m._iris_extra(m._reacting(2.0)) == (0.0, 0.0)  # O1: de frente, para ele
    for k in range(10):
        m.tick(1.0 + k / 30)
    assert m.eyes_id(2.0).startswith("live:")
