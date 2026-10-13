"""SSE dos eventos (``GET /v1/eventos``) — stub (dono: Y2.3; spec §2.2).

Por ora só autentica pela linha de ``ESCOPO_DE_ROTA`` e responde ``501``. A Y2.3 troca pelo real.
"""

from __future__ import annotations

from fastapi import APIRouter

from ayanami.api.auth import rota_stub

router = APIRouter()

rota_stub(router, "GET", "/v1/eventos", "Y2.3")
