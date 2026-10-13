"""Assinatura de Web Push — stub (dono: P2.1; spec §2.2).

Por ora só autentica pela linha de ``ESCOPO_DE_ROTA`` e responde ``501``. A P2.1 troca pelo real.
"""

from __future__ import annotations

from fastapi import APIRouter

from ayanami.api.auth import rota_stub

router = APIRouter()

rota_stub(router, "POST", "/v1/push/assinar", "P2.1")
rota_stub(router, "DELETE", "/v1/push/assinar", "P2.1")
