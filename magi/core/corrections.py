"""Correções de transcrição (tarefa 1.6, §4.1 ``corrections``, R3.3-R3.4).

- ``Corrections``: implementa ``Corrector``. Aplica os pares ouvido→certo ao texto transcrito
  antes do roteador: substituição por palavras inteiras, sem acento nem caixa; em frases curtas
  (≤ ``short_max_words`` palavras) também casa por aproximação (rapidfuzz, limiar alto). Cada par
  usado incrementa ``uses``. Guarda as últimas transcrições para o "não, eu falei X".
- ``CorrectionHandler``: ``ActionHandler`` de ``correction.fix``. Compara o texto do turno
  anterior com o X, deduz o trecho ouvido errado, salva o par e refaz o turno com o texto
  corrigido via ``redo`` (normalmente ``TurnPipeline.respond``), confirmando com "Anotado.".

Ligação no núcleo (o turno é sem estado e o ``ActionResult`` não tem "refazer turno")::

    corrections = Corrections(repo)
    fix = CorrectionHandler(corrections)
    pipeline = TurnPipeline(TurnDeps(corrector=corrections, actions=Registry([fix, ...]), ...))
    fix.redo = pipeline.respond
"""

from __future__ import annotations

import dataclasses
import difflib
import logging
import re
import unicodedata
from collections import deque
from collections.abc import Awaitable, Callable

from rapidfuzz import fuzz

from magi.common.contracts import (
    ActionHandler,
    ActionRequest,
    ActionResult,
    Correction,
    CorrectionsRepo,
    Expression,
    IntentId,
    SlotName,
    Transcript,
    TurnContext,
)

log = logging.getLogger(__name__)

SAY_SAVED = "Anotado."
SAY_NOTHING_TO_FIX = "Não tenho o que corrigir agora."
SAY_WHAT = "Falou o quê? Repete a frase certa."
SAY_SAME = "Foi isso mesmo que eu entendi."

#: "não, eu falei X" / "eu disse X" quando o roteador não manda o slot ``text``.
_FIX_RE = re.compile(r"^\W*(?:n[aã]o\W+)?(?:eu\s+)?(?:falei|disse)\W+(?P<x>.+)$", re.IGNORECASE)
_WORD_RE = re.compile(r"\w+")

Redo = Callable[[Transcript, TurnContext], Awaitable[ActionResult]]


def fold(text: str) -> str:
    """Minúsculas e sem acento (ex.: "Não" → "nao")."""
    text = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in text if not unicodedata.combining(c))


def _words(text: str) -> list[re.Match[str]]:
    return list(_WORD_RE.finditer(text))


def _fwords(text: str) -> list[str]:
    return [fold(m.group()) for m in _words(text)]


class Corrections:
    """Implementação de ``Corrector`` sobre um ``CorrectionsRepo``.

    Os pares ficam em cache (carregados no primeiro uso; ``reload()`` relê). Falha do banco não
    derruba o turno: o texto segue sem correção.
    """

    def __init__(
        self,
        repo: CorrectionsRepo,
        *,
        fuzzy_threshold: float = 90.0,
        short_max_words: int = 4,
        fuzzy_min_chars: int = 4,
    ) -> None:
        self.repo = repo
        self.fuzzy_threshold = fuzzy_threshold
        self.short_max_words = short_max_words
        self.fuzzy_min_chars = fuzzy_min_chars
        self._items: list[Correction] | None = None
        self._history: deque[Transcript] = deque(maxlen=4)

    async def reload(self) -> list[Correction]:
        try:
            self._items = await self.repo.all()
        except Exception:
            log.exception("não consegui ler as correções")
            self._items = []
        return self._items

    async def _load(self) -> list[Correction]:
        return self._items if self._items is not None else await self.reload()

    # --- Corrector ---------------------------------------------------------------------------

    async def apply(self, transcript: Transcript) -> Transcript:
        items = await self._load()
        text, used = self.correct_text(transcript.final, items)
        for c in used:
            await self._bump(c)
        if text != transcript.final:
            transcript = transcript.with_final(text)
        self._history.append(transcript)
        return transcript

    def correct_text(self, text: str, items: list[Correction]) -> tuple[str, list[Correction]]:
        """Texto com os pares aplicados e a lista dos pares usados (sem I/O)."""
        tokens = _words(text)
        folded = [fold(m.group()) for m in tokens]
        taken = [False] * len(tokens)
        hits: list[tuple[int, int, Correction]] = []
        pairs = [(c, _fwords(c.heard)) for c in items]
        pairs = sorted((p for p in pairs if p[1]), key=lambda p: -len(p[1]))

        def free(i: int, k: int) -> bool:
            return not any(taken[i : i + k])

        def take(i: int, k: int, c: Correction) -> None:
            taken[i : i + k] = [True] * k
            hits.append((i, i + k, c))

        for c, h in pairs:  # 1) exato por palavras inteiras, maiores primeiro
            k = len(h)
            if h == _fwords(c.correct):  # par que só muda caixa/acento não é aplicado
                continue
            for i in range(len(tokens) - k + 1):
                if free(i, k) and folded[i : i + k] == h:
                    take(i, k, c)

        if len(tokens) <= self.short_max_words:  # 2) aproximado só em frases curtas
            for c, h in pairs:
                target, k = " ".join(h), len(h)
                if len(target) < self.fuzzy_min_chars:
                    continue
                best: tuple[float, int] | None = None
                for i in range(len(tokens) - k + 1):
                    window = " ".join(folded[i : i + k])
                    if not free(i, k) or window == " ".join(_fwords(c.correct)):
                        continue
                    score = fuzz.ratio(window, target)
                    if score >= self.fuzzy_threshold and (best is None or score > best[0]):
                        best = (score, i)
                if best is not None:
                    take(best[1], k, c)

        if not hits:
            return text, []
        out: list[str] = []
        pos = 0
        for start, end, c in sorted(hits, key=lambda h: h[0]):
            out.append(text[pos : tokens[start].start()])
            out.append(c.correct)
            pos = tokens[end - 1].end()
        out.append(text[pos:])
        used = list({id(c): c for _, _, c in hits}.values())
        return "".join(out), used

    async def _bump(self, c: Correction) -> None:
        if c.id is None:
            return
        try:
            await self.repo.bump(c.id)
        except Exception:
            log.exception("não consegui contar o uso da correção %s", c.id)
            return
        if self._items is not None:
            self._items = [dataclasses.replace(x, uses=x.uses + 1) if x is c else x for x in self._items]

    # --- apoio ao "não, eu falei X" ----------------------------------------------------------

    def previous(self) -> Transcript | None:
        """Transcrição do turno anterior ao atual (a atual é o próprio "não, eu falei X")."""
        return self._history[-2] if len(self._history) >= 2 else None

    def replace_last(self, transcript: Transcript) -> None:
        """Troca a fala de correção pelo texto corrigido, para uma nova correção valer sobre ele."""
        if self._history:
            self._history.pop()
            if self._history:
                self._history.pop()
        self._history.append(transcript)

    async def learn(self, heard: str, correct: str) -> Correction:
        """Salva o par e atualiza o cache."""
        saved = await self.repo.add(heard, correct)
        items = [c for c in await self._load() if fold(c.heard) != fold(saved.heard)]
        self._items = [*items, saved]
        return saved


def deduce_pair(previous: str, said: str) -> tuple[str, str, str] | None:
    """(ouvido, certo, texto corrigido) a partir do texto anterior e do X; ``None`` se iguais.

    Palavras em comum fixam o alinhamento: o par é o trecho que difere, e o contexto que o X
    omitiu (palavras só do texto anterior nas pontas) fica de fora do par e entra no texto
    corrigido. Sem nenhuma palavra em comum, o X é um fragmento: o par é a janela do texto
    anterior mais parecida com ele.
    """
    pw, sw = _words(previous), _words(said)
    pf, sf = [fold(m.group()) for m in pw], [fold(m.group()) for m in sw]
    if not pw or not sw:
        return None
    ops = difflib.SequenceMatcher(a=pf, b=sf, autojunk=False).get_opcodes()
    if any(op[0] == "equal" for op in ops):
        while ops and ops[0][0] in ("equal", "delete"):
            ops.pop(0)
        while ops and ops[-1][0] in ("equal", "delete"):
            ops.pop()
        if not ops:
            return None
        i1, j1, i2, j2 = ops[0][1], ops[0][3], ops[-1][2], ops[-1][4]
    else:
        k = len(sw)
        target = " ".join(sf)
        best = (-1.0, 0, 0)
        for size in {max(1, k - 1), k, k + 1}:
            for i in range(len(pw) - size + 1):
                score = fuzz.ratio(" ".join(pf[i : i + size]), target)
                if score > best[0]:
                    best = (score, i, i + size)
        if best[0] < 0:  # X maior que o texto anterior todo
            best = (0.0, 0, len(pw))
        _, i1, i2 = best
        j1, j2 = 0, len(sw)
    correct = said[sw[j1].start() : sw[j2 - 1].end()] if j2 > j1 else ""
    if i2 > i1:
        start, end = pw[i1].start(), pw[i2 - 1].end()
    else:  # inserção pura: ancora na palavra anterior
        anchor = max(i1 - 1, 0)
        start, end = pw[anchor].start(), pw[anchor].end()
        word = previous[start:end]
        correct = f"{word} {correct}" if i1 > 0 else f"{correct} {word}"
    heard = previous[start:end]
    if not correct or fold(heard) == fold(correct):
        return None
    fixed = previous[:start] + correct + previous[end:]
    return heard.casefold(), correct, fixed


class CorrectionHandler:
    """``ActionHandler`` de ``correction.fix`` ("não, eu falei X", R3.3).

    Texto anterior: ``req.args["previous_text"]`` se o núcleo mandar; senão a transcrição
    anterior guardada por ``Corrections``. O X vem do slot ``text`` (``value`` ou ``raw``) ou,
    na falta, do próprio ``req.text``. Sem ``redo`` só salva e confirma, com o texto corrigido
    em ``full_text``.
    """

    intents = frozenset({IntentId.CORRECTION.value})

    def __init__(self, corrections: Corrections, redo: Redo | None = None) -> None:
        self.corrections = corrections
        self.redo = redo
        self._redoing = False

    async def run(self, req: ActionRequest) -> ActionResult:
        said = self._said(req)
        if not said:
            return ActionResult(ok=False, speech=SAY_WHAT, expression=Expression.CONFUSED)
        prev_text = req.args.get("previous_text")
        prev = Transcript.raw(prev_text) if prev_text else self.corrections.previous()
        if prev is None or prev.is_empty or self._redoing:
            return ActionResult(ok=False, speech=SAY_NOTHING_TO_FIX, expression=Expression.CONFUSED)
        pair = deduce_pair(prev.final, said)
        if pair is None:
            return ActionResult(ok=False, speech=SAY_SAME, expression=Expression.CONFUSED)
        heard, correct, fixed = pair
        await self.corrections.learn(heard, correct)
        transcript = Transcript(heard=prev.heard, final=fixed, language=prev.language)
        self.corrections.replace_last(transcript)
        if self.redo is None:
            return ActionResult(ok=True, speech=SAY_SAVED, full_text=fixed, expression=Expression.HAPPY)
        self._redoing = True
        try:
            result = await self.redo(transcript, req.ctx)
        finally:
            self._redoing = False
        return dataclasses.replace(result, speech=f"{SAY_SAVED} {result.speech}".strip())

    @staticmethod
    def _said(req: ActionRequest) -> str:
        slot = req.intent.slot(SlotName.TEXT)
        if slot is not None and (slot.value or slot.raw).strip():
            return (slot.value or slot.raw).strip()
        m = _FIX_RE.match(req.text.strip())
        return m.group("x").strip(" .!?") if m else ""


def handlers(corrections: Corrections, redo: Redo | None = None) -> list[ActionHandler]:
    """Handlers deste módulo, no formato do ``Registry`` (``magi.core.actions``)."""
    return [CorrectionHandler(corrections, redo)]
