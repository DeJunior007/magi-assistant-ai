"""Anti-spoiler: como mostrar uma notícia classificada (tarefa 6.9, R19.1-R19.3).

Entrada: ``NewsItem.spoiler`` gravado pela classificação (6.7) — ``{"has", "of", "safe_title",
"size"}`` — e o progresso do usuário (6.8, tabela ``progress``: ``episode`` da AniList,
``hours`` da Steam). Saída: :class:`Shown`, a **única** coisa que o núcleo/HUD devem exibir.

Modos (:class:`Display`):

- ``ORIGINAL``: sem spoiler; ou spoiler liberado por voz; ou obra largada (não acompanhada,
  R19.2); ou episódio do spoiler já visto (``of`` cita "ep. N" e o progresso ``episode`` ≥ N —
  é assim que uma obra concluída na AniList libera, porque 6.8 grava o total de episódios).
- ``SAFE``: manchete segura; resumo vazio; links reduzidos à origem (``https://site/``), porque
  o slug costuma repetir a manchete original.
- ``HIDDEN``: "Tem notícia de X com spoiler", sem resumo nem links.

Regra de ouro: na dúvida, esconde. Vão para ``HIDDEN``: item não classificado, ``of`` vazio
ou sem nome de obra, progresso desconhecido (nenhuma linha em ``progress`` com o nome exato
da obra do spoiler), ``size`` ≥ :data:`BIG`, manchete segura vazia ou igual à original.
Jogos (só horas) nunca liberam por progresso: horas não dizem onde o spoiler está.

O spoiler é da obra citada em ``of`` ("Silksong, final"), não de ``item.franchise``: liberar
"Hollow Knight" não libera spoiler de Silksong. Comparação de nomes: igualdade após normalizar
(minúsculas, sem acento, só letras e dígitos) — nunca "contém", para não confundir obras
relacionadas.

Liberação por voz ("pode dar spoiler de X", :func:`parse_release`): por obra, gravada em
``franchise_prefs.spoilers_ok`` (contrato ``FranchisePref``). R19.3 não fixa validade, então o
padrão é sem prazo (até :func:`revoke_spoilers`); "por N dias/horas" ou "hoje" põe prazo, que
fica num arquivo de estado JSON (:class:`ReleaseStore`, padrão
``$XDG_STATE_HOME/magi/spoiler_releases.json``: ``{"<obra normalizada>": "<ISO>"}``), porque a
tabela não tem coluna de prazo. Prazo vencido: :func:`load_context` desliga ``spoilers_ok``.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path
from urllib.parse import urlsplit

from magi.common.contracts import FranchisePref, NewsItem, NewsRepo, Progress

BIG = 0.8  # tamanho a partir do qual o spoiler some em vez de virar manchete segura
KIND_EPISODE = "episode"

_EP_RE = re.compile(r"\b(?:ep\.?|epis[oó]dio|episode)\s*(\d+)", re.IGNORECASE)
_OTHER_UNIT_RE = re.compile(
    r"\b(?:mang[aá]|cap\.?|cap[ií]tulo|chapter|temporada|season|volume|vol\.?|filme|movie|ova)\b",
    re.IGNORECASE,
)
_WORK_SPLIT_RE = re.compile(
    r"[,;(]| [-–—] |\s(?:ep\.?|epis[oó]dio|episode|cap\.?|cap[ií]tulo|chapter|temporada|season|"
    r"mang[aá]|anime|final|volume|vol\.?)(?:\s|$)",
    re.IGNORECASE,
)


class Display(StrEnum):
    ORIGINAL = "original"
    SAFE = "safe"
    HIDDEN = "hidden"


@dataclass(frozen=True, slots=True)
class Shown:
    """O que pode ser exibido/falado. ``subtitle`` é a linha do HUD; ``reason`` é só p/ log."""

    mode: Display
    title: str
    summary: str
    subtitle: str
    links: tuple[str, ...]
    franchise: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class SpoilerContext:
    """Progresso por obra (chave normalizada), obras liberadas e largadas (normalizadas)."""

    progress: Mapping[str, Sequence[Progress]] = field(default_factory=dict)
    released: frozenset[str] = frozenset()
    dropped: frozenset[str] = frozenset()


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name.casefold())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


def spoiler_work(item: NewsItem) -> str | None:
    """Nome da obra do spoiler, tirado de ``of``; ``None`` se ambíguo."""
    of = str((item.spoiler or {}).get("of") or "").strip()
    if not of:
        return None
    name = _WORK_SPLIT_RE.split(" " + of + " ", maxsplit=1)[0].strip()
    return name if norm(name) else None


def _seen(of: str, rows: Sequence[Progress]) -> bool:
    """``True`` só se ``of`` cita um episódio (e nada de mangá/temporada) já visto."""
    m = _EP_RE.search(of)
    if m is None or _OTHER_UNIT_RE.search(of):
        return False
    return any(p.kind == KIND_EPISODE and p.value >= int(m.group(1)) for p in rows)


def origin(url: str) -> str | None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}/"


def _hidden(item: NewsItem, work: str | None, reason: str) -> Shown:
    name = item.franchise or work or "uma obra"
    text = f"Tem notícia de {name} com spoiler"
    return Shown(Display.HIDDEN, text, "", text, (), item.franchise, reason)


def decide(item: NewsItem, ctx: SpoilerContext, links: Sequence[str] = ()) -> Shown:
    """Decide como mostrar ``item``. ``links``: URLs das fontes (tratadas conforme o modo)."""
    sp = item.spoiler
    if not sp or "has" not in sp:
        return _hidden(item, None, "não classificado")
    if not sp.get("has"):
        return Shown(Display.ORIGINAL, item.title, item.summary, item.title, tuple(links),
                     item.franchise, "sem spoiler")
    work = spoiler_work(item)
    if work is None:
        return _hidden(item, None, "obra do spoiler ambígua")
    key = norm(work)

    def original(reason: str) -> Shown:
        return Shown(Display.ORIGINAL, item.title, item.summary, item.title, tuple(links),
                     item.franchise, reason)

    if key in ctx.released:
        return original("liberado por voz")
    if key in ctx.dropped:
        return original("obra largada")
    rows = ctx.progress.get(key) or ()
    if not rows:
        return _hidden(item, work, "progresso desconhecido")
    if _seen(str(sp.get("of")), rows):
        return original("trecho já visto")
    try:
        size = float(sp.get("size", 1.0))
    except (TypeError, ValueError):
        size = 1.0
    if size >= BIG:
        return _hidden(item, work, "spoiler grande")
    safe = str(sp.get("safe_title") or "").strip()
    if not safe or norm(safe) == norm(item.title):
        return _hidden(item, work, "sem manchete segura")
    safe_links = tuple(dict.fromkeys(o for o in map(origin, links) if o))
    return Shown(Display.SAFE, safe, "", safe, safe_links, item.franchise, "em andamento")


# --- liberação por voz -----------------------------------------------------------------------


def default_state_path() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "magi" / "spoiler_releases.json"


class ReleaseStore:
    """Prazos das liberações: ``{obra normalizada: ISO}``. Arquivo ausente/corrompido = vazio."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_state_path()

    def load(self) -> dict[str, datetime]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return {str(k): datetime.fromisoformat(v) for k, v in raw.items()}
        except (OSError, ValueError, TypeError, AttributeError):
            return {}

    def save(self, data: Mapping[str, datetime]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({k: v.isoformat() for k, v in data.items()}), encoding="utf-8")
        tmp.replace(self.path)

    def set(self, key: str, until: datetime | None) -> None:
        data = self.load()
        if until is None:
            data.pop(key, None)
        else:
            data[key] = until
        self.save(data)


_RELEASE_RE = re.compile(
    r"pode(?:s)?\s+(?:me\s+)?(?:dar|liberar|soltar)\s+spoilers?\s+(?:de|do|da|dos|das)\s+(?P<rest>.+)",
    re.IGNORECASE,
)
_TTL_RE = re.compile(
    r"\s+(?:(?:por|durante)\s+(?P<n>\d+|um|uma)\s+(?P<unit>horas?|dias?|semanas?)|(?P<hoje>hoje))\s*$",
    re.IGNORECASE,
)


def parse_release(text: str) -> tuple[str, timedelta | None] | None:
    """"pode dar spoiler de Frieren por 2 dias" → ``("Frieren", 2 dias)``; sem prazo → ``None``."""
    m = _RELEASE_RE.search(text.strip().rstrip(".!?"))
    if m is None:
        return None
    rest, ttl = m.group("rest").strip(), None
    t = _TTL_RE.search(rest)
    if t is not None:
        rest = rest[: t.start()].strip()
        if t.group("hoje"):
            ttl = timedelta(hours=24)
        else:
            n = 1 if t.group("n").lower() in ("um", "uma") else int(t.group("n"))
            unit = t.group("unit").lower()
            ttl = (timedelta(hours=n) if unit.startswith("hora")
                   else timedelta(weeks=n) if unit.startswith("semana") else timedelta(days=n))
    return (rest, ttl) if norm(rest) else None


async def _pref(repo: NewsRepo, work: str) -> FranchisePref:
    key = norm(work)
    for p in await repo.franchise_prefs():
        if norm(p.franchise) == key:
            return p
    return FranchisePref(work)


async def allow_spoilers(
    repo: NewsRepo, work: str, now: datetime, *, ttl: timedelta | None = None,
    store: ReleaseStore | None = None,
) -> FranchisePref:
    """Libera spoilers só de ``work`` (R19.3); ``ttl`` ``None`` = sem prazo."""
    pref = replace(await _pref(repo, work), spoilers_ok=True)
    await repo.set_franchise_pref(pref)
    (store or ReleaseStore()).set(norm(work), now + ttl if ttl is not None else None)
    return pref


async def revoke_spoilers(repo: NewsRepo, work: str, *, store: ReleaseStore | None = None) -> None:
    pref = await _pref(repo, work)
    if pref.spoilers_ok:
        await repo.set_franchise_pref(replace(pref, spoilers_ok=False))
    (store or ReleaseStore()).set(norm(work), None)


async def load_context(
    repo: NewsRepo, items: Iterable[NewsItem], now: datetime, *, store: ReleaseStore | None = None,
) -> SpoilerContext:
    """Monta o contexto para ``items``; desliga liberações vencidas."""
    store = store or ReleaseStore()
    expiry = store.load()
    released: set[str] = set()
    dropped: set[str] = set()
    for p in await repo.franchise_prefs():
        key = norm(p.franchise)
        if p.dropped:
            dropped.add(key)
        if not p.spoilers_ok:
            continue
        until = expiry.get(key)
        if until is not None and until <= now:
            await repo.set_franchise_pref(replace(p, spoilers_ok=False))
            store.set(key, None)
        else:
            released.add(key)
    progress: dict[str, Sequence[Progress]] = {}
    for item in items:
        work = spoiler_work(item)
        if work is not None and norm(work) not in progress:
            progress[norm(work)] = await repo.progress(work)
    return SpoilerContext(progress, frozenset(released), frozenset(dropped))


async def present(
    repo: NewsRepo, items: Sequence[NewsItem], now: datetime, *,
    links: Mapping[int, Sequence[str]] | None = None, store: ReleaseStore | None = None,
) -> list[Shown]:
    """Atalho: contexto + :func:`decide` para cada item (``links`` por ``item.id``)."""
    ctx = await load_context(repo, items, now, store=store)
    links = links or {}
    return [decide(i, ctx, links.get(i.id, ()) if i.id is not None else ()) for i in items]
