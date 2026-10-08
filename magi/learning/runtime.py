"""Ciclo de vida do container local das observações (``magi-qwen``; ``[tasks] learning_observe``).

O Qwen roda num container Ollama só de CPU (``deploy/docker-compose.yml``, serviço ``qwen``,
perfil ``learning``). Regra do Pedro: ele **não ocupa recurso fora da aula** — o container fica
parado sempre que não há sessão de Learning aberta.

- ``start()``: ``docker start <nome>``, espera o Ollama responder em ``GET {url}/api/tags`` (até
  ``start_timeout_s``) e aquece o modelo (``POST /api/generate`` com ``keep_alive = -1``). Deu
  certo = ``ready`` setado.
- ``stop()``: cancela uma subida em andamento e faz ``docker stop -t 5``; ``ready`` limpo.
- ``ensure_stopped()``: na partida do núcleo (container órfão de um núcleo que caiu); idempotente
  (``docker stop`` num container parado não faz nada).
- ``launch()``: agenda ``start()`` em segundo plano (a resposta ``lm_mode`` não espera).

Nunca ``docker rm`` nem ``compose down``: o container (e o volume com o modelo) já existe; o núcleo
só liga e desliga. Erros (docker ausente, timeout) só logam e deixam ``ready`` limpo: o Learning
segue sem observações. ``NullRuntime`` é a versão sem container (``local_container`` vazio):
``ready`` sempre setado, nada a ligar.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from typing import Any

import httpx

from magi.learning.config import LearningConfig

log = logging.getLogger(__name__)

#: Prazo de cada chamada ``docker`` (s); ``stop -t 5`` cabe com folga.
DOCKER_TIMEOUT_S = 30.0
#: Segundos que o ``docker stop`` dá ao Ollama antes do SIGKILL.
STOP_GRACE_S = 5
#: Intervalo entre as sondas do Ollama na subida (s).
PROBE_INTERVAL_S = 1.0

#: ``asyncio.create_subprocess_exec`` (injetável nos testes).
Exec = Callable[..., Any]


class NullRuntime:
    """Sem container configurado: nada a subir; ``ready`` sempre setado (observações seguem)."""

    configured = False

    def __init__(self) -> None:
        self.ready = asyncio.Event()
        self.ready.set()

    @property
    def starting(self) -> bool:
        return False

    @property
    def available(self) -> bool:
        return True

    def launch(self) -> None:
        return None

    async def start(self) -> bool:
        return True

    async def stop(self) -> None:
        return None

    async def ensure_stopped(self) -> None:
        return None

    def boot(self) -> None:
        return None


class ContainerRuntime:
    """Liga/desliga o container ``name`` (Ollama em ``url``) e aquece ``model``."""

    configured = True

    def __init__(
        self,
        name: str,
        url: str = "http://127.0.0.1:11435",
        model: str = "qwen-learning",
        start_timeout_s: float = 60.0,
        *,
        exec_: Exec | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        probe_interval_s: float = PROBE_INTERVAL_S,
        docker_timeout_s: float = DOCKER_TIMEOUT_S,
    ) -> None:
        self.name = name
        self.url = url.rstrip("/")
        self.model = model
        self.start_timeout_s = start_timeout_s
        self.probe_interval_s = probe_interval_s
        self.docker_timeout_s = docker_timeout_s
        self._exec = exec_ or asyncio.create_subprocess_exec
        self._transport = transport
        self.ready = asyncio.Event()
        self._lock = asyncio.Lock()  # docker start/stop em ordem de chegada
        self._starting: asyncio.Task[bool] | None = None
        self._boot: asyncio.Task[None] | None = None

    # -- consulta -------------------------------------------------------------------------------

    @property
    def starting(self) -> bool:
        """Subida em andamento (o gate das observações espera)."""
        return self._starting is not None and not self._starting.done()

    @property
    def available(self) -> bool:
        """Vale mandar observação: pronto ou subindo (falhou/parado = descarta em silêncio)."""
        return self.ready.is_set() or self.starting

    # -- ciclo de vida --------------------------------------------------------------------------

    def launch(self) -> asyncio.Task[bool] | None:
        """Agenda ``start()`` em segundo plano; já pronto ou subindo = nada."""
        if self.ready.is_set() or self.starting:
            return self._starting
        self._starting = asyncio.create_task(self.start(), name=f"learning-runtime-{self.name}")
        return self._starting

    def boot(self) -> asyncio.Task[None]:
        """Partida do núcleo: agenda ``ensure_stopped()`` (a referência fica aqui)."""
        if self._boot is None or self._boot.done():
            self._boot = asyncio.create_task(self.ensure_stopped(), name="learning-runtime-boot")
        return self._boot

    async def start(self) -> bool:
        """Sobe o container, espera o Ollama e aquece o modelo. ``True`` = ``ready`` setado."""
        async with self._lock:
            if self.ready.is_set():
                return True
            began = time.monotonic()
            if not await self._docker("start", self.name):
                log.warning("learning: container %s não subiu; seguindo sem observações", self.name)
                return False
            async with httpx.AsyncClient(transport=self._transport) as http:
                if not await self._wait_ollama(http):
                    log.warning("learning: Ollama de %s não respondeu em %g s; seguindo sem observações",
                                self.name, self.start_timeout_s)
                    return False
                await self._warm(http)
            self.ready.set()
            log.info("learning: container %s pronto em %.1f s", self.name, time.monotonic() - began)
            return True

    async def stop(self) -> None:
        """Cancela a subida em andamento e para o container (``docker stop -t 5``)."""
        task, self._starting = self._starting, None
        if task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self.ready.clear()
        async with self._lock:
            self.ready.clear()
            if await self._docker("stop", "-t", str(STOP_GRACE_S), self.name):
                log.info("learning: container %s parado", self.name)

    async def ensure_stopped(self) -> None:
        """Garante o container parado (partida do núcleo, Learning desligado). Idempotente."""
        await self.stop()

    # -- internos -------------------------------------------------------------------------------

    async def _docker(self, *args: str) -> bool:
        """Roda ``docker <args>``; ``False`` em qualquer falha (só loga)."""
        try:
            proc = await self._exec("docker", *args, stdout=asyncio.subprocess.DEVNULL,
                                    stderr=asyncio.subprocess.PIPE)
        except (OSError, ValueError) as e:
            log.warning("learning: docker indisponível (%s)", e)
            return False
        try:
            _out, err = await asyncio.wait_for(proc.communicate(), self.docker_timeout_s)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            log.warning("learning: docker %s passou de %g s", args[0], self.docker_timeout_s)
            return False
        if proc.returncode != 0:
            msg = (err or b"").decode(errors="replace").strip()
            log.warning("learning: docker %s falhou (%s): %s", args[0], proc.returncode, msg)
            return False
        return True

    async def _wait_ollama(self, http: httpx.AsyncClient) -> bool:
        deadline = time.monotonic() + self.start_timeout_s
        while True:
            try:
                r = await http.get(f"{self.url}/api/tags", timeout=5.0)
                if r.status_code == 200:
                    return True
            except httpx.HTTPError:
                pass
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(self.probe_interval_s)

    async def _warm(self, http: httpx.AsyncClient) -> None:
        """Carrega o modelo na RAM (prompt vazio); falha só loga — a 1ª observação carrega."""
        try:
            r = await http.post(f"{self.url}/api/generate",
                                json={"model": self.model, "prompt": "", "keep_alive": -1},
                                timeout=max(self.start_timeout_s, 5.0))
            if r.status_code != 200:
                log.warning("learning: aquecimento de %s respondeu %s", self.model, r.status_code)
        except httpx.HTTPError as e:
            log.warning("learning: aquecimento de %s falhou (%s)", self.model, e)


#: Qualquer um dos dois (o wiring e o núcleo não distinguem).
LearningRuntime = ContainerRuntime | NullRuntime


def make_runtime(cfg: LearningConfig, **kw: Any) -> LearningRuntime:
    """``ContainerRuntime`` com ``[learning] local_container``; vazio = ``NullRuntime``."""
    if not cfg.local_container:
        return NullRuntime()
    return ContainerRuntime(cfg.local_container, cfg.local_url, cfg.local_model,
                            float(cfg.local_start_timeout_s), **kw)
