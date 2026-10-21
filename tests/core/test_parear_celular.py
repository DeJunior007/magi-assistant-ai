"""``celular.parear`` (ayanami-central Y6.6b): "pareia o celular" pede o código à Ayanami falsa,
mostra o card no HUD e responde curto; o código nunca vai para a fala nem para log."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from magi.common.contracts import (
    ActionRequest,
    CardMsg,
    Intent,
    IntentId,
    SubtitleMsg,
    TurnContext,
    WakeSource,
)
from magi.core import i18n
from magi.core.actions.celular import (
    SAY_AYANAMI_FORA,
    SAY_CODIGO_NA_TELA,
    SAY_SEM_AYANAMI,
    SAY_SEM_TOKEN,
    CelularActions,
)
from magi.core.proactive.sink import ProactiveSink
from magi.core.router import LocalRouter

URL = "http://ayanami.teste"
CODIGO = "482913"


class Hud:
    def __init__(self) -> None:
        self.msgs: list[Any] = []

    async def send(self, msg: Any) -> None:
        self.msgs.append(msg)


class Core:
    def __init__(self, hud: Hud) -> None:
        self.proactive = ProactiveSink(hud)


def _api(status: int = 201, chamadas: list[str] | None = None) -> httpx.AsyncClient:
    def h(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST" and req.url.path == "/v1/pareamento"
        assert req.headers["Authorization"] == "Bearer tok-falso"
        if chamadas is not None:
            chamadas.append(req.url.path)
        return httpx.Response(status, json={"codigo": CODIGO, "expira_em": "2026-10-21T12:05:00Z"})

    return httpx.AsyncClient(transport=httpx.MockTransport(h))


def _req() -> ActionRequest:
    ctx = TurnContext(satellite="pc", source=WakeSource.PTT, started_at=datetime.now(UTC))
    return ActionRequest(Intent(IntentId.CELULAR_PAREAR.value), ctx, text="pareia o celular")


@pytest.mark.parametrize("frase", ["pareia o celular", "conectar celular", "código do celular",
                                   "Condessa, pareia o celular"])
def test_frases_caem_no_intent(frase: str) -> None:
    res = LocalRouter().route(frase)
    assert res.intent is not None and res.intent.id == IntentId.CELULAR_PAREAR.value


async def test_pareia_mostra_card_e_fala_curto(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    hud, chamadas = Hud(), []
    h = CelularActions.de_config({"ayanami": {"url": URL}}, Core(hud), token=lambda: "tok-falso",
                                 http=_api(chamadas=chamadas))
    res = await h.run(_req())
    assert res.ok and res.speech == SAY_CODIGO_NA_TELA
    assert chamadas == ["/v1/pareamento"]
    assert [m.title for m in hud.msgs if isinstance(m, CardMsg)] == ["Código de pareamento 482 913"]
    assert not any(isinstance(m, SubtitleMsg) for m in hud.msgs)
    falado = f"{res.speech} {res.full_text or ''}"
    assert CODIGO not in falado and "482 913" not in falado
    assert CODIGO not in caplog.text and "482 913" not in caplog.text and "tok-falso" not in caplog.text


async def test_sem_ayanami_resposta_honesta() -> None:
    hud = Hud()
    h = CelularActions.de_config({}, Core(hud), token=lambda: pytest.fail("não lê token"))
    res = await h.run(_req())
    assert not res.ok and res.speech == SAY_SEM_AYANAMI and hud.msgs == []


async def test_sem_token() -> None:
    h = CelularActions.de_config({"ayanami": {"url": URL}}, Core(Hud()), token=lambda: None)
    res = await h.run(_req())
    assert not res.ok and res.speech == SAY_SEM_TOKEN


@pytest.mark.parametrize("status", [401, 500])
async def test_ayanami_recusa(status: int) -> None:
    hud = Hud()
    h = CelularActions.de_config({"ayanami": {"url": URL}}, Core(hud), token=lambda: "tok-falso",
                                 http=_api(status))
    res = await h.run(_req())
    assert not res.ok and res.speech == SAY_AYANAMI_FORA and hud.msgs == []


def test_frases_tem_ingles() -> None:
    tabela = i18n.load_table("en-gb")
    for s in (SAY_CODIGO_NA_TELA, SAY_SEM_AYANAMI, SAY_SEM_TOKEN, SAY_AYANAMI_FORA):
        assert tabela.phrase(s) not in (None, s)
