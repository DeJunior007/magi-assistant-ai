"""``BookHandler`` (A2.3): os 11 intents com ``Leitura`` real em capítulos falsos, biblioteca,
MPRIS e refino falsos (nada de ``~/Livros``, TTS, D-Bus ou container de verdade)."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from magi.audiolivro import contratos
from magi.audiolivro import handler as hd
from magi.audiolivro import leitor as lt
from magi.audiolivro.biblioteca import SEM_TEXTO, Biblioteca
from magi.audiolivro.config import ConfigAudiolivro
from magi.audiolivro.contratos import Capitulo, Livro, Paragrafo
from magi.audiolivro.marcador import Marcador
from magi.common.contracts import (
    ARG_NARRATE,
    ActionRequest,
    Intent,
    IntentId,
    Slot,
    TurnContext,
    WakeSource,
)

CAPS = [
    Capitulo(0, "Um", (Paragrafo(0, ("Era uma vez.", "O sol nasceu.")), Paragrafo(1, ("Fim do dia.",))), 1.0),
    Capitulo(1, "Dois", (Paragrafo(0, ("Ana olhou.", "Choveu.")),), 1.0),
    Capitulo(2, "Três", (Paragrafo(0, ("Último.",)), Paragrafo(1, ("Mesmo.",))), 1.0),
]


class BibliotecaFalsa:
    ambiguo = staticmethod(Biblioteca.ambiguo)

    def __init__(self, livros: list[Livro]) -> None:
        self._livros = livros
        self.ignorados: dict[Path, str] = {}

    def livros(self) -> list[Livro]:
        return list(self._livros)

    def achar(self, fala: str) -> list[tuple[Livro, float]]:
        return [(lv, 0.9) for lv in self._livros if fala.lower() in lv.titulo.lower()]


class Mpris:
    def __init__(self, tocando: bool = True) -> None:
        self.tocando = tocando
        self.chamadas: list[str] = []

    async def state(self) -> Any:
        return type("S", (), {"playing": self.tocando})()

    async def pause(self) -> None:
        self.chamadas.append("pause")
        self.tocando = False

    async def play(self) -> None:
        self.chamadas.append("play")
        self.tocando = True


class Refino:
    def __init__(self) -> None:
        self.parado = 0

    def pronto(self, livro: Livro, cap: int) -> None:
        return None

    def adiantar(self, *a: Any) -> None:
        return None

    async def parar(self) -> None:
        self.parado += 1


@pytest.fixture
def cfg(tmp_path: Path) -> ConfigAudiolivro:
    return ConfigAudiolivro(
        pasta=tmp_path / "Livros", estado_dir=tmp_path / "estado", cache_dir=tmp_path / "cache"
    )


@pytest.fixture(autouse=True)
def _caps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(contratos, "_extrair", lambda _f, _c, _i, n: CAPS[n])


def _livro(tmp_path: Path, titulo: str = "Duna", lid: str = "abc123") -> Livro:
    return Livro(lid, tmp_path / f"{lid}.epub", titulo, None, "pt-br", "epub", len(CAPS), 100)


def _handler(cfg: ConfigAudiolivro, livros: list[Livro], **kw: Any) -> tuple[hd.BookHandler, Refino]:
    refino = Refino()

    def nova() -> lt.Leitura:
        return lt.Leitura(cfg, Marcador(cfg), voz_dela="pf_dora", idioma_dela="pt-br", refino=refino,
                          extrair=lambda _l, n: CAPS[n])

    return hd.BookHandler(cfg, BibliotecaFalsa(livros), nova, **kw), refino  # type: ignore[arg-type]


def _req(iid: IntentId, fala: str = "", *, in_call: bool = False, reading: Any = None,
         **slots: str) -> ActionRequest:
    ctx = TurnContext("pc", list(WakeSource)[0], datetime.now(), in_call=in_call, reading=reading)
    intent = Intent(iid.value, tuple(Slot(name=k, value=v) for k, v in slots.items()))
    return ActionRequest(intent=intent, ctx=ctx, text=fala)


async def _ler(h: hd.BookHandler, **kw: Any) -> Any:
    return await h.run(_req(IntentId.BOOK_READ, "lê duna", query="duna", **kw))


def test_cobre_os_11_intents() -> None:
    assert len(hd.BookHandler.intents) == 11
    assert {i.value for i in IntentId if i.value.startswith("book.")} == hd.BookHandler.intents


async def test_read_narra_pausa_musica_e_lembra_o_livro(cfg, tmp_path) -> None:
    mpris = Mpris()
    h, _ = _handler(cfg, [_livro(tmp_path)], mpris=mpris)
    r = await _ler(h)
    assert r.ok and r.speech == "Lendo Duna." and not r.needs_confirmation
    narrada = r.on_confirm.args[ARG_NARRATE]
    assert isinstance(narrada, hd.Narrada) and narrada.livro.titulo == "Duna"
    assert narrada.estado == "pausada"
    assert mpris.chamadas == ["pause"]
    assert (cfg.estado_dir / "audiolivro-ultimo").read_text() == "abc123"


async def test_fim_do_livro_volta_musica_e_para_refino(cfg, tmp_path) -> None:
    mpris = Mpris()
    h, refino = _handler(cfg, [_livro(tmp_path)], mpris=mpris)
    narrada = (await _ler(h)).on_confirm.args[ARG_NARRATE]
    partes = [p async for p in narrada.partes()]
    assert [t for t, _ in partes][0] == "Era uma vez."
    await asyncio.sleep(0)
    await asyncio.gather(*h._tarefas)
    assert mpris.chamadas == ["pause", "play"] and refino.parado == 1


async def test_em_call_nao_comeca(cfg, tmp_path) -> None:
    h, _ = _handler(cfg, [_livro(tmp_path)])
    r = await _ler(h, in_call=True)
    assert not r.ok and r.speech == hd.SAY_IN_CALL and r.on_confirm is None


async def test_ambiguo_pergunta_e_nao_achado(cfg, tmp_path) -> None:
    h, _ = _handler(cfg, [_livro(tmp_path, "Duna"), _livro(tmp_path, "Duna Messias", "def456")])
    r = await _ler(h)
    assert r.speech == "Achei mais de um: Duna ou Duna Messias. Qual?" and r.on_confirm is None
    r = await h.run(_req(IntentId.BOOK_READ, query="neuromancer"))
    assert r.speech == hd.SAY_NOT_FOUND
    h.biblioteca.ignorados = {tmp_path / "Neuromancer.pdf": SEM_TEXTO}
    r = await h.run(_req(IntentId.BOOK_READ, query="neuromancer"))
    assert r.speech == hd.SAY_NO_TEXT


async def test_comandos_mexem_na_leitura_e_retomam(cfg, tmp_path) -> None:
    h, _ = _handler(cfg, [_livro(tmp_path)])
    narrada = (await _ler(h)).on_confirm.args[ARG_NARRATE]
    leitura = h.leitura
    r = await h.run(_req(IntentId.BOOK_FORWARD, reading=narrada))
    assert leitura.posicao.par == 1 and r.on_confirm.args[ARG_NARRATE] is narrada
    await h.run(_req(IntentId.BOOK_BACK, "repete", reading=narrada))
    assert leitura.posicao.par == 1
    await h.run(_req(IntentId.BOOK_BACK, reading=narrada, amount="1"))
    assert leitura.posicao.par == 0
    await h.run(_req(IntentId.BOOK_CHAPTER, reading=narrada, text="next"))
    assert leitura.posicao.cap == 1
    await h.run(_req(IntentId.BOOK_CHAPTER, reading=narrada, amount="3"))
    assert leitura.posicao.cap == 2
    await h.run(_req(IntentId.BOOK_CHAPTER, reading=narrada, text="previous"))
    assert leitura.posicao.cap == 1
    r = await h.run(_req(IntentId.BOOK_SPEED, reading=narrada, text="slower"))
    assert r.speech == "Velocidade 0,9." and ARG_NARRATE in r.on_confirm.args
    r = await h.run(_req(IntentId.BOOK_SPEED, reading=narrada, text="normal"))
    assert r.speech == "Velocidade 1."
    r = await h.run(_req(IntentId.BOOK_WHERE))
    assert r.speech == "Capítulo 2 de Duna."


async def test_sem_retomar_apos_comando(cfg, tmp_path) -> None:
    import dataclasses

    h, _ = _handler(dataclasses.replace(cfg, retomar_apos_comando=False), [_livro(tmp_path)])
    await _ler(h)
    r = await h.run(_req(IntentId.BOOK_FORWARD))
    assert r.on_confirm is None


async def test_pause_stop_e_resume_depois_de_reiniciar(cfg, tmp_path) -> None:
    mpris = Mpris()
    livro = _livro(tmp_path)
    h, refino = _handler(cfg, [livro], mpris=mpris)
    narrada = (await _ler(h)).on_confirm.args[ARG_NARRATE]
    await h.run(_req(IntentId.BOOK_FORWARD))
    r = await h.run(_req(IntentId.BOOK_PAUSE))
    assert r.speech == hd.SAY_PAUSED and r.on_confirm is None and narrada.estado == "pausada"
    r = await h.run(_req(IntentId.BOOK_STOP))
    assert r.speech == hd.SAY_STOPPED and narrada.estado == "parada"
    assert mpris.chamadas == ["pause", "play"] and refino.parado == 1
    assert (await h.run(_req(IntentId.BOOK_PAUSE))).speech == hd.SAY_NO_BOOK
    # núcleo reiniciado: handler novo acha o último livro e o marcador
    h2, _ = _handler(cfg, [livro])
    r = await h2.run(_req(IntentId.BOOK_RESUME))
    assert r.ok and h2.leitura.posicao.par == 1 and ARG_NARRATE in r.on_confirm.args


async def test_list_time_e_where_sem_leitura(cfg, tmp_path) -> None:
    h, _ = _handler(cfg, [])
    assert (await h.run(_req(IntentId.BOOK_LIST))).speech == hd.SAY_NO_BOOKS
    assert (await h.run(_req(IntentId.BOOK_WHERE))).speech == hd.SAY_NO_BOOK
    assert (await h.run(_req(IntentId.BOOK_RESUME))).speech == hd.SAY_NO_BOOK
    livros = [_livro(tmp_path), _livro(tmp_path, "Akira", "x9")]
    h, _ = _handler(dataclasses_replace(cfg, chars_por_minuto=1), livros)
    r = await h.run(_req(IntentId.BOOK_LIST))
    assert r.speech == "Tenho 2 livros: Akira, Duna."
    r = await h.run(_req(IntentId.BOOK_TIME, query="duna"))
    total = sum(c.caracteres for c in CAPS)
    assert r.speech == (
        f"Esse capítulo leva uns {CAPS[0].caracteres} minutos; o livro todo, umas "
        f"{hd._num(total / 60)} horas."
    )


def dataclasses_replace(cfg: ConfigAudiolivro, **kw: Any) -> ConfigAudiolivro:
    import dataclasses

    return dataclasses.replace(cfg, **kw)
