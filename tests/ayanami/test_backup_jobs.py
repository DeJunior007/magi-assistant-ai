"""Jobs de backup da Ayanami (Y4.2; CA-Y24, spec §7.2/§7.3). Executor, Telegram e relógio falsos."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest

from ayanami.config import de_dict
from ayanami.deps import Deps
from ayanami.migrar import migrar
from ayanami.relogio import RelogioFalso
from ayanami.workers import backup as bk
from ayanami.workers.backup import Comando, ComandoProibido, Resultado

URL = "https://ayanami.exemplo.ts.net"
SEGREDOS = {
    "B2_ACCOUNT_ID": "id-falso",
    "B2_ACCOUNT_KEY": "chave-falsa",
    "B2_BUCKET": "balde-falso",
    "RESTIC_PASSWORD": "senha-falsa",
    "TELEGRAM_BOT_TOKEN": "bot-falso",
    "TELEGRAM_CHAT_ID": "1",
}
TS = int(datetime(2026, 10, 20, 12, 0, tzinfo=bk.FUSO).timestamp())
DATA = "2026-10-20"


class Executor:
    """Captura cada :class:`Comando`; ``respostas(cmd)`` pode devolver um ``Resultado`` e mexer em disco."""

    def __init__(self, respostas: Callable[[Comando], Resultado | None] | None = None) -> None:
        self.cmds: list[Comando] = []
        self.respostas = respostas

    def __call__(self, cmd: Comando) -> Resultado:
        self.cmds.append(cmd)
        r = self.respostas(cmd) if self.respostas else None
        if r is not None:
            return r
        if cmd.saida is not None:
            cmd.saida.write_bytes(b"dump falso")
        if cmd.argv[:2] == ("restic", "backup"):
            return Resultado(0, "snapshot 1a2b3c4d saved\n")
        return Resultado(0, "")

    @property
    def argvs(self) -> list[tuple[str, ...]]:
        return [c.argv for c in self.cmds]


class TelegramFalso:
    def __init__(self) -> None:
        self.textos: list[str] = []

    async def enviar(self, texto: str) -> bool:
        self.textos.append(texto)
        return True


class DbConexao:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(self.dsn) as conn:
            yield conn


def _deps(db: Any, dados: Path, executor: Executor, **backup: Any) -> Deps:
    cfg = de_dict({"geral": {"url_base": URL}, "backup": backup} if backup else {"geral": {"url_base": URL}})
    return Deps(
        db=db,
        cfg=cfg,
        relogio=RelogioFalso(),
        dados=dados,
        budget=object(),
        extras={
            "executor": executor,
            "segredos": dict(SEGREDOS),
            "telegram": TelegramFalso(),
            "opt_config": "/opt-config",
        },
    )


# --------------------------------------------------------------------------- sem banco


@pytest.mark.parametrize(
    "argv",
    [
        ("restic", "forget", "--tag", "pc", "--prune"),
        ("restic", "forget", "--group-by", "host,tags", "--tag", "pc", "--keep-daily", "7", "--prune"),
        ("restic", "forget", "--group-by", "host", "--tag", "pc", *bk.KEEP),
        ("restic", "unlock"),
        ("docker", "rm", "-f", "x"),
        ("docker", "volume", "ls"),
        ("docker", "compose", "ps"),
        ("docker", "exec", "magi-pg", "pg_dump", "-Fc"),
        ("docker", "exec", "ayanami-pg", "psql", "-c", "SELECT 1"),
        ("docker", "exec", bk.RESTORE, "bash"),
        ("docker", "exec", bk.RESTORE, "pg_restore", "--if-exists", "/tmp/x"),
        ("docker", "exec", bk.RESTORE, "psql", "-U", "postgres", "-Atc", "DELETE FROM x"),
        ("docker", "run", "-d", "--rm", "--name", "outro", "--network", "none", bk.IMAGEM_RESTORE),
        ("docker", "run", "-d", "--rm", "--name", bk.RESTORE, bk.IMAGEM_RESTORE),
        (
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            bk.RESTORE,
            "--network",
            "none",
            "-v",
            "/:/h",
            bk.IMAGEM_RESTORE,
        ),
        (
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            bk.RESTORE,
            "--network",
            "none",
            "-p",
            "5432:5432",
            bk.IMAGEM_RESTORE,
        ),
        ("docker", "stop", "ayanami-pg"),
        ("docker", "cp", "/x", "ayanami-pg:/tmp/x"),
        ("rm", "-rf", "/dados"),
        ("tar", "-cf", "x", "y"),
    ],
)
def test_lista_branca_recusa(argv):
    with pytest.raises(ComandoProibido):
        bk.checar_comando(Comando(argv))


def test_ambiente_restic_sem_segredo_diz_so_os_nomes(tmp_path):
    with pytest.raises(bk.ErroBackup) as e:
        bk.ambiente_restic({"B2_BUCKET": "b"}, tmp_path)
    assert "RESTIC_PASSWORD" in str(e.value) and "B2_BUCKET" not in str(e.value)
    env = bk.ambiente_restic(SEGREDOS, tmp_path)
    assert env["RESTIC_REPOSITORY"] == "b2:balde-falso:magi"
    assert env["RESTIC_CACHE_DIR"] == str(tmp_path / "restic-cache")


def test_comando_nao_mostra_env_no_repr():
    assert "senha-falsa" not in repr(Comando(("restic", "init"), env={"RESTIC_PASSWORD": "senha-falsa"}))


def test_cli_iniciar(capsys):
    ex = Executor()
    assert bk.cli(["iniciar"], executor=ex, env=SEGREDOS) == 0
    assert ex.argvs == [("restic", "init")]
    assert ex.cmds[0].env["RESTIC_REPOSITORY"] == "b2:balde-falso:magi"
    ja = Executor(lambda c: Resultado(1, "", "Fatal: create repository failed: config file already exists"))
    assert bk.cli(["iniciar"], executor=ja, env=SEGREDOS) == 0
    assert bk.cli(["iniciar"], executor=Executor(lambda c: Resultado(1, "", "rede")), env=SEGREDOS) == 1
    assert bk.cli(["iniciar"], executor=Executor(), env={}) == 2
    assert bk.cli([], executor=Executor(), env=SEGREDOS) == 2
    assert "senha-falsa" not in capsys.readouterr().err


def test_cli_despacha_pelo_ayanami():
    from ayanami import cli

    assert cli.main(["backup"]) == 2  # sem "iniciar": uso + 2, nada roda


async def test_desligado_nao_roda_nada(tmp_path):
    ex = Executor()
    deps = _deps(None, tmp_path, ex, ligado=False)
    for job in (bk.dump_ayanami, bk.enviar, bk.reter, bk.verificar, bk.restore_teste):
        assert await job(deps, None, timestamp=TS) == {"pulado": "desligado"}
    assert await bk.restic(deps, None) == {"pulado": "desligado"}
    assert ex.cmds == []


async def test_reter_e_verificar_batem_com_a_tabela(tmp_path):
    ex = Executor()
    deps = _deps(None, tmp_path, ex)
    await bk.reter(deps, None, timestamp=TS)
    await bk.verificar(deps, None, timestamp=TS)
    keep = ("--keep-daily", "7", "--keep-weekly", "4", "--keep-monthly", "6")
    assert ex.argvs == [
        ("restic", "forget", "--group-by", "host,tags", "--tag", "pc", *keep, "--prune"),
        ("restic", "forget", "--group-by", "host,tags", "--tag", "ayanami", *keep, "--prune"),
        ("restic", "check", "--read-data-subset=5%"),
    ]
    assert all(c.env["RESTIC_PASSWORD"] == "senha-falsa" for c in ex.cmds)


# --------------------------------------------------------------------------- com banco


@pytest.fixture
def db(pg_nova_base) -> DbConexao:
    dsn = pg_nova_base("ayanami_bk")
    with psycopg.connect(dsn) as conn:
        migrar(conn)
    return DbConexao(dsn)


def _recebido(db: DbConexao, dados: Path, manifesto: dict[str, Any], data: str = DATA) -> Path:
    pasta = bk.pasta_pc(dados, data)
    pasta.mkdir(parents=True)
    arq = bk.arquivo_pc(dados, data)
    arq.write_bytes(b"pacote")
    (pasta / bk.MANIFESTO).write_text(json.dumps(manifesto))
    with db.connection() as conn:
        conn.execute(
            "INSERT INTO backups (origem, data, bytes, sha256, manifesto) VALUES ('pc', %s, 6, %s, %s)",
            (data, "a" * 64, json.dumps(manifesto)),
        )
    return pasta


@pytest.mark.pg
async def test_restic_sobe_o_pc_e_grava_snapshot(db, tmp_path):
    pasta = _recebido(db, tmp_path, {"tabelas": {}})
    ex = Executor()
    deps = _deps(db, tmp_path, ex)
    r = await bk.restic(deps, None, data=DATA)
    assert r == {"snapshots": {DATA: "1a2b3c4d"}, "sem_arquivo": []}
    assert ex.argvs == [
        ("restic", "backup", "--host", "ayanami", "--tag", "pc", "--tag", f"d{DATA}", str(pasta))
    ]
    with db.connection() as conn:
        snap, enviado = conn.execute("SELECT snapshot, enviado FROM backups").fetchone()
    assert snap == "1a2b3c4d" and enviado is not None
    assert (await bk.restic(deps, None, data=DATA))["snapshots"] == {}  # já enviado: nada roda
    assert len(ex.cmds) == 1


@pytest.mark.pg
async def test_dump_e_enviar(db, tmp_path):
    ex = Executor(lambda c: Resultado(0, "pg_dump (PostgreSQL) 16.4\n") if "--version" in c.argv else None)
    deps = _deps(db, tmp_path, ex)
    r = await bk.dump_ayanami(deps, None, timestamp=TS)
    pasta = bk.pasta_ayanami(tmp_path, DATA)
    assert r == {"data": DATA, "bytes": len(b"dump falso")}
    assert ex.argvs[0] == ("docker", "exec", "ayanami-pg", "pg_dump", "-Fc", "-U", "ayanami", "ayanami")
    assert ex.cmds[0].saida == pasta / "ayanami.dump"
    man = json.loads((pasta / "manifesto.json").read_text())
    assert man["pg_versao"] == "pg_dump (PostgreSQL) 16.4" and man["tabelas"]["dispositivos"] == 0
    # um pc pendente também sobe no enviar
    pasta_pc = _recebido(db, tmp_path, {"tabelas": {}}, data="2026-10-19")
    ex.cmds.clear()
    r = await bk.enviar(deps, None, timestamp=TS)
    assert ex.argvs == [
        ("restic", "backup", "--host", "ayanami", "--tag", "ayanami", str(pasta), "/opt-config"),
        ("restic", "backup", "--host", "ayanami", "--tag", "pc", "--tag", "d2026-10-19", str(pasta_pc)),
    ]
    assert not any(".env" in a for c in ex.cmds for a in c.argv)
    with db.connection() as conn:
        linhas = conn.execute("SELECT origem, snapshot FROM backups ORDER BY origem").fetchall()
    assert linhas == [("ayanami", "1a2b3c4d"), ("pc", "1a2b3c4d")]


@pytest.mark.pg
async def test_dump_que_falha_nao_deixa_arquivo(db, tmp_path):
    def resp(c: Comando) -> Resultado | None:
        if c.saida is not None:
            c.saida.write_bytes(b"meio")
            return Resultado(1, "", "erro")
        return None

    deps = _deps(db, tmp_path, Executor(resp))
    with pytest.raises(bk.ErroComando):
        await bk.dump_ayanami(deps, None, timestamp=TS)
    assert not (bk.pasta_ayanami(tmp_path, DATA) / "ayanami.dump").exists()


def _restore(manifesto: dict[str, Any], contagens: dict[str, str], prontos_depois: int = 1):
    estado = {"isready": 0}

    def resp(c: Comando) -> Resultado | None:
        a = c.argv
        if a[:2] == ("restic", "restore"):
            alvo = Path(a[a.index("--target") + 1])
            pasta = alvo / "dados/entrada/pc" / DATA
            pasta.mkdir(parents=True)
            (pasta / f"magi-{DATA}.tar.zst").write_bytes(b"pacote")
            return Resultado(0, f"restoring <Snapshot 9f8e7d6c of [/dados/entrada/pc/{DATA}]> to {alvo}\n")
        if a[0] == "tar":
            destino = Path(a[5])
            (destino / "magi-pg.dump").write_bytes(b"dump")
            (destino / "manifesto.json").write_text(json.dumps(manifesto))
            return Resultado(0)
        if "pg_isready" in a:
            estado["isready"] += 1
            return Resultado(0 if estado["isready"] >= prontos_depois else 2)
        if "psql" in a:
            tabela = a[-1].split('"')[1]
            return (
                Resultado(0, contagens.get(tabela, "") + "\n")
                if tabela in contagens
                else Resultado(1, "", "x")
            )
        return None

    return Executor(resp)


def _contar(db: DbConexao, sql: str) -> list[tuple]:
    with db.connection() as conn:
        return conn.execute(sql).fetchall()


@pytest.mark.pg
async def test_restore_verde(db, tmp_path):
    man = {"data": DATA, "tabelas": {"turns": 3, "memories": 2, "costs": None}}
    ex = _restore(man, {"turns": "3", "memories": "2"}, prontos_depois=3)
    deps = _deps(db, tmp_path, ex)
    r = await bk.restore_teste(deps, None, timestamp=TS)
    assert r["verde"] is True and r["snapshot"] == "9f8e7d6c"
    alvo = Path(ex.argvs[0][-1])
    assert ex.argvs[0] == ("restic", "restore", "latest", "--tag", "pc", "--target", str(alvo))
    assert alvo.parent == tmp_path / "tmp" and alvo.name.startswith("restore-")
    run = next(c for c in ex.cmds if c.argv[:2] == ("docker", "run"))
    assert run.argv == (
        "docker",
        "run",
        "-d",
        "--rm",
        "--name",
        "ayanami-restore-teste",
        "--network",
        "none",
        "-e",
        "POSTGRES_PASSWORD",
        "pgvector/pgvector:pg16",
    )
    assert len(run.env["POSTGRES_PASSWORD"]) >= 20 and run.env["POSTGRES_PASSWORD"] not in str(ex.argvs)
    docker = [c.argv for c in ex.cmds if c.argv[0] == "docker"]
    assert {a[1] for a in docker} == {"run", "cp", "exec", "stop"}
    assert all(bk.RESTORE in " ".join(a) for a in docker)
    assert (
        "docker",
        "exec",
        bk.RESTORE,
        "pg_restore",
        "--no-owner",
        "-U",
        "postgres",
        "-d",
        "postgres",
        "--create",
        "/tmp/magi-pg.dump",
    ) in docker
    assert sum("pg_isready" in a for a in docker) == 3 and deps.relogio.agora()  # dormiu no relógio falso
    psql = [a for a in docker if "psql" in a]
    assert [a[-1] for a in psql] == ['SELECT count(*) FROM "memories"', 'SELECT count(*) FROM "turns"']
    assert docker[-1] == ("docker", "stop", bk.RESTORE)
    assert not alvo.exists()
    assert _contar(db, "SELECT verde, snapshot FROM restore_testes") == [(True, "9f8e7d6c")]
    assert _contar(db, "SELECT count(*) FROM eventos") == [(0,)]
    assert "verde" in deps.extras["telegram"].textos[0]


@pytest.mark.pg
async def test_manifesto_divergente_vermelho_evento_e_telegram(db, tmp_path):
    man = {"data": DATA, "tabelas": {"turns": 3, "memories": 2}}
    ex = _restore(man, {"turns": "3", "memories": "1"})
    deps = _deps(db, tmp_path, ex)
    r = await bk.restore_teste(deps, None, timestamp=TS)
    assert r["verde"] is False
    assert r["detalhes"]["divergentes"] == {"memories": {"esperado": 2, "achado": 1}}
    assert ex.argvs[-1] == ("docker", "stop", bk.RESTORE)
    assert not any(p.name.startswith("restore-") for p in (tmp_path / "tmp").iterdir())
    ((verde, det),) = _contar(db, "SELECT verde, detalhes FROM restore_testes")
    assert verde is False and det["divergentes"]["memories"]["achado"] == 1
    assert _contar(db, "SELECT tipo, titulo FROM eventos") == [("backup_falhou", "Restore de teste vermelho")]
    assert "VERMELHO" in deps.extras["telegram"].textos[0] and "memories" in deps.extras["telegram"].textos[0]


@pytest.mark.pg
async def test_restore_que_quebra_no_meio_e_vermelho_e_limpa(db, tmp_path):
    def resp(c: Comando) -> Resultado | None:
        if c.argv[:2] == ("restic", "restore"):
            return Resultado(1, "", "Fatal: no snapshot found")
        return None

    ex = Executor(resp)
    deps = _deps(db, tmp_path, ex)
    r = await bk.restore_teste(deps, None, timestamp=TS)
    assert r["verde"] is False and "ErroComando" in r["detalhes"]["erro"]
    assert ex.argvs == [ex.argvs[0]]  # não subiu contêiner, então nem stop
    assert list((tmp_path / "tmp").iterdir()) == []
    assert _contar(db, "SELECT tipo FROM eventos") == [("backup_falhou",)]
    assert len(deps.extras["telegram"].textos) == 1


@pytest.mark.pg
async def test_container_que_nao_fica_pronto_vermelho_com_stop(db, tmp_path):
    man = {"data": DATA, "tabelas": {"turns": 1}}
    ex = _restore(man, {"turns": "1"}, prontos_depois=10_000)
    deps = _deps(db, tmp_path, ex)
    r = await asyncio.wait_for(bk.restore_teste(deps, None, timestamp=TS), 5)
    assert r["verde"] is False and "pronto" in r["detalhes"]["erro"]
    assert ex.argvs[-1] == ("docker", "stop", bk.RESTORE)
