"""Auditoria (dono: Y2.1; design §4.1, spec §2.3, tabela ``auditoria`` da §3).

Toda rota de ``casa``, ``backup``, dispositivo e MCP grava uma linha. ``resumo`` é curto (≤ 300) e
nunca leva token, corpo, áudio nem texto de conversa — só ids, nomes de dispositivo e tamanhos.
O job diário que apaga > 90 dias é da fila (Y3.x).
"""

from __future__ import annotations

from typing import Any

from ayanami.db import Db, transacao

TIPOS = ("casa", "mcp", "dispositivo", "backup", "tarefa", "push", "app", "retrato")
MAX_RESUMO = 300


def registrar(
    alvo_db: Db | Any,
    *,
    tipo: str,
    resumo: str,
    ok: bool,
    dispositivo: int | None = None,
    alvo: str | None = None,
) -> None:
    """Grava uma linha. ``alvo_db`` é um :class:`Db` (abre transação) ou uma conexão já aberta."""
    if tipo not in TIPOS:
        raise ValueError(f"tipo de auditoria inválido: {tipo!r}")
    params = (dispositivo, tipo, alvo, resumo[:MAX_RESUMO], ok)
    sql = "INSERT INTO auditoria (dispositivo, tipo, alvo, resumo, ok) VALUES (%s, %s, %s, %s, %s)"
    if hasattr(alvo_db, "execute"):  # conexão aberta: entra na transação do chamador
        alvo_db.execute(sql, params)
        return
    with transacao(alvo_db) as conn:
        conn.execute(sql, params)
