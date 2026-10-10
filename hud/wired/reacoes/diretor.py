"""Diretor de cenas (spec §8, acordo §4–§5). Dono: V0.10 (esqueleto: V0.1).

Recebe todos os ``Disparo``, agrupa por causa, escolhe roteiro e ramo, aplica fila e interrupção e
entrega **uma** ``Cena`` ao Reactor. O que não vira cena vira atenção dirigida ou só mexe no humor.

Fluxo: ``receber`` guarda os disparos por ``coalescencia_s`` (nível 1 resolve na hora); ``proxima``
resolve o lote (cada causa vira um *acontecimento*), passa cada um pelo ``Governador`` v2 e devolve a
cena a tocar. As 19 reações antigas (``ANTIGAS``) e as do catálogo entram por aqui também: as de
música viram roteiro, as outras ``ATIVA_SOLTA``. A família de uma cena cala a mesma família por 30 s
(música: 90 s), inclusive as ativas soltas; a mesma causa em < 10 min vira o "de novo?".

Entradas do ``fmt`` do ``Disparo`` (todas opcionais): ``causa`` (o acontecimento: faixa, partida...),
``nota`` (-2..2), ``ado``, ``tocou_s`` (pulo), ``dur_s`` (Claude), ``primeiro``/``recuperou``
(episódio), ``episodios``/``pedro_mal`` (jogo fechou), ``cochilou`` (Pedro voltou), ``fura``.
"""

from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass, replace

from . import catalogo
from .contratos import Classe, Disparo
from .estado import Estado
from .governador import FILA_VALIDADE_S, FURA_TUDO, Governador, Pedido, Tipo
from .vida import VIDA_PADRAO, Cena, Evento, Fone, Momento, mesclar

# 19 antigas (``reactions.REACTIONS``) → (tipo de roteiro ou None = ativa solta, ramo, família)
ANTIGAS: dict[str, tuple[str | None, str | None, str]] = {
    "music_love": ("musica", "2", "musica"), "music_like": ("musica", "1", "musica"),
    "music_new": ("musica", "1", "musica"), "music_ok": ("musica", "0", "musica"),
    "music_meh": ("musica", "-1", "musica"), "music_tolerate": ("musica", "-1", "musica"),
    "music_hate": ("musica", "-2", "musica"), "skips": ("pulo", None, "musica"),
    "game_on": ("jogo_abriu", None, "jogo"), "game_off": ("jogo_fechou", None, "jogo_fim"),
    "hot": ("episodio", None, "jogo"), "fps_drop": ("episodio", None, "jogo"),
    "claude": ("claude_terminou", None, "claude"), "news": (None, None, "noticia"),
    "long_session": (None, None, "tempo"), "cleanup": (None, None, "sistema"),
    "led": (None, None, "hud"), "player": (None, None, "musica"), "card": (None, None, "hud"),
    "main": (None, None, "hud"), "idle": (None, None, "hud"),
}
# disparos de roteiro que os detectores novos (V0.8) emitem pelo nome
ROTEIROS = frozenset({
    "musica_comecou", "faixa_trocou", "pulo", "musica_parou", "pedro_fala", "resposta_fim",
    "jogo_abriu", "episodio", "jogo_fechou", "pedro_voltou", "claude_terminou",
})
FAMILIA_EXTRA = {"pulo": "musica", "resposta_fim": "pedro"}
FURA_DE = {"pedro_fala": "pedro_fala", "pedro_voltou": "pedro_volta"}
CARD = {  # família → card da atenção dirigida (LOOK_DIRS)
    "musica": "player", "musica_fim": "player", "radio": "radio", "claude": "claude",
    "sistema": "fps", "jogo": "fps", "jogo_fim": "fps", "rede": "net", "noticia": "history",
}
FAMILIA_CLASSE = ((Classe.MUSICA, "musica"), (Classe.SISTEMA, "sistema"), (Classe.PEDRO, "pedro"),
                  (Classe.TEMPO, "tempo"))
NEGATIVAS = frozenset({"suspiro", "beicinho", "soprando_franja"})  # acordo §4
EM_JOGO = frozenset({"jogo", "jogo_fim", "pedro"})  # famílias que não são suprimidas em jogo
NOTA_RAMO = {2: "2", 1: "1", 0: "0", -1: "-1", -2: "-2"}
NOTA_NEGATIVA = {"-1": "faixa_nota_menos1"}


@dataclass
class Acontecimento:
    tipo: str | None  # roteiro (``catalogo.CENAS``) ou None = ativa solta
    ramo: str | None
    causa: str
    familia: str
    nivel: int
    chave: str
    fura: str | None = None
    negativa: str | None = None  # causa de negativa que este acontecimento deixa (``ctx["causas"]``)
    so_atencao: bool = False  # notou, mas não vira expressão (episódio repetido, Claude rápido)


class Diretor:
    def __init__(self, estado: Estado, cfg: dict | None = None, rng: random.Random | None = None,
                 governador: Governador | None = None) -> None:
        self.estado = estado
        self.cfg = cfg or {}
        self.vida = mesclar(VIDA_PADRAO, self.cfg)
        self.rng = rng or random.Random()
        self.gov = governador or Governador(self.cfg)
        self.buffer: list[Disparo] = []
        self.janela_fim: float | None = None
        self.atual: tuple[Cena, float] | None = None  # (cena, fim)
        self.fila: tuple[Acontecimento, float] | None = None
        self.prontas: deque[Cena] = deque()
        self.atencoes: deque[str] = deque()
        self.atencao_ms = 0
        self.familias: dict[str, float] = {}  # família → início da última cena/ativa
        self.causas_cena: dict[str, float] = {}  # causa → última cena (o "de novo?")
        self.causas: dict[str, float] = {}  # causas de negativa (``ctx["causas"]`` do governador)
        self.pulos = 0
        self.recolocar_em: float | None = None
        self.tirou_fone = False
        self.truque_em: float | None = None
        self.log: list[tuple[float, str, str]] = []  # (em, tipo, chave/motivo)
        self.ctx: dict = {}

    # -- entrada ----------------------------------------------------------------------------------
    def receber(self, disparos: list[Disparo], agora: float, ctx: dict | None = None) -> None:
        """Coalesce os disparos pela causa (``coalescencia_s``) e absorve a mesma família."""
        if ctx is not None:
            self.ctx = ctx
        for d in disparos:
            if not self.buffer:
                self.janela_fim = agora + self.vida["coalescencia_s"]
            self.buffer.append(d)
            if self._acontecimento(d).nivel == 1:
                self.janela_fim = agora  # fala/volta do Pedro não esperam

    def _ctx_gov(self) -> dict:
        causas = {**(self.ctx.get("causas") or {}), **self.causas}
        return {**self.ctx, "vida": self.vida, "causas": causas, "filtros": self.ctx.get("filtros") or ()}

    def _familia_def(self, chave: str) -> str:
        d = catalogo.DEFS.get(chave)
        if d is None:
            return chave
        return next((f for c, f in FAMILIA_CLASSE if c in d.classes), chave)

    def _acontecimento(self, d: Disparo) -> Acontecimento:
        fmt = d.fmt or {}
        tipo, ramo, familia = ANTIGAS.get(d.chave, (None, None, None))
        if d.chave in ROTEIROS:
            tipo, ramo = d.chave, d.variante
        if familia is None:
            familia = (catalogo.FAMILIA_CENA.get(tipo) or FAMILIA_EXTRA.get(tipo, "") if tipo
                       else self._familia_def(d.chave))
        if tipo in ("musica", "musica_comecou", "faixa_trocou"):
            nota = fmt.get("nota")
            ramo = NOTA_RAMO.get(nota, ramo) if nota is not None else ramo
            if ramo == "2" and fmt.get("ado"):
                ramo = "2_ado"
            if tipo == "musica":
                cabeca = self.estado.postura.fone == Fone.CABECA
                tipo = "faixa_trocou" if cabeca else "musica_comecou"
        so = False
        neg = NOTA_NEGATIVA.get(ramo or "") if tipo in ("musica_comecou", "faixa_trocou") else None
        if tipo == "episodio":
            ramo, neg = ("recuperou" if fmt.get("recuperou") else "cobranca"), "episodio_jogo"
        elif tipo == "jogo_fechou":
            ramo = "pedro_mal" if fmt.get("pedro_mal") else ("episodios" if fmt.get("episodios") else "limpo")
        elif tipo == "pedro_voltou":
            ramo = "cochilou" if fmt.get("cochilou") else "orgulhosa"
        elif tipo == "pedro_fala":
            ramo = "com_fone" if self.estado.postura.fone == Fone.CABECA else "sem_fone"
        elif tipo == "pulo" and float(fmt.get("tocou_s", 0)) >= 30:
            ramo = "longo"
        if tipo == "episodio" and not fmt.get("primeiro", True) and ramo == "cobranca":
            so = True  # 2º em diante: vira estado (suor + stress), só atenção
        if tipo == "claude_terminou" and float(fmt.get("dur_s", 0)) <= 300:
            so = True  # Claude rápido: só atenção
        fura = fmt.get("fura") or FURA_DE.get(tipo or "")
        nivel = 1 if fura in FURA_TUDO else catalogo.NIVEL_CENA.get(tipo or "", 2)
        causa = str(fmt.get("causa") or f"{tipo or d.chave}:{d.motivo}")
        return Acontecimento(tipo, ramo, causa, familia, nivel, d.chave, fura, neg, so)

    # -- saída ------------------------------------------------------------------------------------
    def proxima(self, agora: float, ctx: dict | None = None) -> Cena | None:
        """A cena a tocar agora (interrompe, fila de 1 vaga) ou ``None``."""
        if ctx is not None:
            self.ctx = ctx
        if self.atual and agora >= self.atual[1]:
            self.atual = None
        if self.buffer and self.janela_fim is not None and agora >= self.janela_fim:
            lote, self.buffer, self.janela_fim = self.buffer, [], None
            self._resolver(lote, agora)
        self._pendentes(agora)
        if not self.prontas and self.fila and not self.atual:
            ac, em = self.fila
            if agora - em > FILA_VALIDADE_S:
                self.fila = None
                self._atencao(ac, agora, "fila_obsoleta")
            elif self._motivo(ac, agora) is None:
                self.fila = None
                self._decidir(ac, agora)
        return self.prontas.popleft() if self.prontas else None

    def atencao(self, agora: float) -> str | None:
        """Card para onde olhar (``atencao_ms``) quando o acontecimento não virou cena."""
        if not self.atencoes:
            return None
        lo, hi = self.vida["atencao_ms"]
        self.atencao_ms = self.rng.randint(int(lo), int(hi))
        self.gov.registrar(Pedido(Tipo.ATENCAO, "atencao"), agora)
        return self.atencoes.popleft()

    def tocando(self, agora: float) -> Cena | None:
        return self.atual[0] if self.atual and agora < self.atual[1] else None

    # -- decisão ----------------------------------------------------------------------------------
    def _resolver(self, lote: list[Disparo], agora: float) -> None:
        grupos: dict[str, Acontecimento] = {}
        for d in lote:
            ac = self._acontecimento(d)
            atual = grupos.get(ac.causa)
            if atual is None or (ac.nivel, ac.tipo is None) < (atual.nivel, atual.tipo is None):
                grupos[ac.causa] = ac  # coalescência: uma causa, um acontecimento
        for ac in sorted(grupos.values(), key=lambda a: (a.nivel, a.tipo is None)):
            self._decidir(ac, agora)

    def _janela(self, familia: str) -> float:
        return self.vida["familia_musica_s"] if familia == "musica" else self.vida["familia_absorve_s"]

    def _motivo(self, ac: Acontecimento, agora: float) -> str | None:
        """Regras do diretor + ``Governador``; ``None`` se pode virar cena/expressão."""
        if ac.fura is not None:
            return None
        ult = self.familias.get(ac.familia)
        if ult is not None and agora - ult < self._janela(ac.familia):
            return "mesma_familia"
        if self.ctx.get("momento") == Momento.JOGANDO and ac.familia not in EM_JOGO:
            return "suprimido_em_jogo"
        if self.tocando(agora) is not None:
            return "tocando"
        tipo = Tipo.CENA if ac.tipo else Tipo.ATIVA_SOLTA
        return self.gov.motivo(self._pedido(ac, tipo), agora, self._ctx_gov())

    def _pedido(self, ac: Acontecimento, tipo: Tipo) -> Pedido:
        return Pedido(tipo, ac.tipo or ac.chave, familia=ac.familia, fura=ac.fura,
                      truque=ac.tipo == "truque")

    def _decidir(self, ac: Acontecimento, agora: float) -> None:
        if ac.negativa:
            self.causas[ac.negativa] = agora
        if ac.chave == "resposta_fim":
            if self.tirou_fone:
                self.recolocar_em = agora + self.vida["pedro_fala_recoloca_fone_s"]
            return
        if ac.so_atencao:
            self._atencao(ac, agora, "so_atencao")
            return
        if ac.tipo == "pulo":
            if (ac_pulo := self._pulo(ac)) is None:
                self._atencao(ac, agora, "pulo")
                return
            ac = ac_pulo
        motivo = self._motivo(ac, agora)
        if motivo is None and ac.tipo and ac.fura is None:
            ult = self.causas_cena.get(ac.causa)
            if ult is not None and agora - ult < self.vida["de_novo_min"] * 60:
                ac = replace(ac, tipo="de_novo", ramo=None, familia="de_novo", nivel=3)
        if motivo is None:
            self._tocar(ac, agora)
        elif ac.tipo and ac.nivel == 2 and motivo in ("tocando", "min_entre_expressoes",
                                                      "pausa_apos_cena"):
            if self.fila is not None:
                self._atencao(self.fila[0], agora, "fila_obsoleta")
            self.fila = (ac, agora)
        else:
            self._atencao(ac, agora, motivo)

    def _pulo(self, ac: Acontecimento) -> Acontecimento | None:
        """Pulo < 30 s não vira cena; 3 seguidos viram **uma** (``impaciente``)."""
        if ac.ramo == "longo":
            self.pulos = 0
            return None
        self.pulos += 1
        if self.pulos < 3:
            return None
        self.pulos = 0
        return replace(ac, tipo="impaciente", ramo=None)

    def _atencao(self, ac: Acontecimento, agora: float, motivo: str) -> None:
        self.log.append((agora, "atencao", f"{ac.tipo or ac.chave}:{motivo}"))
        card = CARD.get(ac.familia)
        if card and (not self.atencoes or self.atencoes[-1] != card):
            self.atencoes.append(card)

    def _tocar(self, ac: Acontecimento, agora: float) -> None:
        cena = self._cena(ac)
        if cena is None:
            self._atencao(ac, agora, "sem_roteiro")
            return
        tipo = Tipo.CENA if ac.tipo else Tipo.ATIVA_SOLTA
        if ac.tipo == "recoloca_fone":
            tipo = Tipo.CORPO
        interrompida = self.tocando(agora)
        if interrompida is not None:  # nível 1: sai por B1 C1 200 e não recomeça
            cena.passos = catalogo.SAIDA + cena.passos
            self.log.append((agora, "interrompida", interrompida.tipo))
        self.gov.registrar(self._pedido(ac, tipo), agora)
        self.familias[ac.familia] = agora
        if ac.tipo:
            self.causas_cena[ac.causa] = agora
        self._fone(cena)
        if ac.tipo == "pedro_fala":
            self.tirou_fone = cena.ramo == "com_fone" or self.tirou_fone
        if ac.tipo == "pedro_voltou":
            self.fila = None
        if ac.tipo == "truque":
            self.truque_em = agora
        self.atual = (cena, agora + sum(p.ms for p in cena.passos) / 1000)
        self.log.append((agora, str(tipo), f"{cena.tipo}:{cena.ramo}"))
        self.prontas.append(cena)

    def _cena(self, ac: Acontecimento) -> Cena | None:
        if ac.tipo is None:
            d = catalogo.DEFS.get(ac.chave)
            if d is None:
                return None
            return Cena(ac.chave, None, ac.causa, d.passos, ac.nivel)
        d = catalogo.CENAS.get((ac.tipo, ac.ramo)) or catalogo.CENAS.get((ac.tipo, None))
        if d is None:
            return None
        passos = d.passos
        if (ac.tipo, ac.ramo) == ("musica_comecou", "-1"):  # a chance vem do [vida]
            chance = int(self.vida["musica_nota_menos1_chance_s"] * 1000)
            passos = (passos[0], replace(passos[1], ms=chance), *passos[2:])
        return Cena(ac.tipo, ac.ramo, ac.causa, passos, ac.nivel)

    def _fone(self, cena: Cena) -> None:
        """Troca de fone atômica: a postura muda com a cena inteira, nunca pela metade."""
        fone = None
        for p in cena.passos:
            if "fone_on" in p.corpo:
                fone = Fone.CABECA
            elif "fone_off" in p.corpo:
                fone = Fone.PESCOCO
        if fone is not None:
            self.estado.postura.fone = fone
            self.estado.postura.motivo = cena.tipo

    def _pendentes(self, agora: float) -> None:
        if self.recolocar_em is not None and agora >= self.recolocar_em:
            self.recolocar_em, self.tirou_fone = None, False
            if self.ctx.get("musica") and self.estado.postura.fone == Fone.PESCOCO:
                ac = Acontecimento("recoloca_fone", None, "recoloca_fone", "fone", 3, "recoloca_fone")
                if self.tocando(agora) is None:
                    self._tocar(ac, agora)
        if self.truque_em is not None and agora - self.truque_em > self.vida["truque_aplauso_s"]:
            self.truque_em = None
            self.causas["truque_ignorado"] = agora
            self.estado.humor.aplicar(Evento("truque_ignorado", "pedro", agora), agora)
            d = catalogo.CENAS[("truque", "ignorado")]  # continuação da cena: beicinho curto
            self.prontas.append(Cena("truque", "ignorado", "truque", d.passos, 3))

    # -- truque de salão e passivas --------------------------------------------------------------
    def truque(self, agora: float, ctx: dict | None = None) -> Cena | None:
        """≤ 1/dia, só em À toa/Tédio, com o Pedro ativo (inatividade < 60 s)."""
        if ctx is not None:
            self.ctx = ctx
        if self.ctx.get("momento") not in (Momento.A_TOA, Momento.TEDIO):
            return None
        if float(self.ctx.get("inatividade_s", 1e9)) >= 60 or self.truque_em is not None:
            return None
        ac = Acontecimento("truque", None, "truque", "truque", 2, "truque")
        if self._motivo(ac, agora) is not None:
            return None
        self._tocar(ac, agora)
        return self.prontas.popleft()

    def clique(self, agora: float) -> bool:
        """Clique no rosto: dentro de ``truque_aplauso_s`` do truque é aplauso (+0,20)."""
        if self.truque_em is None or agora - self.truque_em > self.vida["truque_aplauso_s"]:
            return False
        self.truque_em = None
        self.estado.humor.aplicar(Evento("truque_aplauso", "pedro", agora), agora)
        return True

    def sortear_passiva(self, chaves: list[str], agora: float, ctx: dict | None = None) -> str | None:
        """Sorteia por ``Governador.peso`` entre as que o governador deixa (negativas com causa)."""
        if ctx is not None:
            self.ctx = ctx
        cg = self._ctx_gov()
        if self.tocando(agora) is not None:
            return None
        ok = [k for k in chaves
              if self.gov.pode(Pedido(Tipo.GESTO, k, negativa=k in NEGATIVAS), agora, cg)]
        if not ok:
            return None
        k = self.rng.choices(ok, weights=[self.gov.peso(k, agora) for k in ok])[0]
        self.gov.registrar(Pedido(Tipo.GESTO, k, negativa=k in NEGATIVAS), agora)
        return k
