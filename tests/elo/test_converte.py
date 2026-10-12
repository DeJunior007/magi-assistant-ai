"""Ponte elo ↔ contracts: CA-Y4."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from magi.common.contracts import (
    ActionRequest,
    ActionResult,
    CardLevel,
    CardMsg,
    Intent,
    Slot,
    TurnContext,
    WakeSource,
)
from magi.elo.converte import (
    card_de_cardmsg,
    intents_perigosos,
    pedido_de_request,
    request_de_pedido,
    resultado_de_action,
)
from magi.elo.mensagens import Acao, AcaoOk, EloError, Envelope, Tipo, decode, encode

CTX = TurnContext(satellite="celular", source=WakeSource.PTT, started_at=datetime(2026, 10, 12, tzinfo=UTC))


def _req(**kw: object) -> ActionRequest:
    intent = Intent(id="volume.set", slots=(Slot(name="volume", value="30", raw="trinta", display="30"),))
    base = {
        "intent": intent,
        "ctx": CTX,
        "text": "volume trinta",
        "confirmed": True,
        "args": {"force": True, "n": 3},
    }
    base.update(kw)
    return ActionRequest(**base)  # type: ignore[arg-type]


def test_ca_y4_ida_e_volta_preserva() -> None:
    req = _req()
    p = pedido_de_request(req)
    # também atravessa o fio
    env = Envelope(t=Tipo.ACAO, corpo=Acao(pedido=p, origem="voz-pc"), de="pc", para="casa")
    p2 = decode(encode(env)).corpo.pedido  # type: ignore[union-attr]
    volta = request_de_pedido(p2, CTX, perigosos=frozenset())
    assert volta.intent.id == "volume.set"
    assert [(s.name, s.value) for s in volta.intent.slots] == [("volume", "30")]
    assert volta.confirmed is True
    assert dict(volta.args) == {"force": True, "n": 3}
    assert volta.text == "volume trinta"
    assert volta.ctx is CTX


def test_ca_y4_danger_do_intents_yaml() -> None:
    perigosos = intents_perigosos()
    assert "game.close" in perigosos
    p = pedido_de_request(_req(intent=Intent(id="game.close")))
    assert request_de_pedido(p, CTX).intent.danger is True
    assert request_de_pedido(p, CTX, perigosos=()).intent.danger is False


def test_args_nao_escalar_recusado() -> None:
    with pytest.raises(EloError) as e:
        pedido_de_request(_req(args={"lista": [1]}))
    assert e.value.codigo == "campo"


def test_ca_y4_precisa_confirmar_sem_on_confirm() -> None:
    res = ActionResult(
        ok=True, speech="Fechar o jogo? Confirma?", needs_confirmation=True, dangerous=True, on_confirm=_req()
    )
    r = resultado_de_action(res)
    assert r.precisa_confirmar is True and r.perigosa is True
    assert r.fala == "Fechar o jogo? Confirma?"
    assert not hasattr(r, "on_confirm")
    env = Envelope(t=Tipo.ACAO_OK, corpo=AcaoOk(resultado=r), de="casa", para="pc")
    assert "on_confirm" not in encode(env)
    assert resultado_de_action(ActionResult(ok=True, full_text="só texto")).fala == "só texto"


def test_card_de_cardmsg() -> None:
    c = card_de_cardmsg(CardMsg(level=CardLevel.ALTA, title="Notícia", url="https://ex.com", source="G1"))
    assert (c.titulo, c.texto, c.url, c.nivel) == ("Notícia", "G1", "https://ex.com", "alta")
    vazio = card_de_cardmsg(CardMsg(level=CardLevel.LINK, title="x"))
    assert vazio.url is None and vazio.texto == ""
