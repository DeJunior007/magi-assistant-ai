"""STT assíncrono (dono: Y3.6; spec §5.5, R3.4) — corpo de ``stt.transcrever`` (fila ``lenta``).

- O áudio chega antes por ``POST /v1/tarefas`` multipart ``tipo=stt`` (:mod:`ayanami.api.tarefas`),
  gravado em ``<dados>/tmp/<arquivo>``; ``params = {"arquivo": "<nome>"}`` (só o nome, sem barra).
- :class:`Transcritor` é o protocolo; o real (:class:`WhisperLocal`) é faster-whisper 1.2.1
  ``small`` ``int8`` ``cpu_threads=4`` ``language="pt"``, carregado uma vez por processo no 1º
  uso (o import de ``faster_whisper`` só acontece aí). Testes passam um falso em
  ``deps.extras["transcritor"]``.
- Saída: ``{"texto": ..., "dados": {...}}``. Texto acima de :data:`MAX_TEXTO` caracteres vai
  inteiro para ``<dados>/stt/<tarefa_id>.txt`` (``dados.arquivo``, ``dados.expira`` = +7 dias) e
  ``texto`` leva só o começo; arquivos vencidos são apagados por :func:`limpar_textos` (chamada
  no início de cada job).
- O áudio é apagado no ``finally``: em sucesso e em falha final. Só fica quando o job vai ser
  repetido pela fila (retry da §4.2 ainda com tentativa, ou desligamento do worker), senão a
  repetição não teria o que transcrever.
- Abort (``cancel_job_by_id_async(abort=True)``): o ``CancelledError`` liga o ``parar`` que a
  transcrição (em thread) confere a cada segmento.
"""

from __future__ import annotations

import asyncio
import re
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from procrastinate import JobContext
from procrastinate.job_context import AbortReason

from ayanami.deps import Deps

MAX_TEXTO = 200_000
EXPIRA_TEXTO = timedelta(days=7)
NOME_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")


class Transcritor(Protocol):
    def transcrever(self, caminho: Path, *, parar: Callable[[], bool]) -> str: ...


class TranscricaoParada(Exception):
    """A transcrição viu ``parar()`` (abort) e saiu no meio."""


class WhisperLocal:
    """faster-whisper ``small`` int8 em CPU (spec §5.5); modelo carregado no 1º uso."""

    def __init__(self, modelo: str = "small", *, threads: int = 4, idioma: str = "pt",
                 pasta: Path | None = None) -> None:
        self.modelo, self.threads, self.idioma, self.pasta = modelo, threads, idioma, pasta
        self._m: Any = None
        self._trava = threading.Lock()

    def _carregar(self) -> Any:
        with self._trava:
            if self._m is None:
                from faster_whisper import WhisperModel  # só aqui: pesado

                self._m = WhisperModel(self.modelo, device="cpu", compute_type="int8",
                                       cpu_threads=self.threads,
                                       download_root=str(self.pasta) if self.pasta else None)
            return self._m

    def transcrever(self, caminho: Path, *, parar: Callable[[], bool]) -> str:
        segmentos, _info = self._carregar().transcribe(str(caminho), language=self.idioma)
        partes: list[str] = []
        for s in segmentos:
            if parar():
                raise TranscricaoParada("abortada")
            partes.append(s.text.strip())
        return " ".join(p for p in partes if p)


_padrao: WhisperLocal | None = None


def transcritor_de(deps: Deps) -> Transcritor:
    global _padrao
    t = deps.extras.get("transcritor")
    if t is not None:
        return t
    if _padrao is None:
        _padrao = WhisperLocal(pasta=deps.dados / "modelos" / "whisper")
    return _padrao


def caminho_audio(dados: Path, arquivo: Any) -> Path:
    """``<dados>/tmp/<arquivo>``; nome com barra, ``..`` ou vazio → ``ValueError``."""
    if not isinstance(arquivo, str) or not NOME_OK.match(arquivo) or ".." in arquivo:
        raise ValueError("arquivo de áudio inválido")
    return dados / "tmp" / arquivo


def limpar_textos(dados: Path, agora: datetime) -> int:
    """Apaga ``<dados>/stt/*.txt`` com mais de 7 dias (mtime); devolve quantos."""
    pasta = dados / "stt"
    if not pasta.is_dir():
        return 0
    limite = (agora - EXPIRA_TEXTO).timestamp()
    n = 0
    for p in pasta.glob("*.txt"):
        try:
            if p.stat().st_mtime < limite:
                p.unlink()
                n += 1
        except FileNotFoundError:
            pass
    return n


def _params(deps: Deps, tarefa_id: str) -> dict[str, Any]:
    with deps.db.connection() as conn:
        r = conn.execute("SELECT params FROM tarefas WHERE id = %s", (tarefa_id,)).fetchone()
        if not conn.autocommit:
            conn.rollback()
    if r is None:
        raise LookupError(f"tarefa {tarefa_id} não existe")
    return dict(r[0] or {})


def _saida(deps: Deps, tarefa_id: str, texto: str) -> dict[str, Any]:
    if len(texto) <= MAX_TEXTO:
        return {"texto": texto, "dados": {"caracteres": len(texto)}}
    pasta = deps.dados / "stt"
    pasta.mkdir(parents=True, exist_ok=True)
    nome = f"{tarefa_id}.txt"
    (pasta / nome).write_text(texto, encoding="utf-8")
    expira = deps.relogio.agora() + EXPIRA_TEXTO
    return {"texto": texto[:MAX_TEXTO],
            "dados": {"caracteres": len(texto), "arquivo": f"stt/{nome}", "expira": expira.isoformat()}}


def _vai_repetir(contexto: Any, e: BaseException) -> bool:
    if isinstance(e, asyncio.CancelledError):
        motivo = contexto.abort_reason() if hasattr(contexto, "abort_reason") else None
        if motivo != AbortReason.SHUTDOWN:
            return False
    try:
        task = contexto.app.tasks.get(contexto.job.task_name)
        return bool(task and task.get_retry_exception(exception=e, job=contexto.job))
    except AttributeError:
        return False


async def transcrever(deps: Deps, contexto: JobContext, *, tarefa_id: str) -> dict[str, Any] | None:
    """``stt.transcrever``: faster-whisper sobre o áudio da tarefa; áudio apagado no fim (dono: Y3.6)."""
    audio: Path | None = None
    manter = False
    parar = threading.Event()
    try:
        await asyncio.to_thread(limpar_textos, deps.dados, deps.relogio.agora())
        params = await asyncio.to_thread(_params, deps, tarefa_id)
        audio = caminho_audio(deps.dados, params.get("arquivo"))
        if not audio.is_file():
            raise FileNotFoundError(f"áudio {audio.name} não está em tmp/")
        t = transcritor_de(deps)
        try:
            texto = await asyncio.to_thread(t.transcrever, audio, parar=parar.is_set)
        except asyncio.CancelledError:
            parar.set()
            raise
        return await asyncio.to_thread(_saida, deps, tarefa_id, texto.strip())
    except BaseException as e:
        manter = _vai_repetir(contexto, e)
        raise
    finally:
        if audio is not None and not manter:
            audio.unlink(missing_ok=True)
