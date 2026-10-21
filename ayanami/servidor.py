"""A Ayanami responde "como está o servidor?" (dono: Y1.3c; node 2 dividido com o Minecraft).

Lê o resumo que o vigia (Y1.3b, ``deploy/ayanami/vigia/vigia.py``) grava a cada minuto no host em
``/opt/ayanami/dados/servidor.json`` — dentro do container é ``/dados/servidor.json``. Caminho:
``AYANAMI_SERVIDOR_JSON``, senão ``$AYANAMI_DADOS/servidor.json``, senão
:data:`ayanami.deps.DADOS_PADRAO`.

:func:`ler` devolve um dict pronto para JSON com ``estado`` (``ok`` | ``velho`` | ``ausente`` |
``corrompido``), os campos validados do vigia, o ``disco`` da partição dos dados (medido aqui) e
``resumo``: frase curta em pt-BR. ``velho`` = ``ts`` com mais de :data:`VELHO_APOS`. Nunca lança
por causa do arquivo; nada de rede.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ayanami.deps import DADOS_PADRAO

CAMINHO_ENV = "AYANAMI_SERVIDOR_JSON"
DADOS_ENV = "AYANAMI_DADOS"
NOME = "servidor.json"
VELHO_APOS = timedelta(minutes=3)
TAMANHO_MAX = 256 * 1024
GIB = 1024**3

SAY_AUSENTE = "Não tenho leitura do servidor: o vigia ainda não gravou nada."
SAY_CORROMPIDO = "A leitura do servidor veio quebrada; o vigia precisa de uma olhada."


def caminho_padrao(env: Mapping[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    if env.get(CAMINHO_ENV):
        return Path(env[CAMINHO_ENV])
    return Path(env.get(DADOS_ENV) or DADOS_PADRAO) / NOME


# --------------------------------------------------------------------------- validação


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    return float(v)


def _txt(v: Any, n: int = 40) -> str | None:
    return v[:n] if isinstance(v, str) else None


def _cpu(v: Any) -> dict | None:
    if not isinstance(v, dict):
        return None
    saida = {}
    for grupo in ("minecraft", "ayanami"):
        g = v.get(grupo)
        if isinstance(g, dict):
            saida[grupo] = {"nucleos": _txt(g.get("nucleos"), 16), "uso": _num(g.get("uso"))}
    return saida or None


def _campos(v: Any, chaves: tuple[str, ...]) -> dict | None:
    if not isinstance(v, dict):
        return None
    saida = {k: _num(v.get(k)) for k in chaves}
    return saida if all(x is not None for x in saida.values()) else None


def _minecraft(v: Any) -> dict | str | None:
    if v == "ausente":
        return "ausente"
    if not isinstance(v, dict) or not isinstance(v.get("status"), str):
        return None
    jog = v.get("jogadores")
    mx = v.get("max_jogadores")
    nomes = v.get("nomes") if isinstance(v.get("nomes"), list) else []
    return {
        "status": v["status"][:40],
        "restart_count": v["restart_count"] if isinstance(v.get("restart_count"), int) else None,
        "rcon": _txt(v.get("rcon"), 80),
        "jogadores": jog if isinstance(jog, int) and not isinstance(jog, bool) else None,
        "max_jogadores": mx if isinstance(mx, int) and not isinstance(mx, bool) else None,
        "nomes": [n[:32] for n in nomes if isinstance(n, str)][:50],
        "tps": _num(v.get("tps")),
    }


def validar(bruto: Any) -> dict:
    """Campos do vigia já checados; ``ValueError`` se não for um resumo (sem ``ts`` válido)."""
    if not isinstance(bruto, dict) or not isinstance(bruto.get("ts"), str):
        raise ValueError("resumo sem ts")
    ts = datetime.fromisoformat(bruto["ts"])
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    load = bruto.get("load")
    if not (isinstance(load, list) and load and all(_num(x) is not None for x in load[:3])):
        load = None
    alertas = bruto.get("alertas") if isinstance(bruto.get("alertas"), list) else []
    return {
        "ts": ts,
        "cpu": _cpu(bruto.get("cpu")),
        "load": [float(x) for x in load[:3]] if load else None,
        "ram": _campos(bruto.get("ram"), ("total_gib", "disponivel_gib")),
        "swap": _campos(bruto.get("swap"), ("total_gib", "usado_gib")),
        "minecraft": _minecraft(bruto.get("minecraft")),
        "alertas": [a[:40] for a in alertas if isinstance(a, str)][:20],
    }


def _disco(pasta: Path, medir: Callable[[Path], Any]) -> dict | None:
    try:
        u = medir(pasta)
    except OSError:
        return None
    return {"total_gib": round(u.total / GIB, 1), "livre_gib": round(u.free / GIB, 1)}


# --------------------------------------------------------------------------- leitura


def ler(caminho: Path | None = None, *, agora: datetime,
        medir_disco: Callable[[Path], Any] = shutil.disk_usage) -> dict[str, Any]:
    """Lê e valida o ``servidor.json``; sempre devolve um dict com ``estado`` e ``resumo``."""
    caminho = caminho or caminho_padrao()
    disco = _disco(caminho.parent, medir_disco)
    try:
        if caminho.stat().st_size > TAMANHO_MAX:
            raise ValueError("grande demais")
        bruto = json.loads(caminho.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"estado": "ausente", "disco": disco, "resumo": SAY_AUSENTE}
    except (OSError, ValueError):
        return {"estado": "corrompido", "disco": disco, "resumo": SAY_CORROMPIDO}
    try:
        dados = validar(bruto)
    except (TypeError, ValueError):
        return {"estado": "corrompido", "disco": disco, "resumo": SAY_CORROMPIDO}
    idade = (agora - dados["ts"]).total_seconds()
    estado = "velho" if idade > VELHO_APOS.total_seconds() else "ok"
    saida: dict[str, Any] = {"estado": estado, "idade_s": round(idade), **dados, "disco": disco}
    saida["ts"] = dados["ts"].isoformat()
    saida["resumo"] = resumo(saida)
    return saida


# --------------------------------------------------------------------------- frase


def _f(x: float, casas: int = 1) -> str:
    return f"{x:.{casas}f}".replace(".", ",")


def _idade(s: float) -> str:
    m = int(s // 60)
    if m < 120:
        return f"{m} min"
    return f"{m // 60} h"


def _frase_mc(mc: Any) -> str | None:
    if mc == "ausente":
        return "Minecraft não está instalado aqui"
    if not isinstance(mc, dict):
        return None
    if mc["status"] == "erro":
        return "não consegui ver o Minecraft"
    if mc["status"] != "running":
        return f"Minecraft parado ({mc['status']})"
    partes = ["Minecraft no ar"]
    if mc.get("jogadores") is not None:
        j = mc["jogadores"]
        if j == 0:
            partes.append("ninguém jogando")
        else:
            nomes = ", ".join(mc.get("nomes") or [])
            partes.append(f"{j} jogando" + (f" ({nomes})" if nomes and j <= 5 else ""))
    elif mc.get("rcon") and mc["rcon"] != "ok":
        partes.append("RCON sem resposta")
    if mc.get("tps") is not None:
        partes.append(f"TPS {_f(mc['tps'])}")
    return ", ".join(partes)


def resumo(d: Mapping[str, Any]) -> str:
    """Frase curta e seca (estilo da Condessa) a partir da saída de :func:`ler`."""
    if d.get("estado") == "ausente":
        return SAY_AUSENTE
    if d.get("estado") == "corrompido":
        return SAY_CORROMPIDO
    frases = []
    if d.get("estado") == "velho":
        frases.append(f"Leitura velha, de {_idade(d.get('idade_s') or 0)} atrás; o vigia parou?")
    cpu = d.get("cpu") or {}
    grupos = [f"{rot} {_f(cpu[g]['uso'], 0)}%" for g, rot in (("minecraft", "Minecraft"),
                                                                ("ayanami", "eu"))
              if g in cpu and cpu[g]["uso"] is not None]
    if grupos:
        frases.append("CPU: " + ", ".join(grupos) + ".")
    mem = []
    if d.get("ram"):
        mem.append(f"RAM {_f(d['ram']['disponivel_gib'])} de {_f(d['ram']['total_gib'])} GiB livres")
    if d.get("swap") and d["swap"]["total_gib"]:
        mem.append(f"swap {_f(d['swap']['usado_gib'])} GiB em uso")
    if d.get("disco") and d["disco"]["total_gib"]:
        mem.append(f"disco {_f(d['disco']['livre_gib'], 0)} GiB livres")
    if mem:
        texto = "; ".join(mem)
        frases.append(texto[:1].upper() + texto[1:] + ".")
    mc = _frase_mc(d.get("minecraft"))
    if mc:
        frases.append(mc[:1].upper() + mc[1:] + ".")
    if d.get("alertas"):
        frases.append("De olho em: " + ", ".join(d["alertas"]) + ".")
    elif d.get("estado") == "ok":
        frases.insert(0, "Servidor tranquilo.")
    return " ".join(frases) or "Servidor sem números por enquanto."


def ler_agora(caminho: Path | None = None) -> dict[str, Any]:
    """:func:`ler` com o relógio real (atalho das tools)."""
    return ler(caminho, agora=datetime.now(UTC))
