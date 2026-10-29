"""Mesclador de compose em Python para os testes (ayanami-plataforma P0.1, spec §1, CA-P1/CA-P3).

Simula o `docker compose -f a.yml -f b.yml config` sem `docker`: mapeamentos mesclados chave a chave
(recursivo, inclusive `services.<nome>` campo a campo), listas e escalares do override substituem os
da base. As âncoras e `<<:` do YAML já chegam resolvidas pelo `yaml.safe_load`. Os perfis seguem o
Compose: serviço sem `profiles` sempre ativo; com `profiles`, só se algum estiver entre os pedidos.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
DIR = REPO / "deploy" / "ayanami"
COMPOSE = DIR / "compose.yml"
NODE2_INTEIRO = DIR / "compose.node2-inteiro.yml"


def mesclar(base: object, override: object) -> object:
    """Mescla dois documentos de compose: dict com dict recursivo; o resto, o override vence."""
    if isinstance(base, dict) and isinstance(override, dict):
        out = dict(base)
        for chave, valor in override.items():
            out[chave] = mesclar(base[chave], valor) if chave in base else valor
        return out
    return override


def carregar(*caminhos: Path) -> dict:
    """Carrega e mescla os arquivos na ordem dada (como `COMPOSE_FILE=a:b`)."""
    doc: dict = {}
    for caminho in caminhos:
        doc = mesclar(doc, yaml.safe_load(caminho.read_text(encoding="utf-8")) or {})  # type: ignore[assignment]
    return doc


def node2_inteiro() -> dict:
    """`compose.yml` + `compose.node2-inteiro.yml` (o `COMPOSE_FILE` do perfil "node 2 inteiro")."""
    return carregar(COMPOSE, NODE2_INTEIRO)


def servicos_ativos(doc: dict, perfis: Iterable[str] = ()) -> dict[str, dict]:
    """Serviços que o `docker compose --profile <p>…` subiria (sem perfil: só os sem `profiles`)."""
    pedidos = set(perfis)
    return {
        nome: svc
        for nome, svc in (doc.get("services") or {}).items()
        if not svc.get("profiles") or pedidos & set(svc["profiles"])
    }


def bytes_de(v: str | int) -> int:
    """`512m`/`3g`/`3584m`/inteiro → bytes (unidades do Compose)."""
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([kmg]?)b?", str(v).strip().lower())
    if not m:
        raise ValueError(f"tamanho ilegível: {v!r}")
    mult = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3}[m.group(2)]
    return int(float(m.group(1)) * mult)
