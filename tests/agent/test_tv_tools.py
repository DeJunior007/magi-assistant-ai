"""C2.2: ferramentas ``tv_*`` do agente (CA-Y54; spec §13.4, DS14)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from magi.agent.tools.base import ToolArgsError
from magi.agent.tools.tv import map_app, map_entrada, map_volume, tv_tools
from magi.common.contracts import ActionRequest, ActionResult, IntentId, SlotName, TurnContext, WakeSource
from magi.core.actions.tv import SAY_CASA_OFF, TvActions, tv_actions_de
from magi.core.router import CasaCatalogo
from magi.elo.mensagens import AppInfo, TvInfo

CTX = TurnContext(satellite="pc", source=WakeSource.PTT, started_at=datetime.now(UTC))
SALA = TvInfo(id="sala", nome="TV da sala", driver="samsung", apelidos=("sala",), padrao=True)
QUARTO = TvInfo(id="quarto", nome="TV do quarto", driver="roku", apelidos=("quarto",))
CAT = CasaCatalogo(tvs=(SALA, QUARTO), apps=(AppInfo(id="youtube", nome="YouTube"),),
                   entradas={"console": "hdmi2"})


class FakeRegistry:
    def __init__(self) -> None:
        self.calls: list[ActionRequest] = []

    def register(self, handler: object) -> None:  # pragma: no cover
        raise NotImplementedError

    def handles(self, intent_id: str) -> bool:
        return True

    async def run(self, req: ActionRequest) -> ActionResult:
        self.calls.append(req)
        return ActionResult(ok=True, speech="feito")


def _tools(reg: FakeRegistry, tv: TvActions | None = None) -> dict[str, object]:
    return {t.name: t for t in tv_tools(reg, tv)}  # type: ignore[arg-type]


def _tv_com_catalogo(tmp_path: Path) -> TvActions:
    tv = TvActions("127.0.0.1", 1, tmp_path / "sem.token")
    tv.catalogo = CAT
    return tv


async def test_desligar_pede_confirmacao_sem_chamar_o_registry(tmp_path: Path) -> None:
    reg = FakeRegistry()
    tool = _tools(reg, _tv_com_catalogo(tmp_path))["tv_desligar"]
    res = await tool.run({"tv": "quarto"}, CTX)  # type: ignore[attr-defined]
    assert res.needs_confirmation and res.dangerous and reg.calls == []
    assert res.speech == "Desligar a TV do quarto? Confirma?"
    assert res.on_confirm is not None and res.on_confirm.confirmed
    assert res.on_confirm.intent.id == IntentId.TV_POWER_OFF
    assert res.on_confirm.intent.slot(SlotName.TV).value == "quarto"


def test_app_desconhecido_e_tool_args_error() -> None:
    with pytest.raises(ToolArgsError):
        map_app(lambda: CAT)({"app": "Crunchyroll"})
    m = map_app(lambda: CAT)({"app": "youtube", "tv": "sala"})
    assert m.intent_id == IntentId.TV_APP and [s.value for s in m.slots] == ["youtube", "sala"]
    # sem catálogo (casa ainda não respondeu): o nome segue cru, a casa decide
    assert map_app(CasaCatalogo)({"app": "Crunchyroll"}).slots[0].value == "Crunchyroll"


async def test_app_desconhecido_vira_fala_confusa(tmp_path: Path) -> None:
    reg = FakeRegistry()
    res = await _tools(reg, _tv_com_catalogo(tmp_path))["tv_app"].run({"app": "Crunchyroll"}, CTX)  # type: ignore[attr-defined]
    assert not res.ok and res.speech == "Não conheço esse app." and reg.calls == []


def test_tv_estado_nao_e_serial_e_as_acoes_sao() -> None:
    tools = _tools(FakeRegistry())
    assert getattr(tools["tv_estado"], "serial", False) is False
    assert all(t.serial for n, t in tools.items() if n != "tv_estado")  # type: ignore[attr-defined]
    nomes = {"tv_ligar", "tv_desligar", "tv_volume", "tv_mudo", "tv_app", "tv_entrada", "tv_estado"}
    assert set(tools) == nomes


def test_volume_entrada_e_tv_desconhecida() -> None:
    assert map_volume(lambda: CAT)({"valor": "+3"}).slots[0].value == "+3"
    with pytest.raises(ToolArgsError):
        map_volume(lambda: CAT)({"valor": "150"})
    assert map_entrada(lambda: CAT)({"entrada": "HDMI 1"}).slots[0].value == "hdmi1"
    assert map_entrada(lambda: CAT)({"entrada": "console"}).slots[0].value == "hdmi2"
    with pytest.raises(ToolArgsError):
        map_volume(lambda: CAT)({"valor": "10", "tv": "cozinha"})


def test_descricao_lista_as_tvs(tmp_path: Path) -> None:
    tv = _tv_com_catalogo(tmp_path)
    spec = _tools(FakeRegistry(), tv)["tv_ligar"].spec  # type: ignore[attr-defined]
    assert "TV da sala" in spec.description and "padrão: TV da sala" in spec.description


async def test_tv_estado_sem_casa_diz_fora_do_ar(tmp_path: Path) -> None:
    tool = _tools(FakeRegistry(), TvActions("127.0.0.1", 1, tmp_path / "sem.token"))["tv_estado"]
    res = await tool.run({}, CTX)  # type: ignore[attr-defined]
    assert res.speech == SAY_CASA_OFF


def test_tv_actions_de_acha_no_registry(tmp_path: Path) -> None:
    from magi.core.actions import Registry

    tv = _tv_com_catalogo(tmp_path)
    assert tv_actions_de(Registry([tv])) is tv
    assert tv_actions_de(Registry([])) is None
