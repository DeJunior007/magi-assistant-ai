"""O que os jobs da fila recebem (dono: Y3.1 → Y6.1; spec §4, design §4.3).

O worker monta um :class:`Deps` e o passa ao ``procrastinate`` em
``run_worker_async(additional_context={"deps": deps})``; cada tarefa registrada em
:mod:`ayanami.fila` o tira de ``context.additional_context`` e chama o corpo como
``corpo(deps, contexto, **kwargs_do_job)``. Os testes montam um ``Deps`` com banco de teste,
relógio falso e falsos para o resto.

- ``registry``: provedores de LLM/STT/TTS (Y3.4/Y6.1); ``None`` até o dono ligar.
- ``budget``: gasto/teto da nuvem (Y6.1); ``None`` = sem controle de gasto ligado.
- ``hub``: quem empurra eventos às conexões vivas (Y2.2); no worker é ``None`` (o aviso vai por
  ``NOTIFY ayanami_eventos`` e a API empurra).
- ``dados``: raiz dos dados no contêiner (``/dados``: ``entrada/``, ``tmp/``, ``modelos/``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ayanami.config import AyanamiConfig
from ayanami.db import Db
from ayanami.relogio import Relogio, RelogioReal

DADOS_PADRAO = Path("/dados")


@dataclass
class Deps:
    db: Db
    cfg: AyanamiConfig
    relogio: Relogio = field(default_factory=RelogioReal)
    registry: Any = None
    budget: Any = None
    hub: Any = None
    dados: Path = DADOS_PADRAO
    extras: dict[str, Any] = field(default_factory=dict)
