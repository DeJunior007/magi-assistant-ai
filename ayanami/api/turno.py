"""Turno do celular — stub (dono: Y6.4; spec §2.2).

Por ora só autentica pela linha de ``ESCOPO_DE_ROTA`` e responde ``501``. A Y6.4 troca pelo real.
"""

from __future__ import annotations

from fastapi import APIRouter

from ayanami.api.auth import rota_stub

router = APIRouter()

rota_stub(router, "POST", "/v1/turno", "Y6.4")
rota_stub(router, "GET", "/v1/turno/{id}", "Y6.4")
rota_stub(router, "GET", "/v1/turno/{id}/audio", "Y6.4")
