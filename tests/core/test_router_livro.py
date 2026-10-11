"""Roteador e audiolivro (A2.3, spec §5): ``context: reading`` só concorre com leitura (A6.1)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from magi.common.contracts import RouteKind, TurnContext, WakeSource
from magi.core.router import LocalRouter, load_intents

SEM = TurnContext("pc", list(WakeSource)[0], datetime.now())
COM = TurnContext("pc", list(WakeSource)[0], datetime.now(), reading=object())


@pytest.fixture(scope="module")
def router() -> LocalRouter:
    return LocalRouter()


def _id(router: LocalRouter, text: str, ctx: TurnContext) -> str | None:
    r = router.route(text, ctx)
    return r.intent.id if r.kind is RouteKind.LOCAL and r.intent else None


@pytest.mark.parametrize(
    ("text", "sem", "com"),
    [
        ("pausa", "music.pause", "book.pause"),
        ("para", None, "book.stop"),
        ("continua", None, "book.resume"),
        ("espera", None, "book.pause"),
        ("volta um parágrafo", None, "book.back"),
        ("repete", None, "book.back"),
        ("pula 2 parágrafos", None, "book.forward"),
        ("próximo capítulo", None, "book.chapter"),
        ("mais devagar", None, "book.speed"),
        ("para a música", "music.pause", "music.pause"),
        ("lê o livro duna", "book.read", "book.read"),
        ("continua o livro", "book.resume", "book.resume"),
        ("para de ler", "book.stop", "book.stop"),
        ("onde a gente parou", "book.where", "book.where"),
        ("que livros eu tenho", "book.list", "book.list"),
        ("quanto falta desse livro", "book.time", "book.time"),
    ],
)
def test_contexto_reading(router: LocalRouter, text: str, sem: str | None, com: str) -> None:
    assert _id(router, text, SEM) == sem
    assert _id(router, text, COM) == com


def test_slots(router: LocalRouter) -> None:
    slots = {s.name: s.value for s in router.route("volta 3 parágrafos", COM).intent.slots}
    assert slots == {"amount": "3"}
    slots = {s.name: s.value for s in router.route("lê mais rápido", COM).intent.slots}
    assert slots == {"text": "faster"}
    slots = {s.name: s.value for s in router.route("quanto tempo leva duna", SEM).intent.slots}
    assert slots == {"query": "duna"}


def test_contexto_desconhecido_falha(tmp_path: Path) -> None:
    p = tmp_path / "i.yaml"
    yaml = 'intents:\n  - id: book.pause\n    context: jogo\n    phrases: ["pausa"]\n'
    p.write_text(yaml, encoding="utf-8")
    with pytest.raises(ValueError, match="context"):
        load_intents(p)
