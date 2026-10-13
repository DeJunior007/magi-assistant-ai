"""Corpos das tarefas da fila (dono: Y3.1; spec §4.2, §5).

Um módulo por área; :mod:`ayanami.fila` importa cada corpo só quando o job roda. Contrato:
``async def corpo(deps: Deps, contexto: JobContext, **kwargs) -> dict | None`` (ver
:mod:`ayanami.fila`). Os stubs levantam ``NotImplementedError`` com "dono: <ID>".
"""
