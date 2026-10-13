"""Y3.6: STT assíncrono (spec §5.5) — CA-Y19 parte ``stt`` (áudio some em sucesso e falha), texto
longo vai a arquivo, upload multipart do ``POST /v1/tarefas`` (≤ 200 MB → 413 sem arquivo em disco).
Transcritor falso (nada baixado, nada carregado); o teste com o modelo real pula por padrão
(``AYANAMI_STT_REAL=<áudio>``)."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import procrastinate
import psycopg
import pytest
from procrastinate import testing

from ayanami import fila
from ayanami import tarefas as tf
from ayanami.api import tarefas as api_tarefas
from ayanami.api.app import criar_app
from ayanami.api.auth import criar_dispositivo
from ayanami.config import de_dict
from ayanami.deps import Deps
from ayanami.migrar import migrar
from ayanami.relogio import RelogioFalso
from ayanami.workers import stt

URL = "https://ayanami.exemplo.ts.net"
CFG = de_dict({"geral": {"url_base": URL}})


class Falso:
    def __init__(self, texto: str = "olá mundo", erro: Exception | None = None) -> None:
        self.texto, self.erro = texto, erro
        self.vistos: list[tuple[Path, bool]] = []

    def transcrever(self, caminho: Path, *, parar: Any) -> str:
        self.vistos.append((caminho, caminho.exists()))
        if self.erro:
            raise self.erro
        return self.texto


# --------------------------------------------------------------------------- sem banco


def test_caminho_audio_recusa_fuga_de_tmp(tmp_path):
    assert stt.caminho_audio(tmp_path, "abc.ogg") == tmp_path / "tmp" / "abc.ogg"
    for ruim in ("../x", "a/b", "", None, "..", ".oculto", 3):
        with pytest.raises(ValueError):
            stt.caminho_audio(tmp_path, ruim)


def test_limpar_textos_apaga_so_os_vencidos(tmp_path):
    rel = RelogioFalso()
    pasta = tmp_path / "stt"
    pasta.mkdir()
    velho, novo = pasta / "a.txt", pasta / "b.txt"
    velho.write_text("x")
    novo.write_text("y")
    agora = rel.agora()
    os.utime(velho, ((agora - timedelta(days=8)).timestamp(),) * 2)
    os.utime(novo, ((agora - timedelta(days=6)).timestamp(),) * 2)
    assert stt.limpar_textos(tmp_path, agora) == 1
    assert not velho.exists() and novo.exists()
    assert stt.limpar_textos(tmp_path / "nada", agora) == 0


def test_whisper_local_nao_importa_nada_ate_o_uso():
    w = stt.WhisperLocal()
    assert (w.modelo, w.threads, w.idioma, w._m) == ("small", 4, "pt", None)
    assert "faster_whisper" not in sys.modules


@pytest.mark.skipif(not os.environ.get("AYANAMI_STT_REAL"), reason="modelo real: AYANAMI_STT_REAL=<áudio>")
def test_whisper_real_opcional():  # pragma: no cover
    texto = stt.WhisperLocal().transcrever(Path(os.environ["AYANAMI_STT_REAL"]), parar=lambda: False)
    assert texto.strip()


# --------------------------------------------------------------------------- com banco


class DbConexao:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        with psycopg.connect(self.dsn) as conn:
            yield conn


@pytest.fixture
def db(pg_nova_base) -> DbConexao:
    dsn = pg_nova_base("ayanami_stt")
    with psycopg.connect(dsn) as conn:
        migrar(conn)
    return DbConexao(dsn)


@pytest.fixture
def rel() -> RelogioFalso:
    return RelogioFalso()


@pytest.fixture
def app_fila() -> procrastinate.App:
    return fila.montar(None, testing.InMemoryConnector(), periodicas=False)


def _audio(dados: Path, nome: str = "a1.ogg") -> Path:
    (dados / "tmp").mkdir(parents=True, exist_ok=True)
    p = dados / "tmp" / nome
    p.write_bytes(b"OggS" + b"\0" * 64)
    return p


async def _criar(db, app, rel, nome: str) -> tf.TarefaOut:
    t, _ = await tf.criar_tarefa(db, tf.TarefaIn("stt", "reunião", {"arquivo": nome}), None,
                                 app=app, relogio=rel)
    return t


async def _rodar(app: procrastinate.App, deps: Deps) -> None:
    await app.run_worker_async(queues=["lenta"], wait=False, listen_notify=False,
                               worker_middleware=[tf.on_job_status(deps)],
                               additional_context={"deps": deps})


@pytest.mark.pg
async def test_ca_y19_stt_sucesso_apaga_o_audio(db, rel, app_fila, tmp_path):
    audio = _audio(tmp_path)
    falso = Falso("  olá, condessa  ")
    deps = Deps(db=db, cfg=CFG, relogio=rel, dados=tmp_path, extras={"transcritor": falso})
    t = await _criar(db, app_fila, rel, audio.name)
    await _rodar(app_fila, deps)
    assert falso.vistos == [(audio, True)]
    assert not audio.exists()
    fim = tf.obter_tarefa(db, t.id)
    assert fim.estado == "ok"
    assert fim.resultado == {"texto": "olá, condessa", "dados": {"caracteres": 13}}


@pytest.mark.pg
async def test_ca_y19_stt_falha_apaga_o_audio_so_na_ultima_tentativa(db, rel, app_fila, tmp_path):
    audio = _audio(tmp_path)
    deps = Deps(db=db, cfg=CFG, relogio=rel, dados=tmp_path,
                extras={"transcritor": Falso(erro=RuntimeError("decodificador quebrou"))})
    t = await _criar(db, app_fila, rel, audio.name)
    await _rodar(app_fila, deps)
    # a=2 da §4.2: vai repetir, o áudio fica para a repetição
    assert tf.obter_tarefa(db, t.id).estado == "na_fila" and audio.exists()
    for _ in range(2):
        app_fila.connector.jobs[t.job_id]["scheduled_at"] = None
        await _rodar(app_fila, deps)
    fim = tf.obter_tarefa(db, t.id)
    assert fim.estado == "falhou" and "decodificador" in fim.erro
    assert not audio.exists()


@pytest.mark.pg
async def test_texto_longo_vai_a_arquivo_com_expiracao(db, rel, app_fila, tmp_path):
    audio = _audio(tmp_path)
    longo = "palavra " * 30_000  # 240 mil caracteres
    deps = Deps(db=db, cfg=CFG, relogio=rel, dados=tmp_path, extras={"transcritor": Falso(longo)})
    t = await _criar(db, app_fila, rel, audio.name)
    r = await stt.transcrever(deps, object(), tarefa_id=str(t.id))  # type: ignore[arg-type]
    inteiro = longo.strip()
    assert len(r["texto"]) == stt.MAX_TEXTO
    assert r["dados"]["arquivo"] == f"stt/{t.id}.txt"
    assert r["dados"]["caracteres"] == len(inteiro)
    assert r["dados"]["expira"] == (rel.agora() + timedelta(days=7)).isoformat()
    assert (tmp_path / "stt" / f"{t.id}.txt").read_text(encoding="utf-8") == inteiro
    assert not audio.exists()


# --------------------------------------------------------------------------- upload (API)


@pytest.fixture
def api(db, rel, app_fila, tmp_path):
    app = criar_app(CFG, db, rel, gerar_codigo=lambda: "123456")
    app.state.ctx.extras["fila"] = app_fila
    app.state.ctx.extras["dados"] = tmp_path
    return app


@pytest.fixture
def token(db) -> str:
    with db.connection() as conn:
        tok, _ = criar_dispositivo(conn, "celular-pedro", "celular")
    return tok


def _cliente(app, token: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=URL,
                             headers={"Authorization": f"Bearer {token}"})


def _no_tmp(dados: Path) -> list[str]:
    pasta = dados / "tmp"
    return sorted(p.name for p in pasta.iterdir()) if pasta.is_dir() else []


@pytest.mark.pg
async def test_upload_stt_grava_em_tmp_e_cria_tarefa(api, token, app_fila, tmp_path):
    async with _cliente(api, token) as c:
        r = await c.post("/v1/tarefas", data={"tipo": "stt", "titulo": "aula", "chave": "aula-1"},
                         files={"arquivo": ("aula.OGG", b"OggS" + b"x" * 5000, "audio/ogg")})
        assert r.status_code == 201, r.text
        corpo = r.json()
        assert (corpo["tipo"], corpo["estado"]) == ("stt", "na_fila")
        [nome] = _no_tmp(tmp_path)
        assert nome.endswith(".ogg") and (tmp_path / "tmp" / nome).stat().st_size == 5004
        [job] = app_fila.connector.jobs.values()
        assert job["task_name"] == "stt.transcrever" and job["queue_name"] == "lenta"
        # mesma chave com a tarefa viva: devolve a existente e o 2º áudio não fica
        r2 = await c.post("/v1/tarefas", data={"tipo": "stt", "titulo": "aula", "chave": "aula-1"},
                          files={"arquivo": ("aula.ogg", b"OggS", "audio/ogg")})
        assert r2.status_code == 200 and r2.json()["id"] == corpo["id"]
        assert _no_tmp(tmp_path) == [nome]


@pytest.mark.pg
async def test_upload_acima_de_200_mb_413_sem_arquivo(api, token, tmp_path, monkeypatch):
    monkeypatch.setattr(api_tarefas, "STT_MAX_BYTES", 1000)
    async with _cliente(api, token) as c:
        # pelo Content-Length: nem lê
        r = await c.post("/v1/tarefas", content=b"x",
                         headers={"content-type": "multipart/form-data; boundary=b",
                                  "content-length": str(1000 + 64 * 1024 + 1)})
        assert r.status_code == 413
        # contando os bytes do arquivo no fluxo: o parcial é apagado
        r = await c.post("/v1/tarefas", data={"tipo": "stt", "titulo": "grande"},
                         files={"arquivo": ("g.ogg", b"y" * 5000, "audio/ogg")})
        assert r.status_code == 413 and r.json()["erro"] == "corpo_grande"
    assert _no_tmp(tmp_path) == []


@pytest.mark.pg
async def test_upload_invalido_nao_deixa_arquivo(api, token, tmp_path):
    async with _cliente(api, token) as c:
        sem_titulo = await c.post("/v1/tarefas", data={"tipo": "stt"},
                                  files={"arquivo": ("a.ogg", b"OggS", "audio/ogg")})
        outro_tipo = await c.post("/v1/tarefas", data={"tipo": "pesquisa", "titulo": "x"},
                                  files={"arquivo": ("a.ogg", b"OggS", "audio/ogg")})
        sem_arquivo = await c.post("/v1/tarefas", data={"tipo": "stt", "titulo": "x"},
                                   files={"outro": ("a.txt", b"oi", "text/plain")})
        json_stt = await c.post("/v1/tarefas", json={"tipo": "stt", "titulo": "x",
                                                     "params": {"arquivo": "../../etc/passwd"}})
        json_grande = await c.post("/v1/tarefas", json={"tipo": "pesquisa", "titulo": "x",
                                                        "params": {"pedido": "a" * 300_000}})
    assert [r.status_code for r in (sem_titulo, outro_tipo, sem_arquivo, json_stt)] == [422] * 4
    assert json_grande.status_code == 413
    assert _no_tmp(tmp_path) == []


async def test_upload_sem_token_nao_grava(tmp_path):
    class DbFora:
        @contextmanager
        def connection(self) -> Iterator[psycopg.Connection]:
            raise psycopg.OperationalError("banco falso fora do ar")
            yield  # pragma: no cover

    app = criar_app(CFG, DbFora(), RelogioFalso())
    app.state.ctx.extras["dados"] = tmp_path
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=URL) as c:
        r = await c.post("/v1/tarefas", data={"tipo": "stt", "titulo": "x"},
                         files={"arquivo": ("a.ogg", b"OggS", "audio/ogg")})
    assert r.status_code in (401, 503)
    assert _no_tmp(tmp_path) == []
