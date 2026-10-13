"""Tarefas da Ayanami: criar, ver, cancelar e acompanhar o estado (dono: Y3.1; spec §4.3, R2).

- :class:`TarefaIn` (validado por :func:`validar`) e :class:`TarefaOut` (JSON da §2.2).
- :func:`criar_tarefa`: insere em ``tarefas`` e defere o job com ``queueing_lock=chave``; mesma
  chave viva (índice ``tarefas_chave_viva``) ou ``AlreadyEnqueued`` → devolve a existente com
  ``criada=False`` (DS3: o lock da lib só vê ``todo``; quem segura em ``doing`` é o índice).
- :func:`cancelar_tarefa`: na fila → ``cancel_job_by_id_async`` e grava ``cancelada`` aqui (o
  worker nunca vê); rodando → ``abort=True`` e devolve ``"cancelando"`` (o middleware grava
  ``cancelada`` quando o job sai).
- :func:`on_job_status` (S5: a 3.10 não tem ``on_job_status``): fábrica do ``worker_middleware``
  que grava ``rodando`` → ``ok``/``falhou``/``cancelada`` (ou ``na_fila`` se o retry ainda tem
  tentativa) nos jobs com ``tarefa_id``. Falha final com ``avisar`` → evento ``tarefa_falhou``
  (linha em ``eventos`` + ``NOTIFY ayanami_eventos``).
- :func:`redigir`: tira ``sk-…``, ``ayn_…`` e ``Bearer …`` de toda mensagem de erro gravada.

O banco é síncrono (``psycopg``); as funções async rodam os acessos em ``asyncio.to_thread``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID

import psycopg
from procrastinate import exceptions as pexc
from procrastinate.job_context import AbortReason
from psycopg.types.json import Jsonb

from ayanami import fila
from ayanami.db import Db, transacao
from ayanami.relogio import Relogio, RelogioReal

Tipo = Literal["pesquisa", "resumo", "lembrete", "monitor", "stt"]
Estado = Literal["na_fila", "rodando", "ok", "falhou", "cancelada"]
TIPOS: tuple[str, ...] = ("pesquisa", "resumo", "lembrete", "monitor", "stt")
VIVOS = ("na_fila", "rodando")
TERMINAIS = ("ok", "falhou", "cancelada")
CANAL_EVENTOS = "ayanami_eventos"

# estado do job do procrastinate → estado da tarefa (§4.3)
ESTADO_DO_JOB: Mapping[str, Estado] = {
    "todo": "na_fila",
    "doing": "rodando",
    "succeeded": "ok",
    "failed": "falhou",
    "cancelled": "cancelada",
    "aborted": "cancelada",
}

JOB_DO_TIPO: Mapping[str, str] = {
    "pesquisa": "agente.pesquisar",
    "resumo": "agente.pesquisar",
    "lembrete": "agente.lembrete",
    "monitor": "monitor.passo",
    "stt": "stt.transcrever",
}

_SEGREDOS = (
    (re.compile(r"sk-[A-Za-z0-9_\-]+"), "sk-…"),
    (re.compile(r"ayn_[A-Za-z0-9_\-]+"), "ayn_…"),
    (re.compile(r"Bearer\s+\S+", re.IGNORECASE), "Bearer …"),
)


def redigir(texto: str, limite: int = 500) -> str:
    """Mensagem sem ``sk-…``, ``ayn_…`` e ``Bearer …``, cortada em ``limite``."""
    for padrao, troca in _SEGREDOS:
        texto = padrao.sub(troca, texto)
    return texto[:limite]


class TarefaInvalida(ValueError):
    def __init__(self, campo: str, msg: str) -> None:
        super().__init__(f"{campo}: {msg}")
        self.campo = campo


class TarefaNaoEncontrada(LookupError):
    pass


class JaTerminou(RuntimeError):
    def __init__(self, estado: str) -> None:
        super().__init__(f"tarefa já terminou ({estado})")
        self.estado = estado


@dataclass(frozen=True, slots=True)
class TarefaIn:
    tipo: Tipo
    titulo: str
    params: Mapping[str, Any]
    chave: str | None = None
    pessoal: bool = False
    avisar: bool = True


@dataclass(frozen=True, slots=True)
class TarefaOut:
    id: UUID
    tipo: str
    titulo: str
    estado: Estado
    progresso: int | None
    frase: str | None
    origem: int | None
    criada: datetime
    atualizada: datetime
    resultado: Mapping[str, Any] | None
    erro: str | None
    job_id: int | None = field(default=None, compare=False)
    chave: str | None = field(default=None, compare=False)

    def para_json(self) -> dict[str, Any]:
        from ayanami.api.auth import iso_z

        return {
            "id": str(self.id), "tipo": self.tipo, "titulo": self.titulo, "estado": self.estado,
            "progresso": self.progresso, "frase": self.frase, "origem": self.origem,
            "criada": iso_z(self.criada), "atualizada": iso_z(self.atualizada),
            "resultado": self.resultado, "erro": self.erro,
        }


_COLUNAS = ("id, tipo, titulo, estado, progresso, frase, origem, criada, atualizada, resultado, "
            "erro, job_id, chave")


def _out(r: Any) -> TarefaOut:
    return TarefaOut(*r)


# --------------------------------------------------------------------------- validação


def _texto(params: Mapping[str, Any], nome: str, maximo: int) -> str:
    v = params.get(nome)
    if not isinstance(v, str) or not v.strip():
        raise TarefaInvalida(f"params.{nome}", "obrigatório")
    if len(v) > maximo:
        raise TarefaInvalida(f"params.{nome}", f"mais de {maximo} caracteres")
    return v


def _inteiro(params: Mapping[str, Any], nome: str, padrao: int, minimo: int, maximo: int) -> int:
    v = params.get(nome, padrao)
    if isinstance(v, bool) or not isinstance(v, int) or not minimo <= v <= maximo:
        raise TarefaInvalida(f"params.{nome}", f"inteiro de {minimo} a {maximo}")
    return v


def _quando(params: Mapping[str, Any]) -> datetime:
    v = params.get("quando")
    try:
        quando = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError as e:
        raise TarefaInvalida("params.quando", "data ISO 8601 com fuso") from e
    if quando.tzinfo is None:
        raise TarefaInvalida("params.quando", "data ISO 8601 com fuso")
    return quando


def validar(t: TarefaIn) -> dict[str, Any]:
    """Confere ``t`` (§4.3) e devolve os ``params`` normalizados."""
    if t.tipo not in TIPOS:
        raise TarefaInvalida("tipo", "desconhecido")
    if not isinstance(t.titulo, str) or not 1 <= len(t.titulo.strip()) <= 120 or len(t.titulo) > 120:
        raise TarefaInvalida("titulo", "1 a 120 caracteres")
    if t.chave is not None and (not isinstance(t.chave, str) or not 1 <= len(t.chave) <= 128):
        raise TarefaInvalida("chave", "1 a 128 caracteres")
    p = dict(t.params or {})
    if t.tipo in ("pesquisa", "resumo"):
        return {"pedido": _texto(p, "pedido", 2000)}
    if t.tipo == "lembrete":
        return {"texto": _texto(p, "texto", 2000), "quando": _quando(p).isoformat()}
    if t.tipo == "monitor":
        return {"o_que": _texto(p, "o_que", 2000), "condicao": _texto(p, "condicao", 2000),
                "a_cada_h": _inteiro(p, "a_cada_h", 2, 1, 6),
                "expira_dias": _inteiro(p, "expira_dias", 30, 1, 90)}
    return {"arquivo": _texto(p, "arquivo", 200)}


def chave_padrao(tipo: str, params: Mapping[str, Any]) -> str:
    bruto = tipo + json.dumps(params, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(bruto.encode()).hexdigest()


# --------------------------------------------------------------------------- banco


def _ler(conn: psycopg.Connection, tid: UUID | str) -> TarefaOut | None:
    r = conn.execute(f"SELECT {_COLUNAS} FROM tarefas WHERE id = %s", (str(tid),)).fetchone()
    return _out(r) if r else None


def obter_tarefa(db: Db, tid: UUID | str) -> TarefaOut | None:
    with db.connection() as conn:
        t = _ler(conn, tid)
        if not conn.autocommit:
            conn.rollback()
    return t


def listar_tarefas(db: Db, estado: str | None = None, n: int = 50) -> list[TarefaOut]:
    with db.connection() as conn:
        linhas = conn.execute(
            f"SELECT {_COLUNAS} FROM tarefas WHERE (%(e)s::text IS NULL OR estado = %(e)s)"
            " ORDER BY atualizada DESC, id LIMIT %(n)s",
            {"e": estado, "n": n},
        ).fetchall()
        if not conn.autocommit:
            conn.rollback()
    return [_out(r) for r in linhas]


def marcar(db: Db, tid: UUID | str, estado: Estado, agora: datetime, *, de: tuple[str, ...] = VIVOS,
           **campos: Any) -> TarefaOut | None:
    """Muda o estado (só a partir de ``de``) e grava ``campos``; ``None`` se não mudou."""
    sets = ["estado = %(estado)s", "atualizada = %(agora)s"]
    valores: dict[str, Any] = {"estado": estado, "agora": agora, "id": str(tid), "de": list(de)}
    for nome, v in campos.items():
        if nome not in ("erro", "resultado", "progresso", "frase", "job_id"):
            raise ValueError(f"campo {nome!r}")
        sets.append(f"{nome} = %({nome})s")
        valores[nome] = Jsonb(v) if nome == "resultado" and v is not None else v
    with transacao(db) as conn:
        r = conn.execute(
            f"UPDATE tarefas SET {', '.join(sets)} WHERE id = %(id)s AND estado = ANY(%(de)s)"
            f" RETURNING {_COLUNAS}",
            valores,
        ).fetchone()
    return _out(r) if r else None


def criar_evento(conn: psycopg.Connection, tipo: str, titulo: str, resumo: str, ref: str,
                 agora: datetime) -> int:
    """Linha em ``eventos`` + ``NOTIFY ayanami_eventos`` (payload = id). A Y2.3 é dona dos eventos;
    isto só grava o aviso de falha da §4.3."""
    eid = conn.execute(
        "INSERT INTO eventos (tipo, titulo, resumo, ref, criado) VALUES (%s, %s, %s, %s, %s)"
        " RETURNING id",
        (tipo, titulo[:120], resumo[:500], ref, agora),
    ).fetchone()[0]
    conn.execute("SELECT pg_notify(%s, %s)", (CANAL_EVENTOS, str(eid)))
    return int(eid)


def _falhar(db: Db, tid: str, erro: str, agora: datetime) -> TarefaOut | None:
    t = marcar(db, tid, "falhou", agora, erro=redigir(erro))
    if t is not None:
        with transacao(db) as conn:
            avisar = conn.execute("SELECT avisar FROM tarefas WHERE id = %s", (tid,)).fetchone()
            if avisar and avisar[0]:
                criar_evento(conn, "tarefa_falhou", t.titulo, t.erro or "", f"tarefa:{tid}", agora)
    return t


# --------------------------------------------------------------------------- criar e cancelar


def _inserir(db: Db, t: TarefaIn, params: dict[str, Any], chave: str, origem: int | None,
             agora: datetime) -> tuple[TarefaOut, bool]:
    agenda = expira = None
    if t.tipo == "lembrete":
        agenda = datetime.fromisoformat(params["quando"])
    elif t.tipo == "monitor":
        agenda = agora
        expira = agora + timedelta(days=params["expira_dias"])
    try:
        with transacao(db) as conn:
            r = conn.execute(
                "INSERT INTO tarefas (tipo, titulo, chave, origem, params, pessoal, avisar, agenda,"
                " expira, criada, atualizada) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
                f" RETURNING {_COLUNAS}",
                (t.tipo, t.titulo.strip(), chave, origem, Jsonb(params), t.pessoal, t.avisar,
                 agenda, expira, agora, agora),
            ).fetchone()
        return _out(r), True
    except psycopg.errors.UniqueViolation:
        with db.connection() as conn:
            r = conn.execute(
                f"SELECT {_COLUNAS} FROM tarefas WHERE chave = %s AND estado = ANY(%s)",
                (chave, list(VIVOS)),
            ).fetchone()
            if not conn.autocommit:
                conn.rollback()
        if r is None:  # terminou entre o INSERT e o SELECT: tenta de novo
            return _inserir(db, t, params, chave, origem, agora)
        return _out(r), False


def _apagar_e_achar_outra(db: Db, nova: TarefaOut) -> TarefaOut | None:
    with transacao(db) as conn:
        conn.execute("DELETE FROM tarefas WHERE id = %s", (str(nova.id),))
        r = conn.execute(
            f"SELECT {_COLUNAS} FROM tarefas WHERE chave = %s ORDER BY criada DESC LIMIT 1",
            (nova.chave,),
        ).fetchone()
    return _out(r) if r else None


async def criar_tarefa(db: Db, t: TarefaIn, origem: int | None, *, app: Any = None,
                       relogio: Relogio | None = None) -> tuple[TarefaOut, bool]:
    """``(tarefa, criada?)``; ``app`` padrão = o de produção (:func:`ayanami.fila.app_aberto`)."""
    params = validar(t)
    chave = t.chave or chave_padrao(t.tipo, params)
    agora = (relogio or RelogioReal()).agora()
    tarefa, criada = await asyncio.to_thread(_inserir, db, t, params, chave, origem, agora)
    if not criada:
        return tarefa, False
    app = await fila.app_aberto(app)
    nome = JOB_DO_TIPO[t.tipo]
    extra: dict[str, Any] = {}
    if t.tipo == "lembrete":
        extra["schedule_at"] = datetime.fromisoformat(params["quando"])
    opcoes = fila.defer_opcoes(nome, chave=chave, lock_id=str(tarefa.id), **extra)
    try:
        job_id = await app.configure_task(nome, **opcoes).defer_async(tarefa_id=str(tarefa.id))
    except pexc.AlreadyEnqueued:
        outra = await asyncio.to_thread(_apagar_e_achar_outra, db, tarefa)
        if outra is None:
            raise
        return outra, False
    except Exception as e:
        await asyncio.to_thread(marcar, db, tarefa.id, "falhou", agora,
                                erro=redigir(f"fila: {type(e).__name__}: {e}"))
        raise
    marcada = await asyncio.to_thread(_gravar_job, db, tarefa.id, job_id)
    return marcada or tarefa, True


def _gravar_job(db: Db, tid: UUID, job_id: int) -> TarefaOut | None:
    with transacao(db) as conn:
        r = conn.execute(
            f"UPDATE tarefas SET job_id = %s WHERE id = %s RETURNING {_COLUNAS}", (job_id, str(tid))
        ).fetchone()
    return _out(r) if r else None


async def cancelar_tarefa(db: Db, id: UUID | str, *, app: Any = None,
                          relogio: Relogio | None = None) -> Literal["cancelada", "cancelando"]:
    """Na fila → ``"cancelada"`` (o job nunca roda); rodando → abort e ``"cancelando"``.
    Sem a tarefa → :class:`TarefaNaoEncontrada`; já terminada → :class:`JaTerminou`."""
    agora = (relogio or RelogioReal()).agora()
    t = await asyncio.to_thread(obter_tarefa, db, id)
    if t is None:
        raise TarefaNaoEncontrada(str(id))
    if t.estado in TERMINAIS:
        raise JaTerminou(t.estado)
    if t.job_id is None:
        if await asyncio.to_thread(marcar, db, t.id, "cancelada", agora):
            return "cancelada"
        raise JaTerminou((await asyncio.to_thread(obter_tarefa, db, id)).estado)  # type: ignore[union-attr]
    app = await fila.app_aberto(app)
    jm = app.job_manager
    if await jm.cancel_job_by_id_async(t.job_id):
        await asyncio.to_thread(marcar, db, t.id, "cancelada", agora)
        return "cancelada"
    status = (await jm.get_job_status_async(t.job_id)).value
    if status == "doing":
        await jm.cancel_job_by_id_async(t.job_id, abort=True)
        return "cancelando"
    novo = ESTADO_DO_JOB.get(status, "cancelada")
    if novo in TERMINAIS:
        await asyncio.to_thread(marcar, db, t.id, novo, agora)
        raise JaTerminou(novo)
    return "cancelando"


# --------------------------------------------------------------------------- middleware do worker

ProximoJob = Callable[[], Awaitable[Any]]


def _vai_repetir(contexto: Any, e: BaseException) -> bool:
    task = contexto.app.tasks.get(contexto.job.task_name)
    return bool(task and task.get_retry_exception(exception=e, job=contexto.job))


def _resultado(r: Any) -> dict[str, Any] | None:
    if r is None:
        return None
    if isinstance(r, Mapping):
        return {"texto": str(r.get("texto", ""))[:6000], "dados": dict(r.get("dados") or {})}
    return {"texto": str(r)[:6000], "dados": {}}


def on_job_status(deps: Any) -> Callable[[ProximoJob, Any, Any], Awaitable[Any]]:
    """``worker_middleware`` que sincroniza ``tarefas`` com o desfecho dos jobs (§4.3, S5)."""
    db = deps.db

    def agora() -> datetime:
        return deps.relogio.agora()

    async def middleware(call_next: ProximoJob, contexto: Any, worker: Any) -> Any:
        tid = (contexto.job.task_kwargs or {}).get("tarefa_id")
        if not tid:
            return await call_next()
        await asyncio.to_thread(marcar, db, tid, "rodando", agora(), de=("na_fila",))
        try:
            r = await call_next()
        except fila.PrazoEstourado:
            await asyncio.to_thread(_falhar, db, tid, "prazo", agora())
            raise
        except (pexc.JobAborted, asyncio.CancelledError) as e:
            desligando = contexto.abort_reason() == AbortReason.SHUTDOWN
            novo: Estado = "na_fila" if desligando and _vai_repetir(contexto, e) else "cancelada"
            await asyncio.shield(asyncio.to_thread(marcar, db, tid, novo, agora()))
            raise
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            if _vai_repetir(contexto, e):
                await asyncio.to_thread(marcar, db, tid, "na_fila", agora(), erro=redigir(msg))
            else:
                await asyncio.to_thread(_falhar, db, tid, msg, agora())
            raise
        await asyncio.to_thread(marcar, db, tid, "ok", agora(), resultado=_resultado(r), erro=None)
        return r

    middleware.__name__ = "on_job_status"
    return middleware
