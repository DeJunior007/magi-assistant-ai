"""``EventosPc`` (Y6.6): eventos da Ayanami na fila da proatividade com as regras dos avisos
locais (call/jogo → tela; satélite ocupado → espera), confirmação pela pergunta proativa e nada
enviado quando expira. Ayanami falsa; relógio e espera injetados."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from magi.common.contracts import CardMsg, SubtitleMsg
from magi.core.proactive.ayanami import AvisoBackup, AvisosAyanami
from magi.core.proactive.sink import Offer, ProactiveSink
from magi.elo.eventos_pc import EventosPc
from magi.elo.mensagens import Confirma, Envelope, Evento, EventoTipo, Tipo

T0 = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


class Hud:
    def __init__(self) -> None:
        self.msgs: list[Any] = []

    async def send(self, msg: Any) -> None:
        self.msgs.append(msg)

    def cards(self) -> list[str]:
        return [m.title for m in self.msgs if isinstance(m, CardMsg)]

    def legendas(self) -> list[str]:
        return [m.text for m in self.msgs if isinstance(m, SubtitleMsg)]


class Satelite:
    def __init__(self, *, in_call: bool = False, livre: bool = True) -> None:
        self.in_call = in_call
        self.livre = livre
        self.falas: list[tuple[str, Offer | None]] = []

    async def announce(self, text: str, expression: Any = None, *, offer: Offer | None = None) -> bool:
        if not self.livre:
            return False
        self.falas.append((text, offer))
        return True


async def _nada(_s: float) -> None:
    await asyncio.sleep(0)


async def _gira() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


def _sink(hud: Hud, sat: Satelite | None) -> ProactiveSink:
    return ProactiveSink(hud, (lambda: [sat]) if sat else None, sleep=_nada, max_wait_s=1e9)


def _ev(seq: int, tipo: EventoTipo, titulo: str, **kw: Any) -> Envelope:
    corpo = Evento(seq=seq, tipo=tipo, titulo=titulo, **kw)
    return Envelope(t=Tipo.EVENTO, corpo=corpo, de="ayanami", para="pc")


def _conf(pedido: str = "01JABCDEFGHJKMNPQRSTVWXYZ0", expira: datetime | None = None) -> Envelope:
    expira = expira or T0 + timedelta(seconds=120)
    c = Confirma(pedido=pedido, descricao="desligar a TV da sala", expira_em=expira)
    return Envelope(t=Tipo.CONFIRMA, corpo=c, de="ayanami", para="pc")


async def test_evento_falado_e_card_pesquisa_pronta() -> None:
    hud, sat = Hud(), Satelite()
    sink = _sink(hud, sat)
    ev = EventosPc(SimpleNamespace(proactive=sink))
    assert await ev.evento(_ev(1, EventoTipo.TAREFA_PRONTA, "preço da RTX 5090")) is None
    await sink.drain()
    assert hud.cards() == ["Pesquisa pronta: preço da RTX 5090"]
    assert [f for f, _ in sat.falas] == ["Pesquisa pronta: preço da RTX 5090"]


async def test_evento_em_call_vai_para_a_tela() -> None:
    hud, sat = Hud(), Satelite(in_call=True)
    ev = EventosPc(SimpleNamespace(proactive=_sink(hud, sat)))
    await ev.evento(_ev(2, EventoTipo.NOTICIA_BOMBA, "Notícia bomba: algo"))
    assert hud.cards() == ["Notícia bomba: algo"] and hud.legendas() == ["Notícia bomba: algo"]
    assert sat.falas == []


async def test_evento_espera_o_satelite_livre_como_os_locais() -> None:
    hud, sat = Hud(), Satelite(livre=False)
    sink = _sink(hud, sat)
    ev = EventosPc(SimpleNamespace(proactive=sink))
    await ev.evento(_ev(3, EventoTipo.LEMBRETE, "tomar água"))
    for _ in range(5):
        await asyncio.sleep(0)
    assert sat.falas == [] and hud.legendas() == []  # na fila, nem caiu para a tela
    sat.livre = True
    await sink.drain()
    assert [f for f, _ in sat.falas] == ["Lembrete: tomar água"]
    await sink.aclose()


async def test_seq_repetido_e_dispositivo_so_tela() -> None:
    hud, sat = Hud(), Satelite()
    sink = _sink(hud, sat)
    ev = EventosPc(SimpleNamespace(proactive=sink))
    await ev.evento(_ev(4, EventoTipo.DISPOSITIVO, "celular-pedro conectado"))
    await ev.evento(_ev(4, EventoTipo.DISPOSITIVO, "celular-pedro conectado"))
    await ev.evento(_ev(5, EventoTipo.MONITOR, "site voltou", proativo=False))
    await sink.drain()
    assert hud.cards() == ["celular-pedro conectado", "site voltou"]
    assert sat.falas == []


async def test_sem_core_nao_quebra() -> None:
    assert await EventosPc(None).evento(_ev(1, EventoTipo.LEMBRETE, "x")) is None


async def test_confirma_sim_responde_com_resp() -> None:
    hud, sat = Hud(), Satelite()
    sink = _sink(hud, sat)
    enviados: list[tuple[Any, ...]] = []

    async def enviar(t: Tipo, corpo: Any, para: str, *, resp: str | None = None) -> None:
        enviados.append((t, corpo, para, resp))

    ev = EventosPc(SimpleNamespace(proactive=sink), enviar=enviar, agora=lambda: T0)
    env = _conf()
    assert await ev.confirma(env) is None  # ack na hora, não segura o elo
    await _gira()
    await sink.drain()
    fala, offer = sat.falas[0]
    assert fala == "Confirma desligar a TV da sala?" and offer is not None
    r = await offer.accept()
    assert r.ok
    await asyncio.gather(*ev._tarefas)
    t, corpo, para, resp = enviados[0]
    assert t is Tipo.CONFIRMA and para == "ayanami" and resp == env.id
    assert corpo.pedido == env.corpo.pedido and corpo.resposta is True


async def test_confirma_nao() -> None:
    hud, sat = Hud(), Satelite()
    sink = _sink(hud, sat)
    enviados: list[Any] = []

    async def enviar(t: Tipo, corpo: Any, para: str, *, resp: str | None = None) -> None:
        enviados.append(corpo)

    ev = EventosPc(SimpleNamespace(proactive=sink), enviar=enviar, agora=lambda: T0)
    await ev.confirma(_conf())
    await _gira()
    await sink.drain()
    sat.falas[0][1].decline()
    await asyncio.gather(*ev._tarefas)
    assert enviados[0].resposta is False


async def test_confirma_sem_resposta_em_120s_nao_manda_nada() -> None:
    hud, sat = Hud(), Satelite()
    sink = _sink(hud, sat)
    enviados: list[Any] = []
    prazos: list[float] = []

    async def enviar(*a: Any, **k: Any) -> None:
        enviados.append(a)

    async def esperar(fut: Any, prazo: float) -> bool:
        prazos.append(prazo)
        raise TimeoutError

    ev = EventosPc(SimpleNamespace(proactive=sink), enviar=enviar, agora=lambda: T0, esperar=esperar)
    await ev.confirma(_conf())
    await asyncio.gather(*ev._tarefas)
    assert prazos == [120.0] and enviados == [] and ev._pendentes == {}


async def test_confirma_ja_expirada_e_respondida_no_celular() -> None:
    hud = Hud()
    enviados: list[Any] = []

    async def enviar(*a: Any, **k: Any) -> None:
        enviados.append(a)

    ev = EventosPc(SimpleNamespace(proactive=_sink(hud, Satelite())), enviar=enviar, agora=lambda: T0)
    await ev.confirma(_conf(expira=T0 - timedelta(seconds=1)))
    assert ev._tarefas == set() and hud.msgs == []
    await ev.confirma(_conf("01JABCDEFGHJKMNPQRSTVWXYZ1"))
    assert "01JABCDEFGHJKMNPQRSTVWXYZ1" in ev._pendentes
    resp = Envelope(t=Tipo.CONFIRMA, corpo=Confirma(pedido="01JABCDEFGHJKMNPQRSTVWXYZ1", resposta=True),
                    de="ayanami", para="pc")
    await ev.confirma(resp)
    await asyncio.gather(*ev._tarefas, return_exceptions=True)
    assert enviados == []


async def test_aviso_backup_uma_vez_por_quando(tmp_path: Path) -> None:
    hud = Hud()
    p = tmp_path / "backup_state.json"
    p.write_text(json.dumps({"quando": "2026-10-13T03:00:00", "resultado": "falhou", "data": "2026-10-13"}))
    av = AvisoBackup(AvisosAyanami(_sink(hud, None)), p)
    assert await av.checar() is True
    assert await av.checar() is False
    assert hud.cards() == ["Backup não subiu para a Ayanami (2026-10-13)"]
    p.write_text(json.dumps({"quando": "2026-10-14T03:00:00", "resultado": "ok"}))
    assert await av.checar() is False
