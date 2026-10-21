"""Banco da Ayanami e migração do PC (Y0.3; spec §3, CA-Y11, CA-Y12, [DS3], [DS5])."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import psycopg
import pytest

from ayanami import migrar as mod
from ayanami.db import ConexaoUnica, Db, DbError, dsn_padrao, recusar_magi, transacao
from magi.memory import migrate as pc_migrate

RAIZ = Path(__file__).resolve().parents[2]
PC_005 = RAIZ / "magi/memory/migrations/005_ayanami_sync.sql"
PC_006 = RAIZ / "magi/memory/migrations/006_turns_nuvem_uid.sql"
PROIBIDO = re.compile(r"\b(DROP|TRUNCATE)\b", re.IGNORECASE)

TABELAS = {
    "schema_migracoes",
    "dispositivos",
    "pareamentos",
    "tarefas",
    "eventos",
    "auditoria",
    "push_assinaturas",
    "confirmacoes",
    "nuvem_turnos",
    "costs",
    "custos_pc",
    "backups",
    "restore_testes",
    "workers_batimento",
    "news_sources",
    "news_raw",
    "news_items",
    "news_item_sources",
    "franchise_prefs",
    "progress",
    "news_feedback",
}


# --- sem banco ---------------------------------------------------------------


def test_lista_migracoes():
    assert [(m.version, m.name) for m in mod.migracoes()] == [("001", "base"), ("002", "noticias")]


def test_migracoes_sem_drop_nem_truncate():
    """CA-Y11 (parte em texto): nenhuma migração da Ayanami nem a 005 do PC apaga nada."""
    arquivos = [m.path for m in mod.migracoes()] + [PC_005, PC_006]
    for arq in arquivos:
        texto = arq.read_text(encoding="utf-8")
        assert not PROIBIDO.search(texto), arq.name


def test_005_do_pc_e_aditiva():
    texto = PC_005.read_text(encoding="utf-8")
    comandos = [c.strip() for c in re.sub(r"--[^\n]*", "", texto).split(";") if c.strip()]
    assert comandos == [
        "ALTER TABLE news_items ADD COLUMN IF NOT EXISTS ayanami_uid uuid UNIQUE",
        "ALTER TABLE costs ADD COLUMN IF NOT EXISTS origem_uid uuid UNIQUE",
    ]
    assert "005" in [m.version for m in pc_migrate.available_migrations()]


def test_006_do_pc_e_aditiva():
    """Y6.5b: só colunas novas nulas e índice único parcial, tudo reexecutável."""
    texto = PC_006.read_text(encoding="utf-8")
    comandos = [c.strip() for c in re.sub(r"--[^\n]*", "", texto).split(";") if c.strip()]
    assert comandos == [
        "ALTER TABLE turns ADD COLUMN IF NOT EXISTS nuvem_uid uuid",
        "ALTER TABLE turns ADD COLUMN IF NOT EXISTS ferramentas jsonb",
        "CREATE UNIQUE INDEX IF NOT EXISTS turns_nuvem_uid_key ON turns (nuvem_uid)"
        " WHERE nuvem_uid IS NOT NULL",
    ]
    assert [m.version for m in pc_migrate.available_migrations()][-1] == "006"


def test_002_e_copia_das_noticias_do_pc_com_o_mesmo_renderizador():
    pc = pc_migrate.available_migrations()[0].render({"MEMORIES_DIM": 1536, "NEWS_DIM": 384})
    nossa = mod.migracoes()[1].render({"NEWS_DIM": 384})
    for tabela in (
        "news_sources",
        "news_raw",
        "news_items",
        "news_item_sources",
        "franchise_prefs",
        "progress",
        "news_feedback",
    ):
        bloco = re.search(rf"CREATE TABLE {tabela} \(.*?\n\);", pc, re.DOTALL)
        assert bloco and bloco.group(0) in nossa, tabela
    assert "vector(384)" in nossa and "{{" not in nossa
    with pytest.raises(ValueError):
        mod.migracoes()[1].render({})


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://magi:magi@127.0.0.1:54329/magi",
        "postgresql://x:y@127.0.0.1:54329/outra",
        "postgresql://x:y@127.0.0.1:54340/magi",
        "host=127.0.0.1 port=54329 dbname=ayanami",
    ],
)
def test_recusa_o_banco_do_pc(dsn):
    with pytest.raises(DbError):
        recusar_magi(dsn)


def test_aceita_o_banco_de_teste_e_o_da_ayanami():
    recusar_magi("postgresql://ayanami:teste@127.0.0.1:54340/ayanami_teste")
    recusar_magi("postgresql://ayanami:x@ayanami-pg:5432/ayanami")


def test_fixture_recusa_a_porta_54329():
    spec = importlib.util.spec_from_file_location(
        "_conftest_ayanami", Path(__file__).with_name("conftest.py")
    )
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    validar_dsn_teste = modulo.validar_dsn_teste

    with pytest.raises(pytest.fail.Exception):
        validar_dsn_teste("postgresql://magi:magi@127.0.0.1:54329/magi")
    with pytest.raises(pytest.fail.Exception):
        validar_dsn_teste("postgresql://a:b@127.0.0.1:54340/magi")
    assert validar_dsn_teste("postgresql://a:b@127.0.0.1:54340/x") == "postgresql://a:b@127.0.0.1:54340/x"


def test_dsn_padrao():
    assert dsn_padrao({"AYANAMI_DB_DSN": "postgresql://a@h/b"}) == "postgresql://a@h/b"
    assert dsn_padrao({"POSTGRES_PASSWORD": "s/e@nha"}) == (
        "postgresql://ayanami:s%2Fe%40nha@ayanami-pg:5432/ayanami"
    )
    assert dsn_padrao({"POSTGRES_PASSWORD": "x", "PGHOST": "h", "PGPORT": "6000"}) == (
        "postgresql://ayanami:x@h:6000/ayanami"
    )
    with pytest.raises(DbError) as e:
        dsn_padrao({})
    assert "POSTGRES_PASSWORD" in str(e.value)


def test_cli_recusa_magi_pg_sem_conectar(capsys):
    assert mod.cli(["--dsn", "postgresql://magi:magi@127.0.0.1:54329/magi", "--dim", "768"]) == 1
    assert "54329" in capsys.readouterr().err


def test_cli_le_dim_da_config(tmp_path, monkeypatch):
    exemplo = (RAIZ / "deploy/ayanami/ayanami.example.toml").read_text(encoding="utf-8")
    cfg = tmp_path / "ayanami.toml"
    cfg.write_text(exemplo.replace("dim = 768", "dim = 384"), encoding="utf-8")
    vistos = {}

    def falso_migrar(conn, *, dim):
        vistos["dim"] = dim
        return []

    class ConexaoFalsa:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(mod, "migrar", falso_migrar)
    monkeypatch.setattr(mod.psycopg, "connect", lambda *a, **k: ConexaoFalsa())
    assert mod.cli(["--dsn", "postgresql://a:b@127.0.0.1:54340/x", "--config", str(cfg)]) == 0
    assert vistos["dim"] == 384


def test_migrar_recusa_dim_fora_da_faixa():
    with pytest.raises(ValueError):
        mod.migrar(None, dim=0)  # type: ignore[arg-type]


# --- com o ayanami-pg-teste ----------------------------------------------------


def _tabelas(conn) -> set[str]:
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    ).fetchall()
    return {r[0] for r in rows}


def _dim(conn, tabela: str) -> int:
    return conn.execute(
        "SELECT a.atttypmod FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid"
        " WHERE c.relname = %s AND a.attname = 'embedding'",
        [tabela],
    ).fetchone()[0]


@pytest.mark.pg
def test_ca_y11_banco_vazio_aplica_e_e_idempotente(pg_nova_base):
    dsn = pg_nova_base()
    with psycopg.connect(dsn) as conn:
        assert mod.migrar(conn, dim=384) == ["001", "002"]
        assert _tabelas(conn) == TABELAS
        assert _dim(conn, "news_items") == 384
        assert mod.migrar(conn, dim=384) == []
        assert mod.aplicadas(conn) == ["001", "002"]
    assert mod.cli(["--dsn", dsn, "--dim", "384"]) == 0


@pytest.mark.pg
def test_news_items_uid_e_gatilho_atualizado(pg):
    with transacao(ConexaoUnica(pg)) as c:
        uid, antes = c.execute(
            "INSERT INTO news_items (title) VALUES ('x') RETURNING uid, atualizado"
        ).fetchone()
    assert uid is not None
    with transacao(ConexaoUnica(pg)) as c:
        (depois,) = c.execute(
            "UPDATE news_items SET title = 'y' WHERE uid = %s RETURNING atualizado", [uid]
        ).fetchone()
    assert depois > antes
    idx = pg.execute(
        "SELECT indexdef FROM pg_indexes WHERE indexname = 'news_items_atualizado_idx'"
    ).fetchone()
    assert idx and "(atualizado, id)" in idx[0]


@pytest.mark.pg
def test_ca_y12_chave_viva(pg):
    sql_ins = "INSERT INTO tarefas (tipo, titulo, chave) VALUES ('pesquisa', 't', %s) RETURNING id"
    chave = "ca-y12-chave"
    with pg.transaction():
        (id1,) = pg.execute(sql_ins, [chave]).fetchone()
    for estado in ("na_fila", "rodando"):
        with pg.transaction():
            pg.execute("UPDATE tarefas SET estado = %s WHERE id = %s", [estado, id1])
        with pytest.raises(psycopg.errors.UniqueViolation), pg.transaction():
            pg.execute(sql_ins, [chave])
    with pg.transaction():
        pg.execute("UPDATE tarefas SET estado = 'ok' WHERE id = %s", [id1])
        pg.execute(sql_ins, [chave])


@pytest.mark.pg
def test_ca_y12_um_pc_nao_revogado(pg):
    ins = "INSERT INTO dispositivos (nome, tipo, escopos, hash, prefixo) VALUES (%s, %s, '{}', %s, 'ayn_')"
    with pg.transaction():
        pg.execute(ins, ["pc-a", "pc", "h-pc-a"])
        pg.execute(ins, ["cel-a", "celular", "h-cel-a"])
        pg.execute(ins, ["cel-b", "celular", "h-cel-b"])
    with pytest.raises(psycopg.errors.UniqueViolation), pg.transaction():
        pg.execute(ins, ["pc-b", "pc", "h-pc-b"])
    with pg.transaction():
        pg.execute("UPDATE dispositivos SET revogado = now() WHERE nome = 'pc-a'")
        pg.execute(ins, ["pc-b", "pc", "h-pc-b"])
    for nome in ("ayanami", "Maiusc", "-x"):
        with pytest.raises(psycopg.errors.CheckViolation), pg.transaction():
            pg.execute(ins, [nome, "casa", f"h-{nome}"])


@pytest.mark.pg
def test_db_protocolo_e_pool(pg_base):
    pytest.importorskip("psycopg_pool")
    from ayanami.db import abrir_pool

    with abrir_pool(pg_base, minimo=1, maximo=2) as pool:
        assert isinstance(pool, Db)
        with transacao(pool) as c:
            assert c.execute("SELECT count(*) FROM schema_migracoes").fetchone() == (2,)


@pytest.mark.pg
def test_005_no_banco_do_pc(pg_base_pc):
    with psycopg.connect(pg_base_pc) as conn:
        versoes = [r[0] for r in conn.execute("SELECT version FROM schema_migrations ORDER BY 1")]
        assert versoes[-2:] == ["005", "006"]
        colunas = conn.execute(
            "SELECT table_name, column_name, is_nullable FROM information_schema.columns"
            " WHERE column_name IN ('ayanami_uid', 'origem_uid') ORDER BY 1"
        ).fetchall()
        assert colunas == [("costs", "origem_uid", "YES"), ("news_items", "ayanami_uid", "YES")]
        # reexecutável (o núcleo aplica sozinho; rodar o texto de novo não muda nada)
        indices_antes = conn.execute("SELECT count(*) FROM pg_indexes WHERE schemaname = 'public'").fetchone()
        with conn.transaction():
            conn.execute(PC_005.read_text(encoding="utf-8").encode())
        indices_depois = conn.execute(
            "SELECT count(*) FROM pg_indexes WHERE schemaname = 'public'"
        ).fetchone()
        assert indices_antes == indices_depois
