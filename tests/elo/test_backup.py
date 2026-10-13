"""``magi-backup`` (Y4.1, spec §7.1, CA-Y23): docker/pg_dump/zstd e Ayanami falsos."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import shutil
import tarfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from magi.elo import backup as bk
from magi.elo.backup import BackupConfig, Resultado

AGORA = datetime(2026, 10, 12, 6, 30, tzinfo=UTC)  # 03:30 em Brasília
TOKEN = "ayn_pc_FALSO"


class Docker:
    """Executor falso: ``pg_dump`` escreve bytes, ``psql`` devolve contagens, ``zstd`` copia."""

    def __init__(self, *, dump_falha: bool = False) -> None:
        self.cmds: list[list[str]] = []
        self.dump_falha = dump_falha

    def __call__(self, cmd: Sequence[str], saida: Path | None = None) -> Resultado:
        cmd = list(cmd)
        self.cmds.append(cmd)
        if cmd[:3] == ["docker", "exec", "magi-pg"]:
            if cmd[3] == "pg_dump" and cmd[4] == "--version":
                return Resultado(0, "pg_dump (PostgreSQL) 16.4\n")
            if cmd[3] == "pg_dump":
                assert saida is not None
                if self.dump_falha:
                    return Resultado(1, "connection refused")
                saida.write_bytes(b"PGDMP-falso")
                return Resultado(0)
            if cmd[3] == "psql":
                if "learning_sessions" in cmd[-1]:
                    return Resultado(1, "não existe")
                return Resultado(0, "7\n")
        if cmd[0] == "zstd":
            shutil.copyfile(cmd[-1], cmd[cmd.index("-o") + 1])  # "comprime" copiando
            return Resultado(0)
        raise AssertionError(f"comando inesperado: {cmd}")


class Ayanami:
    """Servidor falso por ``httpx.MockTransport``: lista de respostas (a última repete)."""

    def __init__(self, *respostas: int | type[Exception]) -> None:
        self.respostas = list(respostas) or [201]
        self.pedidos: list[tuple[httpx.Request, bytes]] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        corpo = req.read()
        self.pedidos.append((req, corpo))
        r = self.respostas.pop(0) if len(self.respostas) > 1 else self.respostas[0]
        if isinstance(r, type):
            raise r("falso", request=req)
        return httpx.Response(r, json={"recebido": len(corpo)} if r == 201 else {})

    def cliente(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))


@pytest.fixture
def cfg(tmp_path: Path) -> BackupConfig:
    conf = tmp_path / "config" / "magi"
    (conf / "sub").mkdir(parents=True)
    (conf / "config.toml").write_text("[ayanami]\n")
    (conf / "casa.toml").write_text("[[tv]]\n")
    (conf / "casa.token").write_text("segredo")
    (conf / "ayanami.token").write_text(TOKEN)
    (conf / "api_key.txt").write_text("x")
    (conf / "client_secret.json").write_text("{}")
    (conf / "sub" / "outro.token").write_text("x")
    (conf / "sub" / "persona.yaml").write_text("nome: Condessa\n")
    (conf / "keys").mkdir()
    (conf / "keys" / "a.txt").write_text("x")
    tmpb = tmp_path / "cache"
    return BackupConfig(url="https://ayanami.falsa/", token=TOKEN, config_dir=conf,
                        data_dir=tmp_path / "dados", tmp_base=tmpb)


def _roda(cfg: BackupConfig, docker: Docker, ay: Ayanami) -> tuple[int, list[float]]:
    dormiu: list[float] = []
    with ay.cliente() as c:
        rc = bk.executar(cfg, executor=docker, cliente=c, dormir=dormiu.append, agora=lambda: AGORA)
    return rc, dormiu


def _estado(cfg: BackupConfig) -> dict:
    return json.loads((cfg.data_dir / bk.STATE_FILE).read_text())


def _temporarios(cfg: BackupConfig) -> list[Path]:
    assert cfg.tmp_base is not None
    return list(cfg.tmp_base.iterdir()) if cfg.tmp_base.exists() else []


def test_ca_y23_monta_tar_com_dump_manifesto_e_config_sem_segredos(cfg: BackupConfig) -> None:
    docker, ay = Docker(), Ayanami(201)
    rc, dormiu = _roda(cfg, docker, ay)
    assert rc == 0 and dormiu == []
    (req, corpo), = ay.pedidos
    assert req.method == "PUT" and str(req.url) == "https://ayanami.falsa/v1/backup/pc"
    assert req.headers["Authorization"] == f"Bearer {TOKEN}"
    assert req.headers["X-Sha256"] == hashlib.sha256(corpo).hexdigest()
    data = AGORA.astimezone().date().isoformat()
    assert req.headers["X-Data"] == data
    man = json.loads(base64.b64decode(req.headers["X-Manifesto"]))
    assert man["data"] == data and man["pg_versao"] == "16.4"
    assert man["tabelas"] == {"turns": 7, "memories": 7, "costs": 7, "news_items": 7, "taste": 7,
                              "learning_sessions": None}
    with tarfile.open(fileobj=io.BytesIO(corpo)) as tar:
        assert sorted(tar.getnames()) == ["config.tar", "magi-pg.dump", "manifesto.json"]
        assert tar.extractfile("magi-pg.dump").read() == b"PGDMP-falso"  # type: ignore[union-attr]
        assert json.loads(tar.extractfile("manifesto.json").read()) == man  # type: ignore[union-attr]
        interno = tar.extractfile("config.tar").read()  # type: ignore[union-attr]
    with tarfile.open(fileobj=io.BytesIO(interno)) as tar:
        nomes = set(tar.getnames())
    assert {"magi/config.toml", "magi/casa.toml", "magi/sub/persona.yaml"} <= nomes
    assert not any(n.endswith(".token") or "key" in n or "secret" in n for n in nomes)
    assert _temporarios(cfg) == []
    st = _estado(cfg)
    assert st["resultado"] == "ok" and st["sha256"] == req.headers["X-Sha256"]
    assert TOKEN not in (cfg.data_dir / bk.STATE_FILE).read_text()


def test_comandos_contra_o_magi_pg_so_pg_dump_e_select_count(cfg: BackupConfig) -> None:
    docker = Docker()
    _roda(cfg, docker, Ayanami(201))
    contra_pg = [c for c in docker.cmds if "magi-pg" in c]
    assert contra_pg and all(c[:3] == ["docker", "exec", "magi-pg"] for c in contra_pg)
    for c in contra_pg:
        if c[3] == "pg_dump":
            assert c[4:] in (["-Fc", "-U", "magi", "-d", "magi"], ["--version"])
        else:
            assert c[3] == "psql" and c[-2] == "-Atc" and c[-1].startswith("SELECT count(*) FROM ")
    assert [c[0] for c in docker.cmds if "magi-pg" not in c] == ["zstd"]
    assert ["zstd", "-10"] == docker.cmds[-1][:2]
    texto = " ".join(" ".join(c) for c in docker.cmds).upper()
    assert not any(p in texto for p in ("DROP", "TRUNCATE", "--CLEAN", "DELETE", "COMPOSE"))


def test_409_ja_recebido_sai_0(cfg: BackupConfig) -> None:
    ay = Ayanami(409)
    rc, dormiu = _roda(cfg, Docker(), ay)
    assert rc == 0 and dormiu == [] and len(ay.pedidos) == 1
    assert _estado(cfg)["resultado"] == "ja_recebido"
    assert _temporarios(cfg) == []


def test_rede_fora_tenta_1_5_15_min_e_apaga_temporario(cfg: BackupConfig) -> None:
    ay = Ayanami(httpx.ConnectError)
    rc, dormiu = _roda(cfg, Docker(), ay)
    assert rc == 1
    assert dormiu == [60.0, 300.0, 900.0] and len(ay.pedidos) == 4
    st = _estado(cfg)
    assert st["resultado"] == "falhou" and st["tentativas"] == 4 and "rede" in st["erro"]
    assert _temporarios(cfg) == []


def test_falha_e_depois_sobe(cfg: BackupConfig) -> None:
    ay = Ayanami(503, 400, 201)
    rc, dormiu = _roda(cfg, Docker(), ay)
    assert rc == 0 and dormiu == [60.0, 300.0]
    assert len({h for h in (r.headers["X-Sha256"] for r, _ in ay.pedidos)}) == 1
    assert all(len(c) == len(ay.pedidos[0][1]) for _, c in ay.pedidos)  # reenvia o arquivo inteiro
    assert _estado(cfg)["tentativas"] == 3


@pytest.mark.parametrize("status", [401, 403, 413])
def test_erro_que_nao_adianta_repetir(cfg: BackupConfig, status: int) -> None:
    ay = Ayanami(status)
    rc, dormiu = _roda(cfg, Docker(), ay)
    assert rc == 1 and dormiu == [] and len(ay.pedidos) == 1
    assert _estado(cfg)["erro"] == f"HTTP {status}"


def test_pg_dump_falha_nao_envia_e_apaga_temporario(cfg: BackupConfig) -> None:
    ay = Ayanami(201)
    rc, _ = _roda(cfg, Docker(dump_falha=True), ay)
    assert rc == 1 and ay.pedidos == []
    assert "pg_dump falhou" in _estado(cfg)["erro"]
    assert _temporarios(cfg) == []


def test_sem_url_ou_token_fica_desligado(cfg: BackupConfig) -> None:
    from dataclasses import replace

    for c in (replace(cfg, url=None), replace(cfg, token=None)):
        docker, ay = Docker(), Ayanami(201)
        rc, _ = _roda(c, docker, ay)
        assert rc == 0 and docker.cmds == [] and ay.pedidos == []
        assert _estado(c)["resultado"] == "desligado"


def test_config_de_le_url_e_token_ao_lado_do_config(cfg: BackupConfig) -> None:
    c = bk.config_de({"ayanami": {"url": "https://a.falsa"}}, cfg.config_dir, cfg.data_dir)
    assert c.url == "https://a.falsa" and c.token == TOKEN
    c = bk.config_de({}, cfg.config_dir / "nada", cfg.data_dir)
    assert c.url is None and c.token is None


def test_main_sem_ayanami_no_config_sai_0(tmp_path: Path) -> None:
    conf = tmp_path / "magi" / "config.toml"
    conf.parent.mkdir()
    conf.write_text(f'[paths]\ndata_dir = "{tmp_path / "dados"}"\n')
    assert bk.main(["--config", str(conf)]) == 0
    assert json.loads((tmp_path / "dados" / bk.STATE_FILE).read_text())["resultado"] == "desligado"


def test_excluido_casa_qualquer_componente() -> None:
    assert bk.excluido("magi/casa.token") and bk.excluido("magi/keys/a.txt")
    assert bk.excluido("magi/my_secret.json") and not bk.excluido("magi/persona.yaml")


def test_contagem_so_de_tabela_conhecida() -> None:
    with pytest.raises(ValueError):
        bk.cmd_contagem("turns; DROP TABLE turns")
