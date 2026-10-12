"""Ponte entre o elo e ``magi.common.contracts`` (spec §1.2, ``converte.py``).

``on_confirm`` não viaja: ``precisa_confirmar=True`` e quem pediu reenvia com ``confirmed=True``.
``danger`` do ``Intent`` reconstruído vem do ``intents.yaml`` (lido uma vez, sob demanda) ou do
conjunto ``perigosos`` passado por quem chama.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from magi.common.contracts import ActionRequest, ActionResult, CardMsg, Intent, Slot, TurnContext
from magi.elo.mensagens import AcaoPedido, AcaoResultado, CardElo, EloError

INTENTS_PATH = Path(__file__).resolve().parent.parent / "core" / "intents.yaml"


@cache
def intents_perigosos(caminho: Path = INTENTS_PATH) -> frozenset[str]:
    """Ids com ``danger: true`` no ``intents.yaml``."""
    dados = yaml.safe_load(Path(caminho).read_text(encoding="utf-8")) or {}
    return frozenset(
        str(i["id"]) for i in dados.get("intents", ()) if isinstance(i, Mapping) and i.get("danger")
    )


def _escalar(k: str, v: Any) -> str | int | float | bool:
    if isinstance(v, str | int | float | bool):
        return v
    raise EloError("campo", f"args.{k}: só texto, número ou booleano viajam no elo")


def pedido_de_request(req: ActionRequest) -> AcaoPedido:
    """``ActionRequest`` → ``AcaoPedido`` (sem ``TurnContext``). Arg não escalar → ``EloError``."""
    return AcaoPedido(
        intent=str(req.intent.id),
        slots=tuple((str(s.name), s.value) for s in req.intent.slots),
        texto=req.text,
        confirmed=req.confirmed,
        args={str(k): _escalar(str(k), v) for k, v in req.args.items()},
    )


def request_de_pedido(
    p: AcaoPedido, ctx: TurnContext, *, perigosos: Collection[str] | None = None
) -> ActionRequest:
    """``AcaoPedido`` + contexto local → ``ActionRequest``. ``danger`` do ``intents.yaml``."""
    danger = p.intent in (intents_perigosos() if perigosos is None else perigosos)
    intent = Intent(id=p.intent, slots=tuple(Slot(name=n, value=v) for n, v in p.slots), danger=danger)
    return ActionRequest(intent=intent, ctx=ctx, text=p.texto, confirmed=p.confirmed, args=dict(p.args))


def resultado_de_action(res: ActionResult) -> AcaoResultado:
    """``ActionResult`` → ``AcaoResultado``; ``fala`` = ``speech`` ou, sem ela, ``full_text``."""
    return AcaoResultado(
        ok=res.ok,
        fala=res.speech or (res.full_text or ""),
        precisa_confirmar=res.needs_confirmation,
        perigosa=res.dangerous,
    )


def card_de_cardmsg(c: CardMsg) -> CardElo:
    """``CardMsg`` → ``CardElo`` (``texto`` = fonte; ``url`` vazia vira ``None``)."""
    return CardElo(titulo=c.title, texto=c.source or "", url=c.url or None, nivel=str(c.level.value))
