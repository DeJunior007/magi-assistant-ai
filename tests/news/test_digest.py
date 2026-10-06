"""Resumo extrativo e texto da matéria do "conta mais dessa" (sem rede)."""

from __future__ import annotations

from magi.news.article import article_text
from magi.news.digest import MAX_CHARS, digest, sentences

A = (
    "A Playground Games finalmente respondeu à comunidade de Forza Horizon 6 depois de meses de silêncio. "
    "O estúdio disse que está lendo todos os comentários e que vai falar mais com os jogadores. "
    "Leia também: as melhores ofertas da semana em jogos de corrida. "
    "Os jogadores reclamam da falta de chat de voz no Forza Horizon 6, que existia no Forza Motorsport. "
    "O jogo recebeu nota 10 da IGN no lançamento, mas a comunidade segue frustrada."
)
B = (
    "Forza Horizon 6: a Playground Games respondeu à comunidade depois de meses de silêncio total. "
    "Um patch com chat de voz está em estudo, segundo a postagem do estúdio nas redes sociais. "
    "Clique aqui para seguir nosso canal."
)


def test_frases_sem_chamada_nem_frase_curta():
    got = sentences(A + "\nCurta.")
    assert all("Leia também" not in s for s in got) and "Curta." not in got
    assert len(got) == 4


def test_resumo_sem_repetir_e_na_ordem():
    out = digest([A, B], "Forza Horizon 6: Playground responde à comunidade")
    assert len(out) <= MAX_CHARS
    assert out.count("meses de silêncio") == 1  # a mesma informação de duas fontes entra uma vez
    assert "chat de voz" in out and "Clique aqui" not in out
    assert out.index("Playground Games finalmente") < out.index("patch com chat de voz")  # A antes de B


def test_resumo_limita_tamanho_e_vazio():
    assert digest([]) == "" and digest(["curto."]) == ""
    longo = " ".join(f"Frase número {i} fala de Forza Horizon e da Playground Games aqui." for i in range(80))
    assert len(digest([longo], max_chars=300)) <= 300


def test_texto_da_materia_pega_o_bloco_com_mais_texto():
    p = "<p>" + "Parágrafo da matéria principal com bastante texto para contar. " * 2 + "</p>"
    html = (
        "<html><body><nav><p>" + "menu " * 30 + "</p></nav>"
        "<article><p>Oferta: monitor gamer em promoção hoje mesmo na loja parceira aqui.</p></article>"
        f"<article><h1>Título</h1>{p * 5}<p>curto</p></article>"
        "<footer><p>" + "rodapé " * 30 + "</p></footer></body></html>"
    )
    text = article_text(html)
    assert text.count("Parágrafo da matéria principal") == 10
    assert "menu" not in text and "rodapé" not in text and "Oferta" not in text and "curto" not in text
    assert article_text("") == ""
