"""Roteador local (tarefa 1.8, §4.2, R4.1-R4.4).

Pipeline: minúsculas sem acento → formas canônicas de verbos ("abri" → "abre") → slots fixos
(número, cor, painel) viram marcadores → nota de cada frase-modelo do ``intents.yaml`` com
``rapidfuzz.fuzz.token_set_ratio`` menos penalidades por palavra sobrando/faltando → slot livre
(jogo, música, texto) é o rabo da frase depois do comando; jogo é resolvido no ``GameCatalog``.

Nota ≥ ``execute_score`` executa; entre ``ask_score`` e ``execute_score`` pergunta
"você quis dizer X?"; abaixo vai ao agente.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from rapidfuzz import fuzz

from magi.common.contracts import (
    ROUTER_ASK_SCORE,
    ROUTER_EXECUTE_SCORE,
    GameCatalog,
    Intent,
    IntentId,
    RouteKind,
    RouteResult,
    Slot,
    SlotName,
    TurnContext,
)

__all__ = [
    "COLORS",
    "INTENTS_PATH",
    "IntentSpec",
    "LocalRouter",
    "load_intents",
    "normalize_text",
    "parse_number",
]

INTENTS_PATH = Path(__file__).with_name("intents.yaml")

# ---------------------------------------------------------------------------
# Vocabulário

#: Palavras que não mudam o comando: somem do texto e das frases-modelo antes da nota.
FILLERS = frozenset(
    "o a os as um uma uns umas e ai ae la ei oi ow opa po pfv pf mim me ne eu magui maggie condessa hey "
    "vai so agora logo rapidinho pra pro no na nos nas em de do da dos das num numa pela pelo "
    "ate ok beleza".split()
)
#: Palavras de pouco peso quando sobram ("abaixa o volume que ta muito alto").
LIGHT = frozenset(
    "que ta esta to tô muito ja aqui bem tambem assim entao tipo mano cara porque pq pode voce "
    "consegue por seu sua meu minha mesmo hein ae favorzinho dai alto baixo demais pouco".split()
)
#: Primeira palavra de pergunta: se a frase-modelo não a tem, é conversa (vai ao agente).
QUESTION_START = frozenset(
    "qual quais quem como quando onde quanto quanta quantos quantas que porque pq sera "
    "explica conta sabe".split()
)
_PHRASE_FILLERS = [("por favor", ""), ("pra mim", ""), ("por cento", ""), ("porcento", "")]

#: Formas que o STT/fala produz → forma canônica (aplicada a texto e frases-modelo).
_LEMMA_GROUPS = {
    "abre": "abri abra abrir abrei abreai",
    "fecha": "feche fechar fexa fechou",
    "coloca": "bota bote botar colocar coloque poe ponha taca tacar taque mete solta",
    "toca": "tocar toque",
    "aumenta": "aumente aumentar sobe subir suba",
    "abaixa": "abaixe abaixar baixa baixar diminui diminua diminuir reduz reduzir",
    "pausa": "pause pausar pauza pausei",
    "proxima": "proximo",
    "musica": "musicas",
    "muda": "mude mudar troca trocar troque",
    "liga": "ligar ligue ativa ativar acende acender",
    "desliga": "desligar desligue desativa desativar apaga apagar",
    "mostra": "mostrar mostre exibe",
    "volta": "voltar volte",
    "esquece": "esqueca esquecer",
    "confirma": "confirmar confirmo confirme",
    "cancela": "cancelar cancele cancelo",
    "pula": "pular pule",
    "passa": "passar passe",
    "reinicia": "reiniciar reinicie reseta restarta",
    "inicia": "iniciar inicie executa executar roda rodar",
    "desmuta": "desmutar desmute",
    "muta": "mutar mute",
    "jogo": "game",
    "novidade": "novidades",
    "dolar": "dolares",
}
LEMMA = {form: canon for canon, forms in _LEMMA_GROUPS.items() for form in forms.split()}

#: Cores faladas → ``#rrggbb`` (slot ``color``).
COLORS = {
    "azul claro": "#66ccff",
    "azul escuro": "#00008b",
    "verde agua": "#40e0d0",
    "azul": "#0000ff",
    "vermelho": "#ff0000",
    "verde": "#00ff00",
    "roxo": "#8000ff",
    "roxa": "#8000ff",
    "vermelha": "#ff0000",
    "amarela": "#ffff00",
    "branca": "#ffffff",
    "dourada": "#ffd700",
    "lilas": "#c8a2c8",
    "violeta": "#8a2be2",
    "rosa": "#ff69b4",
    "pink": "#ff1493",
    "amarelo": "#ffff00",
    "laranja": "#ff8000",
    "branco": "#ffffff",
    "ciano": "#00ffff",
    "magenta": "#ff00ff",
    "dourado": "#ffd700",
    "turquesa": "#40e0d0",
}
_DETAILS = {
    "placa de video": "gpu",
    "placa": "gpu",
    "video": "gpu",
    "gpu": "gpu",
    "cpu": "cpu",
    "processador": "cpu",
    "memoria": "memory",
    "ram": "memory",
}

_UNITS = {
    "zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5,
    "seis": 6, "sete": 7, "oito": 8, "nove": 9, "dez": 10, "onze": 11, "doze": 12, "treze": 13,
    "catorze": 14, "quatorze": 14, "quinze": 15, "dezesseis": 16, "dezessete": 17, "dezoito": 18,
    "dezenove": 19,
}  # fmt: skip
_TENS = {
    "vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50, "sessenta": 60, "setenta": 70,
    "oitenta": 80, "noventa": 90,
}  # fmt: skip
_HUNDREDS = {
    "cem": 100, "cento": 100, "duzentos": 200, "trezentos": 300, "quatrocentos": 400,
    "quinhentos": 500,
}  # fmt: skip
_SPECIAL_NUMBERS = {"maximo": 100, "talo": 100, "metade": 50, "minimo": 0}

PH_NUM, PH_COLOR, PH_DETAIL = "#num", "#cor", "#det"
_NUM_SLOTS = {SlotName.VOLUME, SlotName.BRIGHTNESS, SlotName.AMOUNT}
_PLACEHOLDER = {SlotName.COLOR: PH_COLOR, SlotName.DETAIL: PH_DETAIL} | dict.fromkeys(_NUM_SLOTS, PH_NUM)
_FREE_SLOTS = {SlotName.GAME, SlotName.QUERY, SlotName.TEXT, SlotName.FRANCHISE}
_TAIL_LEAD = FILLERS | {"jogo", "musica", "som"}
#: Sobra no fim do rabo que não é nome ("uma só da Willow então", "Linkin Park por favor").
_TAIL_END = FILLERS | {"entao", "hein", "mesmo", "por", "favor", "tambem", "ai"}

_EXTRA_PEN, _LIGHT_PEN, _MISSING_PEN, _QUESTION_PEN = 7.0, 2.0, 15.0, 25.0
_FREE_MISSING_PEN = 25.0  # num slot livre o rabo engole qualquer coisa: faltar palavra pesa mais
_VAGUE_PEN, _UNKNOWN_GAME_PEN = 20.0, 5.0
_VAGUE_TAIL = frozenset("isso isto em se pra para na no nele nela".split())
#: Busca de música cujo rabo fala de outra coisa ("coloca o HUD em modo ocioso", "o LED do PC")
#: ou é comprida demais para nome de música/artista vai ao agente.
_OFF_MUSIC = frozenset(
    "hud tela ocioso ociosidade led leds luz luzes rgb brilho volume painel pc computador".split()
)
_OFF_MUSIC_PEN = 40.0
_LONG_QUERY_WORDS = 6


# ---------------------------------------------------------------------------
# Normalização


def normalize_text(text: str) -> list[str]:
    """Palavras em minúsculas, sem acento nem pontuação (números ficam como foram ditos)."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    text = text.replace("'", "").replace("’", "")
    text = " ".join(re.findall(r"[a-z0-9]+", text))
    for phrase, repl in _PHRASE_FILLERS:
        text = re.sub(rf"\b{phrase}\b", repl, text)
    return text.split()


def _lemmas(words: Iterable[str]) -> list[str]:
    return [LEMMA.get(w, w) for w in words]


def parse_number(words: Sequence[str], i: int) -> tuple[int, int] | None:
    """Número em ``words[i:]`` (dígitos ou por extenso) → ``(valor, fim)``; ``None`` se não há.

    "um"/"uma" sozinhos não contam (são artigos na maioria das frases).
    """
    w = words[i]
    if w.isdigit():
        return int(w), i + 1
    if w in _SPECIAL_NUMBERS:
        return _SPECIAL_NUMBERS[w], i + 1
    total, j, parts = 0, i, 0
    while j < len(words):
        cur = words[j]
        val = _HUNDREDS.get(cur, _TENS.get(cur, _UNITS.get(cur)))
        if val is None or (cur in ("um", "uma") and parts == 0):
            break
        total += val
        parts += 1
        j += 1
        if (
            j + 1 < len(words)
            and words[j] == "e"
            and (words[j + 1] in _UNITS or words[j + 1] in _TENS or words[j + 1] in _HUNDREDS)
        ):
            j += 1
        else:
            break
    return (total, j) if parts else None


@dataclass(frozen=True, slots=True)
class _Found:
    """Slot fixo achado no texto: marcador, valor canônico, trecho falado."""

    placeholder: str
    value: str
    raw: str


def _match_phrase(words: Sequence[str], i: int, table: Mapping[str, str]) -> tuple[str, str, int] | None:
    for key, value in table.items():  # tabelas em ordem: chaves de várias palavras primeiro
        parts = key.split()
        if tuple(words[i : i + len(parts)]) == tuple(parts):
            return key, value, i + len(parts)
    return None


def _extract_fixed(words: Sequence[str]) -> tuple[list[str], list[_Found]]:
    """Troca número, cor e painel por marcadores; devolve palavras e o que achou, em ordem."""
    out: list[str] = []
    found: list[_Found] = []
    i = 0
    while i < len(words):
        num = parse_number(words, i)
        if num is not None:
            value, end = num
            found.append(_Found(PH_NUM, str(value), " ".join(words[i:end])))
            out.append(PH_NUM)
            i = end
            continue
        hit = _match_phrase(words, i, COLORS)
        if hit is not None:
            found.append(_Found(PH_COLOR, hit[1], hit[0]))
            out.append(PH_COLOR)
            i = hit[2]
            continue
        hit = _match_phrase(words, i, _DETAILS)
        if hit is not None:
            found.append(_Found(PH_DETAIL, hit[1], hit[0]))
            out.append(PH_DETAIL)
            i = hit[2]
            continue
        out.append(words[i])
        i += 1
    return out, found


# ---------------------------------------------------------------------------
# Nota


@lru_cache(maxsize=4096)
def _same(a: str, b: str) -> bool:
    if a == b:
        return True
    if a.startswith("#") or b.startswith("#") or min(len(a), len(b)) < 4:
        return False
    return fuzz.ratio(a, b) >= 75


def _score(text: Sequence[str], tpl: Sequence[str], missing_pen: float = _MISSING_PEN) -> float:
    """``token_set_ratio`` menos penalidades: palavra sobrando, faltando e pergunta (§4.2).

    Palavra sobrando pesa mais em frase-modelo curta ("manda" ≠ "manda uma mensagem pro João").
    """
    if not text or not tpl:
        return 0.0
    base = fuzz.token_set_ratio(" ".join(text), " ".join(tpl))
    extra = _EXTRA_PEN * max(1.0, 2.5 / len(tpl))
    pen = 0.0
    for w in text:
        if not any(_same(w, p) for p in tpl):
            pen += _LIGHT_PEN if w in LIGHT else extra
    for p in tpl:
        if not any(_same(p, w) for w in text):
            pen += missing_pen
    first = "que" if text[0] == "por" and len(text) > 1 and text[1] == "que" else text[0]
    if first in QUESTION_START and first not in tpl:
        pen += _QUESTION_PEN
    return max(0.0, base - pen)


def _core(words: Iterable[str]) -> list[str]:
    return [w for w in words if w not in FILLERS]


# ---------------------------------------------------------------------------
# intents.yaml

_SLOT_RE = re.compile(r"\{(\w+)(?::([+-]))?\}")


@dataclass(frozen=True, slots=True)
class _Template:
    words: tuple[str, ...]  # canônicas, sem enchimento, slots fixos como marcadores
    fixed: tuple[tuple[str, str], ...]  # (slot, sinal) na ordem dos marcadores
    free: str | None  # slot livre no fim da frase
    consts: tuple[tuple[str, str], ...]
    label: str | None


@dataclass(frozen=True, slots=True)
class IntentSpec:
    """Uma intenção do ``intents.yaml``."""

    id: str
    templates: tuple[_Template, ...]
    danger: bool = False
    reply: str | None = None
    label: str = ""
    required: frozenset[str] = frozenset()


def _parse_template(say: str, consts: Mapping[str, Any], label: str | None, where: str) -> _Template:
    slots: list[tuple[str, str]] = []

    def mark(m: re.Match[str]) -> str:
        slots.append((m.group(1), m.group(2) or ""))
        return f" qqslot{len(slots) - 1} "

    words = _lemmas(normalize_text(_SLOT_RE.sub(mark, say)))
    fixed: list[tuple[str, str]] = []
    free: str | None = None
    out: list[str] = []
    for k, w in enumerate(words):
        if not w.startswith("qqslot"):
            out.append(w)
            continue
        name, sign = slots[int(w[6:])]
        if name in _FREE_SLOTS:
            if k != len(words) - 1:
                raise ValueError(f"{where}: slot livre {{{name}}} precisa estar no fim: {say!r}")
            free = name
        elif name in _PLACEHOLDER:
            out.append(_PLACEHOLDER[SlotName(name)])
            fixed.append((name, sign))
        else:
            raise ValueError(f"{where}: slot desconhecido {name!r}")
    return _Template(
        words=tuple(_core(out)),
        fixed=tuple(fixed),
        free=free,
        consts=tuple((str(k), str(v)) for k, v in consts.items()),
        label=label,
    )


def load_intents(path: Path | str = INTENTS_PATH, *, strict: bool = True) -> list[IntentSpec]:
    """Lê o ``intents.yaml``. ``strict``: ids e slots precisam existir em ``contracts``."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    valid_ids = {i.value for i in IntentId}
    valid_slots = {s.value for s in SlotName}
    specs: list[IntentSpec] = []
    for item in data.get("intents", []):
        iid = str(item["id"])
        if strict and iid not in valid_ids:
            raise ValueError(f"intents.yaml: id fora de IntentId: {iid!r}")
        templates = []
        for k, phrase in enumerate(item.get("phrases", [])):
            where = f"{iid}[{k}]"
            if isinstance(phrase, str):
                tpl = _parse_template(phrase, {}, None, where)
            else:
                tpl = _parse_template(phrase["say"], phrase.get("slots", {}), phrase.get("label"), where)
            names = [n for n, _ in tpl.fixed] + [n for n, _ in tpl.consts] + ([tpl.free] if tpl.free else [])
            if strict and (bad := set(names) - valid_slots):
                raise ValueError(f"intents.yaml: slot fora de SlotName em {where}: {bad}")
            templates.append(tpl)
        specs.append(
            IntentSpec(
                id=iid,
                templates=tuple(templates),
                danger=bool(item.get("danger", False)),
                reply=item.get("reply"),
                label=str(item.get("label", iid)),
                required=frozenset(item.get("required", ())),
            )
        )
    return specs


# ---------------------------------------------------------------------------
# Roteador


@dataclass(frozen=True, slots=True)
class _Candidate:
    score: float
    fixed: bool  # frase sem slot livre ganha empate
    spec: IntentSpec
    slots: tuple[Slot, ...]
    label: str


class _Fmt(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return ""


class LocalRouter:
    """Implementa ``contracts.Router`` (R4, §4.2).

    ``catalog``: jogos para o slot ``game`` (sem catálogo o slot sai com ``value=""``).
    ``intents``: specs já carregadas ou caminho do YAML. Limiares ajustáveis (config, §4.2).
    """

    def __init__(
        self,
        catalog: GameCatalog | None = None,
        intents: Sequence[IntentSpec] | Path | str | None = None,
        *,
        execute_score: float = ROUTER_EXECUTE_SCORE,
        ask_score: float = ROUTER_ASK_SCORE,
    ) -> None:
        if intents is None or isinstance(intents, (str, Path)):
            intents = load_intents(intents or INTENTS_PATH)
        self.intents: list[IntentSpec] = list(intents)
        self.catalog = catalog
        self.execute_score = execute_score
        self.ask_score = ask_score

    # -- Router -----------------------------------------------------------

    def route(self, text: str, ctx: TurnContext | None = None) -> RouteResult:
        best = self.best(text)
        if best is None or best.score < self.ask_score:
            return RouteResult(RouteKind.AGENT, text, best.score if best else 0.0)
        intent = Intent(id=best.spec.id, slots=best.slots, danger=best.spec.danger, reply=best.spec.reply)
        if best.score >= self.execute_score:
            return RouteResult(RouteKind.LOCAL, text, best.score, intent)
        return RouteResult(
            RouteKind.ASK, text, best.score, intent, suggestion=f"Você quis dizer {best.label}?"
        )

    # -- nota -------------------------------------------------------------

    def best(self, text: str) -> _Candidate | None:
        """Melhor candidato (intenção + slots + nota), ou ``None`` se o texto é vazio."""
        raw = normalize_text(text)
        if not raw:
            return None
        lem = _lemmas(raw)
        marked, found = _extract_fixed(lem)
        core = _core(marked)
        best: _Candidate | None = None
        for spec in self.intents:
            for tpl in spec.templates:
                if tpl.free is None:
                    cand = self._fixed(spec, tpl, core, found)
                else:
                    cand = self._free(spec, tpl, raw, lem)
                if cand is not None and (best is None or (cand.score, cand.fixed) > (best.score, best.fixed)):
                    best = cand
        return best

    def _fixed(
        self, spec: IntentSpec, tpl: _Template, core: list[str], found: list[_Found]
    ) -> _Candidate | None:
        score = _score(core, tpl.words)
        if score <= 0:
            return None
        slots: list[Slot] = []
        pool = list(found)
        for name, sign in tpl.fixed:
            ph = _PLACEHOLDER[SlotName(name)]
            hit = next((f for f in pool if f.placeholder == ph), None)
            if hit is None:
                return None
            pool.remove(hit)
            value = hit.value
            if name in (SlotName.VOLUME, SlotName.BRIGHTNESS):
                value = f"{sign}{min(int(value), 100)}"
            slots.append(Slot(name=name, value=value, raw=hit.raw, display=hit.raw))
        slots += [Slot(name=n, value=v) for n, v in tpl.consts]
        return _Candidate(score, True, spec, tuple(slots), self._label(spec, tpl, slots))

    def _free(self, spec: IntentSpec, tpl: _Template, raw: list[str], lem: list[str]) -> _Candidate | None:
        best: tuple[float, int] | None = None
        for i in range(1, len(lem)):
            head = _core(lem[:i])
            if not head or not _core(lem[i:]):
                continue
            s = _score(head, tpl.words, missing_pen=_FREE_MISSING_PEN)
            if best is None or s >= best[0]:
                best = (s, i)
        if best is None or best[0] <= 0:
            return None
        score, i = best
        k = next(j for j in range(i) if lem[j] not in FILLERS) + 1  # depois do verbo
        if tpl.free != SlotName.GAME and any(w in _VAGUE_TAIL for w in raw[k : i + 1]):
            score -= _VAGUE_PEN  # "coloca isso na agenda", "toca em algum assunto"
        if score < self.execute_score and any(w in QUESTION_START for w in raw[i:]):
            score -= _QUESTION_PEN  # comando incompleto + pergunta no rabo = conversa
        tail = list(raw[i:])
        while tail and tail[0] in _TAIL_LEAD:
            tail.pop(0)
        while tail and tail[-1] in _TAIL_END:
            tail.pop()
        if not tail:
            return None
        phrase = " ".join(tail)
        assert tpl.free is not None
        if tpl.free == SlotName.GAME:
            slot, score = self._game(phrase, score, required=SlotName.GAME in spec.required)
            if slot is None:
                return None
        else:
            if tpl.free == SlotName.QUERY and (set(tail) & _OFF_MUSIC or len(tail) > _LONG_QUERY_WORDS):
                score -= _OFF_MUSIC_PEN
            slot = Slot(name=tpl.free, value=phrase, raw=phrase, display=phrase)
        slots = [slot, *(Slot(name=n, value=v) for n, v in tpl.consts)]
        return _Candidate(score, False, spec, tuple(slots), self._label(spec, tpl, slots))

    def _game(self, phrase: str, score: float, *, required: bool) -> tuple[Slot | None, float]:
        """Resolve o jogo no catálogo (R4.4). Não achado: obrigatório sai vazio (a ação sugere)."""
        hits = self.catalog.find(phrase, limit=1) if self.catalog is not None else []
        if hits and hits[0][1] >= self.ask_score:
            game, gs = hits[0]
            return Slot(SlotName.GAME, str(game.appid), raw=phrase, display=game.name, score=gs), min(
                score, gs
            )
        if not required:
            return None, 0.0
        gs = hits[0][1] if hits else 0.0
        words = phrase.split()
        # nome desconhecido curto ("abre o minecraft") executa e a ação sugere (R5.2);
        # rabo comprido ou com pergunta é conversa
        pen = _UNKNOWN_GAME_PEN * (len(words) - 1) + _QUESTION_PEN * any(w in QUESTION_START for w in words)
        slot = Slot(SlotName.GAME, "", raw=phrase, display=phrase, score=gs)
        return slot, min(score, self.execute_score) - pen

    @staticmethod
    def _label(spec: IntentSpec, tpl: _Template, slots: Iterable[Slot]) -> str:
        fmt = _Fmt({s.name: s.display or s.value for s in slots})
        return (tpl.label or spec.label).format_map(fmt).strip()
