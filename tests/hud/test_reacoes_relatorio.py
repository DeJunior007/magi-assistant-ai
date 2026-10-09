"""R3.2: relatório do reacoes.jsonl com registro sintético."""

from __future__ import annotations

import json

from hud.tools import reacoes_relatorio as rel

T0 = 1_800_000_000 - 1_800_000_000 % 3600  # início de hora (UTC)


def _linha(t, chave, n, furou=False, variante=None):
    return {"t": t, "hora": "x", "chave": chave, "n": n, "variante": variante,
            "motivo": "teste", "furou_cota": furou}


def _grava(caminho, linhas, lixo=False):
    texto = "".join(json.dumps(linha) + "\n" for linha in linhas)
    caminho.write_text(texto + ("{quebrada\n" if lixo else ""), encoding="utf-8")


def test_ausente_e_vazio_saem_com_zero(tmp_path, capsys):
    assert rel.main([str(tmp_path / "nada.jsonl")]) == 0
    assert "ausente ou vazio" in capsys.readouterr().out
    vazio = tmp_path / "vazio.jsonl"
    vazio.write_text("", encoding="utf-8")
    assert rel.main([str(vazio)]) == 0
    assert "ausente ou vazio" in capsys.readouterr().out


def test_contas_por_hora_furos_top_e_nunca(tmp_path, capsys):
    linhas = [_linha(T0 + i * 60, "colocando_fone", 24) for i in range(10)]  # 10 na cota na 1ª hora
    linhas += [_linha(T0 + 3600 * 2 + 5, "refrao", 26)]
    linhas += [_linha(T0 + 100 + i, "respirar", 1) for i in range(3)]  # passivas
    linhas += [_linha(T0 + 200, "hot", 35, furou=True, variante="alivio"),
               _linha(T0 + 300, "sobressalto", 20, furou=True)]
    caminho = tmp_path / "reacoes.jsonl"
    _grava(caminho, linhas, lixo=True)

    lidas = rel.ler(caminho)
    assert len(lidas) == len(linhas)  # linha quebrada pulada
    texto = rel.relatorio(lidas, ativas={"colocando_fone", "refrao", "tirando_fone"})

    assert "Reações: 16 em 3 h" in texto
    assert "Ativas/h: média 4,33 · pico 12" in texto
    assert "na cota/h: média 3,67 · pico 10" in texto
    assert "Passivas/h: média 1,00 · pico 3" in texto
    assert "Horas acima de 8 ativas na cota: 1" in texto
    assert "Furos de cota por classe: sistema 1, vitoria 1, volta 1" in texto
    top = texto.split("Top 10:\n")[1].splitlines()
    assert top[0].split() == ["10", "24", "colocando_fone"]
    assert "35 hot/alivio" in texto
    assert "Nunca tocadas (1 de 3 ativas):\n  25 tirando_fone" in texto

    assert rel.main([str(caminho)]) == 0
    assert "Top 10:" in capsys.readouterr().out


def test_dias_filtra_e_le_o_giro(tmp_path):
    caminho = tmp_path / "reacoes.jsonl"
    _grava(caminho.with_name("reacoes.jsonl.1"), [_linha(T0 - 10 * 86400, "refrao", 26)])
    _grava(caminho, [_linha(T0, "colocando_fone", 24)])
    lidas = rel.ler(caminho)
    assert [linha["chave"] for linha in lidas] == ["refrao", "colocando_fone"]
    texto = rel.relatorio(lidas, dias=7, agora=T0 + 60, ativas=set())
    assert "Reações: 1 em 1 h" in texto and "refrao" not in texto
    assert "nos últimos 1 dias" in rel.relatorio(lidas, dias=1, agora=T0 + 3 * 86400)
