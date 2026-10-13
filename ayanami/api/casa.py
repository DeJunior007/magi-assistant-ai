"""Ação e estado da casa — stub (dono: Y2.2; spec §2.2).

Por ora só autentica pela linha de ``ESCOPO_DE_ROTA`` e responde ``501``. A Y2.2 troca pelo real.
"""

from __future__ import annotations

from fastapi import APIRouter

from ayanami.api.auth import rota_stub

router = APIRouter()

rota_stub(router, "POST", "/v1/casa/acao", "Y2.2")
rota_stub(router, "GET", "/v1/casa/estado", "Y2.2")
