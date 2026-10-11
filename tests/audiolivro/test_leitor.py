"""``Leitura`` (A2.2): partes frase a frase, marcador, Qwen sem esperar, comandos, cache de PCM."""

from __future__ import annotations

import asyncio
import dataclasses
from pathlib import Path
from typing import Any

import pytest

from magi.audiolivro import leitor as lt
from magi.audiolivro.config import ConfigAudiolivro
from magi.audiolivro.contratos import Capitulo, Livro, OpcoesVoz, Paragrafo, Posicao, Tipo, Trecho
from magi.audiolivro.marcador import Marcador

VOZ = "pf_dora"
CAPS = [
    Capitulo(0, "Um", (Paragrafo(0, ("Era uma vez.", "O sol nasceu.")), Paragrafo(1, ("Fim do dia.",))), 1.0),
    Capitulo(1, "Dois", (Paragrafo(0, ("Ana olhou.", "Choveu.")),), 1.0),
    Capitulo(2, "Três", (Paragrafo(0, ("Último.",)), Paragrafo(1, ("Mesmo.",))), 1.0),
]


class Relogio:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class RefinoLento:
    """Qwen falso: ``adiantar`` agenda e nunca termina; só o cap. ``prontos`` tem cache."""

    def __init__(self, prontos: dict[int, list[list[Trecho]]]) -> None:
        self.prontos = prontos
        self.agendados: list[int] = []
        self.tarefas: list[asyncio.Task[Any]] = []

    def pronto(self, livro: Livro, cap: int) -> list[list[Trecho]] | None:
        return self.prontos.get(cap)

    def adiantar(self, livro: Livro, capitulo: Capitulo, trechos: list[list[Trecho]]) -> asyncio.Task[Any]:
        self.agendados.append(capitulo.n)
        t = asyncio.create_task(asyncio.Event().wait())
        self.tarefas.append(t)
        return t


class TtsFalso:
    output_format = "pcm"

    def __init__(self) -> None:
        self.sintetizados: list[tuple[str, dict[str, Any]]] = []
        self.over: dict[str, Any] = {}

    def com_opcoes(self, **over: Any) -> TtsFalso:
        novo = TtsFalso()
        novo.sintetizados, novo.over = self.sintetizados, over
        return novo

    async def synthesize(self, text: str, *, personal: bool) -> Any:
        self.sintetizados.append((text, self.over))
        yield text.encode()


@pytest.fixture
def cfg(tmp_path: Path) -> ConfigAudiolivro:
    return ConfigAudiolivro(
        pasta=tmp_path / "Livros", estado_dir=tmp_path / "estado", cache_dir=tmp_path / "cache"
    )


@pytest.fixture
def livro(tmp_path: Path) -> Livro:
    return Livro("abc123", tmp_path / "x.epub", "Duna", None, "pt-br", "epub", len(CAPS), 100)


def _leitura(cfg: ConfigAudiolivro, **kw: Any) -> lt.Leitura:
    kw.setdefault("relogio", Relogio())
    return lt.Leitura(
        cfg,
        Marcador(cfg, relogio=kw["relogio"]),
        voz_dela=VOZ,
        idioma_dela="pt-br",
        extrair=lambda _l, n: CAPS[n],
        **kw,
    )


async def _todas(leitura: lt.Leitura, tocar: bool = True) -> list[tuple[str, OpcoesVoz]]:
    out = []
    async for texto, op in leitura.partes():
        if tocar:
            leitura.tocando(len(out))
        out.append((texto, op))
    return out


async def test_partes_frase_a_frase_com_texto_intacto_e_marcador(cfg, livro) -> None:
    lei = _leitura(cfg)
    lei.abrir(livro)
    assert lei.estado == "pausada"
    partes = await _todas(lei)
    assert [t for t, _ in partes] == [f for c in CAPS for p in c.paragrafos for f in p.frases]  # A9
    assert all(op.voice == VOZ and op.lang == "pt-br" for _, op in partes)
    assert partes[1][1].pausa_ms >= lt.PAUSA_PARAGRAFO  # fim do parágrafo
    assert lei.estado == "parada" and lei.posicao == Posicao(2, 1, 0, 1.0)
    assert Marcador(cfg).posicao(livro.id) == Posicao(2, 1, 0, 1.0)


async def test_abre_no_marcador_e_retoma_na_frase(cfg, livro) -> None:
    Marcador(cfg).avancar(livro.id, Posicao(0, 0, 1, 1.1), forcar=True)
    lei = _leitura(cfg)
    lei.abrir(livro)
    partes = await _todas(lei, tocar=False)
    assert partes[0][0] == "O sol nasceu."
    assert lei.posicao.velocidade == 1.1


async def test_qwen_lento_comeca_nas_regras_e_troca_no_capitulo_com_cache(cfg, livro) -> None:
    refinado = [
        [
            Trecho("Ana olhou.", Tipo.FALA, falante="Ana", genero="f", par=0, frase=0),
            Trecho("Choveu.", par=0, frase=1),
        ]
    ]
    refino = RefinoLento({1: refinado})
    lei = _leitura(cfg, refino=refino)
    lei.abrir(livro)
    partes = await asyncio.wait_for(_todas(lei), 1)  # nunca espera o Qwen
    vozes_ = {t: op.voice for t, op in partes}
    assert vozes_["Era uma vez."] == VOZ  # regras
    assert vozes_["Ana olhou."] != VOZ and vozes_["Choveu."] == VOZ  # marcas do Qwen (cache)
    assert refino.agendados[:2] == [0, 1]  # atual + próximo
    assert all(not t.done() for t in refino.tarefas)
    for t in refino.tarefas:
        t.cancel()


async def test_interrompida_pausa_na_frase_tocando_e_expira(cfg, livro) -> None:
    relogio = Relogio()
    lei = _leitura(cfg, relogio=relogio)
    lei.abrir(livro)
    gen = lei.partes()
    for _ in range(3):
        await gen.__anext__()
    lei.tocando(1)  # o say_parts pré-sintetiza: a 3ª saiu, mas a 2ª é a que toca
    lei.interrompida()
    await gen.aclose()
    assert lei.estado == "pausada" and lei.posicao == Posicao(0, 0, 1, 1.0)
    assert Marcador(cfg).posicao(livro.id) == Posicao(0, 0, 1, 1.0)
    relogio.t += cfg.pausa_expira_min * 60 + 1
    assert lei.estado == "parada"


async def test_comandos_de_posicao_e_velocidade(cfg, livro) -> None:
    lei = _leitura(cfg)
    lei.abrir(livro, Posicao(1, 0, 1))
    lei.voltar()
    assert (lei.posicao.cap, lei.posicao.par, lei.posicao.frase) == (0, 1, 0)
    lei.voltar(0)
    assert (lei.posicao.cap, lei.posicao.par) == (0, 1)
    lei.pular(2)
    assert (lei.posicao.cap, lei.posicao.par) == (2, 0)
    lei.pular(9)
    assert (lei.posicao.cap, lei.posicao.par) == (2, 1)
    lei.capitulo(delta=-1)
    assert (lei.posicao.cap, lei.posicao.par) == (1, 0)
    lei.capitulo(n=0)
    assert lei.posicao.cap == 0
    assert lei.velocidade(-0.1) == 0.9
    assert lei.velocidade(-0.5) == lt.FATOR_MIN
    assert lei.velocidade(+1) == lt.FATOR_MAX
    partes = await _todas(lei, tocar=False)
    assert partes[0][1].speed >= lt.FATOR_MAX  # × fator da emoção
    assert Marcador(cfg).posicao(livro.id).velocidade == lt.FATOR_MAX


async def test_parar_apos_capitulos(cfg, livro) -> None:
    cfg = dataclasses.replace(cfg, parar_apos_capitulos=1)
    lei = _leitura(cfg)
    lei.abrir(livro)
    partes = await _todas(lei)
    assert len(partes) == 3
    assert lei.estado == "pausada" and lei.posicao == Posicao(1, 0, 0, 1.0)


async def test_cache_pcm_dos_3_ultimos_paragrafos(cfg, livro) -> None:
    tts = TtsFalso()
    lei = _leitura(cfg, tts=tts)
    lei.abrir(livro)

    async def falar(cap: int, par: int, texto: str) -> bytes:
        lei._gerando = (cap, par)
        prov = lei.tts.com_opcoes(voice=VOZ, speed=1.0)
        return b"".join([p async for p in prov.synthesize(texto, personal=False)])

    assert await falar(0, 0, "a") == b"a"
    assert await falar(0, 0, "a") == b"a"
    assert len(tts.sintetizados) == 1 and tts.sintetizados[0][1] == {"voice": VOZ, "speed": 1.0}
    for par in (1, 2, 3):
        await falar(0, par, "b")
    await falar(0, 0, "a")  # saiu do cache (só 3 parágrafos)
    assert len(tts.sintetizados) == 5
    assert lei.tts.output_format == "pcm"
