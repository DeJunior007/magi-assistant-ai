"""Relatório do registro de reações (R3.2, R10).

Uso: ``uv run python -m hud.tools.reacoes_relatorio [caminho] [--dias N]``

Lê o ``reacoes.jsonl`` (padrão ``~/.local/state/magi/reacoes.jsonl``, mais o ``.1`` do giro se
existir) e imprime, em texto curto: ativas e passivas por hora (média e pico), horas que passaram
do teto de ativas, furos de cota por classe, top 10 e as reações de ``ATIVAS`` nunca tocadas.

"Ativa" = qualquer reação sem a classe ``PASSIVA``. O teto (``governador.ATIVAS_POR_HORA``) conta só
as ativas que não furam cota (``SISTEMA``/``VITORIA``/``VOLTA`` ficam de fora, spec §3). A média por
hora usa todas as horas do intervalo coberto (da primeira à última linha), não só as com registro.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from hud.wired.reacoes import catalogo
from hud.wired.reacoes.contratos import Classe
from hud.wired.reacoes.governador import ATIVAS_POR_HORA, FURAM_COTA
from hud.wired.reacoes.registro import REGISTRO_FILE

HORA_S = 3600


def ler(caminho: Path) -> list[dict]:
    """Linhas válidas do registro (o ``.1`` do giro vem antes); linha quebrada é pulada."""
    linhas: list[dict] = []
    for p in (caminho.with_name(caminho.name + ".1"), caminho):
        try:
            texto = p.read_text(encoding="utf-8")
        except OSError:
            continue
        for bruta in texto.splitlines():
            try:
                linha = json.loads(bruta)
            except ValueError:
                continue
            if isinstance(linha, dict) and isinstance(linha.get("t"), (int, float)) and linha.get("chave"):
                linhas.append(linha)
    linhas.sort(key=lambda linha: linha["t"])
    return linhas


def _chave(linha: dict) -> str | tuple[str, str]:
    v = linha.get("variante")
    return linha["chave"] if v is None else (linha["chave"], v)


def _def(linha: dict):
    return catalogo.DEFS.get(_chave(linha)) or catalogo.DEFS.get(linha["chave"])


def _nome(k: str | tuple[str, str]) -> str:
    d = catalogo.DEFS.get(k)
    rotulo = k if isinstance(k, str) else f"{k[0]}/{k[1]}"
    return f"{d.n} {rotulo}" if d else str(rotulo)


def _rotulo(linha: dict) -> str:
    d = _def(linha)
    k = _chave(linha)
    rotulo = k if isinstance(k, str) else f"{k[0]}/{k[1]}"
    return f"{linha.get('n', d.n if d else '?')} {rotulo}"


def relatorio(linhas: Iterable[dict], dias: float | None = None, agora: float | None = None,
              ativas: Iterable = None) -> str:
    """Texto do relatório. ``dias`` filtra as linhas com ``t ≥ agora − dias``."""
    linhas = list(linhas)
    if dias is not None:
        ref = time.time() if agora is None else agora
        linhas = [linha for linha in linhas if linha["t"] >= ref - dias * 86400]
    if not linhas:
        return "Nenhuma reação no registro" + (f" nos últimos {dias:g} dias." if dias else ".")
    ativas = catalogo.ATIVAS if ativas is None else frozenset(ativas)

    por_hora_at: Counter[int] = Counter()
    por_hora_cota: Counter[int] = Counter()
    por_hora_pas: Counter[int] = Counter()
    furos: Counter[str] = Counter()
    top: Counter[str] = Counter()
    tocadas: set = set()
    for linha in linhas:
        h = int(linha["t"] // HORA_S)
        d = _def(linha)
        classes = d.classes if d else frozenset()
        top[_rotulo(linha)] += 1
        tocadas.add(_chave(linha))
        tocadas.add(linha["chave"])
        if Classe.PASSIVA in classes:
            por_hora_pas[h] += 1
            continue
        por_hora_at[h] += 1
        if linha.get("furou_cota"):
            furadas = sorted(c.value for c in classes & FURAM_COTA) or ["?"]
            for c in furadas:
                furos[c] += 1
        else:
            por_hora_cota[h] += 1

    h0, h1 = int(linhas[0]["t"] // HORA_S), int(linhas[-1]["t"] // HORA_S)
    n_horas = h1 - h0 + 1

    def fmt_h(h: int) -> str:
        return time.strftime("%Y-%m-%d %Hh", time.localtime(h * HORA_S))

    def media_pico(c: Counter[int]) -> str:
        if not c:
            return "média 0,00 · pico 0"
        h, pico = max(c.items(), key=lambda kv: (kv[1], -kv[0]))
        return f"média {sum(c.values()) / n_horas:.2f}".replace(".", ",") + f" · pico {pico} ({fmt_h(h)})"

    out = [
        f"Reações: {len(linhas)} em {n_horas} h ({fmt_h(h0)} → {fmt_h(h1)})",
        f"Ativas/h: {media_pico(por_hora_at)}",
        f"  na cota/h: {media_pico(por_hora_cota)}",
        f"Passivas/h: {media_pico(por_hora_pas)}",
    ]
    estouro = sorted(h for h, n in por_hora_cota.items() if n > ATIVAS_POR_HORA)
    out.append(f"Horas acima de {ATIVAS_POR_HORA} ativas na cota: {len(estouro)}")
    out += [f"  {fmt_h(h)}: {por_hora_cota[h]}" for h in estouro]
    out.append("Furos de cota por classe: " + (
        ", ".join(f"{c} {n}" for c, n in sorted(furos.items(), key=lambda kv: (-kv[1], kv[0])))
        or "nenhum"))
    out.append("Top 10:")
    out += [f"  {n:>4}  {r}" for r, n in top.most_common(10)]
    nunca = sorted((k for k in ativas if k not in tocadas), key=lambda k: _nome(k))
    out.append(f"Nunca tocadas ({len(nunca)} de {len(ativas)} ativas):")
    if nunca:
        out.append("  " + ", ".join(_nome(k) for k in nunca))
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Relatório do reacoes.jsonl (R3.2)")
    ap.add_argument("caminho", nargs="?", type=Path, default=REGISTRO_FILE)
    ap.add_argument("--dias", type=float, default=None, help="só os últimos N dias")
    args = ap.parse_args(argv)
    linhas = ler(args.caminho.expanduser())
    if not linhas:
        print(f"Registro ausente ou vazio: {args.caminho}")
        return 0
    print(relatorio(linhas, dias=args.dias))
    return 0


if __name__ == "__main__":
    sys.exit(main())
