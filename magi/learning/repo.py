"""Repositório do Learning Mode (tarefa LM1.1; design §8, spec §8, §10–§10.3; DAT-001..003,
MEM-002, LM-010, LM-011, LM-012, LM-013).

Interface única ``LearningRepo`` (assíncrona) com dois backends, escolhidos por
``[learning] storage`` (P4) em ``make_repo``:

- ``PostgresRepo``: tabelas ``learning_*`` da migração ``003_learning.sql`` sobre a conexão
  compartilhada do núcleo (``magi.memory.conn.SerialConn``). Se o banco cai, mensagens,
  observações, tema, fechamento e resumo ficam num buffer em memória (até ``BUFFER_MAX`` itens; o
  mais antigo sai primeiro) e são gravados na volta, na ordem. Mensagens gravadas no buffer
  recebem ID provisório **negativo**; depois da gravação o repositório traduz o ID provisório para o
  real em toda chamada. Ações não têm cache com o banco fora (spec §11 "Banco cai").
- ``JsonlRepo``: um arquivo por sessão em ``~/.local/share/magi/learning/LS-….jsonl`` (linhas
  ``{"kind": "session"|"msg"|"obs"|"act"|"topic"|"end"|"summary", …}``) e
  ``saved_words.jsonl`` (linhas ``{"op": "save"|"unsave", …}``). Tudo é carregado em memória ao
  abrir.

Regras comuns
-------------
- Observação sem ``rule_key`` ou sem ``session_id`` é recusada com ``ValueError`` (MEM-002, CA-16).
- ``set_topic`` só acrescenta em ``topics`` quando o tema muda (o mesmo tema de novo só confirma).
- Palavras salvas: um ativo por ``norm`` (``normalize_term``); ``save_word`` com ``norm`` já ativo
  devolve o existente; ``unsave_word`` marca ``removed_at`` (nunca apaga); salvar de novo cria
  linha nova (spec §10.3).
- ``session_stats`` junta o que o resumo (LM4.5) lê: sessão, contagens de mensagens, observações e
  palavras salvas ativas da sessão; no Postgres tem prazo de ``STATS_TIMEOUT_S`` e cai no buffer.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import psycopg

from magi.learning.config import LearningConfig
from magi.learning.contracts import (
    SESSION_ID_RE,
    ActionKind,
    ActionResult,
    Author,
    LearningMessage,
    ObsCategory,
    Observation,
    SavedWord,
    SessionSummary,
    Source,
    Topic,
    make_session_id,
)
from magi.learning.interview.contracts import (
    InterviewDebrief,
    InterviewRun,
    JobPost,
    JobProfile,
    RunState,
)

log = logging.getLogger(__name__)

#: Itens guardados em memória enquanto o banco está fora (spec §11).
BUFFER_MAX = 500
#: Prazo de leitura do resumo (spec §10.2 item 2).
STATS_TIMEOUT_S = 2.0
#: Mensagens recarregadas ao reconectar o HUD (spec §10).
RECENT_DEFAULT = 200
#: Pasta padrão do backend JSONL (P4).
DEFAULT_JSONL_DIR = Path.home() / ".local" / "share" / "magi" / "learning"
SAVED_WORDS_FILE = "saved_words.jsonl"
#: Vagas do backend JSONL (LI0.2, spec §8): linhas ``{"op": "job"|"profile"|"used", …}``.
JOBS_FILE = "jobs.jsonl"
#: Estados em que a simulação está encerrada (``ended_at`` preenchido).
_RUN_ENDED = (RunState.DONE, RunState.ERROR)

_DB_ERRORS = (psycopg.OperationalError, psycopg.InterfaceError, OSError, asyncio.TimeoutError)
_EDGE_PUNCT = re.compile(r"^[\W_]+|[\W_]+$")


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(at: datetime | None) -> datetime:
    if at is None:
        return _now()
    if at.tzinfo is None:
        raise ValueError("datetime precisa de fuso horário")
    return at


def normalize_term(term: str) -> str:
    """``norm`` de uma palavra salva: minúsculas, sem pontuação nas pontas, espaços simples
    (spec §10.3 item 2). Ex.: ``"  Trade-Off!"`` → ``"trade-off"``."""
    return _EDGE_PUNCT.sub("", " ".join(term.split()).lower())


def _check_observation(obs: Observation) -> None:
    if not obs.session_id:
        raise ValueError("observação sem session_id (MEM-002)")
    if not obs.rule_key or not obs.rule_key.strip():
        raise ValueError("observação sem rule_key (MEM-002)")


# ---------------------------------------------------------------------------------------------
# Tipos do repositório
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionInfo:
    """Linha de ``learning_sessions``. ``topics`` = ``[(tema, quando), …]`` em ordem."""

    id: str
    started_at: datetime
    ended_at: datetime | None
    end_reason: str | None
    level: str | None
    track: str | None
    topic: Topic
    topics: list[tuple[Topic, datetime]] = field(default_factory=list)
    summary: SessionSummary | None = None
    scenario: str | None = None  # cenário do roleplay da última entrada de ``topics`` (LI5.1)


@dataclass(frozen=True)
class SessionStats:
    """O que o resumo ao sair lê (spec §10.2 item 2), sem LLM. ``observations`` em ordem de
    gravação; ``saved`` = palavras com ``session_id`` da sessão e ``removed_at`` nulo."""

    session: SessionInfo
    n_msgs: int
    n_you: int
    last_msg_at: datetime | None
    observations: list[Observation]
    saved: list[SavedWord]


@dataclass(frozen=True)
class StoredAction:
    """Ação gravada, resolvida pelo ``action_id`` (o núcleo usa em ``lm_save``, spec §10.3)."""

    result: ActionResult
    message_id: int
    sel_start: int
    sel_end: int


@dataclass(frozen=True)
class StoredJob:
    """Linha de ``learning_jobs`` (LI0.2, spec §8). ``profile`` é ``None`` até a extração dar certo."""

    post: JobPost
    profile: JobProfile | None
    last_used: datetime
    model: str | None = None
    cost_usd: float | None = None


@dataclass(frozen=True)
class InterviewInfo:
    """Uma simulação pelo id (LI5.1): título/empresa/fim do retorno pendente depois de reiniciar
    o núcleo e a run inteira para refazer o retorno (``run`` = ``None`` se a vaga sumiu)."""

    run_id: str
    session_id: str
    job_id: str
    title: str | None
    company: str | None
    started_at: datetime
    ended_at: datetime | None = None
    end_reason: str | None = None
    has_debrief: bool = False
    run: InterviewRun | None = None


def _same_topic(s: SessionInfo, topic: Topic, scenario: str | None) -> bool:
    """O tema (e o cenário) de agora já é o da última entrada: ``set_topic`` só confirma."""
    return bool(s.topics) and s.topics[-1][0] == topic and s.scenario == (scenario or None)


@dataclass
class _IvRow:
    """Linha de ``learning_interviews`` no backend em memória/JSONL."""

    run: InterviewRun
    started_at: datetime
    ended_at: datetime | None = None
    end_reason: str | None = None
    debrief: InterviewDebrief | None = None
    seen: bool = False
    debrief_seq: int = 0


@runtime_checkable
class LearningRepo(Protocol):
    """Contrato do repositório (igual nos dois backends)."""

    # sessão
    async def open_session(
        self, *, level: str | None, track: str | None, topic: Topic = Topic.FREE,
        at: datetime | None = None,
    ) -> SessionInfo: ...
    async def get_session(self, session_id: str) -> SessionInfo | None: ...
    async def open_session_last(self) -> SessionInfo | None: ...
    async def end_session(self, session_id: str, reason: str, at: datetime | None = None) -> None: ...
    async def set_topic(self, session_id: str, topic: Topic, at: datetime | None = None, *,
                        scenario: str | None = None) -> bool: ...
    async def session_stats(self, session_id: str) -> SessionStats | None: ...
    async def save_summary(self, session_id: str, summary: SessionSummary) -> None: ...
    # mensagens
    async def add_message(
        self, session_id: str, author: Author, source: Source, text: str, *,
        text_final: str | None = None, turn_id: int | None = None, at: datetime | None = None,
    ) -> LearningMessage: ...
    async def get_message(self, message_id: int) -> LearningMessage | None: ...
    async def recent_messages(
        self, session_id: str, limit: int = RECENT_DEFAULT
    ) -> list[LearningMessage]: ...
    # observações
    async def add_observation(self, obs: Observation, *, model: str | None = None,
                              at: datetime | None = None) -> Observation: ...
    async def observations(self, session_id: str) -> list[Observation]: ...
    # ações
    async def cached_action(self, message_id: int, kind: ActionKind, sel_start: int,
                            sel_end: int) -> ActionResult | None: ...
    async def save_action(self, result: ActionResult, *, message_id: int, sel_start: int,
                          sel_end: int, model: str | None = None) -> None: ...
    async def get_action(self, action_id: str) -> StoredAction | None: ...
    # palavras salvas
    async def save_word(self, word: SavedWord) -> SavedWord: ...
    async def unsave_word(self, norm: str, at: datetime | None = None) -> bool: ...
    async def saved_norms(self) -> set[str]: ...
    async def saved_words(self, session_id: str | None = None) -> list[SavedWord]: ...
    # -- entrevista pela vaga (LI0.2, spec §8) --
    async def save_job(self, post: JobPost, at: datetime | None = None) -> None: ...
    async def get_job(self, job_id: str) -> StoredJob | None: ...
    async def set_profile(self, job_id: str, profile: JobProfile, *, model: str | None = None,
                          cost_usd: float | None = None) -> bool: ...
    async def recent_jobs(self, n: int = 3) -> list[tuple[str, JobProfile]]: ...
    async def save_interview(self, run: InterviewRun, end_reason: str | None = None,
                             at: datetime | None = None) -> None: ...
    async def active_interview(self, session_id: str) -> InterviewRun | None: ...
    async def interview_of(self, run_id: str) -> InterviewInfo | None: ...
    async def save_debrief(self, debrief: InterviewDebrief) -> bool: ...
    async def unseen_debrief(self) -> InterviewDebrief | None: ...
    async def mark_seen(self, run_id: str) -> bool: ...


def _local_day(at: datetime) -> date:
    return at.astimezone().date()


def _next_n(existing: list[str], day: date) -> int:
    prefix = f"LS-{day:%Y%m%d}-"
    ns = [int(m.group(2)) for s in existing if s.startswith(prefix) and (m := SESSION_ID_RE.match(s))]
    return max(ns, default=0) + 1


def _topics_from_json(raw: Any) -> list[tuple[Topic, datetime]]:
    out: list[tuple[Topic, datetime]] = []
    for item in raw or []:
        try:
            out.append((Topic(item["topic"]), datetime.fromisoformat(item["at"])))
        except (KeyError, ValueError, TypeError):
            continue
    return out


def _topics_to_json(topics: list[tuple[Topic, datetime]],
                    scenario: str | None = None) -> list[dict[str, str]]:
    out = [{"topic": t.value, "at": at.isoformat()} for t, at in topics]
    if out and scenario:
        out[-1]["scenario"] = scenario
    return out


def _scenario_from_json(raw: Any) -> str | None:
    """Cenário gravado na última entrada de ``topics`` (``None`` se não houver)."""
    try:
        last = (raw or [])[-1]
    except (IndexError, TypeError, KeyError):
        return None
    sc = last.get("scenario") if isinstance(last, dict) else None
    return sc if isinstance(sc, str) and sc else None


# ---------------------------------------------------------------------------------------------
# Núcleo em memória (base do JSONL e do buffer do Postgres)
# ---------------------------------------------------------------------------------------------


class _Mem:
    """Estado em memória com a mesma semântica das tabelas."""

    def __init__(self) -> None:
        self.sessions: dict[str, SessionInfo] = {}
        self.messages: dict[int, LearningMessage] = {}
        self.observations: list[Observation] = []
        self.actions: dict[str, StoredAction] = {}
        self.words: list[SavedWord] = []
        self.next_msg = 1
        self.next_obs = 1
        self.next_word = 1
        self.jobs: dict[str, StoredJob] = {}
        self.interviews: dict[str, _IvRow] = {}
        self.debrief_seq = 0

    # -- entrevista pela vaga (LI0.2) -----------------------------------------------------------

    def save_job(self, post: JobPost, at: datetime) -> None:
        old = self.jobs.get(post.id)
        self.jobs[post.id] = StoredJob(post, None, at) if old is None else replace(old, last_used=at)

    def set_profile(self, job_id: str, profile: JobProfile, model: str | None,
                    cost_usd: float | None) -> bool:
        old = self.jobs.get(job_id)
        if old is None:
            return False
        self.jobs[job_id] = replace(old, profile=profile, model=model, cost_usd=cost_usd)
        return True

    def recent_jobs(self, n: int) -> list[tuple[str, JobProfile]]:
        done = [j for j in self.jobs.values() if j.profile is not None]
        done.sort(key=lambda j: j.last_used, reverse=True)
        return [(j.post.id, j.profile) for j in done[:max(n, 0)] if j.profile is not None]

    def save_interview(self, run: InterviewRun, end_reason: str | None, at: datetime) -> None:
        row = self.interviews.get(run.id)
        if row is None:
            row = self.interviews[run.id] = _IvRow(run, at)
        row.run = run
        if end_reason is not None:
            row.end_reason = end_reason
        if row.ended_at is None and (end_reason is not None or run.state in _RUN_ENDED):
            row.ended_at = at

    def active_interview(self, session_id: str) -> InterviewRun | None:
        open_ = [r for r in self.interviews.values()
                 if r.run.session_id == session_id and r.ended_at is None]
        return max(open_, key=lambda r: (r.started_at, r.run.id)).run if open_ else None

    def save_debrief(self, debrief: InterviewDebrief) -> bool:
        row = self.interviews.get(debrief.run_id)
        if row is None:
            return False
        self.debrief_seq += 1
        row.debrief, row.seen, row.debrief_seq = debrief, False, self.debrief_seq
        return True

    def unseen_debrief(self) -> InterviewDebrief | None:
        rows = [r for r in self.interviews.values() if r.debrief is not None and not r.seen]
        return max(rows, key=lambda r: r.debrief_seq).debrief if rows else None

    def mark_seen(self, run_id: str) -> bool:
        row = self.interviews.get(run_id)
        if row is None or row.debrief is None or row.seen:
            return False
        row.seen = True
        return True

    def put_session(self, info: SessionInfo) -> None:
        self.sessions[info.id] = info

    def add_message(self, msg: LearningMessage) -> None:
        self.messages[msg.id] = msg
        self.next_msg = max(self.next_msg, msg.id + 1)

    def add_obs(self, obs: Observation) -> None:
        self.observations.append(obs)
        if obs.id is not None:
            self.next_obs = max(self.next_obs, obs.id + 1)

    def set_topic(self, session_id: str, topic: Topic, at: datetime,
                  scenario: str | None = None) -> bool:
        s = self.sessions[session_id]
        if _same_topic(s, topic, scenario):
            return False
        self.sessions[session_id] = replace(s, topic=topic, topics=[*s.topics, (topic, at)],
                                            scenario=scenario or None)
        return True

    def interview_of(self, run_id: str) -> InterviewInfo | None:
        row = self.interviews.get(run_id)
        if row is None:
            return None
        r = row.run
        return InterviewInfo(r.id, r.session_id, r.job_id, r.profile.title, r.profile.company,
                             row.started_at, row.ended_at, row.end_reason,
                             row.debrief is not None, r)

    def stats(self, session_id: str) -> SessionStats | None:
        s = self.sessions.get(session_id)
        if s is None:
            return None
        msgs = sorted((m for m in self.messages.values() if m.session_id == session_id), key=lambda m: m.id)
        return SessionStats(
            session=s,
            n_msgs=len(msgs),
            n_you=sum(1 for m in msgs if m.author is Author.YOU),
            last_msg_at=max((m.at for m in msgs), default=None),
            observations=[o for o in self.observations if o.session_id == session_id],
            saved=[w for w in self.words if w.session_id == session_id and w.removed_at is None],
        )

    def active(self, norm: str) -> SavedWord | None:
        return next((w for w in self.words if w.norm == norm and w.removed_at is None), None)

    def save_word(self, word: SavedWord) -> SavedWord:
        existing = self.active(word.norm)
        if existing is not None:
            return existing
        w = replace(word, id=word.id if word.id is not None else self.next_word, removed_at=None)
        self.words.append(w)
        self.next_word = max(self.next_word, (w.id or 0) + 1)
        return w

    def unsave_word(self, norm: str, at: datetime) -> bool:
        for i, w in enumerate(self.words):
            if w.norm == norm and w.removed_at is None:
                self.words[i] = replace(w, removed_at=at)
                return True
        return False


# ---------------------------------------------------------------------------------------------
# JSONL
# ---------------------------------------------------------------------------------------------


class JsonlRepo:
    """Backend JSONL (P4): sem banco; o contrato é o mesmo do ``PostgresRepo``."""

    def __init__(self, root: Path | str = DEFAULT_JSONL_DIR) -> None:
        self.root = Path(root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)
        self._mem = _Mem()
        self._load()

    # -- arquivo --------------------------------------------------------------------------------

    def _session_file(self, session_id: str) -> Path:
        if not SESSION_ID_RE.match(session_id):
            raise ValueError(f"ID de sessão inválido: {session_id!r}")
        return self.root / f"{session_id}.jsonl"

    def _append(self, path: Path, row: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    @staticmethod
    def _rows(path: Path) -> list[dict[str, Any]]:
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                log.warning("linha inválida ignorada em %s", path.name)
                continue
            if isinstance(row, dict):
                rows.append(row)
        return rows

    def _load(self) -> None:
        m = self._mem
        for path in sorted(self.root.glob("LS-*.jsonl")):
            for row in self._rows(path):
                try:
                    self._apply(row)
                except (KeyError, ValueError, TypeError) as exc:
                    log.warning("linha ignorada em %s: %s", path.name, exc)
        words = self.root / SAVED_WORDS_FILE
        if words.exists():
            for row in self._rows(words):
                try:
                    if row.get("op") == "save":
                        w = SavedWord.from_dict(row["word"])
                        m.words.append(w)
                        m.next_word = max(m.next_word, (w.id or 0) + 1)
                    elif row.get("op") == "unsave":
                        m.unsave_word(row["norm"], datetime.fromisoformat(row["at"]))
                except (KeyError, ValueError, TypeError) as exc:
                    log.warning("linha ignorada em %s: %s", SAVED_WORDS_FILE, exc)
        jobs = self.root / JOBS_FILE
        if jobs.exists():
            for row in self._rows(jobs):
                try:
                    self._apply_job(row)
                except (KeyError, ValueError, TypeError) as exc:
                    log.warning("linha ignorada em %s: %s", JOBS_FILE, exc)

    def _apply_job(self, row: dict[str, Any]) -> None:
        m = self._mem
        op = row["op"]
        if op == "job":
            m.save_job(JobPost.from_dict(row["post"]), datetime.fromisoformat(row["at"]))
        elif op == "used":
            m.save_job(m.jobs[row["job_id"]].post, datetime.fromisoformat(row["at"]))
        elif op == "profile":
            m.set_profile(row["job_id"], JobProfile.from_dict(row["profile"]), row.get("model"),
                          row.get("cost_usd"))

    def _apply(self, row: dict[str, Any]) -> None:
        m = self._mem
        kind = row["kind"]
        if kind == "session":
            at = datetime.fromisoformat(row["started_at"])
            topic = Topic(row.get("topic", Topic.FREE))
            m.put_session(SessionInfo(row["id"], at, None, None, row.get("level"), row.get("track"),
                                      topic, [(topic, at)]))
        elif kind == "msg":
            m.add_message(LearningMessage.from_dict(row["msg"]))
        elif kind == "obs":
            m.add_obs(Observation.from_dict(row["obs"]))
        elif kind == "act":
            res = ActionResult.from_dict(row["result"])
            m.actions[res.id] = StoredAction(res, row["message_id"], row["sel_start"], row["sel_end"])
        elif kind == "topic":
            m.set_topic(row["session_id"], Topic(row["topic"]), datetime.fromisoformat(row["at"]),
                        row.get("scenario"))
        elif kind == "end":
            s = m.sessions[row["session_id"]]
            m.put_session(replace(s, ended_at=datetime.fromisoformat(row["at"]), end_reason=row["reason"]))
        elif kind == "summary":
            s = m.sessions[row["session_id"]]
            m.put_session(replace(s, summary=SessionSummary.from_dict(row["summary"])))
        elif kind == "interview":  # LI0.2
            m.save_interview(InterviewRun.from_dict(row["run"]), row.get("end_reason"),
                             datetime.fromisoformat(row["at"]))
        elif kind == "debrief":
            m.save_debrief(InterviewDebrief.from_dict(row["debrief"]))
        elif kind == "seen":
            m.mark_seen(row["run_id"])

    def _write(self, session_id: str, row: dict[str, Any]) -> None:
        self._append(self._session_file(session_id), row)
        self._apply(row)

    # -- sessão ---------------------------------------------------------------------------------

    async def open_session(
        self, *, level: str | None, track: str | None, topic: Topic = Topic.FREE,
        at: datetime | None = None,
    ) -> SessionInfo:
        at = _aware(at)
        day = _local_day(at)
        sid = make_session_id(day, _next_n(list(self._mem.sessions), day))
        self._write(sid, {"kind": "session", "id": sid, "started_at": at.isoformat(),
                          "level": level, "track": track, "topic": Topic(topic).value})
        return self._mem.sessions[sid]

    async def get_session(self, session_id: str) -> SessionInfo | None:
        return self._mem.sessions.get(session_id)

    async def open_session_last(self) -> SessionInfo | None:
        open_ = [s for s in self._mem.sessions.values() if s.ended_at is None]
        return max(open_, key=lambda s: s.started_at, default=None)

    async def end_session(self, session_id: str, reason: str, at: datetime | None = None) -> None:
        self._write(session_id, {"kind": "end", "session_id": session_id, "reason": reason,
                                 "at": _aware(at).isoformat()})

    async def set_topic(self, session_id: str, topic: Topic, at: datetime | None = None, *,
                        scenario: str | None = None) -> bool:
        s = self._mem.sessions[session_id]
        if _same_topic(s, topic, scenario):
            return False
        row = {"kind": "topic", "session_id": session_id, "topic": Topic(topic).value,
               "at": _aware(at).isoformat()}
        if scenario:
            row["scenario"] = scenario
        self._write(session_id, row)
        return True

    async def session_stats(self, session_id: str) -> SessionStats | None:
        return self._mem.stats(session_id)

    async def save_summary(self, session_id: str, summary: SessionSummary) -> None:
        self._write(session_id, {"kind": "summary", "session_id": session_id, "summary": summary.to_dict()})

    # -- mensagens ------------------------------------------------------------------------------

    async def add_message(
        self, session_id: str, author: Author, source: Source, text: str, *,
        text_final: str | None = None, turn_id: int | None = None, at: datetime | None = None,
    ) -> LearningMessage:
        if session_id not in self._mem.sessions:
            raise ValueError(f"sessão desconhecida: {session_id}")
        msg = LearningMessage(
            self._mem.next_msg, session_id, Author(author), Source(source), text, _aware(at)
        )
        row: dict[str, Any] = {"kind": "msg", "msg": msg.to_dict()}
        if text_final is not None:
            row["text_final"] = text_final
        if turn_id is not None:
            row["turn_id"] = turn_id
        self._write(session_id, row)
        return msg

    async def get_message(self, message_id: int) -> LearningMessage | None:
        return self._mem.messages.get(message_id)

    async def recent_messages(self, session_id: str, limit: int = RECENT_DEFAULT) -> list[LearningMessage]:
        msgs = [m for m in self._mem.messages.values() if m.session_id == session_id]
        msgs.sort(key=lambda m: m.id)
        return msgs[-limit:] if limit > 0 else []

    # -- observações ----------------------------------------------------------------------------

    async def add_observation(self, obs: Observation, *, model: str | None = None,
                              at: datetime | None = None) -> Observation:
        _check_observation(obs)
        if obs.session_id not in self._mem.sessions:
            raise ValueError(f"sessão desconhecida: {obs.session_id}")
        saved = replace(obs, id=self._mem.next_obs)
        self._write(obs.session_id, {"kind": "obs", "obs": saved.to_dict(), "model": model,
                                     "at": _aware(at).isoformat()})
        return saved

    async def observations(self, session_id: str) -> list[Observation]:
        return [o for o in self._mem.observations if o.session_id == session_id]

    # -- ações ----------------------------------------------------------------------------------

    async def cached_action(self, message_id: int, kind: ActionKind, sel_start: int,
                            sel_end: int) -> ActionResult | None:
        for a in self._mem.actions.values():
            key = (a.message_id, a.result.kind, a.sel_start, a.sel_end)
            if key == (message_id, kind, sel_start, sel_end):
                return replace(a.result, cached=True)
        return None

    async def save_action(self, result: ActionResult, *, message_id: int, sel_start: int,
                          sel_end: int, model: str | None = None) -> None:
        msg = self._mem.messages.get(message_id)
        if msg is None:
            raise ValueError(f"mensagem desconhecida: {message_id}")
        if await self.cached_action(message_id, result.kind, sel_start, sel_end) is not None:
            return
        self._write(msg.session_id, {"kind": "act", "result": result.to_dict(), "message_id": message_id,
                                     "sel_start": sel_start, "sel_end": sel_end, "model": model})

    async def get_action(self, action_id: str) -> StoredAction | None:
        return self._mem.actions.get(action_id)

    # -- palavras salvas ------------------------------------------------------------------------

    async def save_word(self, word: SavedWord) -> SavedWord:
        existing = self._mem.active(word.norm)
        if existing is not None:
            return existing
        w = self._mem.save_word(replace(word, id=None))
        self._append(self.root / SAVED_WORDS_FILE, {"op": "save", "word": w.to_dict()})
        return w

    async def unsave_word(self, norm: str, at: datetime | None = None) -> bool:
        at = _aware(at)
        if not self._mem.unsave_word(norm, at):
            return False
        self._append(self.root / SAVED_WORDS_FILE, {"op": "unsave", "norm": norm, "at": at.isoformat()})
        return True

    async def saved_norms(self) -> set[str]:
        return {w.norm for w in self._mem.words if w.removed_at is None}

    async def saved_words(self, session_id: str | None = None) -> list[SavedWord]:
        return [w for w in self._mem.words
                if w.removed_at is None and (session_id is None or w.session_id == session_id)]

    # -- entrevista pela vaga (LI0.2, spec §8) --------------------------------------------------

    def _append_job(self, row: dict[str, Any]) -> None:
        self._append(self.root / JOBS_FILE, row)
        self._apply_job(row)

    async def save_job(self, post: JobPost, at: datetime | None = None) -> None:
        at = _aware(at)
        if post.id in self._mem.jobs:
            self._append_job({"op": "used", "job_id": post.id, "at": at.isoformat()})
        else:
            self._append_job({"op": "job", "post": post.to_dict(), "at": at.isoformat()})

    async def get_job(self, job_id: str) -> StoredJob | None:
        return self._mem.jobs.get(job_id)

    async def set_profile(self, job_id: str, profile: JobProfile, *, model: str | None = None,
                          cost_usd: float | None = None) -> bool:
        if job_id not in self._mem.jobs:
            return False
        self._append_job({"op": "profile", "job_id": job_id, "profile": profile.to_dict(),
                          "model": model, "cost_usd": cost_usd})
        return True

    async def recent_jobs(self, n: int = 3) -> list[tuple[str, JobProfile]]:
        return self._mem.recent_jobs(n)

    async def save_interview(self, run: InterviewRun, end_reason: str | None = None,
                             at: datetime | None = None) -> None:
        self._write(run.session_id, {"kind": "interview", "run": run.to_dict(),
                                     "end_reason": end_reason, "at": _aware(at).isoformat()})

    async def active_interview(self, session_id: str) -> InterviewRun | None:
        return self._mem.active_interview(session_id)

    async def interview_of(self, run_id: str) -> InterviewInfo | None:
        return self._mem.interview_of(run_id)

    async def save_debrief(self, debrief: InterviewDebrief) -> bool:
        row = self._mem.interviews.get(debrief.run_id)
        if row is None:
            return False
        self._write(row.run.session_id, {"kind": "debrief", "debrief": debrief.to_dict()})
        return True

    async def unseen_debrief(self) -> InterviewDebrief | None:
        return self._mem.unseen_debrief()

    async def mark_seen(self, run_id: str) -> bool:
        row = self._mem.interviews.get(run_id)
        if row is None or row.debrief is None or row.seen:
            return False
        self._write(row.run.session_id, {"kind": "seen", "run_id": run_id})
        return True


# ---------------------------------------------------------------------------------------------
# Postgres
# ---------------------------------------------------------------------------------------------

_MSG_COLS = "id, session_id, author, source, text, at"
_OBS_COLS = "id, session_id, message_id, category, rule_key, label, span, suggestion"
_WORD_COLS = ("id, norm, term, meaning, pos, cefr, example, session_id, message_id, action_id,"
              " saved_at, removed_at")
_SESSION_COLS = "id, started_at, ended_at, end_reason, level, track, topic, topics, summary"


def _msg(row: Any) -> LearningMessage:
    return LearningMessage(int(row[0]), row[1], Author(row[2]), Source(row[3]), row[4], row[5])


def _obs(row: Any) -> Observation:
    return Observation(int(row[0]), row[1], int(row[2]), ObsCategory(row[3]), row[4], row[5], row[6], row[7])


def _word(row: Any) -> SavedWord:
    return SavedWord(int(row[0]), row[1], row[2], row[3], row[4], row[5], row[6], row[7], int(row[8]),
                     row[9] or "", row[10], row[11])


def _session(row: Any) -> SessionInfo:
    summary = SessionSummary.from_dict(row[8]) if row[8] else None
    return SessionInfo(row[0], row[1], row[2], row[3], row[4], row[5], Topic(row[6]),
                       _topics_from_json(row[7]), summary, _scenario_from_json(row[7]))


@dataclass
class _Pending:
    kind: str  # session | msg | obs | topic | end | summary
    args: dict[str, Any]


class PostgresRepo:
    """Backend Postgres (``public`` em produção; testes usam schema próprio pelo search_path).

    ``conn`` é a conexão compartilhada (``SerialConn`` ou ``psycopg.AsyncConnection`` em
    autocommit-off com transações explícitas). ``reconnect`` (opcional) devolve uma conexão nova
    quando a atual fechou; sem ele o repositório tenta de novo na mesma conexão."""

    def __init__(
        self,
        conn: Any,
        *,
        reconnect: Callable[[], Awaitable[Any]] | None = None,
        buffer_max: int = BUFFER_MAX,
        stats_timeout_s: float = STATS_TIMEOUT_S,
    ) -> None:
        self._conn = conn
        self._reconnect = reconnect
        self._pending: deque[_Pending] = deque()
        self._buffer_max = buffer_max
        self._stats_timeout_s = stats_timeout_s
        self._ids: dict[int, int] = {}  # ID provisório (negativo) -> real
        self._next_tmp = -1
        self._mem = _Mem()  # espelho do que está no buffer (para leitura com o banco fora)
        self._known: dict[str, SessionInfo] = {}  # sessões vistas (fallback de leitura)
        self._down = False

    # -- infraestrutura -------------------------------------------------------------------------

    @property
    def pending(self) -> int:
        """Itens no buffer à espera do banco."""
        return len(self._pending)

    def _real(self, message_id: int) -> int:
        return self._ids.get(message_id, message_id)

    async def _ensure_conn(self) -> None:
        if self._reconnect is not None and getattr(self._conn, "closed", False):
            self._conn = await self._reconnect()

    def _mark_down(self, exc: BaseException) -> None:
        if not self._down:
            log.warning("banco do Learning Mode fora (%s); gravando em memória", exc)
        self._down = True

    def _buffer(self, item: _Pending) -> None:
        if len(self._pending) >= self._buffer_max:
            dropped = self._pending.popleft()
            log.warning("buffer do Learning Mode cheio (%d); descartado: %s", self._buffer_max, dropped.kind)
        self._pending.append(item)

    async def flush(self) -> int:
        """Grava o buffer no banco, na ordem; devolve quantos itens gravou. Para no primeiro erro
        de conexão (o item volta para a frente da fila)."""
        if not self._pending:
            self._down = False
            return 0
        try:
            await self._ensure_conn()
        except _DB_ERRORS as exc:
            self._mark_down(exc)
            return 0
        done = 0
        while self._pending:
            item = self._pending.popleft()
            try:
                await self._replay(item)
            except _DB_ERRORS as exc:
                self._pending.appendleft(item)
                self._mark_down(exc)
                return done
            except psycopg.Error as exc:  # dado órfão (ex.: mensagem descartada do buffer)
                log.warning("item do buffer descartado (%s): %s", item.kind, exc)
            done += 1
        self._down = False
        self._mem = _Mem()
        return done

    async def _replay(self, item: _Pending) -> None:
        a = item.args
        if item.kind == "session":
            await self._insert_session(a["info"], conflict_ok=True)
        elif item.kind == "msg":
            m: LearningMessage = a["msg"]
            real = await self._insert_message(m.session_id, m.author, m.source, m.text,
                                              a["text_final"], a["turn_id"], m.at)
            self._ids[m.id] = real.id
        elif item.kind == "obs":
            o: Observation = a["obs"]
            await self._insert_obs(replace(o, message_id=self._real(o.message_id)), a["model"], a["at"])
        elif item.kind == "topic":
            await self._db_set_topic(a["session_id"], a["topic"], a["at"], a.get("scenario"))
        elif item.kind == "end":
            await self._db_end(a["session_id"], a["reason"], a["at"])
        elif item.kind == "summary":
            await self._db_summary(a["session_id"], a["summary"])

    async def _pre(self) -> bool:
        """Antes de cada operação: tenta esvaziar o buffer. ``True`` se o banco está no ar."""
        if self._pending:
            await self.flush()
            return not self._pending
        try:
            await self._ensure_conn()
        except _DB_ERRORS as exc:
            self._mark_down(exc)
            return False
        return True

    async def _fetchone(self, query: str, params: list[Any] | None = None) -> Any:
        async with self._conn.transaction():
            cur = await self._conn.execute(query, params or [])
            return await cur.fetchone()

    async def _fetchall(self, query: str, params: list[Any] | None = None) -> list[Any]:
        async with self._conn.transaction():
            cur = await self._conn.execute(query, params or [])
            return list(await cur.fetchall())

    async def _exec(self, query: str, params: list[Any] | None = None) -> None:
        async with self._conn.transaction():
            await self._conn.execute(query, params or [])

    # -- SQL ------------------------------------------------------------------------------------

    async def _insert_session(self, info: SessionInfo, *, conflict_ok: bool = False) -> None:
        q = ("INSERT INTO learning_sessions (id, started_at, level, track, topic, topics)"
             " VALUES (%s, %s, %s, %s, %s, %s::jsonb)")
        if conflict_ok:
            q += " ON CONFLICT (id) DO NOTHING"
        await self._exec(q, [info.id, info.started_at, info.level, info.track, info.topic.value,
                             json.dumps(_topics_to_json(info.topics, info.scenario))])

    async def _insert_message(self, session_id: str, author: Author, source: Source, text: str,
                              text_final: str | None, turn_id: int | None, at: datetime) -> LearningMessage:
        row = await self._fetchone(
            "INSERT INTO learning_messages (session_id, author, source, text, text_final, turn_id, at)"
            f" VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING {_MSG_COLS}",
            [session_id, Author(author).value, Source(source).value, text, text_final, turn_id, at],
        )
        return _msg(row)

    async def _insert_obs(self, obs: Observation, model: str | None, at: datetime) -> Observation:
        row = await self._fetchone(
            "INSERT INTO learning_observations"
            " (session_id, message_id, category, rule_key, label, span, suggestion, model, at)"
            f" VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING {_OBS_COLS}",
            [obs.session_id, obs.message_id, ObsCategory(obs.category).value, obs.rule_key, obs.label,
             obs.span, obs.suggestion, model, at],
        )
        return _obs(row)

    async def _db_set_topic(self, session_id: str, topic: Topic, at: datetime,
                            scenario: str | None = None) -> bool:
        # O cenário (LI5.1) vai no JSON da entrada (sem coluna nova); dedup por tema + cenário.
        scenario = scenario or None
        row = await self._fetchone(
            "UPDATE learning_sessions SET topic = %s,"
            " topics = topics || jsonb_build_array(jsonb_strip_nulls(jsonb_build_object("
            "   'topic', %s::text, 'at', %s::text, 'scenario', %s::text)))"
            " WHERE id = %s AND (jsonb_array_length(topics) = 0"
            "   OR topics -> (jsonb_array_length(topics) - 1) ->> 'topic' IS DISTINCT FROM %s"
            "   OR topics -> (jsonb_array_length(topics) - 1) ->> 'scenario' IS DISTINCT FROM %s)"
            " RETURNING id",
            [topic.value, topic.value, at.isoformat(), scenario, session_id, topic.value, scenario],
        )
        return row is not None

    async def _db_end(self, session_id: str, reason: str, at: datetime) -> None:
        await self._exec("UPDATE learning_sessions SET ended_at = %s, end_reason = %s WHERE id = %s",
                         [at, reason, session_id])

    async def _db_summary(self, session_id: str, summary: SessionSummary) -> None:
        await self._exec("UPDATE learning_sessions SET summary = %s::jsonb WHERE id = %s",
                         [summary.to_json(), session_id])

    # -- sessão ---------------------------------------------------------------------------------

    async def open_session(
        self, *, level: str | None, track: str | None, topic: Topic = Topic.FREE,
        at: datetime | None = None,
    ) -> SessionInfo:
        at = _aware(at)
        topic = Topic(topic)
        day = _local_day(at)
        if await self._pre():
            for _ in range(5):
                try:
                    rows = await self._fetchall("SELECT id FROM learning_sessions WHERE id LIKE %s",
                                                [f"LS-{day:%Y%m%d}-%"])
                    sid = make_session_id(day, _next_n([r[0] for r in rows], day))
                    info = SessionInfo(sid, at, None, None, level, track, topic, [(topic, at)])
                    await self._insert_session(info)
                    self._known[sid] = info
                    return info
                except psycopg.errors.UniqueViolation:
                    continue
                except _DB_ERRORS as exc:
                    self._mark_down(exc)
                    break
        known = list(self._known) + list(self._mem.sessions)
        sid = make_session_id(day, _next_n(known, day))
        info = SessionInfo(sid, at, None, None, level, track, topic, [(topic, at)])
        self._known[sid] = info
        self._mem.put_session(info)
        self._buffer(_Pending("session", {"info": info}))
        return info

    async def get_session(self, session_id: str) -> SessionInfo | None:
        if await self._pre():
            try:
                row = await self._fetchone(f"SELECT {_SESSION_COLS} FROM learning_sessions WHERE id = %s",
                                           [session_id])
                if row is not None:
                    self._known[session_id] = _session(row)
                    return self._known[session_id]
                return None
            except _DB_ERRORS as exc:
                self._mark_down(exc)
        return self._mem.sessions.get(session_id) or self._known.get(session_id)

    async def open_session_last(self) -> SessionInfo | None:
        if await self._pre():
            try:
                row = await self._fetchone(
                    f"SELECT {_SESSION_COLS} FROM learning_sessions WHERE ended_at IS NULL"
                    " ORDER BY started_at DESC LIMIT 1")
                return _session(row) if row is not None else None
            except _DB_ERRORS as exc:
                self._mark_down(exc)
        open_ = [s for s in {**self._known, **self._mem.sessions}.values() if s.ended_at is None]
        return max(open_, key=lambda s: s.started_at, default=None)

    def _mirror_session(self, session_id: str) -> None:
        if session_id not in self._mem.sessions and session_id in self._known:
            self._mem.put_session(self._known[session_id])

    async def end_session(self, session_id: str, reason: str, at: datetime | None = None) -> None:
        at = _aware(at)
        if await self._pre():
            try:
                await self._db_end(session_id, reason, at)
                return
            except _DB_ERRORS as exc:
                self._mark_down(exc)
        self._mirror_session(session_id)
        if session_id in self._mem.sessions:
            s = self._mem.sessions[session_id]
            self._mem.put_session(replace(s, ended_at=at, end_reason=reason))
        self._buffer(_Pending("end", {"session_id": session_id, "reason": reason, "at": at}))

    async def set_topic(self, session_id: str, topic: Topic, at: datetime | None = None, *,
                        scenario: str | None = None) -> bool:
        at = _aware(at)
        topic = Topic(topic)
        if await self._pre():
            try:
                return await self._db_set_topic(session_id, topic, at, scenario)
            except _DB_ERRORS as exc:
                self._mark_down(exc)
        self._mirror_session(session_id)
        changed = (self._mem.set_topic(session_id, topic, at, scenario)
                   if session_id in self._mem.sessions else True)
        if changed:
            self._buffer(_Pending("topic", {"session_id": session_id, "topic": topic, "at": at,
                                            "scenario": scenario}))
        return changed

    async def session_stats(self, session_id: str) -> SessionStats | None:
        if await self._pre():
            try:
                return await asyncio.wait_for(self._db_stats(session_id), self._stats_timeout_s)
            except _DB_ERRORS as exc:
                self._mark_down(exc)
        self._mirror_session(session_id)
        return self._mem.stats(session_id)

    async def _db_stats(self, session_id: str) -> SessionStats | None:
        row = await self._fetchone(
            f"SELECT {_SESSION_COLS} FROM learning_sessions WHERE id = %s", [session_id]
        )
        if row is None:
            return None
        info = _session(row)
        self._known[session_id] = info
        counts = await self._fetchone(
            "SELECT count(*), count(*) FILTER (WHERE author = 'you'), max(at)"
            " FROM learning_messages WHERE session_id = %s", [session_id])
        obs = await self.observations(session_id)
        saved = await self.saved_words(session_id)
        return SessionStats(info, int(counts[0]), int(counts[1]), counts[2], obs, saved)

    async def save_summary(self, session_id: str, summary: SessionSummary) -> None:
        if await self._pre():
            try:
                await self._db_summary(session_id, summary)
                return
            except _DB_ERRORS as exc:
                self._mark_down(exc)
        self._buffer(_Pending("summary", {"session_id": session_id, "summary": summary}))

    # -- mensagens ------------------------------------------------------------------------------

    async def add_message(
        self, session_id: str, author: Author, source: Source, text: str, *,
        text_final: str | None = None, turn_id: int | None = None, at: datetime | None = None,
    ) -> LearningMessage:
        at = _aware(at)
        if await self._pre():
            try:
                return await self._insert_message(session_id, author, source, text, text_final, turn_id, at)
            except _DB_ERRORS as exc:
                self._mark_down(exc)
        msg = LearningMessage(self._next_tmp, session_id, Author(author), Source(source), text, at)
        self._next_tmp -= 1
        self._mirror_session(session_id)
        self._mem.messages[msg.id] = msg
        self._buffer(_Pending("msg", {"msg": msg, "text_final": text_final, "turn_id": turn_id}))
        return msg

    async def get_message(self, message_id: int) -> LearningMessage | None:
        if message_id in self._mem.messages:
            return self._mem.messages[message_id]
        if await self._pre():
            try:
                row = await self._fetchone(f"SELECT {_MSG_COLS} FROM learning_messages WHERE id = %s",
                                           [self._real(message_id)])
                return _msg(row) if row is not None else None
            except _DB_ERRORS as exc:
                self._mark_down(exc)
        return None

    async def recent_messages(self, session_id: str, limit: int = RECENT_DEFAULT) -> list[LearningMessage]:
        if limit <= 0:
            return []
        if await self._pre():
            try:
                rows = await self._fetchall(
                    f"SELECT {_MSG_COLS} FROM (SELECT {_MSG_COLS} FROM learning_messages"
                    " WHERE session_id = %s ORDER BY id DESC LIMIT %s) t ORDER BY id",
                    [session_id, limit])
                return [_msg(r) for r in rows]
            except _DB_ERRORS as exc:
                self._mark_down(exc)
        msgs = [m for m in self._mem.messages.values() if m.session_id == session_id]
        return sorted(msgs, key=lambda m: -m.id)[-limit:]  # provisórios: -1, -2, … em ordem

    # -- observações ----------------------------------------------------------------------------

    async def add_observation(self, obs: Observation, *, model: str | None = None,
                              at: datetime | None = None) -> Observation:
        _check_observation(obs)
        at = _aware(at)
        if await self._pre():
            try:
                return await self._insert_obs(replace(obs, message_id=self._real(obs.message_id)), model, at)
            except _DB_ERRORS as exc:
                self._mark_down(exc)
        self._mirror_session(obs.session_id)
        self._mem.observations.append(obs)
        self._buffer(_Pending("obs", {"obs": obs, "model": model, "at": at}))
        return obs

    async def observations(self, session_id: str) -> list[Observation]:
        if await self._pre():
            try:
                rows = await self._fetchall(
                    f"SELECT {_OBS_COLS} FROM learning_observations WHERE session_id = %s ORDER BY id",
                    [session_id])
                return [_obs(r) for r in rows]
            except _DB_ERRORS as exc:
                self._mark_down(exc)
        return [o for o in self._mem.observations if o.session_id == session_id]

    # -- ações (sem cache com o banco fora) -----------------------------------------------------

    async def cached_action(self, message_id: int, kind: ActionKind, sel_start: int,
                            sel_end: int) -> ActionResult | None:
        if message_id < 0 and message_id not in self._ids:
            return None
        if not await self._pre():
            return None
        try:
            row = await self._fetchone(
                "SELECT id, kind, ok, data, error, cost_usd FROM learning_action_results"
                " WHERE message_id = %s AND kind = %s AND sel_start = %s AND sel_end = %s",
                [self._real(message_id), ActionKind(kind).value, sel_start, sel_end])
        except _DB_ERRORS as exc:
            self._mark_down(exc)
            return None
        if row is None:
            return None
        return ActionResult(row[0], ActionKind(row[1]), row[2], row[3], row[4], True, 0, float(row[5]))

    async def save_action(self, result: ActionResult, *, message_id: int, sel_start: int,
                          sel_end: int, model: str | None = None) -> None:
        if message_id < 0 and message_id not in self._ids:
            return
        if not await self._pre():
            return
        try:
            await self._exec(
                "INSERT INTO learning_action_results"
                " (id, message_id, kind, sel_start, sel_end, ok, data, error, model, cost_usd)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)"
                " ON CONFLICT DO NOTHING",
                [result.id, self._real(message_id), ActionKind(result.kind).value, sel_start, sel_end,
                 result.ok, json.dumps(result.data) if result.data is not None else None, result.error,
                 model, result.cost_usd])
        except _DB_ERRORS as exc:
            self._mark_down(exc)

    async def get_action(self, action_id: str) -> StoredAction | None:
        if not await self._pre():
            return None
        try:
            row = await self._fetchone(
                "SELECT id, kind, ok, data, error, cost_usd, message_id, sel_start, sel_end"
                " FROM learning_action_results WHERE id = %s", [action_id])
        except _DB_ERRORS as exc:
            self._mark_down(exc)
            return None
        if row is None:
            return None
        res = ActionResult(row[0], ActionKind(row[1]), row[2], row[3], row[4], True, 0, float(row[5]))
        return StoredAction(res, int(row[6]), int(row[7]), int(row[8]))

    # -- palavras salvas (exigem o banco: a mensagem de origem precisa existir) ----------------

    async def save_word(self, word: SavedWord) -> SavedWord:
        await self._pre()
        mid = self._real(word.message_id)
        if mid < 0:
            raise ValueError("mensagem de origem ainda não gravada no banco")
        async with self._conn.transaction():
            cur = await self._conn.execute(
                "INSERT INTO learning_saved_words"
                " (norm, term, meaning, pos, cefr, example, session_id, message_id, action_id, saved_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s,"
                "  (SELECT id FROM learning_action_results WHERE id = %s), %s)"
                " ON CONFLICT (norm) WHERE removed_at IS NULL DO NOTHING"
                f" RETURNING {_WORD_COLS}",
                [word.norm, word.term, word.meaning, word.pos, word.cefr, word.example, word.session_id,
                 mid, word.action_id, word.saved_at])
            row = await cur.fetchone()
            if row is None:
                cur = await self._conn.execute(
                    f"SELECT {_WORD_COLS} FROM learning_saved_words WHERE norm = %s AND removed_at IS NULL",
                    [word.norm])
                row = await cur.fetchone()
        return _word(row)

    async def unsave_word(self, norm: str, at: datetime | None = None) -> bool:
        await self._pre()
        row = await self._fetchone(
            "UPDATE learning_saved_words SET removed_at = %s WHERE norm = %s AND removed_at IS NULL"
            " RETURNING id", [_aware(at), norm])
        return row is not None

    async def saved_norms(self) -> set[str]:
        if not await self._pre():
            return set()
        try:
            rows = await self._fetchall("SELECT norm FROM learning_saved_words WHERE removed_at IS NULL")
        except _DB_ERRORS as exc:
            self._mark_down(exc)
            return set()
        return {r[0] for r in rows}

    async def saved_words(self, session_id: str | None = None) -> list[SavedWord]:
        q = f"SELECT {_WORD_COLS} FROM learning_saved_words WHERE removed_at IS NULL"
        params: list[Any] = []
        if session_id is not None:
            q += " AND session_id = %s"
            params.append(session_id)
        if await self._pre():
            try:
                rows = await self._fetchall(q + " ORDER BY id", params)
                return [_word(r) for r in rows]
            except _DB_ERRORS as exc:
                self._mark_down(exc)
        return []

    # -- entrevista pela vaga (LI0.2, spec §8) --------------------------------------------------
    # Sem buffer: com o banco fora, a gravação é perdida (com aviso) e a leitura devolve vazio.

    async def _iv(self, what: str, op: Callable[[], Awaitable[Any]], default: Any) -> Any:
        if await self._pre():
            try:
                return await op()
            except _DB_ERRORS as exc:
                self._mark_down(exc)
        log.warning("banco do Learning Mode fora: %s sem efeito", what)
        return default

    async def save_job(self, post: JobPost, at: datetime | None = None) -> None:
        at = _aware(at)
        await self._iv("save_job", lambda: self._exec(
            "INSERT INTO learning_jobs (id, created_at, last_used, source, text)"
            " VALUES (%s, %s, %s, %s, %s)"
            " ON CONFLICT (id) DO UPDATE SET last_used = EXCLUDED.last_used",
            [post.id, post.created_at, at, post.source, post.text]), None)

    async def get_job(self, job_id: str) -> StoredJob | None:
        row = await self._iv("get_job", lambda: self._fetchone(
            "SELECT id, text, source, created_at, profile, last_used, model, cost_usd"
            " FROM learning_jobs WHERE id = %s", [job_id]), None)
        if row is None:
            return None
        post = JobPost(row[0], row[1], row[2], row[3])
        profile = JobProfile.from_dict(row[4]) if row[4] else None
        return StoredJob(post, profile, row[5], row[6], float(row[7]) if row[7] is not None else None)

    async def set_profile(self, job_id: str, profile: JobProfile, *, model: str | None = None,
                          cost_usd: float | None = None) -> bool:
        row = await self._iv("set_profile", lambda: self._fetchone(
            "UPDATE learning_jobs SET profile = %s::jsonb, model = %s, cost_usd = %s"
            " WHERE id = %s RETURNING id", [profile.to_json(), model, cost_usd, job_id]), None)
        return row is not None

    async def recent_jobs(self, n: int = 3) -> list[tuple[str, JobProfile]]:
        rows = await self._iv("recent_jobs", lambda: self._fetchall(
            "SELECT id, profile FROM learning_jobs WHERE profile IS NOT NULL"
            " ORDER BY last_used DESC, id LIMIT %s", [max(n, 0)]), [])
        return [(r[0], JobProfile.from_dict(r[1])) for r in rows]

    async def save_interview(self, run: InterviewRun, end_reason: str | None = None,
                             at: datetime | None = None) -> None:
        at = _aware(at)
        ended = at if end_reason is not None or run.state in _RUN_ENDED else None
        progress = {k: v for k, v in run.to_dict().items() if k not in ("plan", "profile")}
        await self._iv("save_interview", lambda: self._exec(
            "INSERT INTO learning_interviews"
            " (id, session_id, job_id, plan, state, progress, started_at, ended_at, end_reason)"
            " VALUES (%s, %s, %s, %s::jsonb, %s, %s::jsonb, %s, %s, %s)"
            " ON CONFLICT (id) DO UPDATE SET plan = EXCLUDED.plan, state = EXCLUDED.state,"
            "   progress = EXCLUDED.progress,"
            "   ended_at = COALESCE(learning_interviews.ended_at, EXCLUDED.ended_at),"
            "   end_reason = COALESCE(EXCLUDED.end_reason, learning_interviews.end_reason)",
            [run.id, run.session_id, run.job_id, run.plan.to_json(), run.state.value,
             json.dumps(progress, ensure_ascii=False), at, ended, end_reason]), None)

    async def active_interview(self, session_id: str) -> InterviewRun | None:
        row = await self._iv("active_interview", lambda: self._fetchone(
            "SELECT i.plan, i.state, i.progress, j.profile FROM learning_interviews i"
            " JOIN learning_jobs j ON j.id = i.job_id"
            " WHERE i.session_id = %s AND i.ended_at IS NULL"
            " ORDER BY i.started_at DESC, i.id DESC LIMIT 1", [session_id]), None)
        if row is None:
            return None
        if not row[3]:
            log.warning("simulação ativa sem perfil da vaga na sessão %s", session_id)
            return None
        return InterviewRun.from_dict({**row[2], "plan": row[0], "state": row[1], "profile": row[3]})

    async def interview_of(self, run_id: str) -> InterviewInfo | None:
        row = await self._iv("interview_of", lambda: self._fetchone(
            "SELECT i.id, i.session_id, i.job_id, j.profile, i.started_at, i.ended_at, i.end_reason,"
            " i.debrief IS NOT NULL, i.plan, i.state, i.progress"
            " FROM learning_interviews i LEFT JOIN learning_jobs j ON j.id = i.job_id"
            " WHERE i.id = %s", [run_id]), None)
        if row is None:
            return None
        profile = JobProfile.from_dict(row[3]) if row[3] else None
        run = None
        if row[3]:
            try:
                run = InterviewRun.from_dict({**row[10], "plan": row[8], "state": row[9],
                                              "profile": row[3]})
            except (KeyError, TypeError, ValueError):
                log.warning("simulação %s não reconstruída", run_id, exc_info=True)
        return InterviewInfo(row[0], row[1], row[2], profile.title if profile else None,
                             profile.company if profile else None, row[4], row[5], row[6],
                             bool(row[7]), run)

    async def save_debrief(self, debrief: InterviewDebrief) -> bool:
        row = await self._iv("save_debrief", lambda: self._fetchone(
            "UPDATE learning_interviews SET debrief = %s::jsonb, debrief_seen = false"
            " WHERE id = %s RETURNING id", [debrief.to_json(), debrief.run_id]), None)
        return row is not None

    async def unseen_debrief(self) -> InterviewDebrief | None:
        row = await self._iv("unseen_debrief", lambda: self._fetchone(
            "SELECT debrief FROM learning_interviews WHERE debrief IS NOT NULL AND NOT debrief_seen"
            " ORDER BY ended_at DESC NULLS LAST, started_at DESC, id DESC LIMIT 1"), None)
        return InterviewDebrief.from_dict(row[0]) if row is not None else None

    async def mark_seen(self, run_id: str) -> bool:
        row = await self._iv("mark_seen", lambda: self._fetchone(
            "UPDATE learning_interviews SET debrief_seen = true"
            " WHERE id = %s AND debrief IS NOT NULL AND NOT debrief_seen RETURNING id", [run_id]), None)
        return row is not None


# ---------------------------------------------------------------------------------------------
# Fábrica (P4)
# ---------------------------------------------------------------------------------------------


def make_repo(
    cfg: LearningConfig,
    *,
    conn: Any | None = None,
    reconnect: Callable[[], Awaitable[Any]] | None = None,
    jsonl_dir: Path | str = DEFAULT_JSONL_DIR,
) -> LearningRepo:
    """Backend de ``[learning] storage``: ``postgres`` (precisa de ``conn``) ou ``jsonl``."""
    if cfg.storage == "postgres":
        if conn is None:
            raise ValueError("storage = postgres exige a conexão do núcleo")
        return PostgresRepo(conn, reconnect=reconnect)
    if cfg.storage == "jsonl":
        return JsonlRepo(jsonl_dir)
    raise ValueError(f"storage desconhecido: {cfg.storage!r}")
