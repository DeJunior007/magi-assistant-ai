"""Autoconhecimento da Magui (tarefa 3.9): a "ficha" dela gerada de fontes vivas.

Nada aqui é lista fixa de capacidades: os comandos vêm do ``intents.yaml`` (agrupados pela área do
id, ``game.open`` → Jogos), filtrados pelo ``ActionRegistry`` (intent sem handler vira "ainda não
sei"); as ferramentas são as registradas no agente; o estado sai da config (``[satellite]``,
``[tasks].tts``, ``[alerts]``, ``[news.delivery]``) e de funções injetadas (Spotify, call, chaves,
orçamento). Usos:

- ``about_section()``: seção "Sobre você" do prompt do agente (≤ ``SELF_MAX_TOKENS``);
- ``info(topic)``: detalhe por tópico (ferramenta ``self_info``) — fala curta + lista no HUD;
- ``help_result()``: resposta do intent local ``magi.help``, sem LLM.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from magi.agent.prompt import SELF_MAX_TOKENS, estimate_tokens, truncate_to_tokens
from magi.common.contracts import (
    ActionRegistry,
    ActionRequest,
    ActionResult,
    BudgetStatus,
    CardLevel,
    CardMsg,
    IntentId,
    ToolSpec,
    TurnContext,
)

INTENTS_PATH = Path(__file__).resolve().parent.parent / "core" / "intents.yaml"

TOPICS = ("capacidades", "comandos", "estado", "gasto", "ativacao", "limites")

#: Nome falado de cada área (prefixo do id). Prefixo novo aparece com o próprio nome.
AREA_NAMES: dict[str, str] = {
    "game": "Jogos",
    "hud": "HUD",
    "volume": "Volume",
    "rgb": "RGB",
    "system": "Sistema",
    "music": "Música",
    "correction": "Correção",
    "memory": "Memória",
    "mood": "Humor",
    "budget": "Orçamento",
    "news": "Notícias",
    "magi": "Sobre mim",
}
#: Intents de controle do turno, que não são "comandos" para o usuário.
HIDDEN_AREAS = frozenset({"confirm"})
#: Intents tratados pelo próprio turno (não passam pelo registro de ações).
TURN_INTENTS = frozenset({IntentId.CONFIRM_YES.value, IntentId.CONFIRM_NO.value})

#: Ferramentas que, ausentes, viram limite ("ainda não sei"). Só o nome da capacidade é fixo.
TOOL_GAPS: dict[str, str] = {
    "screenshot": "ver a tela",
    "search": "pesquisar na internet",
    "news_query": "responder sobre novidades de jogos e anime",
    "spotify_pick": "escolher música pelo seu gosto",
    "remember": "lembrar de coisas entre conversas",
}

_SLOT_WORDS = {"game": "jogo", "volume": "número", "brightness": "número", "amount": "valor",
               "color": "cor", "detail": "painel", "query": "música", "text": "texto",
               "franchise": "obra", "on_off": "liga/desliga"}
_SLOT_RE = re.compile(r"\{(\w+)(?::[+-])?\}")


@dataclass(frozen=True, slots=True)
class Command:
    """Um intent do ``intents.yaml`` como a Magui o descreve."""

    id: str
    label: str
    examples: tuple[str, ...]
    available: bool = True


@dataclass(frozen=True, slots=True)
class Area:
    name: str
    commands: tuple[Command, ...]


@dataclass(frozen=True, slots=True)
class SelfState:
    """Estado atual relevante para "como você está?" / "dá pra...?"."""

    wake_word: str
    wake_provisional: bool
    ptt: tuple[str, ...]
    voice: str | None
    spotify_connected: bool | None
    in_call: bool | None
    alerts_on: bool
    news_on: bool
    missing_keys: tuple[str, ...]
    budget: BudgetStatus | None = None


def _slot_text(text: str) -> str:
    return _SLOT_RE.sub(lambda m: f"<{_SLOT_WORDS.get(m.group(1), m.group(1))}>", text)


def _plain_label(label: str) -> str:
    return " ".join(_SLOT_RE.sub("", label).split())


#: Palavra de ativação definitiva (modelo ``condessa.onnx``, spike S4).
WAKE_WORD = "Condessa"


def wake_word_name(model: str) -> tuple[str, bool]:
    """Nome falável do wake word pelo arquivo do modelo e se é provisório (não é o "Condessa")."""
    words = Path(model).stem.replace("-", "_").split("_")
    words = [w for w in words if w and not re.fullmatch(r"v\d+(\.\d+)*", w)]
    if WAKE_WORD.lower() in (w.lower() for w in words):
        return WAKE_WORD, False
    name = " ".join(w if i == 0 else w.capitalize() for i, w in enumerate(words)) or model
    return name, True


def _read_intents(path: Path) -> list[dict[str, Any]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return [i for i in data.get("intents", []) if isinstance(i, Mapping) and "id" in i]


@dataclass
class SelfModel:
    """Ficha viva da Magui. ``registry``/``tools`` podem ser ligados depois da montagem.

    ``raw``: config crua (``Config.raw``). ``spotify``/``in_call``/``missing_keys``: leituras
    baratas do estado; ``budget``: corrotina de ``BudgetStatus``. Tudo opcional: o que faltar
    aparece como "não sei".
    """

    raw: Mapping[str, Any] = field(default_factory=dict)
    intents_path: Path = INTENTS_PATH
    registry: ActionRegistry | None = None
    tools: Sequence[ToolSpec] = ()
    spotify: Callable[[], bool] | None = None
    in_call: Callable[[], bool] | None = None
    missing_keys: Callable[[], Iterable[str]] | None = None
    budget: Callable[[], Awaitable[BudgetStatus]] | None = None
    agent_ready: bool = True
    _cache: tuple[float, list[dict[str, Any]]] | None = field(default=None, repr=False)

    # -- fontes -----------------------------------------------------------------------------

    def _intents(self) -> list[dict[str, Any]]:
        try:
            mtime = self.intents_path.stat().st_mtime
        except OSError:
            return []
        if self._cache is None or self._cache[0] != mtime:
            self._cache = (mtime, _read_intents(self.intents_path))
        return self._cache[1]

    def _available(self, intent_id: str) -> bool:
        if self.registry is None or intent_id in TURN_INTENTS:
            return True
        return self.registry.handles(intent_id)

    def areas(self, *, available: bool | None = True) -> list[Area]:
        """Comandos por área, na ordem do ``intents.yaml``. ``available``: filtra (``None`` = todos)."""
        grouped: dict[str, list[Command]] = {}
        for item in self._intents():
            iid = str(item["id"])
            prefix = iid.split(".", 1)[0]
            if prefix in HIDDEN_AREAS:
                continue
            phrases = [p if isinstance(p, str) else str(p.get("say", "")) for p in item.get("phrases", [])]
            cmd = Command(
                id=iid,
                label=_plain_label(str(item.get("label") or iid)),
                examples=tuple(_slot_text(p) for p in phrases[:2] if p),
                available=self._available(iid),
            )
            if available is None or cmd.available == available:
                grouped.setdefault(AREA_NAMES.get(prefix, prefix.capitalize()), []).append(cmd)
        return [Area(name, tuple(cmds)) for name, cmds in grouped.items()]

    def tool_names(self) -> list[str]:
        return [t.name for t in self.tools]

    def gaps(self) -> list[str]:
        """O que ainda não sei fazer: ferramentas ausentes, agente fora e comandos sem ação."""
        names = set(self.tool_names())
        out = [what for tool, what in TOOL_GAPS.items() if tool not in names]
        if not self.agent_ready:
            out.insert(0, "responder perguntas livres (agente sem chave)")
        for area in self.areas(available=False):
            out.append(f"{area.name.lower()}: " + ", ".join(c.label for c in area.commands))
        return out

    def state(self, ctx: TurnContext | None = None, budget: BudgetStatus | None = None) -> SelfState:
        sat = self.raw.get("satellite") if isinstance(self.raw.get("satellite"), Mapping) else {}
        wake, provisional = wake_word_name(str(sat.get("wake_model", "hey_jarvis")))
        ptt = []
        if sat.get("ptt_keyboard", True):
            ptt.append(f"tecla {sat.get('ptt_key', 'Pause')}")
        if sat.get("ptt_dualsense", True):
            ptt.append("PS+Share no DualSense")
        tasks = self.raw.get("tasks") if isinstance(self.raw.get("tasks"), Mapping) else {}
        tts = tasks.get("tts") if isinstance(tasks.get("tts"), Mapping) else {}
        voice = str(tts.get("voice") or "").strip() or None
        if voice and voice.startswith("<"):
            voice = None  # placeholder do config.example.toml
        alerts = self.raw.get("alerts") if isinstance(self.raw.get("alerts"), Mapping) else {}
        news = self.raw.get("news") if isinstance(self.raw.get("news"), Mapping) else {}
        delivery = news.get("delivery") if isinstance(news.get("delivery"), Mapping) else {}
        in_call = ctx.in_call if ctx is not None else (self.in_call() if self.in_call else None)
        return SelfState(
            wake_word=wake,
            wake_provisional=provisional,
            ptt=tuple(ptt),
            voice=voice,
            spotify_connected=_safe(self.spotify),
            in_call=in_call,
            alerts_on=bool(alerts.get("enabled", True)),
            news_on=bool(delivery.get("enabled", True)),
            missing_keys=tuple(_safe(self.missing_keys) or ()),
            budget=budget,
        )

    async def budget_status(self) -> BudgetStatus | None:
        if self.budget is None:
            return None
        try:
            return await self.budget()
        except Exception:
            return None

    # -- textos -----------------------------------------------------------------------------

    @staticmethod
    def _activation(s: SelfState) -> str:
        if s.wake_provisional:
            wake = f'palavra "{s.wake_word}" (provisória, até treinar o "{WAKE_WORD}")'
        else:
            wake = f'fale "{s.wake_word}" (ou "hey/oi/oh {s.wake_word}")'
        return wake + (f", ou segurar {' ou '.join(s.ptt)} e falar" if s.ptt else "")

    @staticmethod
    def _state_lines(s: SelfState) -> list[str]:
        def yn(v: bool | None, yes: str, no: str) -> str:
            return "não sei" if v is None else (yes if v else no)

        lines = [
            f"Spotify: {yn(s.spotify_connected, 'conectado', 'desconectado (magi-spotify-login)')}",
            f"Call no Discord: {yn(s.in_call, 'em call (avisos só na tela)', 'fora de call')}",
            f"Ativação: {SelfModel._activation(s)}",
            f"Voz: {s.voice or 'não escolhida ainda'}",
            f"Alertas: {'ligados' if s.alerts_on else 'desligados'}; "
            f"notícias: {'ligadas' if s.news_on else 'desligadas'}",
        ]
        if s.budget is not None:
            lines.append(_budget_line(s.budget))
        lines.append("Chaves faltando: " + (", ".join(s.missing_keys) if s.missing_keys else "nenhuma"))
        return lines

    def about_section(self) -> str:
        """Seção "Sobre você" do prompt (≤ ``SELF_MAX_TOKENS``): nome, ativação, controle, limites."""
        s = self.state()
        areas = ", ".join(a.name for a in self.areas() if a.name != AREA_NAMES["magi"])
        gaps = self.gaps()
        user = self.raw.get("user") if isinstance(self.raw.get("user"), Mapping) else {}
        name = str(user.get("name") or "").strip()
        owner = f"de {name}" if name else "do usuário"
        who = f" Quem fala com você é {name}; chame pelo nome." if name else ""
        lines = [
            "## Sobre você",
            f'Você é a MAGI (fala-se "Magui"), roda no PC {owner} (Linux/KDE): satélite de voz, núcleo e '
            "o HUD MAGI Gamer no 2º monitor." + who,
            f"Ativação: {self._activation(s)}.",
            f"Comandos locais: {areas or 'nenhum'}. "
            f"Ferramentas: {', '.join(self.tool_names()) or 'nenhuma'}.",
        ]
        if s.spotify_connected is not None:
            spot = "conectado." if s.spotify_connected else "desconectado: não toca busca por nome."
            lines.append(f"Spotify {spot}")
        last = "Detalhes de comandos, estado, gasto e limites: self_info. Fora disso, não ofereça."
        if gaps:
            # Os limites ficam com o que sobrar do teto; a linha final nunca é cortada.
            room = SELF_MAX_TOKENS - estimate_tokens("\n".join([*lines, last])) - 2
            lines.append(truncate_to_tokens("Ainda não sabe: " + "; ".join(gaps) + ".", room))
        lines.append(last)
        return truncate_to_tokens("\n".join(x for x in lines if x), SELF_MAX_TOKENS)

    def commands_text(self, *, examples: bool = True) -> str:
        out = []
        for area in self.areas():
            if examples:
                items = "; ".join(
                    f'{c.label} ("{c.examples[0]}")' if c.examples else c.label for c in area.commands
                )
            else:
                items = ", ".join(c.label for c in area.commands)
            out.append(f"{area.name}: {items}")
        return "\n".join(out)

    async def info(self, topic: str, ctx: TurnContext | None = None) -> ActionResult:
        """Detalhe por tópico (``TOPICS``): fala curta + texto completo e card para o HUD."""
        topic = _norm_topic(topic)
        budget = await self.budget_status() if topic in ("estado", "gasto") else None
        s = self.state(ctx, budget)
        match topic:
            case "comandos":
                full = self.commands_text()
                speech = "Mandei a lista de comandos pra tela, separada por área."
            case "estado":
                full = "\n".join(self._state_lines(s))
                spot = {True: "Spotify conectado", False: "Spotify desconectado", None: "Spotify sem leitura"}
                call = {True: "em call", False: "fora de call", None: ""}[s.in_call]
                speech = f"{spot[s.spotify_connected]}{', ' + call if call else ''}. O resto tá na tela."
            case "gasto":
                if s.budget is None:
                    speech = full = "Não consigo ler o gasto agora, o orçamento tá sem banco."
                else:
                    full = _budget_line(s.budget)
                    speech = full
            case "ativacao":
                full = f"Ativação: {self._activation(s)}."
                speech = f'Diz "{s.wake_word}" ou segura {s.ptt[0] if s.ptt else "o atalho"} e fala.'
            case "limites":
                gaps = self.gaps()
                full = "Ainda não sei:\n" + "\n".join(f"- {g}" for g in gaps) if gaps else "Nada pendente."
                first = ", ".join(gaps[:2]) if gaps else "nada que eu saiba"
                speech = f"Ainda não sei {first}. Mas abro jogo, mexo no HUD, volume e música."
            case _:
                full = self.commands_text(examples=False)
                areas = [a.name.lower() for a in self.areas() if a.name != AREA_NAMES["magi"]]
                speech = f"Eu cuido de {_join(areas[:5])}, e manjo de games e anime. A lista tá na tela."
        card = CardMsg(CardLevel.NORMAL, f"MAGI · {topic}")
        return ActionResult(ok=True, speech=speech, full_text=full, cards=(card,))

    def help_result(self, ctx: TurnContext | None = None) -> ActionResult:
        """Resposta do ``magi.help`` (sem LLM): 2 frases + lista agrupada no HUD."""
        s = self.state(ctx)
        ptt = f" ou segurando {s.ptt[0]}" if s.ptt else ""
        speech = (
            'Sou a MAGI, fala "Magui", sua parceira gamer aqui no PC. '
            f'Me chama {"com" if s.wake_provisional else "de"} "{s.wake_word}"{ptt}, '
            "e o que eu sei fazer tá na tela."
        )
        full = f"Ativação: {self._activation(s)}.\n{self.commands_text()}"
        gaps = self.gaps()
        if gaps:
            full += "\nAinda não sei: " + "; ".join(gaps) + "."
        card = CardMsg(CardLevel.NORMAL, "MAGI · o que eu sei fazer")
        return ActionResult(ok=True, speech=speech, full_text=full, cards=(card,))


def _safe[T](fn: Callable[[], T] | None) -> T | None:
    if fn is None:
        return None
    try:
        return fn()
    except Exception:
        return None


def _join(items: Sequence[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " e " + items[-1] if items else ""


def _budget_line(b: BudgetStatus) -> str:
    pct = round(b.fraction * 100)
    def brl(v: float) -> str:  # vírgula decimal: a frase vai para a voz
        return f"{v:.2f}".replace(".", ",")

    return f"Gastei US$ {brl(b.spent_usd)} de US$ {brl(b.cap_usd)} este mês, {pct}% do teto."


_TOPIC_ALIASES = {"ativação": "ativacao", "capacidade": "capacidades", "comando": "comandos",
                  "limite": "limites", "custo": "gasto", "status": "estado"}


def _norm_topic(topic: str) -> str:
    t = (topic or "").strip().lower()
    t = _TOPIC_ALIASES.get(t, t)
    return t if t in TOPICS else "capacidades"


# -- ferramenta e handler ---------------------------------------------------------------------

SELF_INFO_SPEC = ToolSpec(
    name="self_info",
    description="Detalhes sobre você mesma: o que sabe fazer, comandos, estado, gasto, ativação, limites.",
    parameters={
        "type": "object",
        "properties": {"topic": {"type": "string", "enum": list(TOPICS)}},
        "required": ["topic"],
    },
)


class SelfInfoTool:
    """Ferramenta ``self_info(topic)`` do agente (3.9)."""

    spec = SELF_INFO_SPEC
    danger = False

    def __init__(self, model: SelfModel) -> None:
        self.model = model

    @property
    def name(self) -> str:
        return self.spec.name

    async def run(self, args: Mapping[str, Any], ctx: TurnContext, text: str = "") -> ActionResult:
        return await self.model.info(str(args.get("topic") or ""), ctx)


class HelpHandler:
    """Handler local de ``magi.help``: "o que você sabe fazer", "quem é você"..."""

    intents = frozenset({IntentId.HELP.value})

    def __init__(self, model: SelfModel) -> None:
        self.model = model

    async def run(self, req: ActionRequest) -> ActionResult:
        return self.model.help_result(req.ctx)
