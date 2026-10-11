"""Leitura em curso (tarefa A2.2; design §3–§4, requirements A5, A6.2, A8).

``partes()`` gera ``(texto, OpcoesVoz)`` frase a frase: regras sempre, marcas do Qwen quando o
cache do capítulo já existe (nunca espera), voz pelo ``Elenco``. Cache de PCM dos 3 últimos
parágrafos; ``interrompida()`` pausa na frase em curso.

Posição: o gerador corre à frente (o ``say_parts`` pré-sintetiza), então a posição que vale é a
da parte que **começou a tocar**: o ``TurnMachine`` chama ``tocando(i)`` no ``on_sentence``
(índice ``i`` = i-ésima parte não vazia deste ``partes()``), e ela vai ao ``Marcador`` (A5).
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from typing import Any, Literal

from magi.audiolivro import vozes
from magi.audiolivro.config import ConfigAudiolivro
from magi.audiolivro.contratos import Capitulo, Livro, OpcoesVoz, Posicao, Trecho
from magi.audiolivro.marcador import Marcador
from magi.audiolivro.marcas import marcar_capitulo

log = logging.getLogger(__name__)

Estado = Literal["lendo", "pausada", "parada"]

#: Silêncio entre parágrafos (ms), além das pausas de emoção/troca de voz.
PAUSA_PARAGRAFO = 350
#: Parágrafos com PCM guardado (voltar/repetir sem ressintetizar, design §4).
PARAGRAFOS_CACHE = 3
PASSO_VELOCIDADE = 0.1
FATOR_MIN, FATOR_MAX = 0.8, 1.25  # "mais devagar/rápido" (design §4)


def _fator(v: float) -> float:
    return round(min(FATOR_MAX, max(FATOR_MIN, v)), 3)


def _extrair(livro: Livro, n: int) -> Capitulo:
    return livro.capitulo(n)


class _CachePcm:
    """Embrulha o TTS do livro: guarda o PCM das partes dos últimos ``PARAGRAFOS_CACHE``
    parágrafos lidos (chave: opções + texto). ``com_opcoes`` devolve outra visão do mesmo cache."""

    def __init__(
        self,
        base: Any,
        leitura: Leitura,
        store: OrderedDict[tuple[int, int], dict[tuple[Any, str], bytes]] | None = None,
        chave: tuple[Any, ...] = (),
    ) -> None:
        self._base = base
        self._leitura = leitura
        self._store = store if store is not None else OrderedDict()
        self._chave = chave

    def __getattr__(self, nome: str) -> Any:
        return getattr(self._base, nome)

    def com_opcoes(self, **over: Any) -> _CachePcm:
        make = getattr(self._base, "com_opcoes", None)
        base = make(**over) if make is not None else self._base
        chave = tuple(sorted((k, repr(v)) for k, v in over.items()))
        return _CachePcm(base, self._leitura, self._store, chave)

    def limpar(self) -> None:
        self._store.clear()

    async def synthesize(self, text: Any, *, personal: bool) -> AsyncIterator[bytes]:
        par = self._leitura._gerando  # parágrafo da parte que o say_parts acabou de puxar
        chave = (self._chave, text) if isinstance(text, str) else None
        if chave is not None and par is not None:
            feito = self._store.get(par, {}).get(chave)
            if feito is not None:
                self._store.move_to_end(par)
                yield feito
                return
        buf = bytearray()
        async for pcm in self._base.synthesize(text, personal=personal):
            buf += pcm
            yield pcm
        if chave is not None and par is not None:
            self._store.setdefault(par, {})[chave] = bytes(buf)
            self._store.move_to_end(par)
            while len(self._store) > PARAGRAFOS_CACHE:
                self._store.popitem(last=False)


class Leitura:
    """Uma leitura (um livro aberto). ``tts``: o TTS Kokoro do livro (``registry.tts_livro()``),
    já embrulhado pelo cache de PCM — é o ``provider`` do ``say_parts``. ``refino``: o
    ``RefinoQwen`` (A1.3) ou ``None`` (só regras). Relógio e extração injetáveis (testes)."""

    def __init__(
        self,
        cfg: ConfigAudiolivro,
        marcador: Marcador,
        *,
        voz_dela: str,
        idioma_dela: str,
        tts: Any = None,
        refino: Any = None,
        extrair: Callable[[Livro, int], Capitulo] = _extrair,
        relogio: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cfg = cfg
        self.marcador = marcador
        self.voz_dela = voz_dela
        self.idioma_dela = idioma_dela
        self.refino = refino
        self.extrair = extrair
        self.relogio = relogio
        self.tts = _CachePcm(tts, self) if tts is not None else None
        self.livro: Livro | None = None
        self.elenco: vozes.Elenco | None = None
        self.posicao = Posicao(0, 0, 0)
        self._estado: Estado = "parada"
        self._pausada_em: float | None = None
        self._fila: list[Posicao] = []
        self._gerando: tuple[int, int] | None = None
        self._marcas: dict[int, tuple[bool, list[list[Trecho]]]] = {}

    # -- estado ---------------------------------------------------------------------------------

    @property
    def estado(self) -> Estado:
        """``pausada`` há mais de ``pausa_expira_min`` vira ``parada`` (o marcador fica)."""
        if self._estado == "pausada" and self._pausada_em is not None:
            if self.relogio() - self._pausada_em > self.cfg.pausa_expira_min * 60:
                self._estado = "parada"
        return self._estado

    def _pausar(self) -> None:
        self._estado = "pausada"
        self._pausada_em = self.relogio()

    def _gravar(self, *, forcar: bool = False) -> None:
        if self.livro is not None:
            self.marcador.avancar(self.livro.id, self.posicao, forcar=forcar)

    # -- abrir ----------------------------------------------------------------------------------

    def abrir(self, livro: Livro, posicao: Posicao | None = None) -> None:
        """Abre ``livro`` em ``posicao`` (ou no marcador, ou no início) e fica ``pausada``."""
        self.livro = livro
        pos = posicao or self.marcador.posicao(livro.id) or Posicao(0, 0, 0)
        cap = min(max(0, pos.cap), max(0, livro.capitulos - 1))
        self.posicao = replace(pos, cap=cap, velocidade=_fator(pos.velocidade))
        self.elenco = vozes.Elenco(livro.id, self.voz_dela, self.idioma_dela, self.cfg)
        self._marcas.clear()
        if self.tts is not None:
            self.tts.limpar()
        self._pausar()

    # -- marcação --------------------------------------------------------------------------------

    def _trechos(self, capitulo: Capitulo) -> list[list[Trecho]]:
        """Marcas do Qwen se o cache já existe (nunca espera); senão regras (D2)."""
        assert self.livro is not None
        n = capitulo.n
        guardado = self._marcas.get(n)
        if guardado is not None and guardado[0]:
            return guardado[1]
        if self.refino is not None:
            pronto = self.refino.pronto(self.livro, n)
            if pronto is not None:
                self._marcas[n] = (True, pronto)
                return pronto
        if guardado is None:
            guardado = (False, marcar_capitulo(capitulo.paragrafos, self.livro.idioma))
            self._marcas[n] = guardado
        return guardado[1]

    def _adiantar(self, capitulo: Capitulo) -> None:
        """Refino A1.3 do capítulo atual e do próximo, em segundo plano."""
        if self.refino is None or self.cfg.marcacao != "qwen" or self.livro is None:
            return
        livro = self.livro
        for n in (capitulo.n, capitulo.n + 1):
            if n >= livro.capitulos:
                break
            try:
                cap = capitulo if n == capitulo.n else self.extrair(livro, n)
                self.refino.adiantar(livro, cap, self._trechos(cap))
            except Exception as e:  # noqa: BLE001 — refino é opcional: segue nas regras
                log.warning("audiolivro: refino do cap. %d não agendado (%s)", n, e)

    # -- leitura ---------------------------------------------------------------------------------

    async def partes(self) -> AsyncIterator[tuple[str, OpcoesVoz]]:
        """Partes da posição atual em diante, até o fim do livro ou ``parar_apos_capitulos``."""
        if self.livro is None or self.elenco is None:
            return
        livro, elenco = self.livro, self.elenco
        self._estado, self._pausada_em = "lendo", None
        self._fila = []
        inicio = self.posicao
        cap_n, lidos = inicio.cap, 0
        try:
            while cap_n < livro.capitulos:
                capitulo = await asyncio.to_thread(self.extrair, livro, cap_n)
                trechos = self._trechos(capitulo)
                self._adiantar(capitulo)
                primeiro = cap_n == inicio.cap
                for par in range(inicio.par if primeiro else 0, len(trechos)):
                    lista = [
                        t
                        for t in trechos[par]
                        if t.texto.strip() and not (primeiro and par == inicio.par and t.frase < inicio.frase)
                    ]
                    for k, t in enumerate(lista):
                        op = vozes.opcoes(t, elenco, self.posicao.velocidade)
                        if k + 1 < len(lista):
                            prox = vozes.opcoes(lista[k + 1], elenco, self.posicao.velocidade)
                            if op.pausa_ms == 0 and op.voice != prox.voice:
                                op = replace(op, pausa_ms=vozes.PAUSA_TROCA_VOZ)
                        else:
                            op = replace(op, pausa_ms=max(op.pausa_ms, PAUSA_PARAGRAFO))
                        self._fila.append(Posicao(cap_n, par, t.frase, self.posicao.velocidade))
                        self._gerando = (cap_n, par)
                        yield t.texto, op
                lidos += 1
                cap_n += 1
                if self.cfg.parar_apos_capitulos and lidos >= self.cfg.parar_apos_capitulos:
                    break
        finally:
            self._gerando = None
        # Chegou ao fim sem interrupção: fim do livro = parada (marcador na última parte);
        # ``parar_apos_capitulos`` = pausada no começo do capítulo seguinte.
        if self._estado == "lendo":
            if cap_n >= livro.capitulos:
                self._estado = "parada"
                self._gravar(forcar=True)
            else:
                self._mover(cap_n, 0)
                self._pausar()

    def tocando(self, i: int) -> None:
        """A parte ``i`` deste ``partes()`` começou a tocar: vira a posição (marcador, A5)."""
        if 0 <= i < len(self._fila):
            self.posicao = replace(self._fila[i], velocidade=self.posicao.velocidade)
            self._gravar()

    def interrompida(self) -> None:
        """Ativação/call no meio: pausa na frase em curso (A6.2) e grava já."""
        if self._estado == "lendo":
            self._pausar()
            self._gravar(forcar=True)

    # -- comandos --------------------------------------------------------------------------------

    def _paragrafos(self, cap: int) -> int:
        assert self.livro is not None
        return len(self.extrair(self.livro, cap).paragrafos)

    def _mover(self, cap: int, par: int) -> None:
        self.posicao = Posicao(cap, par, 0, self.posicao.velocidade)
        self._gravar(forcar=True)
        if self._estado == "parada":
            self._pausar()

    def voltar(self, n: int = 1) -> None:
        """Volta ``n`` parágrafos (0 = repete o atual), frase 0; atravessa capítulos."""
        if self.livro is None:
            return
        cap, par = self.posicao.cap, self.posicao.par - max(0, n)
        while par < 0 and cap > 0:
            cap -= 1
            par += self._paragrafos(cap)
        self._mover(cap, max(0, par))

    def pular(self, n: int = 1) -> None:
        """Avança ``n`` parágrafos, frase 0; atravessa capítulos (para no último)."""
        if self.livro is None:
            return
        cap, par = self.posicao.cap, self.posicao.par + max(0, n)
        while cap < self.livro.capitulos - 1 and par >= (total := self._paragrafos(cap)):
            par -= total
            cap += 1
        self._mover(cap, min(par, max(0, self._paragrafos(cap) - 1)))

    def capitulo(self, *, delta: int | None = None, n: int | None = None) -> None:
        """Vai ao capítulo ``n`` (0 = primeiro) ou ``atual + delta``; começa nele."""
        if self.livro is None:
            return
        alvo = n if n is not None else self.posicao.cap + (delta or 0)
        self._mover(min(max(0, alvo), self.livro.capitulos - 1), 0)

    def velocidade(self, delta: float) -> float:
        """Muda o fator (0,8–1,25, passo 0,1); vale da próxima parte gerada em diante."""
        v = _fator(self.posicao.velocidade + delta)
        self.posicao = replace(self.posicao, velocidade=v)
        self._gravar(forcar=True)
        return v
