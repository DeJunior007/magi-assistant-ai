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

Retrato (sinal A, R2.A; o HUD liga ``setMouseTracking`` e chama ``Reactor.on_hover``):
``ctx["gestos"]`` = ``(monotônico, evento)`` com ``"in"`` → 65 ``hover``, ``"dbl"`` (2 cliques
≤ 250 ms, o PTT espera) → 69 ``clique_duplo``, ``"long"`` (≥ 800 ms) → 70 ``segurar_clique``,
``"arrasto"`` (≥ 40 px na metade de cima) → 67 ``carinho``. ``ctx["rosto_parado"]`` = desde quando
o cursor está parado no rosto: 3 s → 77 ``flagrada``, 10 s → 15 ``encarando`` (cada um 1× por
parada; só o 15 se as duas marcas passam no mesmo tick). 64 também vale no retrato: cliques
simples no rosto (alvo ``"face"``, cada um um push-to-talk) contam na rajada junto com os do LED;
o 66 (fone) segue só para o LED. Estado: ``_entrada_gesto``, ``_entrada_parado``.
"""

from __future__ import annotations

from typing import Any

from .contratos import Disparo

RAJADA_S = 5.0  # 64: cliques no LED dentro desta janela contam juntos
ESCALADA = 3  # 64: a partir do 3º
FLAGRADA_S = 3.0  # 77: cursor parado no rosto
ENCARANDO_S = 10.0  # 15
GESTOS = {
    "in": ("hover", "cursor entrou no rosto"),
    "dbl": ("clique_duplo", "clique duplo no rosto"),
    "long": ("segurar_clique", "segurou o clique no rosto"),
    "arrasto": ("carinho", "arrastou no rosto"),
}
CUTUCAVEIS = ("led", "face")  # 64: alvos que contam na rajada


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
    cliques = sorted((t, alvo) for t, alvo in ctx.get("cliques") or () if alvo in CUTUCAVEIS)
    visto = ctx.get("_entrada_visto")
    novos = [c for c in cliques if visto is None or c[0] > visto]
    if not novos:
        return []
    t, alvo = novos[-1]
    ctx["_entrada_visto"] = t
    n = sum(1 for x, _ in cliques if t - RAJADA_S <= x <= t)
    if n >= ESCALADA:
        onde = "no LED" if alvo == "led" else "no retrato"
        return [Disparo("led", f"{n}º clique {onde} em {RAJADA_S:.0f} s")]
    if alvo == "led" and _musica(snap):
        return [Disparo("led", "clique no LED com música", "fone")]
    return []


def _retrato(ctx: dict) -> list[Disparo]:
    out: list[Disparo] = []
    visto = ctx.get("_entrada_gesto")
    gestos = [g for g in ctx.get("gestos") or () if visto is None or g[0] > visto]
    if gestos:
        ctx["_entrada_gesto"] = max(t for t, _ in gestos)
    for _, ev in gestos:
        par = GESTOS.get(ev)
        if par is not None and all(d.chave != par[0] for d in out):
            out.append(Disparo(*par))
    desde = ctx.get("rosto_parado")
    if desde is None:
        ctx["_entrada_parado"] = None
        return out
    marca = ctx.get("_entrada_parado")
    nivel = marca[1] if marca is not None and marca[0] == desde else 0
    parado = float(ctx.get("agora", desde)) - desde
    if parado >= ENCARANDO_S and nivel < 2:
        out.append(Disparo("encarando", f"cursor parado no rosto {parado:.0f} s"))
        nivel = 2
    elif parado >= FLAGRADA_S and nivel < 1:
        out.append(Disparo("flagrada", f"cursor parado no rosto {parado:.0f} s"))
        nivel = 1
    ctx["_entrada_parado"] = (desde, nivel)
    return out


def detectar(anterior: Any, snap: Any, ctx: dict) -> list[Disparo]:
    """Compara o Snapshot ``anterior`` com ``snap`` e devolve os disparos deste tick."""
    out = _cliques(snap, ctx) + _retrato(ctx)
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
