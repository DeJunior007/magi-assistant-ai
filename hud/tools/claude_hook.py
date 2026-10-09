#!/usr/bin/env python3
"""Hook do Claude Code para as reações 54/55 da Condessa (spec §6 C). Só biblioteca padrão.

    python3 hud/tools/claude_hook.py fail|notify|stop   (JSON do hook no stdin)

Grava 1 linha em ``~/.cache/magi/claude-events.jsonl``:
``{"t": epoch, "ev": "fail"|"notify"|"stop", "proj": "<pasta do cwd>"}``; o arquivo gira em 1 MB
(o antigo vira ``claude-events.jsonl.1``). O ``ClaudeStats`` do HUD lê só as linhas novas.

``fail`` vindo de ``PostToolUse`` só grava quando a resposta da ferramenta indica erro (o
``PostToolUse`` também chega nos sucessos); vindo de ``PostToolUseFailure`` grava sempre.

Defensivo: aceita JSON ausente/quebrado/campos faltando, nunca imprime no stdout e sempre sai com
código 0 — não pode atrapalhar o Claude Code. Instalação (D2): ``docs/design/CONDESSA-REACOES.md``.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

EVENTS_FILE = Path("~/.cache/magi/claude-events.jsonl").expanduser()
MAX_BYTES = 1024 * 1024  # gira em 1 MB
EVENTOS = ("fail", "notify", "stop")
# nome do hook (``hook_event_name``) → evento, para quando o argumento faltar
_POR_HOOK = {"PostToolUse": "fail", "PostToolUseFailure": "fail", "Notification": "notify", "Stop": "stop"}


def _falhou(resp) -> bool:
    """A resposta da ferramenta (``tool_response``) indica erro? Na dúvida, não."""
    if isinstance(resp, dict):
        if resp.get("is_error") is True or resp.get("interrupted") is True:
            return True
        if resp.get("error"):
            return True
        for k in ("exit_code", "exitCode", "returncode", "code"):
            v = resp.get(k)
            if isinstance(v, int) and not isinstance(v, bool) and v != 0:
                return True
        return False
    if isinstance(resp, str):
        return resp.lstrip().lower().startswith("error")
    return False


def evento(arg: str | None, dados: dict) -> str | None:
    """Decide o evento a gravar (ou None = nada a gravar)."""
    hook = dados.get("hook_event_name")
    hook = hook if isinstance(hook, str) else ""
    ev = arg if arg in EVENTOS else _POR_HOOK.get(hook)
    if ev is None:
        return None
    if ev == "fail" and hook == "PostToolUse" and not _falhou(dados.get("tool_response")):
        return None
    return ev


def _proj(dados: dict) -> str:
    cwd = dados.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        cwd = os.getcwd()
    return Path(cwd).name or cwd


def gravar(linha: dict, caminho: Path = EVENTS_FILE, max_bytes: int = MAX_BYTES) -> None:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    try:
        if caminho.stat().st_size >= max_bytes:
            caminho.replace(caminho.with_name(caminho.name + ".1"))
    except FileNotFoundError:
        pass
    with caminho.open("a", encoding="utf-8") as f:
        f.write(json.dumps(linha, ensure_ascii=False) + "\n")


def main(argv=None, stdin=None, caminho: Path | None = None, agora: float | None = None) -> int:
    try:
        argv = sys.argv[1:] if argv is None else argv
        stdin = sys.stdin if stdin is None else stdin
        try:
            dados = json.loads(stdin.read() or "{}")
        except (ValueError, OSError, AttributeError):
            dados = {}
        if not isinstance(dados, dict):
            dados = {}
        ev = evento(argv[0] if argv else None, dados)
        if ev is not None:
            t = time.time() if agora is None else agora
            gravar({"t": round(t, 3), "ev": ev, "proj": _proj(dados)}, caminho or EVENTS_FILE)
    except Exception:  # noqa: BLE001 - hook nunca quebra o Claude Code
        pass
    return 0


if __name__ == "__main__":
    main()
    sys.exit(0)
