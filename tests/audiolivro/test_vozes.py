"""A1.2 — voz por trecho e elenco (CA-A3)."""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest

from magi.audiolivro.config import ConfigAudiolivro, parse_audiolivro
from magi.audiolivro.contratos import GENEROS, IDADES, Emocao, OpcoesVoz, Tipo, Trecho
from magi.audiolivro.vozes import (
    JUNTAR_ATE,
    PAUSA_TROCA_VOZ,
    Elenco,
    grupos,
    juntar,
    misturar,
    normalizar,
    opcoes,
    partes,
)

DELA = {"pt-br": "pf_dora", "en-gb": "bf_isabella"}
#: Prefixos das vozes do Kokoro v1.0 (nada de voz paga: alloy, nova, shimmer...).
KOKORO = (
    "af_",
    "am_",
    "bf_",
    "bm_",
    "pf_",
    "pm_",
    "ef_",
    "em_",
    "ff_",
    "if_",
    "im_",
    "jf_",
    "jm_",
    "zf_",
    "zm_",
    "hf_",
    "hm_",
)


def _kokoro(voz: str) -> bool:
    return all(p.split(":")[0].startswith(KOKORO) for p in voz.split(","))


def _elenco(tmp_path: Path, idioma: str = "pt-br", cfg: ConfigAudiolivro | None = None) -> Elenco:
    cfg = cfg or ConfigAudiolivro(estado_dir=tmp_path / "estado")
    return Elenco("livro123", DELA[idioma], idioma, cfg)


@pytest.mark.parametrize("idioma", ["pt-br", "en-gb"])
def test_cobre_todo_par(tmp_path: Path, idioma: str) -> None:
    el = _elenco(tmp_path, idioma)
    for tipo, emocao, genero, idade, falante in itertools.product(
        Tipo, Emocao, (*GENEROS, None), (*IDADES, None), ("Ana", None)
    ):
        t = Trecho("x", tipo=tipo, emocao=emocao, falante=falante, genero=genero, idade=idade)  # type: ignore[arg-type]
        op = opcoes(t, el, 1.0)
        assert op.voice and _kokoro(op.voice), op
        assert op.lang == idioma
        assert op.speed is not None and 0.7 <= op.speed <= 1.3
        if tipo in (Tipo.NARRACAO, Tipo.TITULO) and not (falante and tipo is Tipo.NARRACAO):
            assert op.voice == DELA[idioma]
        if tipo is Tipo.FALA:
            assert op.voice != DELA[idioma]


@pytest.mark.parametrize("idioma", ["pt-br", "en-gb"])
def test_cinco_personagens_cinco_vozes_e_reabrir(tmp_path: Path, idioma: str) -> None:
    el = _elenco(tmp_path, idioma)
    elenco = [
        ("Ana", "f", None),
        ("Bia", "f", None),
        ("Carla", "f", None),
        ("Davi", "m", None),
        ("Edu", "m", None),
    ]
    vozes = [el.voz(n, g, i) for n, g, i in elenco]  # type: ignore[arg-type]
    assert len(set(vozes)) == 5
    assert DELA[idioma] not in vozes
    assert all(_kokoro(v) for v in vozes)
    de_novo = _elenco(tmp_path, idioma)
    assert [de_novo.voz(n, None, None) for n, _, _ in elenco] == vozes
    assert de_novo.voz("ÁNA ", None, "idoso") == vozes[0]  # nome normalizado; voz fixa no livro


def test_grupo_esgotado_mistura_nova(tmp_path: Path) -> None:
    el = _elenco(tmp_path)
    vozes = [el.voz(f"m{i}", "m", None) for i in range(6)]
    assert len(set(vozes)) == 6
    assert vozes[:2] == ["pm_alex", "pm_santa"]
    assert vozes[2] == "pm_alex:0.6,pm_santa:0.4"


def test_grupo_por_idade_e_genero(tmp_path: Path) -> None:
    el = _elenco(tmp_path, "en-gb")
    assert el.voz("Old Tom", "m", "idoso") == "bm_fable"
    assert el.voz("Kid", "f", "crianca") == "bf_lily"
    assert el.voz("Lad", "m", "jovem") == "am_puck"


def test_fala_sem_falante(tmp_path: Path) -> None:
    el = _elenco(tmp_path, "en-gb")
    assert opcoes(Trecho("x", Tipo.FALA, genero="f"), el, 1.0).voice == "bf_emma"
    assert opcoes(Trecho("x", Tipo.FALA, genero="m"), el, 1.0).voice == "bm_george"
    assert opcoes(Trecho("x", Tipo.FALA), el, 1.0).voice == "bf_isabella:0.6,bf_emma:0.4"
    assert not el.vozes  # nada gravado


def test_arquivo_do_elenco_atomico(tmp_path: Path) -> None:
    el = _elenco(tmp_path)
    el.voz("Ana", "f", None)
    arq = tmp_path / "estado" / "audiolivro" / "elenco" / "livro123.json"
    assert json.loads(arq.read_text())["vozes"] == {"ana": el.vozes["ana"]}
    assert not list(arq.parent.glob("*.tmp"))
    arq.write_text("{quebrado")
    assert _elenco(tmp_path).vozes == {}


def test_config_sobrepoe_grupo(tmp_path: Path) -> None:
    cfg = parse_audiolivro({"audiolivro": {"vozes": {"pt-br": {"m": ["pm_santa"]}}}})
    g = grupos("pt-br", cfg)
    assert g["m"] == ("pm_santa",)
    assert g["f"] == grupos("pt-br", ConfigAudiolivro())["f"]
    assert grupos("en-us", cfg)["m"][0] == "am_adam"
    assert grupos("fr-fr", cfg) == grupos("pt-br", ConfigAudiolivro())


@pytest.mark.parametrize(
    ("emocao", "velocidade", "pausa"),
    [
        (Emocao.TENSA, 1.08, 150),
        (Emocao.GRITO, 1.08, 150),
        (Emocao.MEDO, 1.04, 250),
        (Emocao.SUSSURRO, 0.92, 450),
        (Emocao.NEUTRA, 1.0, 0),
        (Emocao.ALEGRE, 1.0, 0),
    ],
)
def test_velocidade_e_pausa_pela_emocao(
    tmp_path: Path, emocao: Emocao, velocidade: float, pausa: int
) -> None:
    op = opcoes(Trecho("x", emocao=emocao), _elenco(tmp_path), 1.0)
    assert (op.speed, op.pausa_ms) == (pytest.approx(velocidade), pausa)


def test_titulo_pensamento_e_limites(tmp_path: Path) -> None:
    el = _elenco(tmp_path)
    assert opcoes(Trecho("x", Tipo.TITULO), el, 1.0) == OpcoesVoz("pf_dora", 0.95, "pt-br", 700)
    assert opcoes(Trecho("x", Tipo.PENSAMENTO), el, 1.0).speed == pytest.approx(0.95)
    assert opcoes(Trecho("x", emocao=Emocao.GRITO), el, 1.5).speed == 1.3
    assert opcoes(Trecho("x", emocao=Emocao.TRISTE), el, 0.5).speed == 0.7


def test_juntar() -> None:
    a = OpcoesVoz("pf_dora", 1.0, "pt-br")
    b = OpcoesVoz("pm_alex", 1.0, "pt-br")
    out = juntar([("Um.", a), ("Dois.", a), ("Três.", b), ("", b), ("Quatro.", a)])
    assert out == [
        ("Um. Dois.", OpcoesVoz("pf_dora", 1.0, "pt-br", PAUSA_TROCA_VOZ)),
        ("Três.", OpcoesVoz("pm_alex", 1.0, "pt-br", PAUSA_TROCA_VOZ)),
        ("Quatro.", a),
    ]
    longos = juntar([("x" * 300, a), ("y" * 300, a)])
    assert len(longos) == 2 and all(len(t) <= JUNTAR_ATE for t, _ in longos)


def test_partes_do_trecho(tmp_path: Path) -> None:
    el = _elenco(tmp_path)
    trechos = [
        Trecho("— Vem", Tipo.FALA, falante="Ana", genero="f"),
        Trecho("— disse ela.", Tipo.NARRACAO),
        Trecho("Ela saiu.", Tipo.NARRACAO, frase=1),
    ]
    out = partes(trechos, el, 1.0)
    assert [t for t, _ in out] == ["— Vem", "— disse ela. Ela saiu."]
    assert out[0][1].voice == el.vozes["ana"] and out[0][1].pausa_ms == PAUSA_TROCA_VOZ


def test_misturar_e_normalizar() -> None:
    assert misturar("bf_emma", "bf_alice") == "bf_emma:0.6,bf_alice:0.4"
    assert misturar("pf_dora:0.5,af_bella:0.5", "pm_alex") == "pm_alex:0.4,pf_dora:0.3,af_bella:0.3"
    assert normalizar("  José   da Silva ") == "jose da silva"
