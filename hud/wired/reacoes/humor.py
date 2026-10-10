"""Leitura do momento e da faixa para as passivas (spec §3, §9). Dono: R1.1, V0.7.

Os 12 fatores antigos (R1.1) foram aposentados: quem manda nas passivas agora é o **momento**
(``momento.py``) e a **faixa** do humor dela (``estado.Humor``). Este módulo só lê do ``ctx``:

- ``momento``: ``ctx["momento"]`` (o que o chamador decidiu com histerese); sem ele, ``momento.bruto``;
- ``faixa``: ``ctx["faixa_humor"]`` (``Faixa`` ou texto) ou ``ctx["humor_estado"].faixa(agora)``;
  sem nenhum, ``Faixa.CONTENTE`` (a base mora aqui). ``ctx["faixa"]`` continua sendo a **música**;
- ``sinais``: o ``ctx`` normalizado para o ``momento.py`` (no formato antigo do ``Reactor``,
  ``faixa=None`` quer dizer sem música, e ``humor`` é o humor do Pedro do núcleo).
"""

from __future__ import annotations

from . import momento as _momento
from .vida import Faixa, Filtro, Fone, Momento


def sinais(ctx: dict) -> dict:
    """Cópia do ``ctx`` com ``musica_nota``/``humor_pedro`` no formato do ``momento.py``."""
    out = dict(ctx)
    if "faixa" in ctx and ctx["faixa"] is None:
        out["musica_nota"] = None
    if "humor_pedro" not in out and out.get("humor") is not None:
        out["humor_pedro"] = out["humor"]
    return out


def filtros(ctx: dict) -> set[Filtro]:
    """``momento.filtros`` + ``ctx["madrugada"]`` (bandeira antiga do ``Reactor``)."""
    fs = _momento.filtros(sinais(ctx))
    if ctx.get("madrugada"):
        fs.add(Filtro.MADRUGADA)
    return fs


def tem_musica(ctx: dict) -> bool:
    return sinais(ctx).get("musica_nota") is not None


def fone(ctx: dict) -> Fone:
    """Onde está o fone: ``ctx["fone"]``; sem ele, na cabeça (E2) só com música de nota ≥ 0."""
    f = ctx.get("fone")
    if f is not None:
        return Fone(f)
    nota = sinais(ctx).get("musica_nota")
    return Fone.CABECA if nota is not None and nota >= 0 else Fone.PESCOCO


def momento(ctx: dict) -> Momento:
    m = ctx.get("momento")
    return Momento(m) if m is not None else _momento.bruto(sinais(ctx))


def faixa(ctx: dict, agora: float | None = None) -> Faixa:
    f = ctx.get("faixa_humor")
    if f is not None:
        return Faixa(f)
    h = ctx.get("humor_estado")
    if h is not None:
        return h.faixa(float(ctx.get("agora", 0.0)) if agora is None else agora)
    return Faixa.CONTENTE


def fatores(ctx: dict) -> dict[str, str]:
    """O que está no ``ctx`` agora: ``{"momento": ..., "faixa": ...}`` (só as chaves presentes)."""
    out: dict[str, str] = {}
    if ctx.get("momento") is not None:
        out["momento"] = str(Momento(ctx["momento"]))
    if ctx.get("faixa_humor") is not None or ctx.get("humor_estado") is not None:
        out["faixa"] = str(faixa(ctx))
    return out
