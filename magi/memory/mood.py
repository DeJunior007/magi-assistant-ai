"""Humor do Pedro no núcleo (tarefa 4.3, §4.4, R13.3-R13.5).

Nota 0..4 (0 = pega leve, 4 = pode zoar pesado) estimada só com sinais LOCAIS e baratos, sem LLM:

- tom da voz (``ToneMetadata`` do satélite): gritando, desanimado (baixo e lento), falando rápido;
- palavras: palavrões/frustração descem, risadas e agradecimentos/elogios sobem;
- reação à zoeira: "para de zoar", "sem graça" descem; "kkk" sobe;
- repetição: mesmo pedido de novo em pouco tempo, correções ("não, eu falei");
- horário: madrugada desce um pouco.

Cada turno vira um alvo ``neutro + viés + soma dos sinais`` (limitado a 0..4) e a nota anda até ele
por média móvel exponencial (α=0,3). Entre turnos a nota decai para o neutro (meia-vida de 1 h).
"Pega leve" põe teto 1 e "pode pegar pesado" piso 3 por ``OVERRIDE_S``; cada comando também mexe
no viés aprendido (±0,25, limite ±1) e fica em ``mood_events`` (R13.5). O estado vai para um JSON
em ``data_dir`` para sobreviver a reinício. O nível entra no ``TurnContext.mood`` (prompt, R13.4)
e, quando muda, vai ao HUD como ``MoodMsg`` (R13.7). Cada turno com sinal também manda a tag local
(``TurnTagMsg``, ``turn_tag.py``) para as reações da Condessa.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from rapidfuzz import fuzz

from magi.common.contracts import (
    MOOD_MAX,
    MOOD_MIN,
    ActionHandler,
    ActionRequest,
    ActionResult,
    HudSink,
    IntentId,
    MoodEvent,
    MoodEventsRepo,
    MoodMsg,
    ToneMetadata,
    TurnContext,
    TurnTagMsg,
)

log = logging.getLogger(__name__)

TZ = ZoneInfo("America/Sao_Paulo")
STATE_FILE = "mood.json"

NEUTRAL = 2.0
ALPHA = 0.3  # média móvel exponencial por turno (§4.4)
HALF_LIFE_S = 3600.0  # decaimento para o neutro entre turnos
OVERRIDE_S = 3 * 3600  # "pega leve" / "pode pegar pesado" valem por 3 h
SOFT_CAP = 1  # teto com "pega leve"
HARD_FLOOR = 3  # piso com "pode pegar pesado"
BIAS_STEP = 0.25  # aprendizado por comando explícito
BIAS_MAX = 1.0

# Pesos (somados ao neutro para formar o alvo do turno).
W_SWEAR = -1.0
W_FRUSTRATION = -0.75
W_STOP_TEASE = -1.0
W_LAUGH = 1.0
W_THANKS = 0.5
W_CORRECTION = -0.5
W_REPEAT = -0.75
W_LOUD = -0.5
W_FLAT = -0.5
W_FAST = -0.25
W_LATE = -0.5

LOUD_DB = -10.0  # acima disso: gritando
FLAT_DB = -35.0  # abaixo disso e devagar: desanimado
SLOW_RATE = 2.5
FAST_RATE = 7.0
REPEAT_S = 180  # mesmo pedido em até 3 min conta como repetição
REPEAT_RATIO = 85
LATE_HOURS = range(0, 6)

_SWEAR = re.compile(
    r"\b(porra|caralho|merda|puta|pqp|droga|inferno|cacete|bosta|desgraca|vsf|fdp|aff+|af)\b"
)
_FRUSTRATION = re.compile(
    r"\b(que raiva|odeio|nao aguento|to puto|to irritado|to mal|to cansado|to triste|que saco|"
    r"nao consigo|travei|to travado|de novo isso)\b"
)
_STOP_TEASE = re.compile(
    r"\b(para de zoar|para de me zoar|sem graca|nao tem graca|(voce|vc|tu) (e|ta) chata|para com isso)\b"
)
_LAUGH = re.compile(r"\b(k{3,}\w*|(ha){2,}h?|(he){2,}h?|rs(rs)+)\b")
_THANKS = re.compile(
    r"\b(valeu|obrigad[oa]|brigad[oa]|boa|show|top|brabo|braba|mandou bem|perfeito|massa|daora|"
    r"isso ai|muito bom|adorei)\b"
)
_CORRECTION = re.compile(r"\b(eu (falei|disse)|nao foi isso|nao e isso|nao era isso)\b")


def normalize(text: str) -> str:
    """Minúsculas, sem acento nem pontuação."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w\s]", " ", text).split())


def read_signals(
    text: str,
    at: datetime,
    tone: ToneMetadata | None = None,
    previous_text: str | None = None,
    previous_at: datetime | None = None,
) -> list[MoodEvent]:
    """Sinais do turno (R13.3). Cada ``value`` é somado ao alvo da nota; sem sinal = neutro."""
    out: list[MoodEvent] = []

    def add(signal: str, value: float) -> None:
        out.append(MoodEvent(signal, value, at))

    norm = normalize(text)
    if norm:
        if _SWEAR.search(norm):
            add("swear", W_SWEAR)
        if _FRUSTRATION.search(norm):
            add("frustration", W_FRUSTRATION)
        if _STOP_TEASE.search(norm):
            add("stop_tease", W_STOP_TEASE)
        if _LAUGH.search(norm):
            add("laugh", W_LAUGH)
        if _THANKS.search(norm):
            add("thanks", W_THANKS)
        if _CORRECTION.search(norm):
            add("correction", W_CORRECTION)
        if (
            previous_text
            and previous_at is not None
            and 0 <= (at - previous_at).total_seconds() <= REPEAT_S
            and fuzz.ratio(norm, normalize(previous_text)) >= REPEAT_RATIO
        ):
            add("repeat", W_REPEAT)
    if tone is not None and tone.duration_ms > 0:
        if tone.energy_db > LOUD_DB:
            add("loud", W_LOUD)
        elif tone.energy_db < FLAT_DB and tone.speech_rate < SLOW_RATE:
            add("flat", W_FLAT)
        if tone.speech_rate > FAST_RATE:
            add("fast", W_FAST)
    if at.astimezone(TZ).hour in LATE_HOURS:
        add("late", W_LATE)
    return out


def _clamp(x: float, lo: float, hi: float) -> float:
    return min(max(x, lo), hi)


@dataclass(frozen=True, slots=True)
class MoodState:
    """Estado persistido. ``cap``/``floor`` valem até ``until`` (comando explícito)."""

    score: float = NEUTRAL
    at: datetime | None = None
    bias: float = 0.0
    cap: int | None = None
    floor: int | None = None
    until: datetime | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "score": self.score,
            "at": self.at.isoformat() if self.at else None,
            "bias": self.bias,
            "cap": self.cap,
            "floor": self.floor,
            "until": self.until.isoformat() if self.until else None,
        }

    @classmethod
    def from_json(cls, raw: dict[str, object]) -> MoodState:
        def when(v: object) -> datetime | None:
            return datetime.fromisoformat(v) if isinstance(v, str) else None

        def opt_int(v: object) -> int | None:
            return int(v) if isinstance(v, int | float) and not isinstance(v, bool) else None

        score = raw.get("score", NEUTRAL)
        bias = raw.get("bias", 0.0)
        return cls(
            score=_clamp(float(score), MOOD_MIN, MOOD_MAX) if isinstance(score, int | float) else NEUTRAL,
            at=when(raw.get("at")),
            bias=_clamp(float(bias), -BIAS_MAX, BIAS_MAX) if isinstance(bias, int | float) else 0.0,
            cap=opt_int(raw.get("cap")),
            floor=opt_int(raw.get("floor")),
            until=when(raw.get("until")),
        )


class MoodTracker:
    """Termômetro de humor. ``now`` injetável (relógio falso nos testes)."""

    def __init__(
        self,
        state_path: Path | str | None = None,
        *,
        hud: HudSink | None = None,
        events: MoodEventsRepo | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.state_path = Path(state_path) if state_path is not None else None
        self.hud = hud
        self.events = events
        self.now = now
        self.state = self._load()
        self._sent: int | None = None

    # -- consulta ------------------------------------------------------------------------------

    def score(self, at: datetime | None = None) -> float:
        """Nota contínua no instante ``at``, já com o decaimento para o neutro."""
        at = at or self.now()
        s = self.state
        neutral = _clamp(NEUTRAL + s.bias, MOOD_MIN, MOOD_MAX)
        if s.at is None:
            return s.score
        dt = max((at - s.at).total_seconds(), 0.0)
        return neutral + (s.score - neutral) * math.pow(0.5, dt / HALF_LIFE_S)

    def level(self, at: datetime | None = None) -> int:
        """Nível inteiro 0..4 com teto/piso do comando explícito em vigor."""
        at = at or self.now()
        lvl = int(_clamp(math.floor(self.score(at) + 0.5), MOOD_MIN, MOOD_MAX))
        s = self.state
        if s.until is not None and at < s.until:
            if s.cap is not None:
                lvl = min(lvl, s.cap)
            if s.floor is not None:
                lvl = max(lvl, s.floor)
        return lvl

    # -- atualização ---------------------------------------------------------------------------

    async def observe(self, text: str, ctx: TurnContext) -> int:
        """Lê os sinais do turno, atualiza a nota e devolve o nível para o prompt."""
        at = self.now()
        signals = read_signals(text, at, ctx.tone, ctx.previous_text, ctx.previous_at)
        base = self.score(at)
        target = _clamp(NEUTRAL + self.state.bias + sum(e.value for e in signals), MOOD_MIN, MOOD_MAX)
        score = (1 - ALPHA) * base + ALPHA * target
        self.state = replace(self._expire(at), score=score, at=at)
        if signals:
            log.debug("humor: %s -> %.2f", ", ".join(f"{e.signal}{e.value:+}" for e in signals), score)
        self._save()
        level = await self.publish(at)
        await self.publish_tag(text, ctx.tone)
        return level

    async def publish_tag(self, text: str, tone: ToneMetadata | None = None) -> str | None:
        """Manda a tag local do turno (``TurnTagMsg``, reações R2.B) ao HUD; turno neutro não manda."""
        from magi.memory.turn_tag import classify  # turn_tag importa as regras daqui

        tag = classify(text, tone)
        if tag is not None and self.hud is not None:
            try:
                await self.hud.send(TurnTagMsg(tag))
            except Exception:
                log.exception("falha ao mandar a tag do turno ao HUD")
        return tag

    async def soften(self) -> int:
        """"Pega leve": teto 1 por algumas horas e viés aprendido para baixo (R13.5)."""
        return await self._explicit(-1)

    async def harden(self) -> int:
        """"Pode pegar pesado": piso 3 por algumas horas e viés aprendido para cima (R13.5)."""
        return await self._explicit(+1)

    async def publish(self, at: datetime | None = None) -> int:
        """Manda ``MoodMsg`` ao HUD se o nível mudou desde o último envio."""
        lvl = self.level(at)
        if self.hud is not None and lvl != self._sent:
            try:
                await self.hud.send(MoodMsg(lvl))
                self._sent = lvl
            except Exception:
                log.exception("falha ao mandar o humor ao HUD")
        return lvl

    async def _explicit(self, direction: int) -> int:
        at = self.now()
        s = self.state
        bias = _clamp(s.bias + direction * BIAS_STEP, -BIAS_MAX, BIAS_MAX)
        score = self.score(at)
        until = at + timedelta(seconds=OVERRIDE_S)
        if direction < 0:
            self.state = MoodState(min(score, SOFT_CAP), at, bias, cap=SOFT_CAP, until=until)
        else:
            self.state = MoodState(max(score, HARD_FLOOR), at, bias, floor=HARD_FLOOR, until=until)
        self._save()
        if self.events is not None:
            try:
                await self.events.add(MoodEvent("explicit", float(direction), at))
            except Exception:
                log.exception("falha ao registrar o ajuste de humor")
        return await self.publish(at)

    def _expire(self, at: datetime) -> MoodState:
        s = self.state
        if s.until is not None and at >= s.until:
            return replace(s, cap=None, floor=None, until=None)
        return s

    # -- persistência --------------------------------------------------------------------------

    def _load(self) -> MoodState:
        if self.state_path is None or not self.state_path.exists():
            return MoodState()
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            return MoodState.from_json(raw) if isinstance(raw, dict) else MoodState()
        except (OSError, ValueError, TypeError):
            log.warning("estado de humor ilegível em %s; começando do neutro", self.state_path)
            return MoodState()

    def _save(self) -> None:
        if self.state_path is None:
            return
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.state.to_json()), encoding="utf-8")
            os.replace(tmp, self.state_path)
        except OSError:
            log.exception("falha ao gravar o estado de humor")


SAY_SOFTER = "Tá, vou maneirar."
SAY_HARDER = "Ah, agora sim."


class MoodHandler:
    """``mood.softer`` ("pega leve") e ``mood.harder`` ("pode pegar pesado") para o ``Registry``."""

    intents = frozenset({IntentId.MOOD_SOFTER.value, IntentId.MOOD_HARDER.value})

    def __init__(self, tracker: MoodTracker) -> None:
        self.tracker = tracker

    async def run(self, req: ActionRequest) -> ActionResult:
        if req.intent.id == IntentId.MOOD_SOFTER.value:
            await self.tracker.soften()
            default = SAY_SOFTER
        else:
            await self.tracker.harden()
            default = SAY_HARDER
        return ActionResult(ok=True, speech=req.intent.reply or default)


def handlers(tracker: MoodTracker) -> list[ActionHandler]:
    return [MoodHandler(tracker)]


class PgMoodEventsRepo:
    """``MoodEventsRepo`` em Postgres (tabela ``mood_events``)."""

    def __init__(self, conn: object) -> None:
        self._conn = conn

    async def add(self, event: MoodEvent) -> None:
        async with self._conn.transaction():  # type: ignore[attr-defined]
            await self._conn.execute(  # type: ignore[attr-defined]
                "INSERT INTO mood_events (at, signal, value) VALUES (%s, %s, %s)",
                [event.at, event.signal, event.value],
            )

    async def since(self, at: datetime) -> list[MoodEvent]:
        async with self._conn.transaction():  # type: ignore[attr-defined]
            cur = await self._conn.execute(  # type: ignore[attr-defined]
                "SELECT signal, value, at FROM mood_events WHERE at >= %s ORDER BY at", [at]
            )
            rows = await cur.fetchall()
        return [MoodEvent(str(r[0]), float(r[1] or 0.0), r[2]) for r in rows]
