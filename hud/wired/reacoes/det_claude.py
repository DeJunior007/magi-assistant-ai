"""Detector `det_claude` (spec §5): 52, 53, 56, 75, 82, 90 · cond. C: 54, 55.
Dono: R1.5 (cond. C: R2.C).

- 52 (`claude` base, Claude passou a rodar) segue no ``fire`` antigo do ``Reactor``: não sai daqui.
- 53 `claude`/`terminou`: rodando → parado depois de ≥ 2 min rodando.
- 56 `claude`/`demorando`: rodando contínuo ≥ 15 min (1× por rodada).
- 90 `claude`/`pesado`: rodando ≥ 15 min com CPU ≥ 70% por ≥ 30 s (1× por rodada; no lugar do 56
  quando os dois valem no mesmo tick).
- 82 `claude`/`com_musica`: passou a valer Claude rodando **e** música tocando (1× por rodada).
- 75 `ideia`: HEAD do git mudou (``snap.git_head`` ou ``ctx["git_head"]``; o 1º visto só registra).

Estado próprio no ``ctx`` (chaves ``_claude_*``): ``_claude_desde`` (monotônico do início da
rodada ou None), ``_claude_feitos`` (set do que já saiu nesta rodada), ``_claude_cpu_desde``
(início da CPU ≥ 70%), ``_claude_head`` (último HEAD visto).
"""

from __future__ import annotations

from typing import Any

from .contratos import Disparo

TERMINOU_S = 120.0  # 53: rodou pelo menos isso
DEMORANDO_S = 15 * 60.0  # 56/90
CPU_PESADO = 70.0  # 90
CPU_PESADO_S = 30.0  # 90: CPU alta contínua


def _rodando(snap: Any) -> bool:
    return (getattr(getattr(snap, "claude", None), "running", 0) or 0) > 0


def _musica(snap: Any) -> bool:
    t = getattr(snap, "track", None)
    return t is not None and bool(getattr(t, "playing", False))


def _head(snap: Any, ctx: dict) -> str | None:
    h = getattr(snap, "git_head", None)
    return h if h is not None else ctx.get("git_head")


def detectar(anterior: Any, snap: Any, ctx: dict) -> list[Disparo]:
    """Compara o Snapshot ``anterior`` com ``snap`` e devolve os disparos deste tick."""
    agora = float(ctx.get("agora", 0.0))
    out: list[Disparo] = []

    head = _head(snap, ctx)
    if head is not None:
        visto = ctx.get("_claude_head")
        if visto is not None and head != visto:
            out.append(Disparo("ideia", f"HEAD {visto} → {head}", fmt={"head": head}))
        ctx["_claude_head"] = head

    desde = ctx.get("_claude_desde")
    if not _rodando(snap):
        if desde is not None and agora - desde >= TERMINOU_S:
            out.append(Disparo("claude", f"parou depois de {agora - desde:.0f} s", "terminou"))
        ctx["_claude_desde"] = None
        ctx["_claude_cpu_desde"] = None
        ctx["_claude_feitos"] = set()
        return out

    if desde is None:
        desde = ctx["_claude_desde"] = agora
        ctx["_claude_feitos"] = set()
    feitos: set = ctx.setdefault("_claude_feitos", set())
    cpu = getattr(snap, "cpu", None)
    if cpu is not None and cpu >= CPU_PESADO:
        if ctx.get("_claude_cpu_desde") is None:
            ctx["_claude_cpu_desde"] = agora
    else:
        ctx["_claude_cpu_desde"] = None
    cpu_desde = ctx.get("_claude_cpu_desde")
    longo = agora - desde >= DEMORANDO_S

    if longo and "pesado" not in feitos and cpu_desde is not None and agora - cpu_desde >= CPU_PESADO_S:
        feitos.update(("pesado", "demorando"))
        out.append(Disparo("claude", f"rodando há {(agora - desde) / 60:.0f} min com CPU alta", "pesado"))
    elif longo and "demorando" not in feitos:
        feitos.add("demorando")
        out.append(Disparo("claude", f"rodando há {(agora - desde) / 60:.0f} min", "demorando"))

    junto_antes = anterior is not None and _rodando(anterior) and _musica(anterior)
    if "com_musica" not in feitos and _musica(snap) and not junto_antes:
        feitos.add("com_musica")
        out.append(Disparo("claude", "Claude rodando com música", "com_musica"))
    return out
