"""Notícias puxadas pelo PC — stub (dono: Y3.2; spec §2.2).

Por ora só autentica pela linha de ``ESCOPO_DE_ROTA`` e responde ``501``. A Y3.2 troca pelo real.
"""

from __future__ import annotations

from fastapi import APIRouter

from ayanami.api.auth import rota_stub

router = APIRouter()

rota_stub(router, "GET", "/v1/noticias", "Y3.2")
rota_stub(router, "PUT", "/v1/noticias/preferencias", "Y3.2")
