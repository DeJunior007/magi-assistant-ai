"""Avisos da Ayanami na proatividade (ayanami-central Y6.6, design §12, R9.2).

O ``sink`` novo da proatividade para o que vem da nuvem: ``AvisosAyanami`` não tem fila própria,
entrega tudo pelo ``ProactiveSink`` do núcleo, então as regras de silêncio/jogo são as mesmas dos
avisos locais (call no Discord ou sem satélite → só tela; fala só com o satélite dormindo e livre;
espera demais → legenda). Os cards usam o ``CardMsg`` que o HUD já conhece.

- ``evento(tipo, titulo, resumo, proativo)``: um ``Evento`` do elo (``magi.elo.eventos_pc``).
  Cards: "Pesquisa pronta: …", "Celular conectado…" (o título vem da Ayanami), notícia bomba etc.
  ``proativo=False`` → só o card, sem fala.
- ``pergunta(descricao, offer)``: ``confirma`` vindo da Ayanami, pela pergunta proativa
  (``Offer``) que a sugestão de música já usa: "sim" → ``accept``, "não" → ``decline``.
- ``codigo_pareamento(codigo)``: card "Código de pareamento 123 456" (``magi.elo.parear``), só na
  tela, sem fala (o código não vai a log nem a legenda).
- ``AvisoBackup``: card "backup não subiu" lendo ``<data_dir>/backup_state.json`` do
  ``magi-backup`` (pedido da Y4.1), uma vez por ``quando``.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from pathlib import Path
from typing import Any

from magi.common.contracts import CardLevel, CardMsg, Expression
from magi.core.proactive.sink import Offer, Outcome, Priority, ProactiveSink

log = logging.getLogger(__name__)

KIND = "ayanami"
BACKUP_STATE_FILE = "backup_state.json"  # = magi.elo.backup.STATE_FILE (Y4.1)

# tipo do Evento (spec §1.2) → (prefixo do card, nível, prioridade, expressão)
_TIPOS: dict[str, tuple[str, CardLevel, Priority, Expression | None]] = {
    "tarefa_pronta": ("Pesquisa pronta", CardLevel.NORMAL, Priority.VOICE, Expression.HAPPY),
    "tarefa_falhou": ("Tarefa falhou", CardLevel.ALTA, Priority.VOICE, Expression.CONFUSED),
    "monitor": ("", CardLevel.ALTA, Priority.VOICE, Expression.ALERT),
    "lembrete": ("Lembrete", CardLevel.ALTA, Priority.VOICE, Expression.ALERT),
    "noticia_bomba": ("Notícia bomba", CardLevel.BOMBA, Priority.VOICE, Expression.ALERT),
    "backup_falhou": ("Backup não subiu", CardLevel.ALTA, Priority.VOICE, Expression.ALERT),
    # a pergunta em si chega pelo ``confirma``: aqui só o card, para não falar duas vezes
    "confirmacao": ("", CardLevel.ALTA, Priority.SCREEN, None),
    "dispositivo": ("", CardLevel.NORMAL, Priority.SCREEN, Expression.HAPPY),
}
_PADRAO = ("", CardLevel.NORMAL, Priority.SCREEN, None)


def _com_prefixo(prefixo: str, titulo: str) -> str:
    titulo = titulo.strip()
    if not prefixo or titulo.casefold().startswith(prefixo.casefold()):
        return titulo
    return f"{prefixo}: {titulo}" if titulo else prefixo


def formatar_codigo(codigo: str) -> str:
    """``"482913"`` → ``"482 913"`` (leitura no HUD)."""
    c = codigo.strip()
    return f"{c[:3]} {c[3:]}" if len(c) == 6 and c.isdigit() else c


class AvisosAyanami:
    """Entrada da Ayanami na proatividade. ``sink`` = ``Core.proactive`` (``None`` → descarta)."""

    def __init__(self, sink: ProactiveSink | None) -> None:
        self.sink = sink

    async def evento(
        self, tipo: str, titulo: str, resumo: str = "", *, proativo: bool = True
    ) -> Outcome | None:
        if self.sink is None:
            return None
        prefixo, nivel, prioridade, expr = _TIPOS.get(str(tipo), _PADRAO)
        texto = _com_prefixo(prefixo, titulo)
        if not texto:
            return None
        card = CardMsg(nivel, texto)
        if not proativo:
            prioridade, fala = Priority.SCREEN, ""
        else:
            fala = texto if prioridade is Priority.VOICE else ""
        log.info("ayanami: evento %s (%s)", tipo, prioridade)
        return await self.sink.deliver(f"{KIND}:{tipo}", fala, card, prioridade, expression=expr)

    async def pergunta(self, descricao: str, offer: Offer) -> Outcome | None:
        """Pergunta de confirmação: "Confirma: desligar a TV da sala?" com escuta do sim/não."""
        if self.sink is None:
            return None
        desc = descricao.strip().rstrip("?.!") or "o pedido da Ayanami"
        fala = f"Confirma {desc}?"
        card = CardMsg(CardLevel.ALTA, f"Confirmar: {desc}")
        return await self.sink.deliver(f"{KIND}:confirma", fala, card, Priority.VOICE,
                                       expression=Expression.ALERT, offer=offer)

    async def codigo_pareamento(self, codigo: str) -> Outcome | None:
        if self.sink is None:
            return None
        card = CardMsg(CardLevel.ALTA, f"Código de pareamento {formatar_codigo(codigo)}")
        log.info("ayanami: card de pareamento mostrado")  # nunca o código
        return await self.sink.deliver(f"{KIND}:pareamento", "", card, Priority.SCREEN)


class AvisoBackup:
    """Card "backup não subiu" (Y4.1): ``backup_state.json`` com ``resultado == "falhou"``, uma vez
    por ``quando`` (marca ``avisado`` no próprio arquivo, como o ``check_cleanup`` faz)."""

    def __init__(self, avisos: AvisosAyanami, path: Path | None) -> None:
        self.avisos = avisos
        self.path = path

    @classmethod
    def de_core(cls, core: Any, avisos: AvisosAyanami) -> AvisoBackup:
        """O ``Core`` não guarda a ``Config``: ela vem de ``_brain_args[0]`` (``assemble``)."""
        data_dir = None
        with contextlib.suppress(Exception):
            data_dir = core._brain_args[0].paths.data_dir
        return cls(avisos, Path(data_dir) / BACKUP_STATE_FILE if data_dir else None)

    async def checar(self) -> bool:
        """``True`` se entregou o card agora."""
        path = self.path
        if path is None or not path.is_file():
            return False
        try:
            dado = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if not isinstance(dado, dict) or dado.get("resultado") != "falhou":
            return False
        quando = str(dado.get("quando") or "")
        if dado.get("avisado") == quando:
            return False
        dado["avisado"] = quando
        with contextlib.suppress(OSError):
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(dado, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)
        data = str(dado.get("data") or "").strip()
        titulo = "Backup não subiu para a Ayanami" + (f" ({data})" if data else "")
        await self.avisos.evento("backup_falhou", titulo)
        return True
