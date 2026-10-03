"""Montagem do prompt do agente (tarefa 3.3, R11.1-R11.3, R13, R14, §4.3).

O prompt final é uma mensagem ``system`` (persona + "Sobre você" + humor + jogo + perfil +
memórias) seguida dos últimos 2 turnos da conversa. O total estimado nunca passa de
``MAX_PROMPT_TOKENS`` (R11.3): a pergunta atual do usuário fica fora da conta e é anexada por
``Prompt.with_user``.

Orçamento por parte (§4.3): persona ~540 · sobre você ≤ 300 · perfil ≤ 300 · humor ~40 · jogo ~80 ·
memórias ≤ 400 · turnos ≤ 180. O teto subiu de 1500 para 1800 na 3.9: a seção "Sobre você"
(autoconhecimento, ``self_model.py``) é fixa e não pode ser cortada para caber memórias. Se mesmo
assim estourar, corta primeiro as memórias menos parecidas, depois os turnos mais antigos e, por
fim, encurta o perfil.

Os tokens são estimados sem chamar API: ``ceil(caracteres / 3,5)`` (estimativa do projeto para
português) mais um custo fixo por mensagem.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from magi.common.contracts import MEMORY_TOP_K, MOOD_MAX, MOOD_MIN, ChatMessage, HelpStep, Memory

MAX_PROMPT_TOKENS = 1_800
SELF_MAX_TOKENS = 300
PROFILE_MAX_TOKENS = 300
MEMORIES_MAX_TOKENS = 400
MEMORY_ITEM_MAX_TOKENS = 100
TURNS_MAX = 2
TURNS_MAX_TOKENS = 180
TURN_MSG_MAX_TOKENS = 60
GAME_NAME_MAX_CHARS = 80
HELP_TOPIC_MAX_CHARS = 60

CHARS_PER_TOKEN = 3.5
MESSAGE_OVERHEAD_TOKENS = 4

PERSONA_PATH = Path(__file__).with_name("persona.md")

ELLIPSIS = "…"

# Instrução de tom por nível de humor (R13.3-R13.4): intensidade da zoeira e tamanho da resposta.
MOOD_TONES: dict[int, str] = {
    0: "0/4, pega leve. Ele não tá pra brincadeira: nada de zoeira. Corrija com jeito, "
    "seja acolhedora e bem breve.",
    1: "1/4. Zoeira mínima, no máximo uma piadinha suave. Corrija numa boa e foque em resolver rápido.",
    2: "2/4. Zoeira leve de amiga: corrija com uma provocada de leve e siga ajudando.",
    3: "3/4. Pode zoar com vontade e ironizar o erro; se ele insistir, aperta mais. "
    "Pode ter um pouco mais de personalidade na fala.",
    4: "4/4, pode zoar pesado. Se ele insistir no erro, pode humilhar de leve, estilo resenha "
    "entre amigos, sem ofensa de verdade.",
}

_HELP_STEP_NAMES: dict[HelpStep, str] = {
    HelpStep.HINT: "pista",
    HelpStep.DIRECT: "dica direta",
    HelpStep.SOLUTION: "solução",
}


class PromptTooLarge(ValueError):
    """Nem cortando memórias, turnos e perfil o prompt cabe no limite (persona grande demais)."""


@dataclass(frozen=True, slots=True)
class GameContext:
    """Jogo em foco (R14). ``help_step`` é o último degrau já dado em ``help_topic``."""

    name: str
    genre: str | None = None
    session_minutes: int | None = None
    help_topic: str | None = None
    help_step: HelpStep | None = None


@dataclass(frozen=True, slots=True)
class Prompt:
    """Prompt montado. ``tokens`` é a estimativa de ``messages`` (sem a pergunta atual)."""

    messages: tuple[ChatMessage, ...]
    tokens: int
    dropped_memories: int = 0
    dropped_turns: int = 0
    profile_truncated: bool = False

    def with_user(self, text: str) -> list[ChatMessage]:
        """Mensagens prontas para o modelo, com a fala atual do usuário no fim."""
        return [*self.messages, ChatMessage(role="user", content=text)]


# ---------------------------------------------------------------------------------------------
# Contagem e corte
# ---------------------------------------------------------------------------------------------


def estimate_tokens(text: str) -> int:
    """Tokens aproximados de ``text`` (heurística por caracteres, sem API)."""
    return math.ceil(len(text) / CHARS_PER_TOKEN) if text else 0


def count_message_tokens(messages: Sequence[ChatMessage]) -> int:
    """Tokens aproximados de uma lista de mensagens (conteúdo + custo fixo por mensagem)."""
    return sum(estimate_tokens(m.content) + MESSAGE_OVERHEAD_TOKENS for m in messages)


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Corta ``text`` para caber em ``max_tokens`` (estimados), terminando em "…"."""
    if estimate_tokens(text) <= max_tokens:
        return text
    if max_tokens <= 0:
        return ""
    max_chars = int(max_tokens * CHARS_PER_TOKEN) - len(ELLIPSIS)
    cut = text[: max(max_chars, 0)].rstrip()
    space = cut.rfind(" ")
    if space > max_chars // 2:  # não corta palavra no meio, se der
        cut = cut[:space].rstrip()
    return cut + ELLIPSIS


# ---------------------------------------------------------------------------------------------
# Partes
# ---------------------------------------------------------------------------------------------


@cache
def load_persona() -> str:
    """Texto fixo da persona (``persona.md``)."""
    return PERSONA_PATH.read_text(encoding="utf-8").strip()


def self_section(about: str | None) -> str | None:
    """Seção "Sobre você" (3.9), cortada em ``SELF_MAX_TOKENS``. Ganha o título se não tiver."""
    body = (about or "").strip()
    if not body:
        return None
    if not body.startswith("## "):
        body = f"## Sobre você\n{body}"
    return truncate_to_tokens(body, SELF_MAX_TOKENS)


def mood_section(mood: int) -> str:
    """Nível de humor + instrução de tom (R13.4). ``mood`` fora de 0..4 é ajustado ao limite."""
    if not isinstance(mood, int) or isinstance(mood, bool):
        raise TypeError(f"humor precisa ser int: {mood!r}")
    level = min(max(mood, MOOD_MIN), MOOD_MAX)
    return f"## Humor dele\n{MOOD_TONES[level]}"


def _help_line(game: GameContext) -> str | None:
    if not game.help_topic:
        return None
    topic = game.help_topic[:HELP_TOPIC_MAX_CHARS]
    if game.help_step is None:
        return f"Ajuda em \"{topic}\": nenhum degrau dado ainda; comece pela pista."
    given = _HELP_STEP_NAMES[game.help_step]
    if game.help_step >= HelpStep.SOLUTION:
        return f"Ajuda em \"{topic}\": já deu a solução; explique de novo ou detalhe."
    nxt = _HELP_STEP_NAMES[HelpStep(game.help_step + 1)]
    return f"Ajuda em \"{topic}\": já deu {given}; agora vá para {nxt}."


def game_section(game: GameContext | None) -> str | None:
    """Contexto do jogo: nome, gênero, tempo de sessão e degrau de ajuda (R14)."""
    if game is None:
        return None
    name = game.name[:GAME_NAME_MAX_CHARS]
    head = f"Jogando: {name}"
    if game.genre:
        head += f" ({game.genre[:40]})"
    if game.session_minutes is not None:
        head += f", sessão de {max(game.session_minutes, 0)} min"
    lines = ["## Jogo agora", head + "."]
    help_line = _help_line(game)
    if help_line:
        lines.append(help_line)
    return "\n".join(lines)


def profile_section(profile: str | None, max_tokens: int = PROFILE_MAX_TOKENS) -> str | None:
    """Perfil compacto (R11.1), cortado em ``max_tokens``."""
    body = (profile or "").strip()
    if not body or max_tokens <= 0:
        return None
    return f"## Perfil dele\n{truncate_to_tokens(body, max_tokens)}"


def memories_section(memories: Sequence[str]) -> str | None:
    """Memórias (R11.2), uma por linha."""
    if not memories:
        return None
    return "## Memórias\n" + "\n".join(f"- {m}" for m in memories)


def _prepare_memories(memories: Sequence[Memory]) -> list[str]:
    """Até ``MEMORY_TOP_K`` memórias, da mais para a menos parecida, cada uma cortada."""
    ranked = sorted(
        (m for m in memories if m.body.strip()),
        key=lambda m: m.score if m.score is not None else 0.0,
        reverse=True,
    )
    return [truncate_to_tokens(m.body.strip(), MEMORY_ITEM_MAX_TOKENS) for m in ranked[:MEMORY_TOP_K]]


def _prepare_turns(history: Sequence[ChatMessage]) -> list[ChatMessage]:
    """Últimos ``TURNS_MAX`` turnos (pares usuário/assistente com texto), cada fala cortada."""
    talk = [m for m in history if m.role in ("user", "assistant") and m.content.strip()]
    recent = talk[-2 * TURNS_MAX :]
    while recent and recent[0].role != "user":  # turno começa na fala dele
        recent = recent[1:]
    return [
        ChatMessage(role=m.role, content=truncate_to_tokens(m.content.strip(), TURN_MSG_MAX_TOKENS))
        for m in recent
    ]


def _drop_oldest_turn(turns: list[ChatMessage]) -> list[ChatMessage]:
    rest = turns[1:]
    while rest and rest[0].role != "user":
        rest = rest[1:]
    return rest


def _fit[T](
    items: list[T], cost: Callable[[list[T]], int], limit: int, drop: Callable[[list[T]], list[T]]
) -> list[T]:
    while items and cost(items) > limit:
        items = drop(items)
    return items


# ---------------------------------------------------------------------------------------------
# Montagem
# ---------------------------------------------------------------------------------------------


def build_prompt(
    *,
    mood: int,
    profile: str | None = None,
    game: GameContext | None = None,
    memories: Sequence[Memory] = (),
    history: Sequence[ChatMessage] = (),
    persona: str | None = None,
    about: str | None = None,
    max_tokens: int = MAX_PROMPT_TOKENS,
) -> Prompt:
    """Monta o prompt do agente sem passar de ``max_tokens`` estimados (R11.3).

    ``memories`` vem da busca por similaridade; ``history`` são as mensagens anteriores em ordem
    cronológica (sem a fala atual). ``persona`` substitui ``persona.md`` (testes). ``about``: seção
    "Sobre você" da ficha viva (``SelfModel.about_section``).
    """
    persona_text = (persona if persona is not None else load_persona()).strip()
    fixed = [persona_text, self_section(about), mood_section(mood), game_section(game)]

    mems = _prepare_memories(memories)
    turns = _prepare_turns(history)
    n_mems, n_turns = len(mems), len(turns)

    def mem_cost(items: list[str]) -> int:
        section = memories_section(items)
        return estimate_tokens(section) + 2 if section else 0

    # Teto de cada parte (§4.3).
    mems = _fit(mems, mem_cost, MEMORIES_MAX_TOKENS, lambda xs: xs[:-1])
    turns = _fit(turns, count_message_tokens, TURNS_MAX_TOKENS, _drop_oldest_turn)
    profile_tokens = PROFILE_MAX_TOKENS
    full_profile = (profile or "").strip()

    def assemble() -> list[ChatMessage]:
        parts = [*fixed, profile_section(profile, profile_tokens), memories_section(mems)]
        system = "\n\n".join(p for p in parts if p)
        return [ChatMessage(role="system", content=system), *turns]

    messages = assemble()
    # Teto total: memórias menos parecidas, depois turnos antigos, depois perfil.
    while count_message_tokens(messages) > max_tokens:
        if mems:
            mems = mems[:-1]
        elif turns:
            turns = _drop_oldest_turn(turns)
        elif full_profile and profile_tokens > 0:
            excess = count_message_tokens(messages) - max_tokens
            profile_tokens = max(profile_tokens - excess - 1, 0)
        else:
            raise PromptTooLarge(
                f"prompt fixo com {count_message_tokens(messages)} tokens passa de {max_tokens}"
            )
        messages = assemble()

    shown_profile = profile_section(profile, profile_tokens)
    return Prompt(
        messages=tuple(messages),
        tokens=count_message_tokens(messages),
        dropped_memories=n_mems - len(mems),
        dropped_turns=(n_turns - len(turns) + 1) // 2,
        profile_truncated=bool(full_profile)
        and (shown_profile is None or not shown_profile.endswith(full_profile)),
    )
