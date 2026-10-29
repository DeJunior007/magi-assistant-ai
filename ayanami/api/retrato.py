"""``/v1/retrato*`` (stub; dono: M1.3; condessa-celular spec §9.3).

Nasce na M1.1 só com as linhas de :data:`ayanami.api.auth.ESCOPO_DE_ROTA` registradas como
``501 nao_implementado`` (o teste da tabela exige rota para cada linha). A M1.3 troca cada stub pela
rota real; os downloads (``pacote``/``modelos``) chamam ``ctx.limites.por_download`` e podem usar
``ayanami.api.app_android.servir_arquivo`` (``ETag``/``Range``/``If-Range``/``416``).
"""

from __future__ import annotations

from fastapi import APIRouter

from ayanami.api.auth import rota_stub

router = APIRouter()

for _metodo, _caminho in (
    ("GET", "/v1/retrato/versao"),
    ("GET", "/v1/retrato/pacote"),
    ("GET", "/v1/retrato/modelos"),
    ("PUT", "/v1/retrato"),
):
    rota_stub(router, _metodo, _caminho, "M1.3")
