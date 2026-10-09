"""Ciclo de vida do container ``magi-qwen`` (``magi.learning.runtime``) e sua ligação com a sessão
(``LearningWiring``) e com o núcleo (``core.service``). Nada de docker real: subprocess e HTTP
falsos."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from magi.common.config import parse_config
from magi.common.contracts import HudMessage, LmModeMsg
from magi.core.service import _learning_runtime, _runtime_gate
from magi.learning.config import LearningConfig, parse_learning
from magi.learning.contracts import Author, Source
from magi.learning.repo import JsonlRepo
from magi.learning.runtime import ContainerRuntime, NullRuntime, make_runtime
from magi.learning.wiring import LearningWiring

# ---------------------------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------------------------


class FakeProc:
    def __init__(self, rc: int = 0, delay: float = 0.0) -> None:
        self.returncode = rc
        self.delay = delay

    async def communicate(self) -> tuple[bytes, bytes]:
        if self.delay:
            await asyncio.sleep(self.delay)
        return b"", b"erro" if self.returncode else b""

    def kill(self) -> None:
        pass


class FakeDocker:
    """``asyncio.create_subprocess_exec`` falso: grava os argumentos."""

    def __init__(self, rc: int = 0, missing: bool = False) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.rc = rc
        self.missing = missing

    async def __call__(self, *args: str, **kw) -> FakeProc:
        if self.missing:
            raise FileNotFoundError("docker")
        self.calls.append(args)
        return FakeProc(self.rc)

    @property
    def verbs(self) -> list[str]:
        return [c[1] for c in self.calls]


class FakeOllama:
    """Ollama falso (``httpx.MockTransport``): ``up_after`` sondas falham antes de responder."""

    def __init__(self, up_after: int = 0, never: bool = False) -> None:
        self.up_after = up_after
        self.never = never
        self.tags = 0
        self.generated: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            self.tags += 1
            if self.never or self.tags <= self.up_after:
                raise httpx.ConnectError("recusado", request=request)
            return httpx.Response(200, json={"models": []})
        if request.url.path == "/api/generate":
            import json

            self.generated.append(json.loads(request.content))
            return httpx.Response(200, json={"done": True})
        return httpx.Response(404)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


def _rt(docker: FakeDocker, ollama: FakeOllama, timeout: float = 1.0) -> ContainerRuntime:
    return ContainerRuntime("magi-qwen", "http://127.0.0.1:11435", "qwen-learning", timeout,
                            exec_=docker, transport=ollama.transport, probe_interval_s=0.01)


class SinkHud:
    def __init__(self) -> None:
        self.sent: list[HudMessage] = []

    async def send(self, msg: HudMessage) -> None:
        self.sent.append(msg)


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 8, 20, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw: float) -> None:
        self.now += timedelta(**kw)


class FakeEngine:
    def __init__(self) -> None:
        self.on_observed = None
        self.published: list = []

    def publish(self, msg) -> bool:
        self.published.append(msg)
        return True

    async def aclose(self) -> None:
        pass


def _wiring(tmp_path, rt, clock: Clock | None = None, engine=None, **cfg) -> LearningWiring:
    return LearningWiring(LearningConfig(storage="jsonl", **cfg), JsonlRepo(tmp_path), SinkHud(),
                          None, clock=clock or Clock(), engine=engine, runtime=rt)  # type: ignore[arg-type]


async def _until(cond, timeout: float = 2.0) -> None:
    for _ in range(int(timeout / 0.01)):
        if cond():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condição não ocorreu")


# ---------------------------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------------------------


def test_config_local_padrao_e_lido() -> None:
    d = parse_learning({})
    assert d.local_container == "" and d.local_url == "http://127.0.0.1:11435"
    assert d.local_model == "qwen-learning" and d.local_start_timeout_s == 60 and d.max_session_min == 180
    assert isinstance(make_runtime(d), NullRuntime)
    c = parse_learning({"learning": {"local_container": "magi-qwen", "local_url": "http://x:1/",
                                     "local_start_timeout_s": 90, "max_session_min": 120}})
    assert c.local_container == "magi-qwen" and c.local_url == "http://x:1" and c.max_session_min == 120
    rt = make_runtime(c)
    assert isinstance(rt, ContainerRuntime) and rt.name == "magi-qwen" and rt.start_timeout_s == 90


# ---------------------------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------------------------


async def test_start_sobe_espera_aquece_e_fica_ready() -> None:
    docker, ollama = FakeDocker(), FakeOllama(up_after=2)
    rt = _rt(docker, ollama)
    assert await rt.start() is True
    assert rt.ready.is_set() and rt.available and not rt.starting
    assert docker.calls == [("docker", "start", "magi-qwen")]
    assert ollama.tags == 3
    assert ollama.generated == [{"model": "qwen-learning", "prompt": "", "keep_alive": -1}]
    await rt.stop()
    assert not rt.ready.is_set() and not rt.available
    assert docker.calls[-1] == ("docker", "stop", "-t", "5", "magi-qwen")
    assert not any(c[1] in ("rm", "compose", "down") for c in docker.calls)


async def test_launch_em_segundo_plano_e_idempotente() -> None:
    docker, ollama = FakeDocker(), FakeOllama(up_after=3)
    rt = _rt(docker, ollama)
    t = rt.launch()
    assert t is not None and rt.starting and rt.available and not rt.ready.is_set()
    assert rt.launch() is t  # já subindo: não sobe de novo
    assert await t is True and rt.ready.is_set()
    rt.launch()
    assert docker.verbs == ["start"]


@pytest.mark.parametrize("docker", [FakeDocker(missing=True), FakeDocker(rc=1)])
async def test_falha_do_docker_nao_derruba(docker) -> None:
    rt = _rt(docker, FakeOllama())
    assert await rt.start() is False
    assert not rt.ready.is_set() and not rt.available
    await rt.stop()  # também não levanta
    await rt.ensure_stopped()


async def test_timeout_do_ollama_deixa_ready_limpo() -> None:
    rt = _rt(FakeDocker(), FakeOllama(never=True), timeout=0.05)
    assert await rt.start() is False
    assert not rt.ready.is_set() and not rt.starting


async def test_stop_cancela_subida_em_andamento() -> None:
    docker = FakeDocker()
    rt = _rt(docker, FakeOllama(never=True), timeout=30)
    rt.launch()
    await _until(lambda: docker.verbs == ["start"])
    await asyncio.wait_for(rt.stop(), 1.0)
    assert not rt.starting and not rt.ready.is_set() and docker.verbs == ["start", "stop"]


async def test_ensure_stopped_idempotente_e_null_runtime() -> None:
    docker = FakeDocker()
    rt = _rt(docker, FakeOllama())
    await rt.ensure_stopped()
    await rt.ensure_stopped()
    assert docker.verbs == ["stop", "stop"]
    null = NullRuntime()
    assert null.ready.is_set() and null.available and not null.configured
    null.launch()
    await null.stop()


# ---------------------------------------------------------------------------------------------
# Wiring: sobe ao abrir, para ao fechar por qualquer motivo
# ---------------------------------------------------------------------------------------------


async def _open(w: LearningWiring, docker: FakeDocker) -> None:
    await w.set_mode(True, "button")
    assert any(isinstance(m, LmModeMsg) and m.on for m in w.hud.sent)  # type: ignore[attr-defined]
    await _until(lambda: w.runtime.ready.is_set())
    assert docker.verbs == ["start"]


@pytest.mark.parametrize("reason", ["button", "voice"])
async def test_fecha_por_botao_ou_voz_para_o_container(tmp_path, reason) -> None:
    docker = FakeDocker()
    w = _wiring(tmp_path, _rt(docker, FakeOllama()))
    await _open(w, docker)
    await w.set_mode(False, reason)
    await w.wait_idle()
    assert docker.verbs == ["start", "stop"] and not w.runtime.ready.is_set()
    await w.aclose()


async def test_lm_mode_nao_espera_a_subida(tmp_path) -> None:
    docker = FakeDocker()
    w = _wiring(tmp_path, _rt(docker, FakeOllama(never=True), timeout=30))
    await asyncio.wait_for(w.set_mode(True, "button"), 0.5)
    assert w.runtime.starting
    await _until(lambda: docker.verbs == ["start"])  # já esperando o Ollama
    await w.aclose()  # shutdown cancela a subida e para
    assert docker.verbs == ["start", "stop"] and not w.runtime.starting


async def test_retomada_sobe_o_container(tmp_path) -> None:
    clock = Clock()
    docker = FakeDocker()
    w = _wiring(tmp_path, _rt(docker, FakeOllama()), clock)
    await w.set_mode(True, "button")
    sid = w.session.id
    w.session._info = None  # núcleo caiu com a sessão aberta no banco
    await w.runtime.stop()
    docker.calls.clear()
    w2 = _wiring(tmp_path, _rt(docker, FakeOllama()), clock)
    await w2.set_mode(True, "voice")
    assert w2.session.id == sid  # retomada
    await _until(lambda: w2.runtime.ready.is_set())
    assert docker.verbs == ["start"]
    await w2.aclose()
    await w.aclose()


async def test_idle_para_o_container(tmp_path) -> None:
    clock = Clock()
    docker = FakeDocker()
    w = _wiring(tmp_path, _rt(docker, FakeOllama()), clock, idle_end_min=20)
    await _open(w, docker)
    clock.advance(minutes=21)
    assert await w.check_idle() is True
    await w.wait_idle()
    assert docker.verbs == ["start", "stop"] and not w.session.active
    await w.aclose()


async def test_shutdown_para_o_container(tmp_path) -> None:
    docker = FakeDocker()
    w = _wiring(tmp_path, _rt(docker, FakeOllama()))
    await _open(w, docker)
    await w.aclose()
    assert docker.verbs == ["start", "stop"] and not w.runtime.ready.is_set()


async def test_watchdog_fecha_sessao_longa(tmp_path) -> None:
    clock = Clock()
    docker = FakeDocker()
    w = _wiring(tmp_path, _rt(docker, FakeOllama()), clock, idle_end_min=20, max_session_min=180)
    await _open(w, docker)
    for _ in range(17):  # quase 3 h de conversa: nunca ociosa
        clock.advance(minutes=10)
        await w.session.add_message(Author.YOU, Source.TEXT, "hi")
        assert await w.check_idle() is False
    clock.advance(minutes=10)  # 180 min
    await w.session.add_message(Author.YOU, Source.TEXT, "hi")
    assert await w.check_idle() is True
    await w.wait_idle()
    assert not w.session.active and docker.verbs == ["start", "stop"]
    sent = w.hud.sent  # type: ignore[attr-defined]
    offs = [i for i, m in enumerate(sent) if isinstance(m, LmModeMsg) and not m.on]
    assert offs  # o modo saiu
    # depois do off só pode vir o resumo da sessão (LM4.5, ligado no wiring na integração)
    assert all(type(m).__name__ == "LmSummaryMsg" for m in sent[offs[-1] + 1:])
    await w.aclose()


async def test_observacao_descartada_sem_container(tmp_path) -> None:
    docker = FakeDocker(rc=1)  # container não sobe
    eng = FakeEngine()
    w = _wiring(tmp_path, _rt(docker, FakeOllama()), engine=eng)
    await w.set_mode(True, "button")
    await _until(lambda: not w.runtime.starting)
    msg = await w.session.add_message(Author.YOU, Source.TEXT, "I have went")
    assert msg is not None
    w._observe(msg)
    assert eng.published == []  # descartada em silêncio
    w.runtime = NullRuntime()
    w._observe(msg)
    assert eng.published == [msg]
    await w.aclose()


def test_gate_fecha_enquanto_sobe() -> None:
    class Rt:
        configured = True
        starting = True

    rt = Rt()
    gate = _runtime_gate(lambda: True, rt)
    assert gate() is False
    rt.starting = False
    assert gate() is True
    base = lambda: True  # noqa: E731
    assert _runtime_gate(base, NullRuntime()) is base and _runtime_gate(base, None) is base


# ---------------------------------------------------------------------------------------------
# Núcleo: partida garante o container parado
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("enabled", [True, False])
async def test_partida_garante_parado(monkeypatch, enabled) -> None:
    docker = FakeDocker()
    monkeypatch.setattr("magi.learning.runtime.asyncio.create_subprocess_exec", docker)
    config = parse_config({"learning": {"enabled": enabled, "local_container": "magi-qwen"}})
    rt = _learning_runtime(config)
    assert isinstance(rt, ContainerRuntime)
    await rt.boot()
    assert docker.calls == [("docker", "stop", "-t", "5", "magi-qwen")]


def test_partida_sem_container_e_nula() -> None:
    assert isinstance(_learning_runtime(None), NullRuntime)
    assert isinstance(_learning_runtime(parse_config({})), NullRuntime)
    assert isinstance(_learning_runtime(parse_config({"learning": {"level": "Z9"}})), NullRuntime)
