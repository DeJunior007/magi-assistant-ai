"""Ferramenta de visão do agente: ``screenshot(target, question)`` (3.7, R9.1-R9.4).

Só roda quando o modelo a chama num turno com fala do usuário (R9.3): nada aqui captura por conta
própria. ``window`` = janela ativa (``spectacle -a``, R9.1); ``screen`` = monitor principal inteiro
(R9.2): captura a área de trabalho (``spectacle -f``) e recorta o monitor de maior prioridade do
``kscreen-doctor -j`` (o do HUD fica de fora). ``-m`` não serve: pega o monitor do cursor.

A captura vai para um diretório temporário em ``$XDG_RUNTIME_DIR`` (tmpfs), é reduzida a no máximo
``MAX_SIDE`` px no lado maior, vira JPEG (``QImage``, sem dependência nova), segue para o provedor
``vision`` (``[tasks].vision``; KeyPool e orçamento ficam no registro) e é apagada logo após o envio,
inclusive em erro (R9.4). A ferramenta é ``final``: a resposta do ``vision`` (curta, pedida no
prompt) vira a fala do turno sem outra volta ao modelo do agente.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from magi.agent.tools.base import arg_str
from magi.common.contracts import (
    ActionResult,
    BudgetExceeded,
    Expression,
    ProviderError,
    ProviderRegistry,
    ToolSpec,
    TurnContext,
)

log = logging.getLogger(__name__)

MAX_SIDE = 1280
JPEG_QUALITY = 80
CAPTURE_TIMEOUT_S = 4.0

SAY_NO_REQUEST = "Só olho a tela quando você pede."
SAY_CAPTURE_FAILED = "Não consegui capturar a tela agora."
SAY_VISION_FAILED = "Não consegui ver a imagem agora, tenta de novo."

VISION_PROMPT = (
    "Esta é uma captura {what} do PC do usuário. Responda em português do Brasil, direto e "
    "informal, em no máximo duas frases curtas, sem markdown."
)
_WHAT = {"window": "da janela ativa", "screen": "do monitor principal"}

SCREENSHOT_SPEC = ToolSpec(
    name="screenshot",
    description=(
        "Captura a tela e pergunta ao modelo de visão. Use SÓ quando o usuário pedir neste turno "
        "algo sobre o que está na tela ('que bicho é esse?', 'o que tá escrito aqui?'). "
        "target='window' (padrão) = janela ativa; target='screen' só se ele disser 'a tela' "
        "(monitor principal inteiro). question = a pergunta dele sobre a imagem."
    ),
    parameters={
        "type": "object",
        "properties": {
            "target": {"type": "string", "enum": ["window", "screen"]},
            "question": {"type": "string", "description": "Pergunta do usuário sobre a imagem"},
        },
        "required": ["question"],
    },
)


@dataclass(frozen=True, slots=True)
class Rect:
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True, slots=True)
class Layout:
    """Monitor principal e a área de trabalho inteira, em coordenadas lógicas."""

    primary: Rect
    desktop: Rect


#: Executa um comando e devolve o código de saída.
Runner = Callable[[Sequence[str]], Awaitable[int]]
#: Devolve o layout dos monitores (``None`` = desconhecido: usa a área de trabalho inteira).
LayoutSource = Callable[[], Awaitable[Layout | None]]


async def run_command(cmd: Sequence[str]) -> int:
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )
    try:
        return await asyncio.wait_for(proc.wait(), CAPTURE_TIMEOUT_S)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return -1


def parse_kscreen(data: Mapping[str, Any]) -> Layout | None:
    """Layout a partir do ``kscreen-doctor -j``: principal = menor ``priority`` habilitado."""
    rects: list[tuple[int, Rect]] = []
    for o in data.get("outputs", []):
        if not o.get("enabled") or not o.get("size"):
            continue
        scale = float(o.get("scale") or 1) or 1.0
        r = Rect(int(o["pos"]["x"]), int(o["pos"]["y"]),
                 round(o["size"]["width"] / scale), round(o["size"]["height"] / scale))
        rects.append((int(o.get("priority") or 99), r))
    if not rects:
        return None
    primary = min(rects, key=lambda t: t[0])[1]
    x0 = min(r.x for _, r in rects)
    y0 = min(r.y for _, r in rects)
    x1 = max(r.x + r.w for _, r in rects)
    y1 = max(r.y + r.h for _, r in rects)
    return Layout(primary, Rect(x0, y0, x1 - x0, y1 - y0))


async def kscreen_layout() -> Layout | None:
    """Lê o layout dos monitores (só leitura)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "kscreen-doctor", "-j", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
        )
        out, _ = await asyncio.wait_for(proc.communicate(), 2.0)
        return parse_kscreen(json.loads(out))
    except (OSError, TimeoutError, ValueError, KeyError, TypeError):
        log.warning("visão: layout dos monitores indisponível; uso a área de trabalho inteira")
        return None


def prepare_image(path: str, layout: Layout | None = None) -> bytes:
    """Recorta o monitor principal (se ``layout``), reduz a ``MAX_SIDE`` e devolve JPEG."""
    from PySide6.QtCore import QBuffer, QIODevice, Qt
    from PySide6.QtGui import QImage

    img = QImage(path)
    if img.isNull():
        raise ValueError("captura ilegível")
    if layout is not None and layout.desktop.w > 0:
        k = img.width() / layout.desktop.w  # escala lógica -> pixels do print
        p, d = layout.primary, layout.desktop
        img = img.copy(round((p.x - d.x) * k), round((p.y - d.y) * k), round(p.w * k), round(p.h * k))
    if max(img.width(), img.height()) > MAX_SIDE:
        img = img.scaled(MAX_SIDE, MAX_SIDE, Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    if not img.save(buf, "JPG", JPEG_QUALITY):
        raise ValueError("falha ao gerar JPEG")
    return bytes(buf.data().data())


def capture_command(target: str, path: str) -> list[str]:
    flag = "-f" if target == "screen" else "-a"
    return ["spectacle", flag, "-b", "-n", "-o", path]


class ScreenshotTool:
    """``screenshot``: captura sob pedido, pergunta ao ``vision`` e apaga a captura (R9)."""

    spec = SCREENSHOT_SPEC
    danger = False
    #: A resposta do ``vision`` já é a fala final: o grafo não volta ao modelo (tempo ≤ 5 s).
    final = True

    def __init__(
        self,
        providers: ProviderRegistry,
        *,
        runner: Runner = run_command,
        layout: LayoutSource = kscreen_layout,
        tmp_root: str | None = None,
    ) -> None:
        self._providers = providers
        self._runner = runner
        self._layout = layout
        self._tmp_root = tmp_root

    @property
    def name(self) -> str:
        return self.spec.name

    async def run(self, args: Mapping[str, Any], ctx: TurnContext, text: str = "") -> ActionResult:
        if not text.strip():  # sem fala do usuário no turno, não há pedido (R9.3)
            return ActionResult(ok=False, speech=SAY_NO_REQUEST)
        target = "screen" if arg_str(args, "target").lower() == "screen" else "window"
        question = arg_str(args, "question") or text.strip()
        root = self._tmp_root or os.environ.get("XDG_RUNTIME_DIR") or None
        tmpdir = tempfile.mkdtemp(prefix="magi-shot-", dir=root)
        path = os.path.join(tmpdir, "shot.png")
        try:
            try:
                code = await self._runner(capture_command(target, path))
                if code != 0 or not os.path.exists(path) or os.path.getsize(path) == 0:
                    log.warning("visão: spectacle falhou (código %s)", code)
                    return ActionResult(ok=False, speech=SAY_CAPTURE_FAILED, expression=Expression.CONFUSED)
                layout = await self._layout() if target == "screen" else None
                image = await asyncio.to_thread(prepare_image, path, layout)
            except (OSError, ValueError):
                log.exception("visão: captura falhou")
                return ActionResult(ok=False, speech=SAY_CAPTURE_FAILED, expression=Expression.CONFUSED)
            prompt = f"{VISION_PROMPT.format(what=_WHAT[target])}\n\nPergunta: {question}"
            try:
                reply = await self._providers.vision().ask(prompt, image, mime="image/jpeg", personal=True)
            except BudgetExceeded:
                raise  # o grafo responde "bati o teto"
            except ProviderError as e:
                log.warning("visão: falha do provedor: %s", e)
                return ActionResult(ok=False, speech=SAY_VISION_FAILED, expression=Expression.CONFUSED)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)  # R9.4: apaga logo após o envio
        answer = reply.text.strip()
        if not answer:
            return ActionResult(ok=False, speech=SAY_VISION_FAILED, expression=Expression.CONFUSED)
        return ActionResult(ok=True, speech=answer, full_text=answer)


def vision_tools(providers: ProviderRegistry) -> list[ScreenshotTool]:
    return [ScreenshotTool(providers)]
