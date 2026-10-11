"""E2.2: seletor da frase de espera (spec §3, §4; CA-03, CA-04). Catálogo de teste, rng fixo."""

from __future__ import annotations

import random
from pathlib import Path

import pytest

from magi.common.config import ConfigError
from magi.core.espera import Catalogo, Cota, demorado, escolher, honesta, mesma_espera, topico

YAML = """
topicos:
  jogo:
    palavras: [build, boss, chefe, conquista, fase, mapa, patch, lore]
    frases: ["Hm, deixa eu pensar nessa.", "Peraí, tô juntando as ideias.", "Essa é das boas."]
    moldes: ["Hm, {jogo}… deixa eu pensar."]
  noticia:
    palavras: [noticia, manchete, aconteceu, saiu]
    frases: ["Hm, deixa eu lembrar disso.", "Boa pergunta, peraí."]
  conta:
    palavras: [quanto, quantos, calcula, converte, porcento]
    frases: ["Hm, deixa eu fazer a conta de cabeça."]
  vazio:
    palavras: [vazio]
  geral:
    frases: ["Hm, deixa eu pensar.", "Boa. Um segundo de cérebro aqui", "Hm, essa é boa."]
demorados: [jogo, noticia, vazio]
sinais_demora: [pesquisa, procura, hoje, preco, steam]
vetadas: ["Essa é das boas."]
"""

GERAL = {"Hm, deixa eu pensar.", "Boa. Um segundo de cérebro aqui", "Hm, essa é boa."}
JOGOS_FALSOS = ("Elden Ring", "Hollow Knight", "Stardew Valley")


@pytest.fixture
def cat(tmp_path: Path) -> Catalogo:
    p = tmp_path / "espera.yaml"
    p.write_text(YAML, encoding="utf-8")
    g = tmp_path / "gosto.toml"
    g.write_text('[espera]\nvetadas = ["Peraí, tô juntando as ideias."]\n', encoding="utf-8")
    return Catalogo.load(p, g)


# --- Catalogo.load -------------------------------------------------------------------------


def test_load_ordem_e_vetadas(cat: Catalogo) -> None:
    assert [t.nome for t in cat.topicos] == ["jogo", "noticia", "conta", "vazio", "geral"]
    assert cat.demorados == {"jogo", "noticia", "vazio"}
    assert "preco" in cat.sinais_demora
    assert "essa e das boas" in cat.vetadas  # do yaml
    assert "perai to juntando as ideias" in cat.vetadas  # do gosto


def test_load_sem_arquivos(tmp_path: Path) -> None:
    cat = Catalogo.load(tmp_path / "nao.yaml", tmp_path / "nao.toml")
    assert cat.topicos == ()
    assert escolher(cat, "pesquisa o preço", Cota(), random.Random(1)) is None


def test_load_invalido(tmp_path: Path) -> None:
    p = tmp_path / "espera.yaml"
    p.write_text("topicos:\n  jogo: {frases: oi}\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        Catalogo.load(p)


# --- topico / demorado (spec §3.2, §3.3, D2) ------------------------------------------------


def test_topico(cat: Catalogo) -> None:
    assert topico(cat, "Como passo desse CHEFE?") == "jogo"
    assert topico(cat, "o que saiu de notícia hoje") == "noticia"  # 2 acertos
    assert topico(cat, "quanto é 8 vezes 7") == "conta"
    assert topico(cat, "oi, tudo bem?") == "geral"
    assert topico(cat, "") == "geral"


def test_topico_empate_pela_ordem(cat: Catalogo) -> None:
    assert topico(cat, "quanto custa o patch") == "jogo"


def test_demorado(cat: Catalogo) -> None:
    assert demorado(cat, "como passo desse chefe")  # tópico
    assert demorado(cat, "o que saiu de notícia hoje")  # tópico
    assert demorado(cat, "procura uma receita de bolo")  # sinal (prefixo: "procura")
    assert demorado(cat, "qual o preço disso")  # sinal sem acento
    assert not demorado(cat, "quanto é 8 vezes 7")  # conta
    assert not demorado(cat, "me conta uma piada")  # geral


# --- Cota / escolher (CA-04) ----------------------------------------------------------------


def test_escolher_so_demorado(cat: Catalogo) -> None:
    rng = random.Random(0)
    assert escolher(cat, "quanto é 8 vezes 7", Cota(), rng) is None
    assert escolher(cat, "me conta uma piada", Cota(), rng) is None
    assert escolher(cat, "quanto é 8 vezes 7", Cota(), rng, so_demorado=False) == (
        "Hm, deixa eu fazer a conta de cabeça."
    )
    assert escolher(cat, "me conta uma piada", Cota(), rng, so_demorado=False) in GERAL


def test_escolher_vetadas_e_topico(cat: Catalogo) -> None:
    vistas = {escolher(cat, "como passo desse chefe", Cota(), random.Random(i)) for i in range(40)}
    assert vistas == {"Hm, deixa eu pensar nessa."}  # as outras duas estão vetadas


def test_escolher_molde_so_com_jogo(cat: Catalogo) -> None:
    vistas = {
        escolher(cat, "qual a build pro boss", Cota(), random.Random(i), jogo="Elden Ring") for i in range(40)
    }
    assert vistas == {"Hm, deixa eu pensar nessa.", "Hm, Elden Ring… deixa eu pensar."}
    longo = "J" * 31
    assert {escolher(cat, "qual a build", Cota(), random.Random(i), jogo=longo) for i in range(20)} == {
        "Hm, deixa eu pensar nessa."
    }
    # molde só no tópico jogo
    assert all(
        "Elden" not in (escolher(cat, "saiu notícia", Cota(), random.Random(i), jogo="Elden Ring") or "")
        for i in range(20)
    )


def test_escolher_topico_vazio_cai_em_geral(cat: Catalogo) -> None:
    assert escolher(cat, "vazio", Cota(), random.Random(3)) in GERAL


def test_escolher_continuacao_curta(cat: Catalogo) -> None:
    rng = random.Random(0)
    assert escolher(cat, "e o chefe?", Cota(), rng, continuacao=True) is None
    assert escolher(cat, "e o chefe da fase final?", Cota(), rng, continuacao=True) is not None
    assert escolher(cat, "e o chefe?", Cota(), rng) is not None


def test_escolher_sem_repetir_as_duas_ultimas(cat: Catalogo) -> None:
    cota = Cota(ultimas=["Hm, deixa eu lembrar disso."])
    for i in range(20):
        assert escolher(cat, "saiu notícia", cota, random.Random(i)) == "Boa pergunta, peraí."
    cota = Cota(ultimas=["Hm, deixa eu lembrar disso.", "Boa pergunta, peraí."])
    assert escolher(cat, "saiu notícia", cota, random.Random(0)) is None


def test_escolher_nao_registra(cat: Catalogo) -> None:
    cota = Cota()
    escolher(cat, "como passo desse chefe", cota, random.Random(0))
    assert cota == Cota()


def test_cota_folga_e_memoria() -> None:
    cota = Cota()
    assert cota.livre()
    cota.registrar("a")
    assert cota.livre()
    cota.registrar("b")
    assert not cota.livre()  # 3º turno seguido: folga
    cota.registrar(None)
    assert cota.livre() and cota.seguidas == 0
    cota.registrar("c")
    assert cota.ultimas == ["b", "c"]


def test_escolher_folga(cat: Catalogo) -> None:
    cota, rng, falas = Cota(), random.Random(7), []
    for _ in range(6):
        f = escolher(cat, "pesquisa o preço disso hoje", cota, rng)
        cota.registrar(f)
        falas.append(f is not None)
    assert falas == [True, True, False, True, True, False]


# --- mesma_espera (spec §3.4) ---------------------------------------------------------------


@pytest.mark.parametrize(
    "frase",
    ["Deixa eu ver…", "Um segundo.", "Peraí, já te falo", "Hmm, deixa eu pensar.", "Só um momento!"],
)
def test_mesma_espera_sim(frase: str) -> None:
    assert mesma_espera(frase)


@pytest.mark.parametrize(
    "frase",
    [
        "O chefe fraco a fogo é o Malenia.",
        "Deixa eu ver: a build de força com espadão costuma ir muito bem nessa fase.",
        "",
    ],
)
def test_mesma_espera_nao(frase: str) -> None:
    assert not mesma_espera(frase)


# --- honesta (spec §4, CA-03) ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("frase", "tipo"),
    [
        ("Vou pesquisar isso.", "acao"),
        ("Vou buscar aqui.", "acao"),
        ("Tô pesquisando.", "acao"),
        ("Tô buscando.", "acao"),
        ("Abrindo o navegador.", "acao"),
        ("Consultando.", "acao"),
        ("Olhando aqui na lista.", "acao"),
        ("Achei!", "resultado"),
        ("Encontrei uma coisa.", "resultado"),
        ("Já sei.", "resultado"),
        ("Já vi isso.", "resultado"),
        ("Pronto.", "resultado"),
        ("Aqui está.", "resultado"),
        ("É isso aí.", "resultado"),
        ("Com certeza.", "certeza"),
        ("Sei sim.", "certeza"),
        ("Garanto.", "certeza"),
        ("Prometo que sai.", "certeza"),
        ("Já já te falo.", "certeza"),
        ("Rapidinho.", "certeza"),
        ("Num instante te digo.", "certeza"),
        ("Segundo a wiki, hm.", "fonte"),
        ("De acordo com eles.", "fonte"),
        ("Hm, no Google tem.", "fonte"),
        ("Hm, na wiki tem.", "fonte"),
        ("Hm, no site deles.", "fonte"),
        ("Hm, 3 opções.", "numero"),
        ("Hm, umas três coisas.", "numero"),
        ("Hm, deixa eu pensar bem nessa pergunta difícil agora.", "tamanho"),
        ("Hm. Deixa eu pensar.", "tamanho"),
    ],
)
def test_honesta_reprova(frase: str, tipo: str) -> None:
    assert any(v.startswith(tipo) for v in honesta(frase)), honesta(frase)


@pytest.mark.parametrize(
    "frase",
    [
        "Hm, deixa eu pensar nessa.",
        "Peraí, tô juntando as ideias.",
        "Boa pergunta, deixa eu lembrar.",
        "Essa é das boas.",
        "Um segundo de cérebro aqui.",  # "um" é artigo; "um segundo" não é fonte
        "Hm, em dezembro, né",  # "dez" só como palavra inteira
        "Hm, Elden Ring… deixa eu pensar.",  # reticências não fecham frase
    ],
)
def test_honesta_aprova(frase: str) -> None:
    assert honesta(frase) == []


def test_honesta_catalogo_de_teste_inteiro(cat: Catalogo) -> None:
    frases = [f for t in cat.topicos for f in t.frases]
    frases += [m.replace("{jogo}", j) for t in cat.topicos for m in t.moldes for j in JOGOS_FALSOS]
    reprovadas = {f: honesta(f) for f in frases if f != "Boa. Um segundo de cérebro aqui"}
    assert all(not v for v in reprovadas.values()), reprovadas
    assert honesta("Boa. Um segundo de cérebro aqui") == ["tamanho: > 1 frase"]
