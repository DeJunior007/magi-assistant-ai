"""Tarefas e fila — stub (dono: Y3.1; spec §2.2).

Por ora só autentica pela linha de ``ESCOPO_DE_ROTA`` e responde ``501``. A Y3.1 troca pelo real.
"""

from __future__ import annotations

from fastapi import APIRouter

from ayanami.api.auth import rota_stub

router = APIRouter()

rota_stub(router, "GET", "/v1/tarefas", "Y3.1")
rota_stub(router, "POST", "/v1/tarefas", "Y3.1")
rota_stub(router, "GET", "/v1/tarefas/{id}", "Y3.1")
rota_stub(router, "DELETE", "/v1/tarefas/{id}", "Y3.1")
rota_stub(router, "GET", "/v1/fila", "Y3.1")
