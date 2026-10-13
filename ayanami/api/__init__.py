"""API da Ayanami (dono: Y2.1; spec §2).

``uvicorn ayanami.api:app`` (Compose): ``app`` é criado só quando pedido (``__getattr__``), lendo
a config e abrindo o pool; importar o pacote não toca em config nem banco. Nos testes use
:func:`ayanami.api.app.criar_app`.
"""

from __future__ import annotations

from typing import Any

_app: Any = None


def __getattr__(nome: str) -> Any:
    global _app
    if nome == "app":
        if _app is None:
            from ayanami.api.app import app_de_producao

            _app = app_de_producao()
        return _app
    raise AttributeError(f"module 'ayanami.api' has no attribute {nome!r}")
