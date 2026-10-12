"""Log da casa: uma linha JSON por evento em stdout/journald (spec §10.4; dono: C1.1).

Campos: ``ts, nivel, evento, tv, driver, acao, ok, motivo, ms, origem`` (``local|ayanami``) e extras.
O filtro nunca deixa passar token, cert, chave, código de pareamento nem texto digitado: campos com
esses nomes somem (texto vira ``<campo>_len``) e valores com cara de segredo viram ``"***"``.
Nível padrão ``INFO``; a sondagem loga só em ``DEBUG``.

Uso: ``configurar()`` uma vez no ``servir``; ``evento("acao", tv="sala", ok=True, ms=120)``.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import IO, Any

NOME = "magi.casa"
CAMPOS = ("tv", "driver", "acao", "ok", "motivo", "ms", "origem")

# nomes de campo que nunca saem (normalizados para minúsculas)
_SEGREDO = re.compile(
    r"(token|cert|chave|private|senha|password|secret|segredo|codigo|\bcode\b|\bpin\b|psk|"
    r"api_?key|auth)",
    re.I,
)
_TEXTO = {"texto", "text", "s", "digitado", "conteudo"}
# valores com cara de segredo, mesmo em campo inocente (mensagem de exceção, detalhe)
_VALOR_SEGREDO = re.compile(
    r"(ayn_[A-Za-z0-9_\-]{6,}|sk-[A-Za-z0-9_\-]{6,}|-----BEGIN [A-Z ]+-----[\s\S]*?(-----END [A-Z ]+-----|$)"
    r"|(?i:bearer)\s+\S+|(?i:token)[=:]\s*\S+)"
)


def limpa_valor(v: Any) -> Any:
    if isinstance(v, str):
        return _VALOR_SEGREDO.sub("***", v)
    if isinstance(v, dict):
        return limpa_campos(v)
    if isinstance(v, list | tuple):
        return [limpa_valor(x) for x in v]
    if v is None or isinstance(v, bool | int | float):
        return v
    return limpa_valor(str(v))


def limpa_campos(campos: dict[str, Any]) -> dict[str, Any]:
    saida: dict[str, Any] = {}
    for k, v in campos.items():
        nome = str(k)
        if nome.lower() in _TEXTO:
            saida[f"{nome}_len"] = len(v) if isinstance(v, str) else None
            continue
        if _SEGREDO.search(nome):
            continue
        saida[nome] = limpa_valor(v)
    return saida


class FormatoJson(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        campos = limpa_campos(dict(getattr(record, "casa", {}) or {}))
        linha: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "nivel": record.levelname,
            "evento": limpa_valor(record.getMessage()),
        }
        for c in CAMPOS:
            if c in campos:
                linha[c] = campos.pop(c)
        linha.update(campos)
        if record.exc_info and record.exc_info[1] is not None:
            e = record.exc_info[1]
            linha["erro"] = type(e).__name__
            linha["erro_msg"] = limpa_valor(str(e))[:300]
        return json.dumps(linha, ensure_ascii=False, default=str)


def logger() -> logging.Logger:
    return logging.getLogger(NOME)


def configurar(nivel: str | int = "INFO", stream: IO[str] | None = None) -> logging.Handler:
    """Liga o handler JSON no logger ``magi.casa`` (troca o anterior; não propaga para a raiz)."""
    lg = logger()
    for h in list(lg.handlers):
        if getattr(h, "_magi_casa", False):
            lg.removeHandler(h)
    h = logging.StreamHandler(stream or sys.stdout)
    h.setFormatter(FormatoJson())
    h._magi_casa = True  # type: ignore[attr-defined]
    lg.addHandler(h)
    lg.setLevel(nivel if isinstance(nivel, int) else nivel.upper())
    lg.propagate = False
    return h


def evento(nome: str, nivel: int = logging.INFO, *, exc: bool = False, **campos: Any) -> None:
    """Emite um evento; ``exc=True`` anexa a exceção corrente (só tipo e mensagem limpa)."""
    logger().log(nivel, nome, extra={"casa": campos}, exc_info=exc)
