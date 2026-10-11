"""V1.4: placar Condessa × Pedro (acordo placar-e-jogo §3). Relógio injetado; nada em disco real."""

from __future__ import annotations

import json
import time

import pytest

from hud.wired.reacoes import registro
from hud.wired.reacoes.placar import FONTES, MAX_LINHA, POS_BATALHA, Placar
from hud.wired.reacoes.vida import VIDA_PADRAO


def t(dia: int, h: int, m: int = 0) -> float:
    """Hora local em outubro de 2026 (dia 12 é segunda-feira)."""
    return time.mktime((2026, 10, dia, h, m, 0, 0, 0, -1))


TETOS = VIDA_PADRAO["placar"]["tetos"]


@pytest.mark.parametrize("fonte", sorted(FONTES))
def test_cada_fonte_ate_o_teto(fonte):
    p = Placar()
    teto = TETOS[fonte]
    for i in range(teto):
        pt = p.pontuar(fonte, f"r{i}", t(13, 15, i))
        assert pt is not None and pt.lado == FONTES[fonte]
    assert p.pontuar(fonte, "a mais", t(13, 16)) is None
    ela, ele = p.hoje(t(13, 17))
    assert (ela if FONTES[fonte] == "ela" else ele) == teto


def test_linha_do_registro_com_ref():
    p = Placar()
    pt = p.pontuar("ele_partida_limpa", "1760000000.5", t(13, 20))
    assert pt.linha["causa"] == "placar:ele_partida_limpa"
    assert pt.linha["placar"] == {"lado": "ele", "fonte": "ele_partida_limpa",
                                  "ref": "1760000000.5"}
    with pytest.raises(ValueError):
        p.pontuar("ele_partida_limpa", "", t(13, 20))


def test_gravar_placar_em_arquivo_temporario(tmp_path):
    arq = tmp_path / "reacoes.jsonl"
    pt = Placar().pontuar("ela_pulo_nota2", "x1", t(13, 10))
    registro.gravar_placar(pt.linha, arq)
    linha = json.loads(arq.read_text(encoding="utf-8"))
    assert linha["placar"]["ref"] == "x1" and linha["causa"] == "placar:ela_pulo_nota2"


@pytest.mark.parametrize("fonte", ["commit", "faxina", "claude_fim", "claude_erro", "pedro_volta",
                                   "clique_carinho", "sem_sentido", "inventada"])
def test_trabalho_voltas_cliques_sem_sentido_nao_contam(fonte):
    p = Placar()
    assert p.pontuar(fonte, "r", t(13, 10)) is None
    assert p.hoje(t(13, 10)) == (0, 0)


def test_teto_zero_desliga_a_fonte_e_liga_false_desliga_tudo():
    p = Placar({"placar": {"tetos": {"ele_faixa_nota2": 0}}})
    assert p.pontuar("ele_faixa_nota2", "r", t(13, 10)) is None
    assert p.pontuar("ela_pulo_nota2", "r", t(13, 10)) is not None
    off = Placar({"placar": {"liga": False}})
    assert off.pontuar("ela_pulo_nota2", "r", t(13, 10)) is None


def test_dia_fecha_as_4h():
    p = Placar()
    p.pontuar("ela_pulo_nota2", "a", t(13, 23))
    p.pontuar("ela_pulo_nota2", "b", t(14, 3, 59))  # madrugada ainda é o dia 13
    assert p.pontuar("ela_pulo_nota2", "c", t(14, 3, 59)) is None  # teto 2 do dia 13
    assert p.dia(t(14, 3, 59)) == "2026-10-13"
    assert p.dia(t(14, 4)) == "2026-10-14"
    assert p.hoje(t(14, 4)) == (0, 0)
    assert p.pontuar("ela_pulo_nota2", "d", t(14, 4)) is not None


def test_semana_soma_os_dias_e_vira_na_segunda():
    p = Placar()
    p.pontuar("ela_pulo_nota2", "a", t(12, 10))  # segunda
    p.pontuar("ele_faixa_nota2", "b", t(15, 10))  # quinta
    p.pontuar("ele_faixa_nota2", "c", t(18, 10))  # domingo
    assert p.semana(t(18, 12)) == (1, 2)
    assert p.semana(t(19, 3)) == (1, 2)  # madrugada de segunda ainda é domingo
    assert p.semana(t(19, 10)) == (0, 0)


def test_virada_no_maximo_viradas_dia():
    p = Placar()
    assert p.pontuar("ela_pulo_nota2", "1", t(13, 10)).virada is None  # 1×0 ainda não é virada
    assert p.pontuar("ele_faixa_nota2", "2", t(13, 11)).virada is None  # empate
    v = p.pontuar("ele_faixa_nota2", "3", t(13, 12)).virada  # 1×2: ele virou
    assert v == {"chave": "soprando_franja", "causa": "placar:virada", "lado": "ele", "ref": "3"}
    p.pontuar("ela_pulo_nota2", "4", t(13, 13))  # 2×2
    v = p.pontuar("ela_favorita_ado", "5", t(13, 14)).virada  # 3×2: ela passou na frente
    assert v["chave"] == "piscadinha" and v["causa"] == "placar:virada"
    p.pontuar("ele_faixa_nota2", "6", t(13, 15))  # 3×3
    pt = p.pontuar("ele_partida_limpa", "7", t(13, 16))  # 3×4: 3ª troca só muda o número
    assert pt is not None and pt.virada is None
    assert p.hoje(t(13, 17)) == (3, 4)


def test_ativo_depois_da_1h_teto_1():
    p = Placar()
    assert p.ativo(t(13, 23), "r") is None
    assert p.ativo(t(14, 0, 59), "r") is None
    pt = p.ativo(t(14, 1, 10), "r1")
    assert pt is not None and pt.fonte == "ela_ativo_madrugada" and pt.lado == "ela"
    assert p.ativo(t(14, 2), "r2") is None  # teto 1
    assert p.ativo(t(14, 4, 1), "r3") is None  # o dia já fechou


def test_resumo_para_o_hover():
    p = Placar()
    p.pontuar("ela_pulo_nota2", "a", t(12, 10))
    p.pontuar("ela_pulo_nota2", "b", t(13, 10))
    p.pontuar("ele_partida_limpa", "c", t(13, 11))
    p.pontuar("ela_truque_aplaudido", "d", t(13, 12))
    p.pontuar("ele_faixa_nota2", "e", t(13, 13))
    r = p.resumo(t(13, 14))
    assert r["texto"] == "Condessa 2 × 2 Pedro · semana 3 × 2"
    assert r["ultimos"] == ["Pedro +1 · faixa até o fim", "Condessa +1 · truque convenceu",
                            "Pedro +1 · partida limpa"]


def test_pos_batalha_so_se_a_partida_mexeu():
    p = Placar()
    pt = p.pontuar("ele_partida_limpa", "a", t(13, 10))
    assert p.linha_pos_batalha(pt) == "Partida limpa. Ponto seu. Não se acostume."
    p.pontuar("ele_partida_limpa", "b", t(13, 11))
    assert p.linha_pos_batalha(p.pontuar("ele_partida_limpa", "c", t(13, 12))) is None  # teto
    assert p.linha_pos_batalha(p.pontuar("ela_pulo_nota2", "d", t(13, 12))) is None  # não é partida
    assert all(len(s) <= MAX_LINHA for s in POS_BATALHA.values())


def test_bom_dia_com_o_de_ontem():
    p = Placar()
    assert p.bom_dia(t(14, 8)) is None
    p.pontuar("ela_pulo_nota2", "a", t(13, 10))
    p.pontuar("ela_pulo_nota2", "b", t(13, 11))
    p.pontuar("ele_faixa_nota2", "c", t(14, 2))  # madrugada conta no dia 13
    s = p.bom_dia(t(14, 8))
    assert s == "Ontem: 2 × 1 pra mim. Revanche?" and len(s) <= MAX_LINHA
    p.pontuar("ele_faixa_nota2", "d", t(14, 3))
    assert p.bom_dia(t(14, 8)) == "Ontem: 2 × 2. Empate é empate."
    p.pontuar("ele_faixa_nota2", "e", t(14, 3, 30))
    assert p.bom_dia(t(14, 8)) == "Ontem: 3 × 2 pra você. Não se acostume."


def test_exportar_importar_preserva_dia_semana_e_tetos():
    p = Placar()
    p.pontuar("ela_pulo_nota2", "a", t(13, 10))
    p.pontuar("ela_pulo_nota2", "b", t(13, 11))
    p.pontuar("ele_faixa_nota2", "c", t(12, 11))
    dados = json.loads(json.dumps(p.exportar()))
    q = Placar()
    q.importar(dados)
    assert q.hoje(t(13, 12)) == (2, 0) and q.semana(t(13, 12)) == (2, 1)
    assert q.pontuar("ela_pulo_nota2", "z", t(13, 12)) is None  # teto continua gasto
    assert q.resumo(t(13, 12))["ultimos"] == p.resumo(t(13, 12))["ultimos"]
    vazio = Placar()
    vazio.importar({"dias": {"lixo": {}}, "ultimos": "x"})
    assert vazio.exportar() == {"dias": {}, "ultimos": []}
