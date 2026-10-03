"""Ajuda no jogo: ``help_log`` e a escolha do degrau (4.5, R14, design §4.5).

Cada pedido de ajuda vira uma linha ``help_log(game_appid, topic, step, at)``. ``topic`` é o resumo
canônico do trecho ("boss da lua"): a pergunta nova é comparada por similaridade de embeddings com
os tópicos já usados no mesmo jogo, então "o chefe da lua" cai no mesmo tópico. Sem embeddings,
usa sobreposição de palavras.

Regras do degrau (``HelpTracker.decide``):

- pediu a solução ("manda a solução", "fala logo") → ``SOLUTION`` direto (R14.2);
- trecho já pedido → próximo degrau depois do último dado (R14.4), até ``SOLUTION``. O pedido
  anterior conta se foi nesta sessão de jogo ou há menos de ``REPEAT_WINDOW`` (2 h, §4.5);
  mais antigo que isso, recomeça na pista (evita spoiler de algo que ele já esqueceu);
- "travado" (R14.5) quando, no mesmo trecho e na mesma sessão, já há pedido anterior
  (≥ ``STUCK_REQUESTS`` contando o atual) ou o primeiro pedido foi há mais de ``STUCK_MINUTES``,
  ou quando o gancho de conquistas diz que nada mudou há ``ACHIEVEMENTS_IDLE_MIN`` numa sessão
  desse tamanho. Travado nunca recebe só a pista: começa na dica direta.

Conquistas da Steam: não há leitura local simples (o cache ``appcache/stats/*.bin`` é KeyValues
binário e a Web API pede chave + steamid). Fica um gancho opcional ``achievements_idle(appid)``
que devolve os minutos sem conquista nova (ou ``None``); o núcleo ainda não liga nenhum.
Nunca captura a tela por conta própria (R14.5).
"""

from __future__ import annotations

import logging
import re
import unicodedata
import zlib
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from magi.common.contracts import HelpEntry, HelpStep
from magi.memory.memories_repo import Embed, cosine

log = logging.getLogger(__name__)

TOPIC_MAX_CHARS = 60
#: Similaridade mínima (cosseno dos embeddings) para dois pedidos serem o mesmo trecho.
TOPIC_MIN_SCORE = 0.7
#: Sem embeddings: Jaccard mínimo entre as palavras.
TOPIC_MIN_JACCARD = 0.5
REPEAT_WINDOW = timedelta(hours=2)
STUCK_REQUESTS = 2
STUCK_MINUTES = 20
ACHIEVEMENTS_IDLE_MIN = 60

_STOP = frozenset(
    "que eu o a os as de do da dos das um uma e é em no na nos nas pra para com por como onde "
    "ajuda me mim faço fazer passar nesse nessa esse essa isso".split()
)

AchievementsIdle = Callable[[int], Awaitable[float | None]]


def _words(text: str) -> set[str]:
    t = unicodedata.normalize("NFKD", text.casefold())
    t = "".join(c if c.isalnum() else " " for c in t if not unicodedata.combining(c))
    return {w for w in t.split() if w not in _STOP and len(w) > 1}


def jaccard(a: str, b: str) -> float:
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / len(wa | wb) if wa and wb else 0.0


def topic_label(text: str) -> str:
    """Rótulo guardado em ``help_log.topic``: uma linha, sem pontuação final, com teto."""
    t = re.sub(r"\s+", " ", text).strip(" .,;:!?")
    return t[:TOPIC_MAX_CHARS].strip()


def game_key(appid: int | None, name: str) -> int:
    """Chave do jogo em ``help_log.game_appid``: o appid da Steam ou, fora dela, um id negativo
    estável derivado do nome (não colide com appids, que são positivos)."""
    if appid is not None:
        return int(appid)
    return -(zlib.crc32(name.casefold().encode()) or 1)


# -- repositórios -----------------------------------------------------------------------------

_COLS = "game_appid, topic, step, at, id"


def _entry(row: Sequence[Any]) -> HelpEntry:
    return HelpEntry(
        game_appid=int(row[0]), topic=str(row[1]), step=HelpStep(int(row[2])), at=row[3], id=row[4]
    )


class PgHelpLogRepo:
    """``HelpLogRepo`` em Postgres (tabela ``help_log`` da migração 001)."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    async def add(self, entry: HelpEntry) -> int:
        async with self._conn.transaction():
            cur = await self._conn.execute(
                "INSERT INTO help_log (game_appid, topic, step, at) VALUES (%s, %s, %s, %s) RETURNING id",
                [entry.game_appid, entry.topic, int(entry.step), entry.at],
            )
            row = await cur.fetchone()
        assert row is not None
        return int(row[0])

    async def last_step(self, game_appid: int, topic: str) -> HelpStep | None:
        cur = await self._conn.execute(
            "SELECT step FROM help_log WHERE game_appid = %s AND topic = %s"
            " ORDER BY at DESC, id DESC LIMIT 1",
            [game_appid, topic],
        )
        row = await cur.fetchone()
        return HelpStep(int(row[0])) if row else None

    async def topics(self, game_appid: int) -> list[str]:
        cur = await self._conn.execute(
            "SELECT topic FROM help_log WHERE game_appid = %s GROUP BY topic ORDER BY max(at) DESC LIMIT 200",
            [game_appid],
        )
        return [str(r[0]) for r in await cur.fetchall()]

    async def count_since(self, game_appid: int, topic: str, since: datetime) -> int:
        cur = await self._conn.execute(
            "SELECT count(*) FROM help_log WHERE game_appid = %s AND topic = %s AND at >= %s",
            [game_appid, topic, since],
        )
        row = await cur.fetchone()
        return int(row[0]) if row else 0

    async def entries(self, game_appid: int, topic: str, since: datetime) -> list[HelpEntry]:
        """Pedidos do trecho desde ``since``, do mais antigo ao mais novo."""
        cur = await self._conn.execute(
            f"SELECT {_COLS} FROM help_log WHERE game_appid = %s AND topic = %s AND at >= %s"
            " ORDER BY at, id",
            [game_appid, topic, since],
        )
        return [_entry(r) for r in await cur.fetchall()]


class InMemoryHelpLogRepo:
    """``HelpLogRepo`` em memória (sem banco; vale até reiniciar)."""

    def __init__(self) -> None:
        self.rows: list[HelpEntry] = []

    async def add(self, entry: HelpEntry) -> int:
        new = replace(entry, id=len(self.rows) + 1)
        self.rows.append(new)
        return int(new.id or 0)

    def _of(self, game_appid: int, topic: str) -> list[HelpEntry]:
        rows = [e for e in self.rows if e.game_appid == game_appid and e.topic == topic]
        return sorted(rows, key=lambda e: (e.at, e.id or 0))

    async def last_step(self, game_appid: int, topic: str) -> HelpStep | None:
        rows = self._of(game_appid, topic)
        return rows[-1].step if rows else None

    async def topics(self, game_appid: int) -> list[str]:
        seen: dict[str, datetime] = {}
        for e in self.rows:
            if e.game_appid == game_appid:
                seen[e.topic] = max(seen.get(e.topic, e.at), e.at)
        return sorted(seen, key=lambda t: seen[t], reverse=True)

    async def count_since(self, game_appid: int, topic: str, since: datetime) -> int:
        return len(await self.entries(game_appid, topic, since))

    async def entries(self, game_appid: int, topic: str, since: datetime) -> list[HelpEntry]:
        return [e for e in self._of(game_appid, topic) if e.at >= since]


# -- degrau -----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HelpDecision:
    """Degrau escolhido para um pedido. ``requests`` conta o pedido atual."""

    game_appid: int
    topic: str
    step: HelpStep
    known_topic: bool = False
    previous: HelpStep | None = None
    requests: int = 1
    stuck_minutes: int = 0
    stuck: bool = False
    reason: str = "primeiro pedido"


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class HelpTracker:
    """Casa o trecho, escolhe o degrau e guarda o pedido em ``help_log``."""

    def __init__(
        self,
        repo: Any,
        embed: Embed | None = None,
        *,
        now: Callable[[], datetime] | None = None,
        achievements_idle: AchievementsIdle | None = None,
        stuck_minutes: int = STUCK_MINUTES,
    ) -> None:
        self.repo = repo
        self.embed = embed
        self.now = now or (lambda: datetime.now(UTC))
        self.achievements_idle = achievements_idle
        self.stuck_minutes = stuck_minutes
        self._vectors: dict[str, list[float]] = {}
        #: Último degrau dado por jogo (para a linha de ajuda do prompt): appid → (tópico, degrau).
        self.current: dict[int, tuple[str, HelpStep]] = {}

    async def match_topic(self, game_appid: int, text: str) -> tuple[str, bool]:
        """(tópico canônico, já existia). O mais parecido entre os do jogo, se passar do limiar."""
        label = topic_label(text)
        known = await self.repo.topics(game_appid)
        if not known:
            return label, False
        if label in known:
            return label, True
        best, score = None, 0.0
        if self.embed is not None:
            try:
                missing = [t for t in known if t not in self._vectors]
                vecs = await self.embed([label, *missing])
                self._vectors.update(zip(missing, vecs[1:], strict=False))
                q = vecs[0]
                for t in known:
                    s = cosine(q, self._vectors.get(t, ()))
                    if s > score:
                        best, score = t, s
                if best is not None and score >= TOPIC_MIN_SCORE:
                    return best, True
                return label, False
            except Exception as e:  # sem embeddings agora: cai para palavras
                log.warning("ajuda: embeddings falharam (%s); comparando palavras", e)
        for t in known:
            s = jaccard(label, t)
            if s > score:
                best, score = t, s
        if best is not None and score >= TOPIC_MIN_JACCARD:
            return best, True
        return label, False

    async def _achievements_stuck(self, game_appid: int, session_minutes: int) -> bool:
        if self.achievements_idle is None or game_appid < 0 or session_minutes < ACHIEVEMENTS_IDLE_MIN:
            return False
        try:
            idle = await self.achievements_idle(game_appid)
        except Exception as e:
            log.debug("ajuda: conquistas indisponíveis (%s)", e)
            return False
        return idle is not None and idle >= ACHIEVEMENTS_IDLE_MIN

    async def decide(
        self,
        game_appid: int,
        topic_text: str,
        *,
        session_start: datetime | None = None,
        want_solution: bool = False,
    ) -> HelpDecision:
        """Degrau para o pedido atual (não grava; veja ``record``)."""
        now = _utc(self.now())
        start = _utc(session_start) if session_start else now
        topic, known = await self.match_topic(game_appid, topic_text)
        since = min(start, now - REPEAT_WINDOW)
        prior = await self.repo.entries(game_appid, topic, since) if known else []
        previous = prior[-1].step if prior else None
        in_session = [e for e in prior if _utc(e.at) >= start]
        requests = len(in_session) + 1
        minutes = int((now - _utc(in_session[0].at)).total_seconds() // 60) if in_session else 0
        session_minutes = int(max((now - start).total_seconds(), 0) // 60)

        reasons: list[str] = []
        if requests >= STUCK_REQUESTS:
            reasons.append(f"{requests}º pedido nesse trecho")
        if in_session and minutes >= self.stuck_minutes:
            reasons.append(f"travado há {minutes} min")
        if await self._achievements_stuck(game_appid, session_minutes):
            reasons.append("sem conquista nova há mais de 1 h")
        stuck = bool(reasons)

        if want_solution:
            step, why = HelpStep.SOLUTION, "pediu a solução"
        else:
            step = HelpStep(min(previous + 1, HelpStep.SOLUTION)) if previous else HelpStep.HINT
            if stuck and step < HelpStep.DIRECT:
                step = HelpStep.DIRECT
            why = "; ".join(reasons) or ("trecho já pedido" if previous else "primeiro pedido")
        return HelpDecision(
            game_appid=game_appid, topic=topic, step=step, known_topic=known, previous=previous,
            requests=requests, stuck_minutes=minutes, stuck=stuck, reason=why,
        )

    async def record(self, d: HelpDecision) -> None:
        """Guarda o degrau dado (R14.3). Falha de banco não derruba a resposta."""
        self.current[d.game_appid] = (d.topic, d.step)
        try:
            entry = HelpEntry(game_appid=d.game_appid, topic=d.topic, step=d.step, at=_utc(self.now()))
            await self.repo.add(entry)
        except Exception as e:
            log.warning("ajuda: não gravou help_log (%s)", e)

    def annotate(self, ctx: Any, game_appid: int | None) -> Any:
        """``GameContext`` com o último trecho/degrau desta execução (linha de ajuda do prompt)."""
        if ctx is None or game_appid is None or game_appid not in self.current:
            return ctx
        topic, step = self.current[game_appid]
        return replace(ctx, help_topic=topic, help_step=step)
