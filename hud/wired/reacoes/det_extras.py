"""Detector `det_extras` (spec §5): cond. fan: 43 · restart: 50 · capturas: 51 · datas: 63 · P13: I20.
Dono: R2.G.

- **43** (``ventoinha``): ``snap.fan = (rpm, média 5 min)`` (``data.Ventoinha``); dispara quando
  ``rpm ≥ média × (1 + ACIMA)`` e ``rpm ≥ RPM_MIN``, 1× por episódio (rearma abaixo de
  ``média × (1 + REARME)``).
- **50** (``pede_reinicio``): ``snap.reinicio`` (``data.Reinicio``, ``dnf needs-restarting -r``)
  passou a True (1× por episódio; False/None rearma).
- **51** (``posando_print``): ``snap.captura`` (mtime da captura mais nova, ``data.Capturas``)
  ficou maior que o último visto; a 1ª leitura só marca. Com ``ctx["relogio"]``, captura com mais
  de ``CAPTURA_MAX_S`` s de idade não reage.
- **63** (``data_especial``): ``[datas]`` do gosto (``ctx["taste"].section("datas")``,
  ``"MM-DD" = "nome"``) contém o dia de ``ctx["relogio"]``; 1× por dia.
- **I20** fica para R3.1 (arte P13): não sai daqui.

Chaves próprias no ``ctx``: ``_extras_fan_alto`` (bool), ``_extras_reinicio`` (bool),
``_extras_captura`` (float ou None), ``_extras_data`` (``"AAAA-MM-DD"`` do último 63).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .contratos import Disparo

ACIMA = 0.30  # 30% acima da média de 5 min
REARME = 0.15
RPM_MIN = 300.0  # ventoinha parada → girando devagar não é "alta"
CAPTURA_MAX_S = 120.0


def _fan(snap: Any, ctx: dict) -> list[Disparo]:
    fan = getattr(snap, "fan", None)
    if not fan:
        ctx["_extras_fan_alto"] = False
        return []
    rpm, media = float(fan[0]), float(fan[1])
    if ctx.get("_extras_fan_alto"):
        if rpm < media * (1 + REARME):
            ctx["_extras_fan_alto"] = False
        return []
    if media > 0 and rpm >= RPM_MIN and rpm >= media * (1 + ACIMA):
        ctx["_extras_fan_alto"] = True
        return [Disparo("ventoinha", f"ventoinha {rpm:.0f} rpm (média {media:.0f})",
                        fmt={"rpm": rpm, "media": media})]
    return []


def _reinicio(snap: Any, ctx: dict) -> list[Disparo]:
    precisa = getattr(snap, "reinicio", None) is True
    antes = ctx.get("_extras_reinicio", False)
    ctx["_extras_reinicio"] = precisa
    if precisa and not antes:
        return [Disparo("pede_reinicio", "dnf needs-restarting: reinício pendente")]
    return []


def _captura(snap: Any, ctx: dict) -> list[Disparo]:
    mtime = getattr(snap, "captura", None)
    if mtime is None:
        return []
    visto = ctx.get("_extras_captura")
    ctx["_extras_captura"] = max(float(mtime), visto or 0.0)
    if visto is None or mtime <= visto:
        return []
    relogio = ctx.get("relogio")
    if relogio is not None and float(relogio) - float(mtime) > CAPTURA_MAX_S:
        return []
    return [Disparo("posando_print", "captura de tela nova")]


def _data(ctx: dict) -> list[Disparo]:
    relogio, taste = ctx.get("relogio"), ctx.get("taste")
    section = getattr(taste, "section", None)
    if relogio is None or section is None:
        return []
    dia = datetime.fromtimestamp(float(relogio))
    hoje = dia.strftime("%Y-%m-%d")
    if ctx.get("_extras_data") == hoje:
        return []
    try:
        datas = section("datas") or {}
    except Exception:  # noqa: BLE001 - gosto ilegível = sem festa
        return []
    nome = datas.get(dia.strftime("%m-%d"))
    if not nome:
        return []
    ctx["_extras_data"] = hoje
    return [Disparo("data_especial", f"data especial: {nome}", fmt={"nome": str(nome)})]


def detectar(anterior: Any, snap: Any, ctx: dict) -> list[Disparo]:
    """Compara o Snapshot ``anterior`` com ``snap`` e devolve os disparos deste tick."""
    return _fan(snap, ctx) + _reinicio(snap, ctx) + _captura(snap, ctx) + _data(ctx)
