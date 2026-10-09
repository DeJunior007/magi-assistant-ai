"""Detector `det_conversa` (spec §5): 71–73, 79, I18 · cond. B: 74, 76, 86, 87 · cond. F: 88.
Dono: R1.5 (cond. B: R2.B; cond. F: R2.F).

- 71/72/73 `noticia_boa`/`noticia_ruim`/`noticia_absurda`: manchete nova (``snap.news[0]``) com
  palavra das listas ``[listas] noticia_*`` do gosto (``ctx["taste"]``). Ordem: ruim > absurda >
  boa; manchete com palavra de morte/desastre (lista ``noticia_ruim`` + ``GRAVES``) nunca vira 71
  nem 73 — só 72 (sem riso nem zoeira). A ``news`` antiga segue no ``fire``: não sai daqui.
- 79 `triste_leve`: humor do Pedro (``ctx["humor"]``) cai de ≥ 2 para ≤ 1.
- I18 `esperando_resposta`: Magui sai de ``speaking`` para parada (nem ``listening`` nem
  ``thinking``).

Estado próprio: ``_conversa_humor`` (último humor visto).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from .contratos import Disparo

# palavras de morte/desastre além da lista do gosto: com elas, nunca riso (71/73)
GRAVES = ("morte", "morre", "morreu", "mortos", "morto", "desastre", "tragedia", "acidente",
          "guerra", "ataque", "massacre", "terremoto", "enchente", "incendio", "queda")
ATIVA = ("speaking", "listening", "thinking")

_LISTAS = {  # recaída sem o gosto
    "noticia_boa": ("vitoria", "recorde", "lanca", "lancamento", "cura", "aprova", "conquista"),
    "noticia_ruim": ("morte", "morre", "ataque", "queda", "crise", "desastre", "guerra"),
    "noticia_absurda": ("bizarro", "inusitado", "inusitada", "estranho", "curioso"),
}


def _palavras(texto: str) -> list[str]:
    s = unicodedata.normalize("NFKD", texto.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+", s)


def _lista(ctx: dict, nome: str) -> tuple[str, ...]:
    taste = ctx.get("taste")
    try:
        sec = taste.section("listas") if taste is not None else {}
    except Exception:  # noqa: BLE001 — gosto quebrado não derruba o detector
        sec = {}
    v = sec.get(nome) if isinstance(sec, dict) else None
    return tuple(str(x).lower() for x in v) if v else _LISTAS[nome]


def _tem(palavras: list[str], lista: tuple[str, ...]) -> bool:
    return any(p.startswith(w) for p in palavras for w in lista if w)


def classificar(manchete: str, ctx: dict) -> str | None:
    """Chave da reação para a manchete (``noticia_*``) ou None."""
    ps = _palavras(manchete)
    if _tem(ps, _lista(ctx, "noticia_ruim")) or _tem(ps, GRAVES):
        return "noticia_ruim"
    if _tem(ps, _lista(ctx, "noticia_absurda")):
        return "noticia_absurda"
    if _tem(ps, _lista(ctx, "noticia_boa")):
        return "noticia_boa"
    return None


def _manchete(snap: Any) -> str | None:
    news = getattr(snap, "news", None) or []
    if not news:
        return None
    n = news[0]
    return n[1] if isinstance(n, tuple) and len(n) > 1 else str(n)


def detectar(anterior: Any, snap: Any, ctx: dict) -> list[Disparo]:
    """Compara o Snapshot ``anterior`` com ``snap`` e devolve os disparos deste tick."""
    out: list[Disparo] = []
    humor = ctx.get("humor")
    antes = ctx.get("_conversa_humor")
    ctx["_conversa_humor"] = humor
    if humor is not None and antes is not None and antes >= 2 and humor <= 1:
        out.append(Disparo("triste_leve", f"humor {antes} → {humor}"))
    if anterior is None:
        return out
    m = _manchete(snap)
    if m is not None and m != _manchete(anterior):
        chave = classificar(m, ctx)
        if chave is not None:
            out.append(Disparo(chave, f"manchete: {m}"))
    falou = getattr(anterior, "magui_state", None) == "speaking"
    if falou and getattr(snap, "magui_state", None) not in ATIVA:
        out.append(Disparo("esperando_resposta", "Magui terminou de falar"))
    return out
