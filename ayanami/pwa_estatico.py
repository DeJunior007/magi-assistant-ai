"""PWA estático em ``/app`` (spec §2.2 ``GET /app/*``, §14). Dono: P1.1.

:func:`montar_pwa` é chamada por ``criar_app`` (Y2.1) via ``montar_pwa_se_houver``. Serve
``ayanami/pwa/`` com ``index.html`` em ``/app/`` (``/app`` redireciona), ``manifest.webmanifest``
como ``application/manifest+json`` e ``Cache-Control: no-cache`` no ``sw.js`` (o navegador sempre
revalida o service worker; o resto fica no cache versionado do próprio SW).
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from starlette.responses import RedirectResponse
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

PWA_DIR = Path(__file__).resolve().parent / "pwa"
PREFIXO = "/app"

mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("text/javascript", ".js")


class _PwaFiles(StaticFiles):
    def file_response(self, full_path: Any, stat_result: Any, scope: Scope, status_code: int = 200):
        resp = super().file_response(full_path, stat_result, scope, status_code)
        if Path(full_path).name == "sw.js":
            resp.headers["Cache-Control"] = "no-cache"
            resp.headers["Service-Worker-Allowed"] = PREFIXO + "/"
        return resp


def montar_pwa(app: Any, pwa_dir: Path | None = None) -> None:
    """Monta o PWA em ``/app`` (``/app`` → ``/app/``)."""
    diretorio = PWA_DIR if pwa_dir is None else Path(pwa_dir)

    async def _raiz(_req: Any) -> RedirectResponse:
        return RedirectResponse(PREFIXO + "/", status_code=308)

    app.add_route(PREFIXO, _raiz, methods=["GET", "HEAD"], include_in_schema=False)
    app.mount(PREFIXO, _PwaFiles(directory=diretorio, html=True), name="pwa")
