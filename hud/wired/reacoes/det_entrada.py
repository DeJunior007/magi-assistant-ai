"""Detector `det_entrada` (spec §5): 5, 64, 66 · cond. A: 15, 65, 67, 69, 70, 77.
Dono: R1.5 (cond. A: R2.A).

- 5 `seguir_cursor`: sacada curta para o card que acabou de mudar — faixa nova (player), manchete
  nova (radio) ou o FPS aparecendo (fps). ``fmt["card"]`` diz qual. Com jogo aberto
  (``ctx["jogo"]`` ou ``snap.gaming``) só o card do FPS.
- 64 `led` base (escalada inteira em 4 passos): 3º+ clique no LED em 5 s. O 1º clique segue no
  ``fire`` antigo (``Reactor.on_click``): não sai daqui.
- 66 `led`/`fone`: clique no LED (1º ou 2º da rajada) com música tocando.

Cliques: o ``Reactor.on_click`` não passa pelos detectores; este módulo lê ``ctx["cliques"]``
(sequência de ``(agora_monotônico, alvo)`` dos cliques recentes, alvo ``"led"``, ``"next"``…)
e guarda em ``_entrada_visto`` o instante do último clique já tratado. Sem a chave: 64/66 não saem.
Estado próprio: ``_entrada_visto``, ``_entrada_faixa`` (última ``(title, artist)`` vista).
"""

from __future__ import annotations

from typing import Any

from .contratos import Disparo

RAJADA_S = 5.0  # 64: cliques no LED dentro desta janela contam juntos
ESCALADA = 3  # 64: a partir do 3º


def _musica(snap: Any) -> bool:
    t = getattr(snap, "track", None)
    return t is not None and bool(getattr(t, "playing", False))


def _faixa(snap: Any) -> tuple | None:
    t = getattr(snap, "track", None)
    if t is None or not getattr(t, "title", None):
        return None
    return (t.title, getattr(t, "artist", None))


def _manchete(snap: Any) -> Any:
    news = getattr(snap, "news", None) or []
    return news[0] if news else None


def _cliques(snap: Any, ctx: dict) -> list[Disparo]:
    leds = sorted(t for t, alvo in ctx.get("cliques") or () if alvo == "led")
    visto = ctx.get("_entrada_visto")
    novos = [t for t in leds if visto is None or t > visto]
    if not novos:
        return []
    ctx["_entrada_visto"] = novos[-1]
    t = novos[-1]
    n = sum(1 for x in leds if t - RAJADA_S <= x <= t)
    if n >= ESCALADA:
        return [Disparo("led", f"{n}º clique no LED em {RAJADA_S:.0f} s")]
    if _musica(snap):
        return [Disparo("led", "clique no LED com música", "fone")]
    return []


def detectar(anterior: Any, snap: Any, ctx: dict) -> list[Disparo]:
    """Compara o Snapshot ``anterior`` com ``snap`` e devolve os disparos deste tick."""
    out = _cliques(snap, ctx)
    faixa = _faixa(snap)
    faixa_antes = ctx.get("_entrada_faixa", _faixa(anterior) if anterior is not None else None)
    ctx["_entrada_faixa"] = faixa
    if anterior is None:
        return out
    card = None
    jogo = bool(ctx.get("jogo") or getattr(snap, "gaming", False))
    if jogo:  # jogando: ela não desvia o olho para player/rádio (só extremos da música falam)
        pass
    elif faixa is not None and faixa != faixa_antes:
        card = "player"
    elif _manchete(snap) is not None and _manchete(snap) != _manchete(anterior):
        card = "radio"
    if card is None and getattr(snap, "fps", None) is not None and getattr(anterior, "fps", None) is None:
        card = "fps"
    if card is not None:
        out.append(Disparo("seguir_cursor", f"card {card} mudou", fmt={"card": card}))
    return out
