"""Reconciliação ``resumo_nuvem`` no PC (Y6.5, spec §6.6): CA-Y22 (reenvio não duplica ``turns``).

Repositório e extrator falsos nos testes sem banco; ``TurnosNuvemPg`` numa base com as migrações
do PC no ``ayanami-pg-teste`` (fixtures da Y0.3) nos marcados ``pg``.
"""

from __future__ import annotations

import importlib.util
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest

from magi.common.contracts import TurnRecord
from magi.elo import reconciliar as rc
from magi.elo.mensagens import ResumoNuvem, TurnoNuvem
from magi.memory import migrate as pc_migrate
from magi.memory.conn import SerialConn

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _conftest_ayanami() -> Any:
    caminho = Path(__file__).resolve().parents[1] / "ayanami" / "conftest.py"
    spec = importlib.util.spec_from_file_location("_y65_conftest_ayanami", caminho)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_cf = _conftest_ayanami()
pg_dsn = _cf.pg_dsn
pg_nova_base = _cf.pg_nova_base


def _turnos(n: int, base: int = 0) -> tuple[TurnoNuvem, ...]:
    return tuple(
        TurnoNuvem(uid=str(uuid.UUID(int=base + i + 1)), ts=T0 + timedelta(seconds=i),
                   dispositivo="celular", texto_usuario=f"liga a tv {i}", texto_resposta=f"ok {i}",
                   ferramentas=("tv_ligar",))
        for i in range(n)
    )


class TurnsFalso:
    def __init__(self, falha_em: set[str] | None = None) -> None:
        self.linhas: list[TurnRecord] = []
        self.falha_em = falha_em or set()

        self.uids: list[str] = []
        self.ferramentas: list[tuple[str, ...]] = []

    async def add_nuvem(self, turn: TurnRecord, uid: str, ferramentas: Sequence[str]) -> int:
        if uid in self.falha_em:
            raise RuntimeError("banco")
        self.linhas.append(turn)
        self.uids.append(uid)
        self.ferramentas.append(tuple(ferramentas))
        return len(self.linhas)

    async def ja_gravados(self, uids: Sequence[str]) -> set[str]:
        return set(self.uids) & set(uids)


class MemoriaFalsa:
    def __init__(self, falha: bool = False) -> None:
        self.lotes: list[list[TurnRecord]] = []
        self.falha = falha

    async def ingerir(self, turnos: Sequence[TurnRecord]) -> None:
        self.lotes.append(list(turnos))
        if self.falha:
            raise RuntimeError("extrator")


async def test_grava_celular_marcado_nuvem_e_passa_pelo_extrator() -> None:
    turns, mem = TurnsFalso(), MemoriaFalsa()
    r = ResumoNuvem(turnos=_turnos(3), restam=0)
    ids = await rc.gravar_resumo(r, turns, mem)
    assert ids == tuple(t.uid for t in r.turnos)
    t0 = turns.linhas[0]
    assert (t0.satellite, t0.intent, t0.text_heard, t0.text_final, t0.reply, t0.at) == (
        "celular", "nuvem", "liga a tv 0", "liga a tv 0", "ok 0", T0)
    assert not t0.routed_local and turns.ferramentas[0] == ("tv_ligar",)
    assert [[t.id for t in lote] for lote in mem.lotes] == [[1, 2, 3]]


async def test_ca_y22_reenvio_nao_duplica_turns() -> None:
    turns, mem = TurnsFalso(), MemoriaFalsa()
    primeiro = ResumoNuvem(turnos=_turnos(50), restam=70)
    assert len(await rc.gravar_resumo(primeiro, turns, mem)) == 50
    # a Ayanami não recebeu o ack: reenvia o mesmo envelope (+ uid repetido no mesmo envelope)
    repetido = ResumoNuvem(turnos=(*_turnos(50), _turnos(1)[0]), restam=70)
    ids = await rc.gravar_resumo(repetido, turns, mem)
    assert ids == tuple(t.uid for t in _turnos(50))  # já gravados também entram no ack
    assert len(turns.linhas) == 50
    assert len(mem.lotes) == 1  # nada novo, extrator não roda de novo


async def test_falha_ao_gravar_tira_do_ack_e_extrator_com_erro_nao() -> None:
    r = ResumoNuvem(turnos=_turnos(4))
    ruim = r.turnos[1].uid
    ids = await rc.gravar_resumo(r, TurnsFalso({ruim}), MemoriaFalsa(falha=True))
    assert ids == tuple(t.uid for t in r.turnos if t.uid != ruim)
    assert await rc.gravar_resumo(r, TurnsFalso(), None) == tuple(t.uid for t in r.turnos)


async def test_reconciliador_do_core() -> None:
    assert await rc.Reconciliador(None).gravar_resumo(ResumoNuvem(turnos=_turnos(1))) == ()
    turns = TurnsFalso()
    perfil = SimpleNamespace(chamadas=0)

    async def maybe_update() -> bool:
        perfil.chamadas += 1
        return False

    perfil.maybe_update = maybe_update
    core = SimpleNamespace(repos=None, profile=perfil)
    rec = rc.Reconciliador(core, turns=turns)
    assert len(await rec.gravar_resumo(ResumoNuvem(turnos=_turnos(2)))) == 2
    assert perfil.chamadas == 1 and len(turns.linhas) == 2


# --- TurnosNuvemPg (base com as migrações do PC no ayanami-pg-teste) ---------------------------


@pytest.fixture
def base(pg_nova_base: Callable[[str], str]) -> str:
    dsn = pg_nova_base("magi_pc_t")
    with psycopg.connect(dsn) as conn:
        pc_migrate.migrate(conn)
    return dsn


@pytest.mark.pg
async def test_pg_reenvio_nao_duplica_turns(base: str) -> None:
    raw = await psycopg.AsyncConnection.connect(base, autocommit=True)
    try:
        conn = SerialConn(raw)
        await conn.execute("INSERT INTO turns (satellite, text_heard, intent) VALUES "
                           "('pc', 'local', 'tv.on')")
        repo = rc.TurnosNuvemPg(conn)
        mem = MemoriaFalsa()
        lote = _turnos(50)
        assert len(await rc.gravar_resumo(ResumoNuvem(turnos=lote, restam=70), repo, mem)) == 50
        ids = await rc.gravar_resumo(ResumoNuvem(turnos=(*lote[10:], *_turnos(5, 100))), repo, mem)
        assert len(ids) == 45
        cur = await conn.execute("SELECT count(*), count(DISTINCT nuvem_uid) FROM turns "
                                 "WHERE satellite = 'celular' AND intent = 'nuvem'")
        assert await cur.fetchone() == (55, 55)
        cur = await conn.execute("SELECT ferramentas FROM turns WHERE nuvem_uid = %s", [lote[0].uid])
        assert (await cur.fetchone())[0] == ["tv_ligar"]  # type: ignore[index]
        cur = await conn.execute("SELECT count(*) FROM turns WHERE satellite = 'pc'")
        assert (await cur.fetchone())[0] == 1  # type: ignore[index]
        assert [len(lote) for lote in mem.lotes] == [50, 5]
        assert await repo.ja_gravados([lote[0].uid, str(uuid.uuid4())]) == {lote[0].uid}
    finally:
        await raw.close()


@pytest.mark.pg
async def test_pg_formato_antigo_y65_conta_como_gravado(base: str) -> None:
    """Linhas da Y6.5 (``intent = 'nuvem:<uid>'``, sem ``nuvem_uid``) não são regravadas."""
    raw = await psycopg.AsyncConnection.connect(base, autocommit=True)
    try:
        conn = SerialConn(raw)
        velho, novo = _turnos(2, 300)
        await conn.execute("INSERT INTO turns (satellite, text_heard, intent) VALUES ('celular', 'x', %s)",
                           [rc.marca(velho.uid)])
        repo = rc.TurnosNuvemPg(conn)
        assert await repo.ja_gravados([velho.uid, novo.uid]) == {velho.uid}
        ids = await rc.gravar_resumo(ResumoNuvem(turnos=(velho, novo)), repo, None)
        assert ids == (velho.uid, novo.uid)
        cur = await conn.execute("SELECT count(*) FROM turns WHERE satellite = 'celular'")
        assert (await cur.fetchone())[0] == 2  # type: ignore[index]
        # corrida: insert direto do mesmo uid devolve o id existente, sem duplicar
        rec = rc.registro(novo)
        primeiro = await repo.add_nuvem(rec, novo.uid, ())
        assert await repo.add_nuvem(rec, novo.uid, ()) == primeiro
        cur = await conn.execute("SELECT count(*) FROM turns WHERE nuvem_uid = %s", [novo.uid])
        assert (await cur.fetchone())[0] == 1  # type: ignore[index]
    finally:
        await raw.close()


@pytest.mark.pg
def test_pg_migracao_006_idempotente(base: str) -> None:
    with psycopg.connect(base) as conn:
        assert pc_migrate.migrate(conn) == []
        sql = (pc_migrate.MIGRATIONS_DIR / "006_turns_nuvem_uid.sql").read_text()
        conn.execute(sql)  # reexecutar à mão não quebra (IF NOT EXISTS)
        cols = {r[0] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'turns'")}
        assert {"nuvem_uid", "ferramentas"} <= cols
