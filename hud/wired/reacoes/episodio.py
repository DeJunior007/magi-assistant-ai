"""Episódio de jogo (spec §7, acordo §5). Dono: V0.6 (esqueleto: V0.1).

FPS e calor = **um** episódio: abre no primeiro problema, termina com ``episodio_fim_min`` estáveis;
problema antes de ``episodio_novo_min`` do fim reabre o mesmo (não conta como novo). O 1º episódio
da partida vira cena (a chave antiga ``hot``/``fps_drop`` sai uma vez); os seguintes viram **estado**
(suor + ``stress``, sem cena). Por partida: ≤ ``cobrancas_partida`` cobranças (a cena do episódio,
``eu_avisei``, ``fps_drop:vergonha``) e ≤ ``recuperacoes_partida`` recuperação (``hot:alivio``,
``fps_drop:recuperou``). Os números vêm do ``[vida].jogo``.
"""

from __future__ import annotations

from .vida import VIDA_PADRAO, mesclar

CENA = frozenset({"hot", "fps_drop"})  # chaves antigas: só a 1ª do 1º episódio da partida
COBRANCAS = frozenset({"hot", "fps_drop", "eu_avisei", "fps_drop:vergonha"})
RECUPERACOES = frozenset({"hot:alivio", "fps_drop:recuperou"})


class Episodio:
    def __init__(self, cfg: dict | None = None) -> None:
        cfg = cfg or {}
        self.cfg = mesclar(VIDA_PADRAO["jogo"], cfg.get("jogo", cfg))
        self.fim_s = float(self.cfg["episodio_fim_min"]) * 60.0
        self.novo_s = float(self.cfg["episodio_novo_min"]) * 60.0
        self.aberto = False
        self.estavel_desde: float | None = None
        self.fechou_em: float | None = None
        self._zerar_partida()

    def _zerar_partida(self) -> None:
        self.episodios = 0  # episódios novos nesta partida
        self.cobrancas = 0
        self.recuperacoes = 0
        self.cena_pendente = False
        self.teve_problema = False

    @property
    def estado(self) -> bool:
        """Episódio aberto que já não é cena: o retrato mostra suor + ``stress``."""
        return self.aberto and not self.cena_pendente

    def atualizar(self, snap: dict, agora: float) -> str | None:
        """Avança pelo ``snap`` (``{"quente": bool, "fps_baixo": bool}``).

        Devolve ``"inicio"`` quando abre episódio **novo**, ``"fim"`` quando fecha, senão ``None``.
        """
        problema = bool(snap.get("quente")) or bool(snap.get("fps_baixo"))
        self.teve_problema |= problema
        if self.aberto:
            if problema:
                self.estavel_desde = None
            elif self.estavel_desde is None:
                self.estavel_desde = agora
            elif agora - self.estavel_desde >= self.fim_s:
                self.aberto, self.estavel_desde, self.cena_pendente = False, None, False
                self.fechou_em = agora
                return "fim"
            return None
        if not problema:
            return None
        self.aberto, self.estavel_desde = True, None
        if self.fechou_em is not None and agora - self.fechou_em < self.novo_s:
            return None  # reabre o mesmo episódio: sem cena nova
        self.episodios += 1
        self.cena_pendente = self.episodios == 1
        return "inicio"

    def pode_emitir(self, chave: str, agora: float) -> bool:
        """O ``det_sistema`` pergunta antes de emitir; ``True`` já **gasta** a vez.

        ``chave`` é a chave do catálogo ou ``"chave:variante"``.
        """
        if chave in CENA:
            if not (self.cena_pendente and self.cobrancas < int(self.cfg["cobrancas_partida"])):
                return False
            self.cena_pendente = False
            self.cobrancas += 1
            return True
        if chave in COBRANCAS:
            if self.cobrancas >= int(self.cfg["cobrancas_partida"]):
                return False
            self.cobrancas += 1
            return True
        if chave in RECUPERACOES:
            if self.recuperacoes >= int(self.cfg["recuperacoes_partida"]):
                return False
            self.recuperacoes += 1
            return True
        return True

    def game_on(self, agora: float) -> None:
        """Partida nova ("cockpit", P12): zera os tetos; um episódio aberto segue como estado."""
        self._zerar_partida()

    def game_off(self, agora: float, pedro_mal: bool = False) -> str:
        """Relatório pós-batalha: ``"vitoria"`` (cockpit), ``"eu_avisei"`` ou ``"desconfiada"``."""
        teve = self.teve_problema or self.episodios > 0 or self.cobrancas > 0
        self._zerar_partida()
        if not teve:
            return "vitoria"
        return "desconfiada" if pedro_mal else "eu_avisei"
