"""3.7 Visão: ``screenshot`` só sob pedido, imagem reduzida em JPEG, captura apagada (R9)."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from magi.agent.graph import GraphAgent
from magi.agent.self_model import TOOL_GAPS
from magi.agent.tools.vision import (
    MAX_SIDE,
    Layout,
    Rect,
    ScreenshotTool,
    parse_kscreen,
    prepare_image,
)
from magi.common.contracts import BudgetExceeded, ChatReply, ProviderError, ProviderTask
from tests.agent.test_graph import CTX, FakeChat, FakeProviders, call

# Área de trabalho do PC: DP-1 (HUD) em cima, DP-2 (principal, ultrawide) embaixo.
KSCREEN = {
    "outputs": [
        {"name": "DP-2", "enabled": True, "pos": {"x": 0, "y": 1440},
         "size": {"width": 3440, "height": 1440}, "scale": 1, "priority": 1},
        {"name": "DP-1", "enabled": True, "pos": {"x": 456, "y": 0},
         "size": {"width": 2560, "height": 1440}, "scale": 1, "priority": 2},
        {"name": "HDMI-1", "enabled": False, "pos": {"x": 0, "y": 0}, "size": None},
    ]
}
LAYOUT = parse_kscreen(KSCREEN)


def _png(path: str, w: int, h: int, split_y: int | None = None) -> None:
    """PNG de teste; com ``split_y``, cima vermelho (HUD) e baixo verde (principal)."""
    from PySide6.QtGui import QColor, QImage, QPainter

    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(QColor(0, 200, 0))
    if split_y:
        p = QPainter(img)
        p.fillRect(0, 0, w, split_y, QColor(255, 0, 0))
        p.end()
    assert img.save(path, "PNG")


class FakeRunner:
    """Spectacle falso: grava um PNG no ``-o`` e registra o comando."""

    def __init__(self, w: int = 2000, h: int = 1000, code: int = 0, write: bool = True,
                 split_y: int | None = None) -> None:
        self.w, self.h, self.code, self.write, self.split_y = w, h, code, write, split_y
        self.cmds: list[list[str]] = []
        self.paths: list[str] = []

    async def __call__(self, cmd):
        self.cmds.append(list(cmd))
        path = cmd[cmd.index("-o") + 1]
        self.paths.append(path)
        if self.write:
            _png(path, self.w, self.h, self.split_y)
        return self.code


class FakeVision:
    name = "fake-vision"
    model = "fake-v1"
    free_tier = False

    def __init__(self, reply: str = "É um Slime azul.", error: Exception | None = None,
                 runner: FakeRunner | None = None) -> None:
        self.reply, self.error, self.runner = reply, error, runner
        self.calls: list[dict] = []

    async def ask(self, question, image, *, mime="image/png", personal):
        from PySide6.QtGui import QImage

        img = QImage.fromData(image)
        # No momento do envio a captura ainda existe só até o fim da chamada.
        self.calls.append({"question": question, "image": image, "mime": mime, "personal": personal,
                           "size": (img.width(), img.height()), "pixel": img.pixelColor(10, 10).name()})
        if self.error:
            raise self.error
        return ChatReply(text=self.reply)


class VisionProviders(FakeProviders):
    def __init__(self, vision: FakeVision, chat: FakeChat | None = None) -> None:
        super().__init__(chat or FakeChat([]))
        self._vision = vision

    def vision(self) -> FakeVision:
        self.tasks.append(ProviderTask.VISION)
        return self._vision


def make_tool(tmp_path: Path, runner: FakeRunner, vision: FakeVision, layout=LAYOUT):
    async def get_layout():
        return layout

    providers = VisionProviders(vision)
    tool = ScreenshotTool(providers, runner=runner, layout=get_layout, tmp_root=str(tmp_path))
    return tool, providers


def _leftovers(tmp_path: Path) -> list[str]:
    return [str(p) for p in tmp_path.rglob("*")]


async def test_janela_ativa_reduzida_jpeg_e_apagada(tmp_path):
    runner = FakeRunner(2000, 1000)
    vision = FakeVision()
    tool, _ = make_tool(tmp_path, runner, vision)
    res = await tool.run({"target": "window", "question": "que bicho é esse?"}, CTX, "que bicho é esse?")
    assert res.ok and res.speech == "É um Slime azul." and res.full_text == res.speech
    assert runner.cmds == [["spectacle", "-a", "-b", "-n", "-o", runner.paths[0]]]
    [c] = vision.calls
    assert c["mime"] == "image/jpeg" and c["personal"] is True
    assert c["image"][:3] == b"\xff\xd8\xff"  # JPEG anexado
    assert c["size"] == (MAX_SIDE, 640)  # lado maior <= 1280, proporção mantida
    assert "que bicho é esse?" in c["question"] and "janela ativa" in c["question"]
    assert not os.path.exists(runner.paths[0]) and _leftovers(tmp_path) == []


async def test_imagem_pequena_nao_e_ampliada(tmp_path):
    runner = FakeRunner(800, 600)
    vision = FakeVision()
    tool, _ = make_tool(tmp_path, runner, vision)
    await tool.run({"question": "o que é isso?"}, CTX, "o que é isso?")
    assert vision.calls[0]["size"] == (800, 600)
    assert runner.cmds[0][1] == "-a"  # padrão = janela ativa


async def test_a_tela_recorta_o_monitor_principal(tmp_path):
    # Print da área de trabalho 3440x2880: HUD (vermelho) nas 1440 linhas de cima.
    runner = FakeRunner(3440, 2880, split_y=1440)
    vision = FakeVision()
    tool, _ = make_tool(tmp_path, runner, vision)
    res = await tool.run({"target": "screen", "question": "o que tem na tela?"}, CTX, "olha a tela")
    assert res.ok
    assert runner.cmds[0][1] == "-f"
    c = vision.calls[0]
    w, h = c["size"]
    assert w == MAX_SIDE and abs(h - 1440 * MAX_SIDE / 3440) <= 1  # só o DP-2
    assert c["pixel"] == "#00c800"  # verde: nada do monitor do HUD
    assert "monitor principal" in c["question"]
    assert _leftovers(tmp_path) == []


def test_parse_kscreen_principal_por_prioridade():
    assert LAYOUT == Layout(primary=Rect(0, 1440, 3440, 1440), desktop=Rect(0, 0, 3440, 2880))
    assert parse_kscreen({"outputs": []}) is None


def test_prepare_image_sem_layout_usa_tudo(tmp_path):
    p = str(tmp_path / "a.png")
    _png(p, 3000, 1500)
    from PySide6.QtGui import QImage

    img = QImage.fromData(prepare_image(p, None))
    assert (img.width(), img.height()) == (MAX_SIDE, 640)


async def test_apaga_em_erro_do_provedor(tmp_path):
    runner = FakeRunner()
    vision = FakeVision(error=ProviderError("timeout"))
    tool, _ = make_tool(tmp_path, runner, vision)
    res = await tool.run({"question": "o que é?"}, CTX, "o que é?")
    assert not res.ok and len(vision.calls) == 1
    assert _leftovers(tmp_path) == []


async def test_apaga_quando_estoura_orcamento(tmp_path):
    runner = FakeRunner()
    vision = FakeVision(error=BudgetExceeded("vision"))
    tool, _ = make_tool(tmp_path, runner, vision)
    with pytest.raises(BudgetExceeded):  # o grafo transforma em "bati o teto"
        await tool.run({"question": "o que é?"}, CTX, "o que é?")
    assert _leftovers(tmp_path) == []


@pytest.mark.parametrize("runner", [FakeRunner(code=1), FakeRunner(write=False)])
async def test_falha_de_captura_nao_envia_e_limpa(tmp_path, runner):
    vision = FakeVision()
    tool, _ = make_tool(tmp_path, runner, vision)
    res = await tool.run({"question": "o que é?"}, CTX, "o que é?")
    assert not res.ok and vision.calls == []
    assert _leftovers(tmp_path) == []


async def test_sem_fala_no_turno_nao_captura(tmp_path):
    runner = FakeRunner()
    vision = FakeVision()
    tool, _ = make_tool(tmp_path, runner, vision)
    res = await tool.run({"question": "o que é?"}, CTX, "")
    assert not res.ok and runner.cmds == [] and vision.calls == []


async def test_agente_nunca_captura_sem_chamada_da_ferramenta(tmp_path):
    runner = FakeRunner()
    vision = FakeVision()
    chat = FakeChat([ChatReply(text="Oi! Tudo certo por aqui.")])
    providers = VisionProviders(vision, chat)
    tool = ScreenshotTool(providers, runner=runner, tmp_root=str(tmp_path))
    agent = GraphAgent(providers, [tool], persona="Você é a Magi.")
    res = await agent.answer("oi magui", CTX)
    assert res.ok and runner.cmds == [] and vision.calls == []
    assert ProviderTask.VISION not in providers.tasks
    assert "screenshot" in [s.name for s in chat.calls[0][1]]  # oferecida, mas não chamada


async def test_agente_chama_screenshot_e_responde_curto(tmp_path):
    runner = FakeRunner()
    vision = FakeVision(reply="É um Slime azul, inofensivo. Dá pra ignorar.")
    chat = FakeChat([
        ChatReply(text="Deixa eu ver.", tool_calls=(call("screenshot", question="que bicho é esse?"),)),
    ])
    providers = VisionProviders(vision, chat)
    tool = ScreenshotTool(providers, runner=runner, tmp_root=str(tmp_path))
    agent = GraphAgent(providers, [tool], persona="Você é a Magi.")
    t0 = time.monotonic()
    res = await agent.answer("que bicho é esse?", CTX)
    assert time.monotonic() - t0 < 5
    # Ferramenta final: a resposta do vision é a fala, sem segunda volta ao modelo.
    assert res.ok and res.speech == "É um Slime azul, inofensivo. Dá pra ignorar."
    assert len(chat.calls) == 1
    assert len(runner.cmds) == 1 and len(vision.calls) == 1
    assert _leftovers(tmp_path) == []


async def test_agente_volta_ao_modelo_se_a_visao_falhar(tmp_path):
    runner = FakeRunner(code=1)
    vision = FakeVision()
    chat = FakeChat([
        ChatReply(text="", tool_calls=(call("screenshot", question="que bicho é esse?"),)),
        ChatReply(text="Não consegui ver a tela agora, foi mal."),
    ])
    providers = VisionProviders(vision, chat)
    tool = ScreenshotTool(providers, runner=runner, tmp_root=str(tmp_path))
    agent = GraphAgent(providers, [tool], persona="Você é a Magi.")
    res = await agent.answer("que bicho é esse?", CTX)
    assert len(chat.calls) == 2 and vision.calls == []
    assert chat.calls[1][0][-1].role == "tool"
    assert res.speech == "Não consegui ver a tela agora, foi mal."


def test_ficha_nao_lista_ver_a_tela_com_a_ferramenta():
    assert TOOL_GAPS["screenshot"] == "ver a tela"
    from magi.core.actions import Registry
    from magi.core.assemble import default_agent

    agent = default_agent(VisionProviders(FakeVision()), Registry([]))
    assert "screenshot" in [s.name for s in agent.tool_specs]


@pytest.mark.live
@pytest.mark.skipif(not os.environ.get("MAGI_LIVE"), reason="MAGI_LIVE=1 e chaves no keyring")
async def test_live_janela_ativa(tmp_path):
    """UMA captura real (só leitura) da janela ativa, enviada ao ``vision`` da config."""
    from magi.common.config import load_config
    from magi.providers.registry import Registry
    from tests.providers.conftest import FakeBudget

    budget = FakeBudget()
    tool = ScreenshotTool(Registry(load_config(), budget), tmp_root=str(tmp_path))
    t0 = time.monotonic()
    q = "o que tem nessa janela?"
    res = await tool.run({"target": "window", "question": q}, CTX, q)
    elapsed = time.monotonic() - t0
    print(f"\nvisão: {elapsed:.2f}s -> {res.speech!r}")
    assert res.ok and res.speech
    assert _leftovers(tmp_path) == []
    assert elapsed <= 5
