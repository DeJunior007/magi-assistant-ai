"""3.6 Resposta curta e completa (R12.3): fala ≤ 2 frases, legenda completa, cards de links."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from magi.common.contracts import (
    ActionResult,
    CardLevel,
    CardMsg,
    SubtitleMsg,
    TurnState,
)
from magi.core.compose import (
    MAX_CARDS,
    SAY_SEE_HUD,
    clean_speech,
    compose,
    merge_cards,
    sentences,
    short_speech,
    subtitle,
)
from magi.core.turn import TurnDeps, TurnMachine, TurnPipeline

LONG = (
    "## Elden Ring 🎮\n"
    "O **Elden Ring** saiu em 2022 pela FromSoftware. É do Sr. Miyazaki, diretor de Dark Souls! "
    "Tem DLC, a *Shadow of the Erdtree*. Veja mais em https://eldenring.wiki/dlc.\n\n"
    "- [Wiki oficial](https://eldenring.wiki)\n"
    "- Guia de chefes https://guias.gg/er/chefes\n"
    "1. Comece pelo Limgrave\n"
)


def test_short_phrase_untouched():
    for text in ("Volume em 30%.", "Pronto, abri o Steam.", "sem ponto", "Tá 22 graus, 3.5 mm de chuva."):
        assert short_speech(text) == text
        assert compose(ActionResult(ok=True, speech=text)) == ActionResult(ok=True, speech=text)


def test_long_answer_becomes_two_sentences_and_full_subtitle():
    res = compose(ActionResult(ok=True, speech=LONG))
    assert res.speech == "Elden Ring. O Elden Ring saiu em 2022 pela FromSoftware."
    assert len(sentences(res.speech)) == 2
    assert res.full_text == LONG
    sub = subtitle(res)
    assert isinstance(sub, SubtitleMsg) and sub.text == res.speech
    assert sub.full is not None
    assert "diretor de Dark Souls!" in sub.full and "Shadow of the Erdtree" in sub.full
    assert "**" not in sub.full and "##" not in sub.full and "http" not in sub.full


def test_cut_only_at_sentence_end_and_abbreviations():
    text = "O Sr. Silva chegou às 10h. Ele trouxe o mapa… Depois saiu. Fim."
    assert short_speech(text) == "O Sr. Silva chegou às 10h. Ele trouxe o mapa…"
    assert short_speech("Uma frase só bem comprida, com vírgulas, sem ponto final") == (
        "Uma frase só bem comprida, com vírgulas, sem ponto final"
    )


def test_url_never_spoken():
    for text in (
        LONG,
        "Achei aqui: https://x.com/a?b=1. Dá uma olhada.",
        "Link: www.site.org/p",
        "https://a.com",
    ):
        speech = compose(ActionResult(ok=True, speech=text)).speech
        assert "http" not in speech and "www." not in speech and ".com" not in speech
    assert compose(ActionResult(ok=True, speech="https://a.com")).speech == SAY_SEE_HUD


def test_markdown_emoji_and_lists_cleaned():
    text = "# Título\n> **Negrito** e _itálico_ com `código` 😀✨\n- item 1\n- item 2\n\n---\nFim."
    assert clean_speech(text) == "Título. Negrito e itálico com código. Fim."
    assert clean_speech("nome_de_arquivo.txt") == "nome_de_arquivo.txt"


def test_cards_from_links_and_lists_deduped_and_capped():
    tool_card = CardMsg(CardLevel.LINK, "Wiki", "https://eldenring.wiki/")
    res = compose(ActionResult(ok=True, speech=LONG, cards=(tool_card,)))
    urls = [c.url for c in res.cards]
    assert res.cards[0] is tool_card  # cards da ferramenta primeiro; a mesma URL não repete
    assert urls == ["https://eldenring.wiki/", "https://eldenring.wiki/dlc", "https://guias.gg/er/chefes", ""]
    assert res.cards[2].title == "Guia de chefes" and res.cards[2].level is CardLevel.LINK
    assert res.cards[3] == CardMsg(CardLevel.NORMAL, "Comece pelo Limgrave")
    many = [CardMsg(CardLevel.LINK, f"L{i}", f"https://s{i}.com") for i in range(8)]
    assert len(merge_cards(many, many)) == MAX_CARDS
    assert compose(res) == res  # idempotente


def test_bare_url_card_uses_host():
    res = compose(ActionResult(ok=True, speech="Saiu notícia em https://www.jogos.com.br/n/1."))
    assert res.cards == (CardMsg(CardLevel.LINK, "jogos.com.br", "https://www.jogos.com.br/n/1"),)
    assert res.speech == "Saiu notícia em."


# -- ligado no núcleo: _deliver (agente/ações) e announce (proativos) ----------------------------


class _Hud:
    def __init__(self) -> None:
        self.sent: list[Any] = []

    async def send(self, msg: Any) -> None:
        self.sent.append(msg)


class _Speaker:
    def __init__(self) -> None:
        self.said: list[str] = []

    async def say(self, text: str, link: Any, *, personal: bool) -> None:
        self.said.append(text)


def _machine(speaker: _Speaker | None) -> tuple[TurnMachine, _Hud]:
    hud = _Hud()
    link = SimpleNamespace(hello=SimpleNamespace(satellite="pc"))
    machine = TurnMachine(link, hud, TurnPipeline(TurnDeps(speaker=speaker)))  # type: ignore[arg-type]
    return machine, hud


async def test_deliver_sends_link_cards_to_hud_and_speaks_short():
    speaker = _Speaker()
    machine, hud = _machine(speaker)
    machine._state = TurnState.THINKING
    await machine._deliver(ActionResult(ok=True, speech=LONG))
    cards = [m for m in hud.sent if isinstance(m, CardMsg)]
    assert any(c.url == "https://eldenring.wiki" and c.title == "Wiki oficial" for c in cards)
    [sub] = [m for m in hud.sent if isinstance(m, SubtitleMsg)]
    assert sub.full and "Dark Souls" in sub.full
    assert speaker.said == ["Elden Ring. O Elden Ring saiu em 2022 pela FromSoftware."]


async def test_announce_composes_proactive_text():
    speaker = _Speaker()
    machine, hud = _machine(speaker)
    machine._start = lambda coro: coro.close()  # type: ignore[method-assign]
    text = "Notícia bomba: saiu o trailer. Assiste aqui https://yt.be/x. Mais detalhes depois. E mais."
    assert await machine.announce(text)
    [sub] = [m for m in hud.sent if isinstance(m, SubtitleMsg)]
    assert sub.text == "Notícia bomba: saiu o trailer. Assiste aqui."
    assert sub.full and "Mais detalhes depois." in sub.full
    assert [c.url for c in hud.sent if isinstance(c, CardMsg)] == ["https://yt.be/x"]
