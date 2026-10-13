"""``magi.elo.parear`` (Y6.6): ``pedir_codigo`` com Ayanami falsa gera o card no HUD pelo sink da
proatividade e nunca loga o código; ``main`` imprime código e URL; erros sem segredo."""

from __future__ import annotations

import io
import json
import logging
from typing import Any

import httpx
import pytest

from magi.common.contracts import CardMsg, SubtitleMsg
from magi.core.proactive.ayanami import AvisosAyanami
from magi.core.proactive.sink import ProactiveSink
from magi.elo import parear
from magi.elo.parear import ErroPareamento, pedir_codigo

URL = "http://ayanami.teste"
CODIGO = "482913"


class Hud:
    def __init__(self) -> None:
        self.msgs: list[Any] = []

    async def send(self, msg: Any) -> None:
        self.msgs.append(msg)


def _api(status: int = 201, pedidos: list[Any] | None = None) -> httpx.AsyncClient:
    def h(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST" and req.url.path == "/v1/pareamento"
        assert req.headers["Authorization"] == "Bearer tok-falso"
        if pedidos is not None:
            pedidos.append(json.loads(req.content or b"{}"))
        return httpx.Response(status, json={"codigo": CODIGO, "expira_em": "2026-10-13T12:05:00Z"})

    return httpx.AsyncClient(transport=httpx.MockTransport(h))


async def test_pedir_codigo_gera_card_e_nao_loga(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    hud, pedidos = Hud(), []
    avisos = AvisosAyanami(ProactiveSink(hud))
    res = await pedir_codigo(URL, "tok-falso", nome_sugerido="celular-pedro", http=_api(pedidos=pedidos),
                             avisos=avisos)
    assert res.codigo == CODIGO and res.url == f"{URL}/app/#/parear?c={CODIGO}"
    assert pedidos == [{"nome_sugerido": "celular-pedro"}]
    cards = [m for m in hud.msgs if isinstance(m, CardMsg)]
    assert [c.title for c in cards] == ["Código de pareamento 482 913"]
    assert not any(isinstance(m, SubtitleMsg) for m in hud.msgs)  # sem legenda nem fala
    assert CODIGO not in caplog.text and "482 913" not in caplog.text and "tok-falso" not in caplog.text
    assert CODIGO not in repr(res)


@pytest.mark.parametrize("status", [401, 403, 500])
async def test_erro_sem_segredo(status: int) -> None:
    with pytest.raises(ErroPareamento) as e:
        await pedir_codigo(URL, "tok-falso", http=_api(status))
    assert "tok-falso" not in str(e.value) and CODIGO not in str(e.value)


def test_main_imprime_codigo_e_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(parear, "_qr_texto", lambda _t: None)
    out = io.StringIO()
    rc = parear.main([], config={"ayanami": {"url": URL}}, token=lambda: "tok-falso", http=_api(), out=out)
    assert rc == 0
    assert "482 913" in out.getvalue() and f"{URL}/app/#/parear?c={CODIGO}" in out.getvalue()


def test_main_sem_config_ou_token() -> None:
    assert parear.main([], config={}, token=lambda: "x") == 2
    assert parear.main([], config={"ayanami": {"url": URL}}, token=lambda: None) == 2
