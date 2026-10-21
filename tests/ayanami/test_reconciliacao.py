"""Reconciliação ``resumo_nuvem`` na Ayanami (Y6.5, spec §6.6): CA-Y22 (parte reconciliação).

Hub falso (``enviar_e_esperar`` responde como o PC); armazém em memória nos testes sem banco e
``ArmazemPg`` no ``ayanami-pg-teste`` nos marcados ``pg``.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from ayanami.db import ConexaoUnica
from ayanami.reconciliacao import ArmazemPg, Cursor, Reconciliacao, montar_envelope
from ayanami.relogio import RelogioFalso
from magi.elo.mensagens import (
    MAX_TEXTO_BYTES,
    Ack,
    Envelope,
    Erro,
    ResumoNuvem,
    Tipo,
    TurnoNuvem,
    encode,
    responder,
)

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


class ArmazemMem:
    def __init__(self, n: int) -> None:
        self.linhas: dict[str, tuple[TurnoNuvem, datetime | None]] = {}
        for i in range(n):
            uid = str(uuid.UUID(int=i + 1))
            t = TurnoNuvem(uid=uid, ts=T0 + timedelta(seconds=i), dispositivo="celular",
                           texto_usuario=f"pergunta {i}", texto_resposta=f"resposta {i}")
            self.linhas[uid] = (t, None)

    def _abertos(self, depois: Cursor | None) -> list[TurnoNuvem]:
        ts = sorted((t for t, s in self.linhas.values() if s is None), key=lambda t: (t.ts, t.uid))
        return [t for t in ts if depois is None or (t.ts, t.uid) > depois]

    def pendentes(self, depois: Cursor | None, n: int) -> list[TurnoNuvem]:
        return self._abertos(depois)[:n]

    def contar(self, depois: Cursor | None) -> int:
        return len(self._abertos(depois))

    def marcar(self, uids: Sequence[str], quando: datetime) -> int:
        n = 0
        for u in uids:
            t, s = self.linhas[u]
            if s is None:
                self.linhas[u] = (t, quando)
                n += 1
        return n

    def sincronizados(self) -> int:
        return sum(1 for _, s in self.linhas.values() if s is not None)


class HubFalso:
    """Responde cada ``resumo_nuvem`` com ``responde(resumo)`` (ids, ``Erro`` ou exceção)."""

    def __init__(self, responde: Callable[[ResumoNuvem], object]) -> None:
        self.responde = responde
        self.enviados: list[Envelope] = []

    async def enviar_e_esperar(self, env: Envelope, prazo: float) -> Envelope:
        assert env.t is Tipo.RESUMO_NUVEM and env.para == "pc"
        encode(env)  # cabe no frame
        self.enviados.append(env)
        r = self.responde(env.corpo)  # type: ignore[arg-type]
        if isinstance(r, BaseException):
            raise r
        if isinstance(r, Erro):
            return responder(env, Tipo.ERRO, r, "pc")
        return responder(env, Tipo.ACK, Ack(ids=tuple(r)), "pc")  # type: ignore[arg-type]


def _todos(r: ResumoNuvem) -> list[str]:
    return [t.uid for t in r.turnos]


async def test_ca_y22_120_turnos_em_50_50_20_e_todos_marcados() -> None:
    arm, hub = ArmazemMem(120), HubFalso(_todos)
    rel = RelogioFalso(T0 + timedelta(days=1))
    r = await Reconciliacao(arm, rel, hub).rodada()
    tamanhos = [len(e.corpo.turnos) for e in hub.enviados]  # type: ignore[union-attr]
    assert tamanhos == [50, 50, 20]
    assert [e.corpo.restam for e in hub.enviados] == [70, 20, 0]  # type: ignore[union-attr]
    ordem = [t.ts for e in hub.enviados for t in e.corpo.turnos]  # type: ignore[union-attr]
    assert ordem == sorted(ordem)
    assert (r.envelopes, r.enviados, r.confirmados, r.interrompida) == (3, 120, 120, False)
    assert arm.sincronizados() == 120
    assert {s for _, s in arm.linhas.values()} == {rel.agora()}
    hub.enviados.clear()
    assert (await Reconciliacao(arm, rel, hub).rodada()).envelopes == 0
    assert hub.enviados == []


async def test_ack_parcial_marca_so_confirmados_e_resto_vai_no_proximo_ola() -> None:
    arm = ArmazemMem(120)
    # PC confirma só os pares; um id estranho (fora do envelope) é ignorado.
    hub = HubFalso(lambda r: [*_todos(r)[::2], str(uuid.UUID(int=999))])
    svc = Reconciliacao(arm, RelogioFalso(), hub)
    r = await svc.rodada()
    assert [len(e.corpo.turnos) for e in hub.enviados] == [50, 50, 20]  # type: ignore[union-attr]
    assert r.confirmados == 60 and arm.sincronizados() == 60
    assert str(uuid.UUID(int=999)) not in arm.linhas
    # próximo ola: só os 60 não confirmados, sem repetir os já marcados
    hub.enviados.clear()
    hub.responde = _todos
    r2 = await svc.rodada()
    reenviados = [u for e in hub.enviados for u in _todos(e.corpo)]  # type: ignore[arg-type]
    assert len(reenviados) == 60 == len(set(reenviados))
    assert [len(e.corpo.turnos) for e in hub.enviados] == [50, 10]  # type: ignore[union-attr]
    assert r2.confirmados == 60 and arm.sincronizados() == 120


@pytest.mark.parametrize("falha", [TimeoutError("sem resposta"), Erro(codigo="interno")])
async def test_sem_ack_para_a_rodada_e_reenvia_no_proximo_ola(falha: object) -> None:
    arm = ArmazemMem(120)
    chamadas = {"n": 0}

    def responde(r: ResumoNuvem) -> object:
        chamadas["n"] += 1
        return _todos(r) if chamadas["n"] == 1 else falha

    hub = HubFalso(responde)
    svc = Reconciliacao(arm, RelogioFalso(), hub)
    r = await svc.rodada()
    assert r.interrompida and len(hub.enviados) == 2 and arm.sincronizados() == 50
    segundo = _todos(hub.enviados[1].corpo)  # type: ignore[arg-type]
    hub.enviados.clear()
    hub.responde = _todos
    await svc.ao_ola_pc(None, None)
    for t in list(svc._tarefas):
        await t
    assert _todos(hub.enviados[0].corpo) == segundo  # type: ignore[arg-type]
    assert arm.sincronizados() == 120
    await svc.fechar()


def test_envelope_encolhe_ate_caber_no_frame() -> None:
    grande = "x" * 3000
    turnos = [TurnoNuvem(uid=str(uuid.UUID(int=i + 1)), ts=T0, dispositivo="celular",
                         texto_usuario=grande, texto_resposta=grande) for i in range(50)]
    env, n = montar_envelope(turnos, 0)
    assert 1 <= n < 50
    assert len(encode(env).encode()) <= MAX_TEXTO_BYTES
    assert env.corpo.restam == 50 - n  # type: ignore[union-attr]
    enorme = [TurnoNuvem(uid=str(uuid.UUID(int=1)), ts=T0, dispositivo="celular",
                         texto_usuario="y" * 70_000, texto_resposta="z" * 70_000)]
    env1, n1 = montar_envelope(enorme, 3)
    assert n1 == 1 and env1.corpo.restam == 3  # type: ignore[union-attr]


# --- ArmazemPg (ayanami-pg-teste) ------------------------------------------------------------


def _semear(pg: psycopg.Connection, n: int) -> list[str]:
    with pg.transaction():
        pg.execute("DELETE FROM nuvem_turnos")
        nome = f"cel-{uuid.uuid4().hex[:8]}"
        disp = pg.execute("INSERT INTO dispositivos (nome, tipo, escopos, hash, prefixo)"
                          " VALUES (%s, 'celular', '{}', %s, 'ayn_') RETURNING id",
                          [nome, f"h-{nome}"]).fetchone()[0]  # type: ignore[index]
        uids = []
        for i in range(n):
            uids.append(str(pg.execute(
                "INSERT INTO nuvem_turnos (ts, dispositivo, texto_usuario, texto_resposta, ferramentas)"
                " VALUES (%s, %s, %s, %s, %s) RETURNING uid",
                [T0 + timedelta(seconds=i // 2), disp, f"p{i}", f"r{i}", ["estado"]],
            ).fetchone()[0]))  # type: ignore[index]
        # um turno já sincronizado não volta
        pg.execute("INSERT INTO nuvem_turnos (dispositivo, texto_usuario, texto_resposta, sincronizado)"
                   " VALUES (%s, 'velho', 'velho', now())", [disp])
    return uids


@pytest.mark.pg
async def test_pg_120_turnos_ack_parcial_e_reenvio(pg: psycopg.Connection) -> None:
    pg.autocommit = True
    uids = _semear(pg, 120)
    arm = ArmazemPg(ConexaoUnica(pg))
    assert arm.contar(None) == 120
    pares = HubFalso(lambda r: _todos(r)[::2])
    svc = Reconciliacao(arm, RelogioFalso(T0 + timedelta(days=1)), pares)
    await svc.rodada()
    assert [len(e.corpo.turnos) for e in pares.enviados] == [50, 50, 20]  # type: ignore[union-attr]
    enviados = [t for e in pares.enviados for t in e.corpo.turnos]  # type: ignore[union-attr]
    assert {t.uid for t in enviados} == set(uids)
    assert enviados[0].ferramentas == ("estado",) and enviados[0].dispositivo.startswith("cel-")
    assert arm.contar(None) == 60
    todos = HubFalso(_todos)
    await Reconciliacao(arm, RelogioFalso(), todos).rodada()
    reenviados = [t.uid for e in todos.enviados for t in e.corpo.turnos]  # type: ignore[union-attr]
    assert len(reenviados) == 60 == len(set(reenviados))
    assert not set(reenviados) & {t.uid for t in enviados[::2]}
    assert arm.contar(None) == 0
    marcados = pg.execute("SELECT count(*) FROM nuvem_turnos WHERE sincronizado = %s",
                          [T0 + timedelta(days=1)]).fetchone()[0]  # type: ignore[index]
    assert marcados == 60


async def test_y65b_parada_da_app_fecha_a_reconciliacao() -> None:
    """O lifespan de ``ayanami.api.app`` chama ``Reconciliacao.fechar()`` na parada (Y6.5b)."""
    from types import SimpleNamespace

    from ayanami.api.app import _vida

    fechou: list[bool] = []

    class Svc:
        async def fechar(self) -> None:
            fechou.append(True)

    app = SimpleNamespace(state=SimpleNamespace(ctx=SimpleNamespace(ciclo=[], extras={})))
    async with _vida(app):  # type: ignore[arg-type]
        app.state.ctx.extras["reconciliacao"] = Svc()  # nasce no 1º WS do pc, depois da subida
    assert fechou == [True]
    async with _vida(app):  # sem reconciliação: nada a fechar, não quebra
        app.state.ctx.extras.clear()
