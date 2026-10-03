"""Perfil e estilo do usuário (tarefa 4.2; R11.1, R11.4; §7 ``profile``, ``vocab``).

- Fonte: o histórico local de turnos (``TurnsRepo``, 4.1). Só ``text_final`` (o que ele falou).
- Sinais locais e baratos (``extract_stats``): gírias/abreviações frequentes, tamanho médio das
  falas, formalidade, palavrões, período do dia, pedidos de resposta curta/longa e jogos citados.
- 1×/dia no máximo (``ProfileUpdater.due``): roda se o último perfil tem mais de 24 h (ou não
  existe) e houve pelo menos ``min_new_turns`` turnos novos desde ele.
- Modelo: o perfil é dado pessoal (R21.5), então vai para a tarefa ``agent`` (provedor pago) com
  ``personal=True``; o registro de provedores checa o orçamento e registra o custo. Se o modelo
  falhar (teto, cota gratuita, sem chave, rede), o perfil sai só dos sinais locais, sem custo.
- Corte duro: ``PROFILE_MAX_TOKENS`` (300) com a mesma estimativa do prompt (3.4).
- Vocabulário (``vocab``): gírias (``slang``) e jogos citados (``name``) viram dica do STT; o
  ``HintedStt`` corta a dica em ``STT_HINT_MAX_TOKENS`` (200).
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any

from magi.agent.prompt import PROFILE_MAX_TOKENS, truncate_to_tokens
from magi.common.contracts import (
    ChatMessage,
    ChatProvider,
    GameCatalog,
    Profile,
    ProviderTask,
    TurnRecord,
    TurnsRepo,
    VocabRepo,
    VocabTerm,
)

log = logging.getLogger(__name__)

#: Intervalo mínimo entre atualizações (R11.4).
UPDATE_INTERVAL = timedelta(hours=24)
#: Turnos novos exigidos para atualizar.
MIN_NEW_TURNS = 20
#: Quantos turnos recentes são lidos e quantas falas vão de amostra ao modelo.
READ_TURNS = 500
SAMPLE_UTTERANCES = 40
SAMPLE_CHARS = 120
#: Limite pedido ao modelo (o corte duro em tokens vem depois).
PROFILE_MAX_CHARS = 900
#: Quantos termos entram no ``vocab`` por atualização.
MAX_SLANG_TERMS = 25
MAX_NAME_TERMS = 15
#: De quanto em quanto tempo o laço confere se está na hora.
CHECK_EVERY_S = 3600.0

SLANG = frozenset(
    """
    mano mana mina véi vei tlgd tlg pique suave sussa bagui bagulho daora dahora top firmeza firma
    slk sla pprt tmj vlw flw blz trampo rolê role zoeira brabo braba monstro mds pô po kkk kkkk
    kkkkk rs uai tipo papo mó mo partiu bora osh oxe gg nerfado buffado noob lag cringe base
    chave chapa parça parceiro truta rapaziada galera treta zoado bizarro massa
    """.split()
)
ABBREVIATIONS = frozenset("vc vcs tb tbm pq q msm mt mto nd td hj agr ss n cmg ctz pfv pls".split())
SWEARS = frozenset("porra caralho krl crl merda pqp foda fdp bosta desgraça puta cacete vsf tnc".split())
FORMAL = (
    "por favor", "obrigado", "obrigada", "senhor", "senhora", "poderia", "gostaria", "gentileza", "agradeço",
)
SHORTER = ("resume", "resumo", "mais curto", "fala menos", "direto ao ponto", "só o principal")
LONGER = ("detalha", "explica melhor", "mais detalhe", "explica direito", "fala mais")
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
_PERIODS = ((0, "madrugada"), (6, "manhã"), (12, "tarde"), (18, "noite"))


# ---------------------------------------------------------------------------------------------
# Sinais locais
# ---------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StyleStats:
    """Sinais do jeito de falar, medidos sem API."""

    turns: int = 0
    avg_words: float = 0.0
    slang: tuple[tuple[str, int], ...] = ()  # (termo, vezes), mais frequente primeiro
    formality: str = "neutro"  # "bem casual" | "casual" | "neutro" | "formal"
    swears_per_turn: float = 0.0
    period: str | None = None  # período com mais falas
    reply_pref: str = "curtas"  # "curtas" | "médias" | "detalhadas"
    games: tuple[tuple[str, int], ...] = ()  # jogos citados (nome do catálogo, vezes)

    def summary(self) -> str:
        """Linhas curtas com os sinais (entram no pedido ao modelo)."""
        lines = [
            f"falas analisadas: {self.turns}; média {self.avg_words:.0f} palavras por fala",
            f"formalidade: {self.formality}",
            f"palavrões por fala: {self.swears_per_turn:.2f}",
            f"respostas preferidas: {self.reply_pref}",
        ]
        if self.slang:
            lines.append("gírias/abreviações: " + ", ".join(f"{t} ({n})" for t, n in self.slang[:15]))
        if self.period:
            lines.append(f"fala mais de {self.period}")
        if self.games:
            lines.append("jogos citados: " + ", ".join(f"{g} ({n})" for g, n in self.games[:10]))
        return "\n".join(lines)


def _period(hour: int) -> str:
    return next(name for start, name in reversed(_PERIODS) if hour >= start)


def _game_names(catalog: GameCatalog | None) -> list[tuple[str, tuple[str, ...]]]:
    if catalog is None:
        return []
    try:
        return [(g.name, (g.name.lower(), *(a.lower() for a in g.aliases))) for g in catalog.all()]
    except Exception as e:  # noqa: BLE001
        log.warning("perfil: catálogo indisponível: %s", e)
        return []


def extract_stats(
    turns: Sequence[TurnRecord], *, catalog: GameCatalog | None = None, tz: tzinfo | None = None
) -> StyleStats:
    """Mede os sinais em ``turns`` (só ``text_final``). ``tz``: fuso do período (padrão: local)."""
    texts = [(t, (t.text_final or t.text_heard or "").strip()) for t in turns]
    texts = [(t, s) for t, s in texts if s]
    if not texts:
        return StyleStats()
    words_total = 0
    slang: Counter[str] = Counter()
    swears = formal = informal = shorter = longer = 0
    periods: Counter[str] = Counter()
    games: Counter[str] = Counter()
    names = _game_names(catalog)
    for turn, text in texts:
        low = text.lower()
        words = _WORD.findall(low)
        words_total += len(words)
        for w in words:
            if w in SLANG or w in ABBREVIATIONS:
                slang[w] += 1
                informal += 1
            if w in SWEARS:
                swears += 1
                informal += 1
        if "tá ligado" in low or "ta ligado" in low:
            slang["tá ligado"] += 1
            informal += 1
        formal += sum(low.count(m) for m in FORMAL)
        shorter += any(m in low for m in SHORTER)
        longer += any(m in low for m in LONGER)
        at = turn.at if turn.at.tzinfo else turn.at.replace(tzinfo=UTC)
        periods[_period(at.astimezone(tz).hour)] += 1
        padded = f" {' '.join(words)} "
        for name, keys in names:
            if any(f" {' '.join(_WORD.findall(k))} " in padded for k in keys if k):
                games[name] += 1
    n = len(texts)
    avg = words_total / n
    score = (informal - 2 * formal) / n
    if score >= 0.6:
        formality = "bem casual"
    elif score >= 0.15:
        formality = "casual"
    else:
        formality = "formal" if score < -0.3 else "neutro"
    if longer > shorter:
        pref = "detalhadas"
    elif shorter > longer or avg <= 12:
        pref = "curtas"
    else:
        pref = "médias"
    return StyleStats(
        turns=n,
        avg_words=avg,
        slang=tuple(slang.most_common(MAX_SLANG_TERMS)),
        formality=formality,
        swears_per_turn=swears / n,
        period=periods.most_common(1)[0][0] if periods else None,
        reply_pref=pref,
        games=tuple(games.most_common(MAX_NAME_TERMS)),
    )


def local_profile(stats: StyleStats, previous: str | None = None) -> str:
    """Perfil só com os sinais locais (sem modelo, sem custo)."""
    fala = f"Fala {stats.formality}, frases de ~{stats.avg_words:.0f} palavras"
    if stats.slang:
        fala += "; usa " + ", ".join(t for t, _ in stats.slang[:8])
    if stats.swears_per_turn >= 0.1:
        fala += "; solta palavrão de boa"
    if stats.period:
        fala += f"; aparece mais de {stats.period}"
    curte = ", ".join(g for g, _ in stats.games[:6]) if stats.games else ""
    if not curte and previous:
        old = next((ln for ln in previous.splitlines() if ln.startswith("Curte:")), "")
        curte = old.removeprefix("Curte:").strip()
    respostas = {
        "curtas": "curtas e diretas",
        "médias": "médias, sem enrolar",
        "detalhadas": "com mais detalhe quando ele pede",
    }[stats.reply_pref]
    body = (
        f"Fala: {fala}.\nCurte: {curte or 'ainda sem sinais claros'}.\n"
        f"Respostas: {respostas}, no mesmo tom dele."
    )
    return clamp_profile(body)


def clamp_profile(body: str) -> str:
    """Corte duro em ``PROFILE_MAX_TOKENS``."""
    return truncate_to_tokens(body.strip(), PROFILE_MAX_TOKENS)


def vocab_terms(stats: StyleStats) -> list[VocabTerm]:
    """Gírias e jogos citados como ``VocabTerm`` (peso > 1 para passar à frente dos jogos só
    instalados na dica do STT)."""
    terms = [VocabTerm(t, "slang", 1.0 + min(n, 20) / 10) for t, n in stats.slang[:MAX_SLANG_TERMS]]
    terms += [VocabTerm(g, "name", 1.5 + min(n, 20) / 10) for g, n in stats.games[:MAX_NAME_TERMS]]
    return terms


# ---------------------------------------------------------------------------------------------
# Repositórios (§7)
# ---------------------------------------------------------------------------------------------


class PgProfileRepo:
    """``ProfileRepo`` em Postgres: linha única ``profile.id = 1``."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    async def get(self) -> Profile | None:
        async with self._conn.transaction():
            cur = await self._conn.execute("SELECT body, updated_at FROM profile WHERE id = 1")
            row = await cur.fetchone()
        return Profile(body=row[0], updated_at=row[1]) if row else None

    async def put(self, body: str) -> Profile:
        async with self._conn.transaction():
            cur = await self._conn.execute(
                "INSERT INTO profile (id, body, updated_at) VALUES (1, %s, now())"
                " ON CONFLICT (id) DO UPDATE SET body = EXCLUDED.body, updated_at = EXCLUDED.updated_at"
                " RETURNING body, updated_at",
                [body],
            )
            row = await cur.fetchone()
        assert row is not None
        return Profile(body=row[0], updated_at=row[1])


class PgVocabRepo:
    """``VocabRepo`` em Postgres (``vocab(term, kind, weight)``)."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    async def all(self, kind: str | None = None) -> list[VocabTerm]:
        where, args = ("WHERE kind = %s", [kind]) if kind else ("", [])
        async with self._conn.transaction():
            cur = await self._conn.execute(
                f"SELECT term, kind, weight FROM vocab {where} ORDER BY weight DESC, term", args
            )
            rows = await cur.fetchall()
        return [VocabTerm(term=r[0], kind=r[1], weight=float(r[2])) for r in rows]

    async def upsert(self, term: VocabTerm) -> None:
        async with self._conn.transaction():
            await self._conn.execute(
                "INSERT INTO vocab (term, kind, weight) VALUES (%s, %s, %s)"
                " ON CONFLICT (term, kind) DO UPDATE SET weight = EXCLUDED.weight",
                [term.term, term.kind, term.weight],
            )


class InMemoryProfileRepo:
    """``ProfileRepo`` sem banco (não persiste). ``now``: relógio (testes)."""

    def __init__(self, now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._now = now
        self.profile: Profile | None = None

    async def get(self) -> Profile | None:
        return self.profile

    async def put(self, body: str) -> Profile:
        self.profile = Profile(body=body, updated_at=self._now())
        return self.profile


class InMemoryVocabRepo:
    """``VocabRepo`` sem banco (não persiste)."""

    def __init__(self) -> None:
        self.terms: dict[tuple[str, str], VocabTerm] = {}

    async def all(self, kind: str | None = None) -> list[VocabTerm]:
        out = [t for t in self.terms.values() if kind is None or t.kind == kind]
        return sorted(out, key=lambda t: (-t.weight, t.term))

    async def upsert(self, term: VocabTerm) -> None:
        self.terms[(term.term, term.kind)] = term


# ---------------------------------------------------------------------------------------------
# Atualização diária
# ---------------------------------------------------------------------------------------------

SYSTEM_PROMPT = f"""Você mantém o perfil de estilo do Pedro para a Magui, assistente de voz dele.
Atualize o perfil com base no perfil atual, nos sinais medidos e nas falas recentes.
Formato: exatamente três linhas, em português do Brasil, no máximo {PROFILE_MAX_CHARS} caracteres:
Fala: como ele fala (gírias, abreviações, formalidade, palavrão, tamanho das falas).
Curte: o que ele curte (jogos, músicas, assuntos) pelas falas.
Respostas: como ele prefere as respostas (tamanho, tom) para a Magui espelhar o estilo dele.
Só o que as falas sustentam. Sem endereços, documentos, saúde ou dados de terceiros."""


@dataclass
class ProfileUpdater:
    """Mantém o perfil (≤ 300 tokens) e o ``vocab`` a partir dos turnos, no máximo 1×/dia.

    ``chat``: fábrica do modelo (``lambda: providers.chat(ProviderTask.AGENT)``) ou ``None`` para
    só os sinais locais. ``current()`` é síncrono e serve de ``profile`` do ``GraphAgent``.
    """

    turns: TurnsRepo
    profiles: Any  # ProfileRepo
    vocab: VocabRepo | None = None
    chat: Callable[[], ChatProvider] | None = None
    catalog: GameCatalog | None = None
    min_new_turns: int = MIN_NEW_TURNS
    interval: timedelta = UPDATE_INTERVAL
    now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    tz: tzinfo | None = None
    body: str | None = None
    last_stats: StyleStats | None = None

    def current(self) -> str | None:
        return self.body or None

    async def load(self) -> str | None:
        try:
            p = await self.profiles.get()
        except Exception as e:  # noqa: BLE001
            log.warning("perfil: leitura falhou: %s", e)
            return self.body
        self.body = p.body if p and p.body else self.body
        return self.body

    async def _new_turns(self, since: datetime | None) -> list[TurnRecord]:
        rows = await self.turns.recent(READ_TURNS)
        if since is None:
            return rows
        return [t for t in rows if (t.at if t.at.tzinfo else t.at.replace(tzinfo=UTC)) > since]

    async def due(self) -> list[TurnRecord] | None:
        """Turnos novos se está na hora de atualizar; senão ``None``."""
        p = await self.profiles.get()
        if p is not None and self.now() - p.updated_at < self.interval:
            return None
        fresh = await self._new_turns(p.updated_at if p else None)
        return fresh if len(fresh) >= self.min_new_turns else None

    async def maybe_update(self) -> bool:
        """Atualiza perfil e ``vocab`` se ``due()``. Devolve se atualizou."""
        fresh = await self.due()
        if fresh is None:
            return False
        stats = extract_stats(fresh, catalog=self.catalog, tz=self.tz)
        self.last_stats = stats
        previous = self.body if self.body is not None else await self.load()
        body = await self._summarize(stats, fresh, previous)
        saved = await self.profiles.put(body)
        self.body = saved.body
        if self.vocab is not None:
            for term in vocab_terms(stats):
                await self.vocab.upsert(term)
        log.info("perfil atualizado (%d turnos novos)", len(fresh))
        return True

    async def _summarize(self, stats: StyleStats, fresh: Sequence[TurnRecord], previous: str | None) -> str:
        if self.chat is None:
            return local_profile(stats, previous)
        sample = [
            "- " + (t.text_final or t.text_heard)[:SAMPLE_CHARS].replace("\n", " ")
            for t in fresh[:SAMPLE_UTTERANCES]
            if (t.text_final or t.text_heard)
        ]
        user = (
            f"Perfil atual:\n{previous or '(vazio)'}\n\nSinais medidos:\n{stats.summary()}\n\n"
            "Falas recentes (mais novas primeiro):\n" + "\n".join(sample)
        )
        messages = [ChatMessage("system", SYSTEM_PROMPT), ChatMessage("user", user)]
        try:
            reply = await self.chat().chat(messages, personal=True)  # perfil é dado pessoal (R21.5)
        except Exception as e:  # noqa: BLE001 — teto, cota gratuita, sem chave ou rede
            log.warning("perfil: modelo indisponível (%s: %s); só sinais locais", type(e).__name__, e)
            return local_profile(stats, previous)
        text = (reply.text or "").strip()
        return clamp_profile(text) if text else local_profile(stats, previous)

    async def run(self, check_every_s: float = CHECK_EVERY_S) -> None:
        """Laço de fundo do núcleo: carrega o perfil e confere a cada ``check_every_s``."""
        await self.load()
        while True:
            try:
                await self.maybe_update()
            except Exception as e:  # noqa: BLE001
                log.warning("perfil: atualização falhou: %s", e)
            await asyncio.sleep(check_every_s)


def agent_chat(providers: Any) -> Callable[[], ChatProvider]:
    """Fábrica do modelo do perfil: tarefa ``agent`` (paga; aceita dados pessoais)."""
    return lambda: providers.chat(ProviderTask.AGENT)
