"""Ações de jogos: abrir pela Steam e fechar com confirmação (R5.1–R5.5, tarefa 1.9).

Abrir: ``steam-mangohud.sh steam://rungameid/<appid>`` (o wrapper sobe a Steam com MangoHud se
ela estiver fechada; aberta, o link vai para a instância existente), em processo desacoplado.

Fechar (perigosa): acha o ``reaper SteamLaunch AppId=N`` (como ``steam_game`` do gamerhud-watch)
e a árvore de filhos; no Proton, também o ``wine64-preloader`` com ``SteamAppId=N`` no environ.
Manda SIGTERM à árvore; se algo seguir vivo após ``grace_s``, pede nova confirmação para SIGKILL
(``args={"force": True}``). Processos, lançamento e sinais ficam atrás de interfaces injetáveis.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import signal
import subprocess
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from magi.common.contracts import (
    ActionHandler,
    ActionRequest,
    ActionResult,
    Expression,
    Game,
    GameCatalog,
    IntentId,
    Slot,
    SlotName,
)

log = logging.getLogger(__name__)

IGNORE_APPIDS = frozenset({228980})  # Steamworks Common Redistributables
OPEN_MIN_SCORE = 85.0  # nota mínima para abrir direto quando o slot não veio resolvido
DEFAULT_WRAPPER = Path.home() / ".local/share/gamerhud/steam-mangohud.sh"
_APPID_ARG = re.compile(r"AppId=(\d+)")


# ---------------------------------------------------------------------------------------------
# Interfaces injetáveis
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProcInfo:
    pid: int
    ppid: int
    args: tuple[str, ...]
    exe: str = ""  # alvo de /proc/<pid>/exe (no Proton, wine64-preloader; o argv vira o .exe)


class ProcessTable(Protocol):
    def list(self) -> list[ProcInfo]: ...

    def environ(self, pid: int) -> Mapping[str, str]: ...

    def alive(self, pid: int) -> bool: ...


Launcher = Callable[[Sequence[str]], None]
Killer = Callable[[int, int], None]
Sleeper = Callable[[float], Awaitable[None]]


class ProcFs:
    """``ProcessTable`` real, lendo ``/proc`` (só leitura)."""

    def __init__(self, root: Path | str = "/proc") -> None:
        self.root = Path(root)

    def list(self) -> list[ProcInfo]:
        out: list[ProcInfo] = []
        for d in self.root.iterdir():
            if not d.name.isdigit():
                continue
            try:
                raw = (d / "cmdline").read_bytes()
                stat = (d / "stat").read_text()
            except OSError:
                continue
            ppid = int(stat.rsplit(")", 1)[1].split()[1])
            args = tuple(a.decode(errors="replace") for a in raw.split(b"\0") if a)
            try:
                exe = os.readlink(d / "exe")
            except OSError:
                exe = ""
            out.append(ProcInfo(int(d.name), ppid, args, exe))
        return out

    def environ(self, pid: int) -> Mapping[str, str]:
        try:
            raw = (self.root / str(pid) / "environ").read_bytes()
        except OSError:
            return {}
        env: dict[str, str] = {}
        for item in raw.split(b"\0"):
            k, sep, v = item.partition(b"=")
            if sep:
                env[k.decode(errors="replace")] = v.decode(errors="replace")
        return env

    def alive(self, pid: int) -> bool:
        try:
            stat = (self.root / str(pid) / "stat").read_text()
        except OSError:
            return False
        return stat.rsplit(")", 1)[1].split()[0] != "Z"  # zumbi já morreu


def spawn_detached(argv: Sequence[str]) -> None:
    """Lança sem herdar terminal nem sessão; o núcleo não espera o processo."""
    subprocess.Popen(  # noqa: S603
        list(argv),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )


def os_kill(pid: int, sig: int) -> None:
    os.kill(pid, sig)


# ---------------------------------------------------------------------------------------------
# Detecção do jogo em execução
# ---------------------------------------------------------------------------------------------


def running_appids(procs: Iterable[ProcInfo]) -> dict[int, int]:
    """appid → pid do ``reaper SteamLaunch AppId=N`` (argumentos separados, não texto solto)."""
    found: dict[int, int] = {}
    for p in procs:
        if "SteamLaunch" not in p.args:
            continue
        for a in p.args:
            m = _APPID_ARG.fullmatch(a)
            if m and int(m.group(1)) not in IGNORE_APPIDS:
                found.setdefault(int(m.group(1)), p.pid)
                break
    return found


def _descendants(roots: Iterable[int], procs: Sequence[ProcInfo]) -> list[int]:
    kids: dict[int, list[int]] = {}
    for p in procs:
        kids.setdefault(p.ppid, []).append(p.pid)
    seen: list[int] = []
    stack = list(roots)
    while stack:
        pid = stack.pop()
        if pid in seen:
            continue
        seen.append(pid)
        stack.extend(kids.get(pid, ()))
    return seen


def _is_wine(p: ProcInfo) -> bool:
    names = (os.path.basename(p.exe), os.path.basename(p.args[0]) if p.args else "")
    return any(n.startswith(("wine64-preloader", "wine-preloader")) for n in names)


def game_tree(appid: int, table: ProcessTable) -> list[int]:
    """Pids do jogo: reaper + filhos e, no Proton, ``wine64-preloader`` com ``SteamAppId``."""
    procs = table.list()
    roots = [pid for a, pid in running_appids(procs).items() if a == appid]
    for p in procs:
        if _is_wine(p) and table.environ(p.pid).get("SteamAppId") == str(appid):
            roots.append(p.pid)
    own = os.getpid()
    return [pid for pid in _descendants(roots, procs) if pid != own]


# ---------------------------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------------------------


def _slot_appid(slot: Slot | None) -> int | None:
    if slot is not None and slot.value.strip().isdigit():
        return int(slot.value)
    return None


class OpenGame:
    """``game.open``: abre pela Steam; sem match, diz que não achou e cita até 3 parecidos."""

    intents = frozenset({IntentId.GAME_OPEN.value})

    def __init__(self, catalog: GameCatalog, launcher: Launcher, wrapper: Path) -> None:
        self.catalog = catalog
        self.launcher = launcher
        self.wrapper = wrapper

    def _resolve(self, req: ActionRequest) -> tuple[Game | None, str, list[Game]]:
        slot = req.intent.slot(SlotName.GAME)
        appid = _slot_appid(slot)
        if appid is not None and (game := self.catalog.get(appid)) is not None:
            return game, "", []
        query = ""
        if slot is not None:
            query = slot.raw or slot.display or slot.value
        query = (query or req.text).strip()
        cands = self.catalog.find(query, limit=3) if query else []
        if cands and cands[0][1] >= OPEN_MIN_SCORE:
            return cands[0][0], query, []
        return None, query, [g for g, _ in cands]

    async def run(self, req: ActionRequest) -> ActionResult:
        game, query, similar = self._resolve(req)
        if game is None:
            what = f"{query}" if query else "esse jogo"
            speech = f"Não achei {what}."
            if similar:
                speech += " Parecidos: " + ", ".join(g.name for g in similar) + "."
            return ActionResult(ok=False, speech=speech, expression=Expression.CONFUSED)
        url = f"steam://rungameid/{game.appid}"
        argv = [str(self.wrapper), url] if self.wrapper.exists() else ["steam", url]
        try:
            self.launcher(argv)
        except OSError:
            log.exception("falha ao abrir %s", game.name)
            return ActionResult(ok=False, speech=f"Não consegui abrir {game.name}.")
        reply = req.intent.reply
        speech = reply.format(game=game.name) if reply and "{game}" in reply else f"Abrindo {game.name}"
        return ActionResult(ok=True, speech=speech)


class CloseGame:
    """``game.close`` (perigosa): SIGTERM com confirmação; SIGKILL só com nova confirmação."""

    intents = frozenset({IntentId.GAME_CLOSE.value})

    def __init__(
        self,
        catalog: GameCatalog,
        table: ProcessTable,
        killer: Killer,
        sleep: Sleeper,
        grace_s: float,
        poll_s: float,
    ) -> None:
        self.catalog = catalog
        self.table = table
        self.killer = killer
        self.sleep = sleep
        self.grace_s = grace_s
        self.poll_s = poll_s

    def _name(self, appid: int) -> str:
        game = self.catalog.get(appid)
        return game.name if game is not None else "o jogo"

    def _target(self, req: ActionRequest) -> int | None:
        wanted = _slot_appid(req.intent.slot(SlotName.GAME))
        if wanted is not None:  # o reaper pode ter saído antes do wine (Proton)
            return wanted if game_tree(wanted, self.table) else None
        return next(iter(running_appids(self.table.list())), None)

    def _ask(self, req: ActionRequest, appid: int, speech: str, force: bool) -> ActionResult:
        name = self._name(appid)
        slot = Slot(SlotName.GAME.value, str(appid), display=name)
        others = tuple(s for s in req.intent.slots if s.name != SlotName.GAME)
        intent = replace(req.intent, slots=(slot, *others), danger=True)
        args = {**req.args, "force": True} if force else dict(req.args)
        on_confirm = replace(req, intent=intent, confirmed=True, args=args)
        return ActionResult(
            ok=True,
            speech=speech,
            needs_confirmation=True,
            dangerous=True,
            on_confirm=on_confirm,
            expression=Expression.ALERT,
        )

    def _signal(self, pids: Iterable[int], sig: int) -> None:
        for pid in pids:
            try:
                self.killer(pid, sig)
            except ProcessLookupError:
                pass
            except OSError:
                log.warning("sinal %s ao pid %d falhou", sig, pid, exc_info=True)

    async def _wait_dead(self, pids: Sequence[int]) -> list[int]:
        left = [p for p in pids if self.table.alive(p)]
        waited = 0.0
        while left and waited < self.grace_s:
            await self.sleep(self.poll_s)
            waited += self.poll_s
            left = [p for p in left if self.table.alive(p)]
        return left

    async def run(self, req: ActionRequest) -> ActionResult:
        appid = self._target(req)
        if appid is None:
            wanted = _slot_appid(req.intent.slot(SlotName.GAME))
            speech = f"{self._name(wanted)} não está aberto." if wanted else "Não tem jogo aberto."
            return ActionResult(ok=False, speech=speech)
        name = self._name(appid)
        force = bool(req.args.get("force"))
        if not req.confirmed:
            verb = "Forçar o fechamento de" if force else "Fechar"
            return self._ask(req, appid, f"{verb} {name}? Diz confirma.", force)
        pids = game_tree(appid, self.table)
        if not pids:
            return ActionResult(ok=False, speech=f"{name} não está aberto.")
        if force:
            self._signal(pids, signal.SIGKILL)
            return ActionResult(ok=True, speech=f"{name} foi forçado a fechar.")
        self._signal(pids, signal.SIGTERM)
        if await self._wait_dead(pids):
            return self._ask(req, appid, f"{name} não fechou. Forço? Diz confirma.", force=True)
        return ActionResult(ok=True, speech=f"{name} fechado.")


def handlers(
    catalog: GameCatalog,
    *,
    launcher: Launcher = spawn_detached,
    wrapper: Path | str = DEFAULT_WRAPPER,
    table: ProcessTable | None = None,
    killer: Killer = os_kill,
    sleep: Sleeper = asyncio.sleep,
    grace_s: float = 5.0,
    poll_s: float = 0.5,
) -> list[ActionHandler]:
    """Handlers de ``game.open`` e ``game.close``."""
    return [
        OpenGame(catalog, launcher, Path(wrapper)),
        CloseGame(catalog, table or ProcFs(), killer, sleep, grace_s, poll_s),
    ]
