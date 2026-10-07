"""Idioma da fala da Condessa (``[speech] language``).

O código produz as frases em português; com outro idioma configurado, ``tr`` troca cada frase
pela tradução da tabela ``<idioma>.yaml`` desta pasta (seções ``fixed``, ``templates`` e
``values``, ver o cabeçalho do arquivo). O Pedro continua falando português: só a saída muda.

Algoritmo de ``tr``: com ``pt-br`` devolve igual. Senão tenta o texto inteiro (``fixed``, depois
``templates``); se não casar, quebra em frases (``compose.sentences``) e traduz o maior trecho de
frases seguidas que casar, da esquerda para a direita. ``{nome}`` de um template casa qualquer
trecho e volta igual, ou traduzido se estiver em ``values``. Frase sem tradução volta igual e vai
ao log uma vez. Texto que já veio em inglês (resposta do agente) simplesmente não casa.
"""

from __future__ import annotations

import dataclasses
import logging
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

from magi.common.contracts import ActionResult
from magi.core.compose import sentences

log = logging.getLogger(__name__)

DEFAULT = "pt-br"
TABLES_DIR = Path(__file__).parent
NAMES = {"pt-br": "português do Brasil", "en-gb": "inglês britânico (en-GB)"}
_PLACEHOLDER = re.compile(r"\{(\w+)\}")
MISSED_MAX = 500


@dataclass(frozen=True, slots=True)
class _Template:
    pattern: re.Pattern[str]
    target: str


@dataclass(frozen=True, slots=True)
class Table:
    """Tabela de um idioma: frases fixas, modelos com ``{nome}`` e trechos variáveis."""

    fixed: dict[str, str]
    templates: tuple[_Template, ...]
    values: dict[str, str]

    @classmethod
    def from_raw(cls, raw: dict) -> Table:
        templates = sorted(
            (raw.get("templates") or {}).items(),
            key=lambda kv: len(_PLACEHOLDER.sub("", kv[0])),
            reverse=True,  # mais texto fixo primeiro: "Tocando o álbum {name}." antes de "Tocando {track}."
        )
        return cls(
            fixed=dict(raw.get("fixed") or {}),
            templates=tuple(_Template(_compile(src), dst) for src, dst in templates),
            values=dict(raw.get("values") or {}),
        )

    def phrase(self, text: str) -> str | None:
        """Tradução de ``text`` inteiro; ``None`` = sem entrada."""
        if (hit := self.fixed.get(text)) is not None:
            return hit
        for tpl in self.templates:
            if (m := tpl.pattern.fullmatch(text)) is not None:
                groups = {k: self.values.get(v, v) for k, v in m.groupdict().items()}
                return tpl.target.format_map(groups)
        return None


def _compile(template: str) -> re.Pattern[str]:
    """Modelo ``"Abrindo {game}."`` → regex ancorada com grupos nomeados."""
    out: list[str] = []
    pos = 0
    for m in _PLACEHOLDER.finditer(template):
        out.append(re.escape(template[pos : m.start()]))
        out.append(f"(?P<{m.group(1)}>.+?)")
        pos = m.end()
    out.append(re.escape(template[pos:]))
    return re.compile("".join(out), re.S)


@cache
def load_table(lang: str) -> Table:
    path = TABLES_DIR / f"{lang}.yaml"
    return Table.from_raw(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


_language = DEFAULT
_missed: set[str] = set()


def configure(lang: str | None) -> None:
    """Escolhe o idioma da fala. Desconhecido (sem tabela) → aviso e ``pt-br``."""
    global _language
    lang = (lang or DEFAULT).strip().lower().replace("_", "-")
    if lang != DEFAULT:
        try:
            load_table(lang)
        except (OSError, yaml.YAMLError) as e:
            log.warning("idioma %r sem tabela de tradução (%s); falando em português", lang, e)
            lang = DEFAULT
    _language = lang


def language() -> str:
    return _language


_listen = "pt"


def configure_listen(listen: str | None) -> None:
    """Idioma que ela entende: "pt", "en"… ou "auto" (detecta). Padrão: "pt" falando
    português e "auto" falando outro idioma (o Pedro fala português e inglês com ela)."""
    global _listen
    _listen = (listen or ("pt" if _language == DEFAULT else "auto")).strip().lower()


def listen_language() -> str:
    return _listen


def language_name() -> str:
    """Nome do idioma para instruções a modelos ("inglês britânico (en-GB)")."""
    return NAMES.get(_language, _language)


def tr(text: str) -> str:
    """``text`` no idioma da fala (ver docstring do módulo). Linha a linha."""
    if _language == DEFAULT or not text or not text.strip():
        return text
    table = load_table(_language)
    return "\n".join(_line(table, line) for line in text.split("\n"))


def _line(table: Table, line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return line
    if (whole := table.phrase(stripped)) is not None:
        return whole
    parts = sentences(stripped)
    out: list[str] = []
    i = 0
    while i < len(parts):
        for j in range(len(parts), i, -1):  # maior trecho de frases seguidas que casar
            if j - i == len(parts):
                continue  # o texto inteiro já foi tentado
            if (hit := table.phrase(" ".join(parts[i:j]))) is not None:
                out.append(hit)
                i = j
                break
        else:
            _miss(parts[i])
            out.append(parts[i])
            i += 1
    return " ".join(out)


def _miss(sentence: str) -> None:
    if sentence in _missed:
        return
    if len(_missed) >= MISSED_MAX:  # respostas do agente são sempre novas: não cresce sem fim
        _missed.clear()
    _missed.add(sentence)
    log.info("sem tradução: %s", sentence)


def tr_result(result: ActionResult) -> ActionResult:
    """``result`` com ``speech`` e ``full_text`` traduzidos."""
    if _language == DEFAULT:
        return result
    speech = tr(result.speech)
    full = tr(result.full_text) if result.full_text else result.full_text
    if speech == result.speech and full == result.full_text:
        return result
    return dataclasses.replace(result, speech=speech, full_text=full)
