"""LI0.2: banco e repositório da entrevista pela vaga (spec §8; R2.6, R5).

Os dois backends passam o mesmo teste: ``jsonl`` (pasta temporária) e ``postgres`` (schema de
teste próprio do fixture do LM, apagado no fim; pulado sem banco). Nunca o ``public``.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from psycopg import sql

from magi.learning.interview.contracts import (
    Aspect,
    AspectScore,
    Cover,
    Coverage,
    InterviewDebrief,
    InterviewPlan,
    InterviewRun,
    JobPost,
    JobProfile,
    Requirement,
    RunState,
    Seniority,
    Stage,
    StageKind,
    make_run_id,
)
from magi.learning.interview.store import InterviewStore
from magi.learning.repo import JsonlRepo, PostgresRepo
from magi.memory import migrate as mig
from magi.memory.conn import SerialConn

SCHEMA = f"learning_iv_test_{os.getpid()}"
SQL_FILE = mig.MIGRATIONS_DIR / "004_learning_jobs.sql"
T0 = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
JOB = "JOB-1a2b3c4d"


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


def post(job_id: str = JOB) -> JobPost:
    return JobPost(job_id, "Senior Backend Engineer at Acme Pay. " * 10, "clipboard", T0)


def profile(title: str = "Senior Backend Engineer") -> JobProfile:
    return JobProfile(
        title=title, company="Acme Pay", seniority=Seniority.SENIOR, language="en",
        stack=("python", "postgresql"),
        requirements=(Requirement("5+ years with Python", "must", "python", "5+ years with Python"),),
        responsibilities=("Build payment APIs",), domain="fintech", remote="remote",
    )


def the_run(session_id: str, n: int = 1, job_id: str = JOB) -> InterviewRun:
    plan = InterviewPlan(job_id, 30, (
        Stage(StageKind.INTRO, "INTRO", (), 1, 3),
        Stage(StageKind.TECHNICAL, "TECHNICAL — PYTHON", ("python",), 2, 26, followups=1),
        Stage(StageKind.WRAP, "WRAP", (), 0, 1),
    ))
    return InterviewRun(
        id=make_run_id(T0, n), session_id=session_id, job_id=job_id, profile=profile(), plan=plan,
        state=RunState.RUNNING, stage=0, asked=0, answers=0, stage_started=0.0, started=0.0,
        paused_s=0.0, first_message_id=None, last_message_id=None,
    )


def the_debrief(run_id: str) -> InterviewDebrief:
    return InterviewDebrief(
        run_id=run_id,
        coverage=(Coverage("5+ years with Python", Cover.COVERED, "six years of Python"),),
        scores=(AspectScore(Aspect.JOB_FIT, 70, "good fit"),),
        strengths=("clear examples",), improve=("use STAR",), rewrites=(("Why us?", "Because…"),),
        language=("past tense",), closing="Thanks.",
    )


# --- fixtures ---------------------------------------------------------------------------------


def _admin():
    try:
        return psycopg.connect(mig.dsn_from_env(), autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres indisponível: {exc}")


@pytest.fixture
def pg_schema():
    admin = _admin()
    drop = sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(SCHEMA))
    admin.execute(drop)
    try:
        with psycopg.connect(mig.dsn_from_env()) as c:
            mig.migrate(c, schema=SCHEMA, memories_dim=3, news_dim=2)
        yield
    finally:
        admin.execute(drop)  # só o schema de teste (regra 7 de tasks.md)
        admin.close()


@pytest.fixture(params=["jsonl", pytest.param("postgres", marks=pytest.mark.db)])
async def repo(request, tmp_path):
    if request.param == "jsonl":
        yield JsonlRepo(tmp_path / "learning")
        return
    request.getfixturevalue("pg_schema")
    raw = await psycopg.AsyncConnection.connect(mig.dsn_from_env())
    await raw.execute("SELECT set_config('search_path', %s, false)", [f'"{SCHEMA}", public'])
    await raw.commit()
    try:
        yield PostgresRepo(SerialConn(raw))
    finally:
        await raw.close()


# --- fluxo completo nos dois backends ---------------------------------------------------------


async def test_vaga_perfil_run_retorno_unseen_mark_seen(repo) -> None:
    st = InterviewStore(repo, clock=Clock())
    s = await repo.open_session(level="B2", track="CONVERSATION", at=T0)

    # vaga → perfil (reuso por hash, R2.6)
    await st.save_post(post())
    assert await st.profile_of(JOB) is None
    assert await st.recent() == []
    await st.set_profile(JOB, profile(), model="fake", cost_usd=0.0012)
    assert await st.profile_of(JOB) == profile()
    assert (await st.post_of(JOB)) == post()
    await st.save_post(post())  # mesma vaga de novo: não apaga o perfil
    assert await st.profile_of(JOB) == profile()
    assert await st.profile_of("JOB-ffffffff") is None
    job = await repo.get_job(JOB)
    assert job.model == "fake" and job.cost_usd == pytest.approx(0.0012)

    # recent: a mais usada por último primeiro, só com perfil
    other = "JOB-0000abcd"
    await st.save_post(post(other))
    assert [j for j, _ in await st.recent()] == [JOB]
    await st.set_profile(other, profile("Data Engineer"))
    assert [j for j, _ in await st.recent()] == [other, JOB]
    await st.save_post(post())  # usada de novo
    assert [j for j, _ in await st.recent(1)] == [JOB]

    # run ativa → retomada na mesma etapa e contagem (R5.3)
    run = the_run(s.id)
    await st.save_run(run)
    assert await st.load_active(s.id) == run
    moved = replace(run, stage=1, asked=2, answers=2, last_message_id=7,
                    asked_log=["Tell me about yourself?"])
    await st.save_run(moved)
    assert await st.load_active(s.id) == moved
    assert await st.load_active("LS-20261011-99") is None

    # fim → retorno → unseen uma vez → mark_seen
    assert await st.unseen() is None
    await st.save_run(replace(moved, state=RunState.DEBRIEFING), end_reason="voice")
    assert await st.load_active(s.id) is None
    await st.save_debrief(the_debrief(run.id))
    assert await st.unseen() == the_debrief(run.id)
    await st.mark_seen(run.id)
    assert await st.unseen() is None
    assert await repo.mark_seen(run.id) is False

    # trocar de vaga fecha a anterior sem retorno (spec §10)
    run2 = the_run(s.id, 2, other)
    await st.save_run(run2)
    await st.save_run(run2, end_reason="replaced")
    assert await st.load_active(s.id) is None and await st.unseen() is None


async def test_retorno_de_run_desconhecida_e_perfil_de_vaga_desconhecida(repo) -> None:
    assert await repo.save_debrief(the_debrief("IV-20261011-07")) is False
    assert await repo.set_profile("JOB-ffffffff", profile()) is False
    assert await repo.get_job("JOB-ffffffff") is None


async def test_estado_done_encerra_sem_end_reason(repo) -> None:
    st = InterviewStore(repo, clock=Clock())
    s = await repo.open_session(level="B2", track="CONVERSATION", at=T0)
    await st.save_post(post())
    run = the_run(s.id)
    await st.save_run(replace(run, state=RunState.DONE))
    assert await st.load_active(s.id) is None


def test_jsonl_recarrega_do_disco(tmp_path) -> None:
    import asyncio

    async def go() -> None:
        root = tmp_path / "learning"
        a = JsonlRepo(root)
        st = InterviewStore(a, clock=Clock())
        s = await a.open_session(level="B2", track="CONVERSATION", at=T0)
        await st.save_post(post())
        await st.set_profile(JOB, profile())
        run = replace(the_run(s.id), stage=1, asked=1)
        await st.save_run(run)
        b = InterviewStore(JsonlRepo(root))
        assert await b.profile_of(JOB) == profile()
        assert await b.load_active(s.id) == run
        await st.save_run(run, end_reason="voice")
        await st.save_debrief(the_debrief(run.id))
        c = InterviewStore(JsonlRepo(root))
        assert await c.load_active(s.id) is None
        assert await c.unseen() == the_debrief(run.id)
        await c.mark_seen(run.id)
        assert await InterviewStore(JsonlRepo(root)).unseen() is None
        assert (root / "jobs.jsonl").exists()

    asyncio.run(go())


# --- migração ---------------------------------------------------------------------------------


def test_migracao_aditiva_sem_tocar_003() -> None:
    text = SQL_FILE.read_text(encoding="utf-8")
    code = "\n".join(line.split("--")[0] for line in text.splitlines()).upper()
    assert "DROP" not in code and "ALTER" not in code and "DELETE" not in code
    assert "UPDATE " not in code and "INSERT" not in code
    creates = re.findall(r"CREATE (?:TABLE|INDEX) (IF NOT EXISTS )?(\w+)", code)
    assert creates and all(ine for ine, _ in creates)
    assert {name.lower() for _, name in creates} == {
        "learning_jobs", "learning_interviews", "learning_interviews_session"}
    assert ("004", "learning_jobs") in [(m.version, m.name) for m in mig.available_migrations()]


@pytest.mark.db
def test_migracao_no_fixture_nao_muda_tabelas_003(tmp_path) -> None:
    admin = _admin()
    drop = sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(SCHEMA))
    admin.execute(drop)
    only_003 = tmp_path / "mig"
    only_003.mkdir()
    for m in mig.available_migrations():
        if m.version <= "003":
            shutil.copy(m.path, only_003 / m.path.name)

    def columns(c) -> list[tuple]:
        return list(c.execute(
            "SELECT table_name, column_name, data_type, is_nullable, column_default"
            " FROM information_schema.columns WHERE table_schema = %s"
            " AND table_name LIKE 'learning\\_%%' AND table_name NOT IN"
            " ('learning_jobs', 'learning_interviews') ORDER BY 1, 2", [SCHEMA]))

    try:
        with psycopg.connect(mig.dsn_from_env()) as c:
            mig.migrate(c, schema=SCHEMA, memories_dim=3, news_dim=2, directory=only_003)
            before = columns(c)
            assert mig.migrate(c, schema=SCHEMA, memories_dim=3, news_dim=2) == ["004", "005", "006"]
            assert columns(c) == before and before
            assert mig.migrate(c, schema=SCHEMA, memories_dim=3, news_dim=2) == []
            c.execute(SQL_FILE.read_text(encoding="utf-8"))  # IF NOT EXISTS: rodar de novo não falha
            tables = {r[0] for r in c.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = %s", [SCHEMA])}
            assert {"learning_jobs", "learning_interviews"} <= tables
    finally:
        admin.execute(drop)  # só o schema de teste
        admin.close()
