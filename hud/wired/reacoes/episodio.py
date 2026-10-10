"""Episódio de jogo (spec §7, acordo §5). Dono: V0.6 (esqueleto: V0.1).

FPS e calor = um episódio com histerese; cobranças e recuperação limitadas por partida.
"""

from __future__ import annotations


class Episodio:
    def __init__(self, cfg: dict | None = None) -> None:
        self.cfg = cfg or {}

    def atualizar(self, snap: dict, agora: float) -> str | None:
        """Avança o episódio pelo snapshot; devolve "inicio"/"fim" quando muda, senão ``None``."""
        raise NotImplementedError

    def pode_emitir(self, chave: str, agora: float) -> bool:
        """O ``det_sistema`` pergunta antes de emitir (1º = cena, depois estado; tetos por partida)."""
        raise NotImplementedError

    def game_on(self, agora: float) -> None:
        raise NotImplementedError

    def game_off(self, agora: float) -> str:
        """Relatório pós-batalha: vitória do cockpit, ``eu_avisei`` ou ``desconfiada``."""
        raise NotImplementedError
