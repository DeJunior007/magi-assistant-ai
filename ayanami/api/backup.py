"""Recebimento do backup do PC — stub (dono: Y4.2; spec §2.2).

Por ora só autentica pela linha de ``ESCOPO_DE_ROTA`` e responde ``501``. A Y4.2 troca pelo real.
"""

from __future__ import annotations

from fastapi import APIRouter

from ayanami.api.auth import rota_stub

router = APIRouter()

rota_stub(router, "PUT", "/v1/backup/pc", "Y4.2")
