"""Repositório do Learning Mode (tarefa LM1.1; spec §8, §10–§10.3; CA-16, parte de repo do CA-22).

Os testes rodam nos dois backends: ``jsonl`` (pasta temporária) e ``postgres`` (schema
``learning_test``, apagado no fim por ele mesmo; pulado sem banco no ar). Nunca o ``public``.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from psycopg import sql

from magi.learning.config import LearningConfig
from magi.learning.contracts import (
    ActionKind,
    ActionResult,
    Author,
    ObsCategory,
    Observation,
    SavedWord,
    SessionSummary,
    Source,
    Topic,
)
from magi.learning.repo import (
    JsonlRepo,
    LearningRepo,
    PostgresRepo,
    make_repo,
    normalize_term,
)
from magi.memory import migrate as mig
from magi.memory.conn import SerialConn

SCHEMA = f"learning_test_{os.getpid()}"  # por processo: rodadas em paralelo não se apagam
T0 = datetime(2026, 10, 7, 15, 0, tzinfo=UTC)
DAY = T0.astimezone().strftime("%Y%m%d")


async def _pg_connect():
    raw = await psycopg.AsyncConnection.connect(mig.dsn_from_env())
    await raw.execute("SELECT set_config('search_path', %s, false)", [f'"{SCHEMA}", public'])
    await raw.commit()
    return raw


@pytest.fixture
def pg_schema():
    try:
        admin = psycopg.connect(mig.dsn_from_env(), autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres indisponível: {exc}")
    drop = sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(SCHEMA))
    admin.execute(drop)
    try:
        with psycopg.connect(mig.dsn_from_env()) as c:
            mig.migrate(c, schema=SCHEMA, memories_dim=3, news_dim=2)
        yield
    finally:
        admin.execute(drop)  # só o schema de teste (regra 6 de tasks.md)
        admin.close()


@pytest.fixture(params=["jsonl", pytest.param("postgres", marks=pytest.mark.db)])
async def repo(request, tmp_path):
    if request.param == "jsonl":
        yield JsonlRepo(tmp_path / "learning")
        return
    request.getfixturevalue("pg_schema")
    raw = await _pg_connect()
    try:
        yield PostgresRepo(SerialConn(raw))
    finally:
        await raw.close()


async def _session_with_msg(repo, text="I goed to the store yesterday."):
    s = await repo.open_session(level="B2", track="CONVERSATION", at=T0)
    m = await repo.add_message(s.id, Author.YOU, Source.VOICE, text, at=T0 + timedelta(seconds=5))
    return s, m


def _obs(session_id, message_id, rule_key="grammar.past_simple.irregular", **kw):
    base = dict(id=None, session_id=session_id, message_id=message_id, category=ObsCategory.GRAMMAR,
                rule_key=rule_key, label="Past tense", span="goed", suggestion="went")
    base.update(kw)
    return Observation(**base)


def _word(session_id, message_id, term="Trade-off", action_id="ACT-0000abcd", at=T0):
    return SavedWord(None, normalize_term(term), term, "compromisso", "noun", "B2",
                     "There is a trade-off here.", session_id, message_id, action_id, at, None)


# --- funções puras -----------------------------------------------------------------------------


def test_normalize_term():
    assert normalize_term("  Trade-Off!") == "trade-off"
    assert normalize_term('"Look   Forward  To,"') == "look forward to"
    assert normalize_term("repository") == "repository"


def test_make_repo(tmp_path):
    assert isinstance(make_repo(LearningConfig(storage="jsonl"), jsonl_dir=tmp_path), JsonlRepo)
    with pytest.raises(ValueError):
        make_repo(LearningConfig(storage="postgres"))
    assert isinstance(make_repo(LearningConfig(), conn=object()), PostgresRepo)


# --- sessão ------------------------------------------------------------------------------------


async def test_sessao_ids_tema_e_fechamento(repo):
    assert isinstance(repo, LearningRepo)
    s1 = await repo.open_session(level="B2", track="CONVERSATION", at=T0)
    s2 = await repo.open_session(level="B2", track="CONVERSATION", at=T0 + timedelta(minutes=1))
    assert (s1.id, s2.id) == (f"LS-{DAY}-01", f"LS-{DAY}-02")
    assert s1.topic is Topic.FREE and [t for t, _ in s1.topics] == [Topic.FREE]

    assert await repo.set_topic(s1.id, Topic.GAME, T0 + timedelta(minutes=2)) is True
    assert await repo.set_topic(s1.id, Topic.GAME, T0 + timedelta(minutes=3)) is False  # só confirma
    assert await repo.set_topic(s1.id, Topic.NEWS, T0 + timedelta(minutes=4)) is True
    got = await repo.get_session(s1.id)
    assert got.topic is Topic.NEWS
    assert [t for t, _ in got.topics] == [Topic.FREE, Topic.GAME, Topic.NEWS]
    assert got.topics[1][1] == T0 + timedelta(minutes=2)

    assert (await repo.open_session_last()).id == s2.id
    await repo.end_session(s2.id, "button", T0 + timedelta(minutes=5))
    assert (await repo.open_session_last()).id == s1.id
    ended = await repo.get_session(s2.id)
    assert ended.end_reason == "button" and ended.ended_at == T0 + timedelta(minutes=5)
    assert await repo.get_session("LS-20000101-01") is None


async def test_mensagens(repo):
    s, m = await _session_with_msg(repo)
    assert m.id > 0 and m.author is Author.YOU and m.source is Source.VOICE
    for i in range(4):
        at = T0 + timedelta(seconds=10 + i)
        await repo.add_message(s.id, Author.CONDESSA, Source.TEXT, f"reply {i}", at=at)
    assert await repo.get_message(m.id) == m
    recent = await repo.recent_messages(s.id, limit=3)
    assert [x.text for x in recent] == ["reply 1", "reply 2", "reply 3"]
    assert len(await repo.recent_messages(s.id)) == 5


# --- CA-16: observações com rule_key e session_id ----------------------------------------------


async def test_ca16_observacao_exige_rule_key_e_sessao(repo):
    s, m = await _session_with_msg(repo)
    saved = await repo.add_observation(_obs(s.id, m.id), model="fake")
    assert saved.id is not None and saved.rule_key and saved.session_id == s.id
    for bad in (_obs(s.id, m.id, rule_key=""), _obs(s.id, m.id, rule_key="   "), _obs("", m.id)):
        with pytest.raises(ValueError):
            await repo.add_observation(bad)
    obs = await repo.observations(s.id)
    assert len(obs) == 1
    assert all(o.rule_key.strip() and o.session_id == s.id for o in obs)


@pytest.mark.db
async def test_ca16_no_banco(pg_schema):
    raw = await _pg_connect()
    try:
        repo = PostgresRepo(SerialConn(raw))
        s, m = await _session_with_msg(repo)
        await repo.add_observation(_obs(s.id, m.id))
        await repo.add_observation(_obs(s.id, m.id, "vocab.repository", category=ObsCategory.VOCABULARY))
        cur = await raw.execute(
            "SELECT count(*) FROM learning_observations WHERE rule_key = '' OR session_id IS NULL")
        assert (await cur.fetchone())[0] == 0
        cur = await raw.execute("SELECT count(*) FROM learning_observations")
        assert (await cur.fetchone())[0] == 2
    finally:
        await raw.close()


# --- ações -------------------------------------------------------------------------------------


async def test_acao_cache_e_por_id(repo):
    s, m = await _session_with_msg(repo)
    res = ActionResult("ACT-1f9a02c4", ActionKind.VOCABULARY, True,
                       {"term": "goed", "meaning": "x"}, None, False, 812, 0.0012)
    assert await repo.cached_action(m.id, ActionKind.VOCABULARY, 2, 6) is None
    await repo.save_action(res, message_id=m.id, sel_start=2, sel_end=6, model="fake")
    await repo.save_action(res, message_id=m.id, sel_start=2, sel_end=6)  # repetido: ignora
    hit = await repo.cached_action(m.id, ActionKind.VOCABULARY, 2, 6)
    assert hit is not None and hit.cached and hit.data == res.data and hit.id == res.id
    assert await repo.cached_action(m.id, ActionKind.EXPLAIN, 2, 6) is None
    stored = await repo.get_action(res.id)
    assert (stored.message_id, stored.sel_start, stored.sel_end) == (m.id, 2, 6)
    assert stored.result.kind is ActionKind.VOCABULARY
    assert await repo.get_action("ACT-ffffffff") is None


# --- CA-22 (parte do repo): um ativo por norm; desfazer por removed_at ---------------------------


async def test_ca22_salvar_desfazer_salvar_de_novo(repo):
    s, m = await _session_with_msg(repo)
    w1 = await repo.save_word(_word(s.id, m.id))
    assert w1.id is not None and w1.norm == "trade-off" and w1.removed_at is None
    again = await repo.save_word(_word(s.id, m.id, term="trade-off."))  # mesmo norm ativo
    assert again.id == w1.id
    assert await repo.saved_norms() == {"trade-off"}
    assert [w.norm for w in await repo.saved_words(s.id)] == ["trade-off"]

    assert await repo.unsave_word("trade-off", T0 + timedelta(minutes=1)) is True
    assert await repo.unsave_word("trade-off") is False
    assert await repo.saved_norms() == set()

    w2 = await repo.save_word(_word(s.id, m.id))
    assert w2.id != w1.id and w2.removed_at is None
    assert await repo.saved_norms() == {"trade-off"}


@pytest.mark.db
async def test_ca22_no_banco_um_ativo_por_norm(pg_schema):
    raw = await _pg_connect()
    try:
        repo = PostgresRepo(SerialConn(raw))
        s, m = await _session_with_msg(repo)
        await repo.save_word(_word(s.id, m.id))  # action_id inexistente vira NULL (sem cache)
        await repo.unsave_word("trade-off")
        await repo.save_word(_word(s.id, m.id))
        cur = await raw.execute(
            "SELECT count(*), count(*) FILTER (WHERE removed_at IS NULL), count(action_id)"
            " FROM learning_saved_words WHERE norm = 'trade-off'")
        assert await cur.fetchone() == (2, 1, 0)
        with pytest.raises(psycopg.errors.UniqueViolation):
            async with raw.transaction():
                await raw.execute(
                    "INSERT INTO learning_saved_words (norm, term, meaning, example, session_id, message_id)"
                    " VALUES ('trade-off', 'x', 'x', 'x', %s, %s)", [s.id, m.id])
    finally:
        await raw.close()


# --- resumo ------------------------------------------------------------------------------------


async def test_session_stats_e_resumo(repo):
    s, m = await _session_with_msg(repo)
    await repo.add_message(s.id, Author.CONDESSA, Source.TEXT, "Nice!", at=T0 + timedelta(minutes=3))
    await repo.add_observation(_obs(s.id, m.id))
    await repo.save_word(_word(s.id, m.id))
    st = await repo.session_stats(s.id)
    assert (st.n_msgs, st.n_you) == (2, 1)
    assert st.last_msg_at == T0 + timedelta(minutes=3)
    assert [o.rule_key for o in st.observations] == ["grammar.past_simple.irregular"]
    assert [w.norm for w in st.saved] == ["trade-off"]
    assert st.session.started_at == T0
    assert await repo.session_stats("LS-20000101-01") is None

    summary = SessionSummary(s.id, 1, T0, T0 + timedelta(minutes=20), 180, "button", 2, 1, 1,
                             ["Past tense"], ["trade-off"], ["trade-off"], 0, 0, ["free"])
    await repo.save_summary(s.id, summary)
    await repo.save_summary(s.id, replace(summary, n_msgs=3))  # regravado a cada fechamento
    assert (await repo.get_session(s.id)).summary == replace(summary, n_msgs=3)


# --- JSONL: persistência -----------------------------------------------------------------------


async def test_jsonl_recarrega_do_disco(tmp_path):
    root = tmp_path / "lm"
    r1 = JsonlRepo(root)
    s, m = await _session_with_msg(r1)
    await r1.set_topic(s.id, Topic.INTERVIEW, T0 + timedelta(minutes=1))
    await r1.add_observation(_obs(s.id, m.id))
    await r1.save_word(_word(s.id, m.id))
    await r1.save_word(_word(s.id, m.id, term="repository"))
    await r1.unsave_word("repository")
    (root / f"{s.id}.jsonl").open("a").write("{quebrada\n")

    r2 = JsonlRepo(root)
    got = await r2.get_session(s.id)
    assert got.topic is Topic.INTERVIEW and len(got.topics) == 2
    assert await r2.recent_messages(s.id) == [m]
    assert len(await r2.observations(s.id)) == 1
    assert await r2.saved_norms() == {"trade-off"}
    m2 = await r2.add_message(s.id, Author.CONDESSA, Source.TEXT, "ok")
    assert m2.id == m.id + 1
    s2 = await r2.open_session(level=None, track=None, at=T0)
    assert s2.id == f"LS-{DAY}-02"
    kinds = [json.loads(line)["kind"] for line in (root / f"{s.id}.jsonl").read_text().splitlines()
             if line.startswith("{\"")]
    assert {"session", "msg", "topic", "obs"} <= set(kinds)
    ops = [json.loads(line)["op"] for line in (root / "saved_words.jsonl").read_text().splitlines()]
    assert ops == ["save", "save", "unsave"]


# --- Postgres: banco cai, buffer em memória, grava na volta -----------------------------------


@pytest.mark.db
async def test_postgres_buffer_quando_banco_cai(pg_schema):
    conns = [await _pg_connect()]

    async def reconnect():
        conns.append(await _pg_connect())
        return conns[-1]

    repo = PostgresRepo(conns[0], buffer_max=500)
    try:
        s, m = await _session_with_msg(repo)
        await conns[0].close()  # banco "cai" (sem reconexão por enquanto)
        repo._reconnect = None
        at = T0 + timedelta(minutes=1)
        tmp = await repo.add_message(s.id, Author.YOU, Source.TEXT, "We was late.", at=at)
        assert tmp.id < 0 and repo.pending == 1
        await repo.add_observation(_obs(s.id, tmp.id, "grammar.agreement.was_were", label="was/were"))
        await repo.set_topic(s.id, Topic.GAME, T0 + timedelta(minutes=2))
        assert await repo.cached_action(tmp.id, ActionKind.EXPLAIN, 0, 2) is None  # ações sem cache
        st = await repo.session_stats(s.id)  # do buffer
        assert st is not None and st.n_you == 1 and len(st.observations) == 1
        assert repo.pending == 3

        repo._reconnect = reconnect  # banco volta
        assert await repo.flush() == 3 and repo.pending == 0
        msgs = await repo.recent_messages(s.id)
        assert [x.text for x in msgs] == [m.text, "We was late."]
        real = msgs[-1].id
        assert real > 0 and await repo.get_message(tmp.id) == msgs[-1]  # ID provisório traduzido
        obs = await repo.observations(s.id)
        assert [(o.message_id, o.rule_key) for o in obs] == [(real, "grammar.agreement.was_were")]
        assert (await repo.get_session(s.id)).topic is Topic.GAME
    finally:
        for c in conns:
            await c.close()


@pytest.mark.db
async def test_postgres_buffer_limite(pg_schema):
    raw = await _pg_connect()
    repo = PostgresRepo(raw, buffer_max=3)
    s, _ = await _session_with_msg(repo)
    await raw.close()
    for i in range(5):
        await repo.add_message(s.id, Author.YOU, Source.TEXT, f"m{i}")
    assert repo.pending == 3
