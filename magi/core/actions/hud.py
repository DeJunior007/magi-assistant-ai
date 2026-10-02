"""Ações do HUD (R6.1): abrir/fechar, tela de ociosidade, RGB Sync e detalhes.

Usa os mecanismos que o HUD já tem:

- abrir/fechar: ``~/.local/bin/gamerhud`` alterna; o estado vem do processo
  ``python3 .../gamerhud.py`` (mesmo padrão do script);
- tela de ociosidade e RGB Sync: chaves ``view`` e ``rgb_sync`` de
  ``~/.config/gamerhud/settings.json`` (o HUD aberto percebe em ~0,3 s);
- detalhes de CPU/GPU/memória: ``DetailMsg`` pelo ``HudSink`` (``none`` fecha).

Caminhos e ``runner`` são injetáveis para os testes não tocarem o HUD real.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from magi.common.contracts import (
    ActionHandler,
    ActionRequest,
    ActionResult,
    DetailMsg,
    DetailTarget,
    Expression,
    HudSink,
    IntentId,
    SlotName,
)

log = logging.getLogger(__name__)

#: Executa um comando e devolve o código de saída.
Runner = Callable[[Sequence[str]], int]

DEFAULT_GAMERHUD_CMD = Path("~/.local/bin/gamerhud").expanduser()
DEFAULT_SETTINGS = Path("~/.config/gamerhud/settings.json").expanduser()
#: Mesmo padrão de ``hud/system/bin/gamerhud``.
HUD_PROCESS_PATTERN = r"^python3 .*/gamerhud\.py$"

VIEW_FULL = "full"
VIEW_IDLE = "idle"

SAY_OPENED = "Abrindo o HUD."
SAY_ALREADY_OPEN = "O HUD já está aberto."
SAY_CLOSED = "HUD fechado."
SAY_ALREADY_CLOSED = "O HUD já está fechado."
SAY_HUD_FAILED = "Não consegui mexer no HUD."
SAY_IDLE = "Tela de ociosidade."
SAY_FULL = "Painel completo."
SAY_RGB_ON = "RGB Sync ligado."
SAY_RGB_OFF = "RGB Sync desligado."
SAY_SETTINGS_FAILED = "Não consegui salvar a configuração do HUD."
SAY_HUD_NOT_OPEN = "O HUD está fechado."
SAY_DETAIL_WHICH = "Detalhe de quê? CPU, GPU ou memória."
SAY_DETAIL = {
    DetailTarget.CPU: "Detalhes da CPU.",
    DetailTarget.GPU: "Detalhes da GPU.",
    DetailTarget.MEMORY: "Detalhes da memória.",
    DetailTarget.NONE: "Fechei os detalhes.",
}

_ON = {"on", "true", "1", "liga", "ligar", "ligado"}
_OFF = {"off", "false", "0", "desliga", "desligar", "desligado"}


def default_runner(argv: Sequence[str]) -> int:
    """Roda ``argv`` sem saída; sessão própria para o HUD não morrer junto com o núcleo."""
    try:
        return subprocess.run(
            list(argv),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            timeout=15,
            check=False,
        ).returncode
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("falha ao rodar %s: %s", argv[0] if argv else "?", e)
        return 127


def load_settings(path: Path) -> dict[str, Any]:
    """Lê o settings.json do HUD; ausente ou inválido = ``{}``."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_settings(path: Path, data: Mapping[str, Any]) -> None:
    """Grava atômico (temporário no mesmo diretório + ``os.replace``)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".settings-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(dict(data), f)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _on_off(value: str | None) -> bool | None:
    v = (value or "").strip().lower()
    if v in _ON:
        return True
    if v in _OFF:
        return False
    return None


class HudActions:
    """Handler único para os intents ``hud.*`` (R6.1)."""

    intents = frozenset(
        {
            IntentId.HUD_OPEN,
            IntentId.HUD_CLOSE,
            IntentId.HUD_IDLE_TOGGLE,
            IntentId.HUD_DETAIL,
            IntentId.HUD_RGB_SYNC,
        }
    )

    def __init__(
        self,
        hud_sink: HudSink,
        *,
        settings_path: Path | str = DEFAULT_SETTINGS,
        gamerhud_cmd: Path | str = DEFAULT_GAMERHUD_CMD,
        runner: Runner = default_runner,
    ) -> None:
        self._sink = hud_sink
        self._settings = Path(settings_path)
        self._cmd = str(gamerhud_cmd)
        self._run = runner
        self._lock = asyncio.Lock()

    async def run(self, req: ActionRequest) -> ActionResult:
        iid = req.intent.id
        if iid == IntentId.HUD_OPEN:
            return await self._open_close(want_open=True)
        if iid == IntentId.HUD_CLOSE:
            return await self._open_close(want_open=False)
        if iid == IntentId.HUD_IDLE_TOGGLE:
            return await self._view(req)
        if iid == IntentId.HUD_RGB_SYNC:
            return await self._rgb_sync(req)
        if iid == IntentId.HUD_DETAIL:
            return await self._detail(req)
        return ActionResult(ok=False, speech="Isso eu ainda não sei fazer.")

    # -- processo -----------------------------------------------------------------------------

    async def is_open(self) -> bool:
        """HUD aberto = existe ``python3 .../gamerhud.py`` (via ``pgrep -f``)."""
        code = await asyncio.to_thread(self._run, ["pgrep", "-f", HUD_PROCESS_PATTERN])
        return code == 0

    async def _open_close(self, *, want_open: bool) -> ActionResult:
        async with self._lock:
            if await self.is_open() == want_open:
                return ActionResult(ok=True, speech=SAY_ALREADY_OPEN if want_open else SAY_ALREADY_CLOSED)
            code = await asyncio.to_thread(self._run, [self._cmd])
        if code != 0:
            log.warning("gamerhud saiu com %s", code)
            return ActionResult(ok=False, speech=SAY_HUD_FAILED, expression=Expression.CONFUSED)
        return ActionResult(ok=True, speech=SAY_OPENED if want_open else SAY_CLOSED)

    # -- settings.json ------------------------------------------------------------------------

    async def _update_settings(self, change: Callable[[dict[str, Any]], Any]) -> Any:
        def work() -> Any:
            cfg = load_settings(self._settings)
            out = change(cfg)
            save_settings(self._settings, cfg)
            return out

        async with self._lock:
            return await asyncio.to_thread(work)

    async def _view(self, req: ActionRequest) -> ActionResult:
        wanted = req.args.get("view")
        if wanted not in (VIEW_FULL, VIEW_IDLE):
            slot = req.intent.slot(SlotName.ON_OFF)
            flag = _on_off(slot.value) if slot else None
            wanted = None if flag is None else (VIEW_IDLE if flag else VIEW_FULL)

        def change(cfg: dict[str, Any]) -> str:
            cur = cfg.get("view", VIEW_FULL)
            new = wanted or (VIEW_FULL if cur == VIEW_IDLE else VIEW_IDLE)
            cfg["view"] = new
            return new

        try:
            new = await self._update_settings(change)
        except OSError as e:
            log.warning("falha ao gravar %s: %s", self._settings, e)
            return ActionResult(ok=False, speech=SAY_SETTINGS_FAILED)
        return ActionResult(ok=True, speech=SAY_IDLE if new == VIEW_IDLE else SAY_FULL)

    async def _rgb_sync(self, req: ActionRequest) -> ActionResult:
        slot = req.intent.slot(SlotName.ON_OFF)
        wanted = _on_off(slot.value) if slot else None

        def change(cfg: dict[str, Any]) -> bool:
            new = (not cfg.get("rgb_sync", True)) if wanted is None else wanted
            cfg["rgb_sync"] = new
            return new

        try:
            new = await self._update_settings(change)
        except OSError as e:
            log.warning("falha ao gravar %s: %s", self._settings, e)
            return ActionResult(ok=False, speech=SAY_SETTINGS_FAILED)
        return ActionResult(ok=True, speech=SAY_RGB_ON if new else SAY_RGB_OFF)

    # -- detalhes -----------------------------------------------------------------------------

    async def _detail(self, req: ActionRequest) -> ActionResult:
        slot = req.intent.slot(SlotName.DETAIL)
        try:
            target = DetailTarget((slot.value if slot else "").strip().lower())
        except ValueError:
            return ActionResult(ok=False, speech=SAY_DETAIL_WHICH, expression=Expression.CONFUSED)
        if not await self.is_open():
            return ActionResult(ok=False, speech=SAY_HUD_NOT_OPEN)
        await self._sink.send(DetailMsg(v=target))
        return ActionResult(ok=True, speech=SAY_DETAIL[target])


def handlers(
    hud_sink: HudSink,
    *,
    settings_path: Path | str = DEFAULT_SETTINGS,
    gamerhud_cmd: Path | str = DEFAULT_GAMERHUD_CMD,
    runner: Runner = default_runner,
) -> list[ActionHandler]:
    """Handlers das ações do HUD para o ``Registry``."""
    return [HudActions(hud_sink, settings_path=settings_path, gamerhud_cmd=gamerhud_cmd, runner=runner)]
