"""Espera viva: frase de espera local por tópico (specs/espera-viva, design §3).

Módulo puro, sem I/O fora do ``Catalogo.load``. O turno (``TurnMachine._think``) usa:

- ``EsperaCfg.from_raw`` — seção ``[espera]`` do ``config.toml`` (spec §5);
- ``Catalogo.load`` — ``magi/core/espera.yaml`` (tópicos → frases e moldes, spec §3.1);
- ``topico`` / ``demorado`` — tópico do pedido e se ele parece demorado (D2: só em pedido
  demorado há frase de espera, spec §3.3);
- ``Cota`` + ``escolher`` — a frase do turno ou ``None`` (R3.6);
- ``mesma_espera`` — a frase interina do modelo é só "espera vazia"? (R3.4);
- ``honesta`` — linter de honestidade (R4, spec §4).

Normalização: minúsculo, sem acento, só palavras; "prefixo de palavra" = o padrão começa numa
palavra do texto (``pesquisa`` acerta "pesquisar").
"""

from __future__ import annotations

import random
import re
import tomllib
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from magi.common.config import ConfigError

SECTION = "espera"


def _bool(raw: Mapping[str, Any], key: str, default: bool) -> bool:
    v = raw.get(key, default)
    if not isinstance(v, bool):
        raise ConfigError(f"[{SECTION}] {key}: esperado true/false, veio {v!r}")
    return v


def _int(raw: Mapping[str, Any], key: str, default: int, lo: int, hi: int) -> int:
    v = raw.get(key, default)
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise ConfigError(f"[{SECTION}] {key}: esperado inteiro em {lo}..{hi}, veio {v!r}")
    return v


@dataclass(frozen=True, slots=True)
class EsperaCfg:
    """Seção ``[espera]`` (spec §5). Seção ausente → padrões."""

    frase: bool = True  # R3: frase de espera local
    so_demorado: bool = True  # D2: frase só em pedido demorado (tópico/sinal, spec §3.3)
    frase_apos_ms: int = 700  # espera após a transcrição antes da frase
    lotes: bool = True  # R5.1–R5.4
    lotes_max: int = 3  # lotes por turno (D3)
    lotes_frases_max: int = 6  # frases faladas no turno: lotes + resposta final (D3)
    ferramentas_paralelo: bool = True  # R5.5

    @classmethod
    def from_raw(cls, raw: Mapping[str, Any] | None) -> EsperaCfg:
        """Lê a seção ``[espera]`` (o mapeamento da seção, não o config inteiro).

        Chave desconhecida ou valor inválido → ``ConfigError`` com o nome da chave.
        """
        if raw is None:
            return cls()
        if not isinstance(raw, Mapping):
            raise ConfigError(f"[{SECTION}] deve ser uma tabela, veio {type(raw).__name__}")
        known = set(cls.__dataclass_fields__)
        for key in raw:
            if key not in known:
                raise ConfigError(f"[{SECTION}] chave desconhecida: {key!r}")
        d = cls()
        cfg = cls(
            frase=_bool(raw, "frase", d.frase),
            so_demorado=_bool(raw, "so_demorado", d.so_demorado),
            frase_apos_ms=_int(raw, "frase_apos_ms", d.frase_apos_ms, 0, 10_000),
            lotes=_bool(raw, "lotes", d.lotes),
            lotes_max=_int(raw, "lotes_max", d.lotes_max, 1, 10),
            lotes_frases_max=_int(raw, "lotes_frases_max", d.lotes_frases_max, 2, 20),
            ferramentas_paralelo=_bool(raw, "ferramentas_paralelo", d.ferramentas_paralelo),
        )
        return cfg


_WORD = re.compile(r"\w+")
_SENT_END = re.compile(r"[.!?]+(?=\s+\S)")
_ELLIPSIS = re.compile(r"…|\.{2,}")


def _norm(texto: str) -> str:
    """Minúsculo, sem acento, só palavras separadas por um espaço."""
    sem = unicodedata.normalize("NFD", texto.casefold())
    sem = "".join(c for c in sem if not unicodedata.combining(c))
    return " ".join(_WORD.findall(sem))


def _tem_prefixo(norm: str, padrao: str) -> bool:
    """``padrao`` (normalizado) começa numa palavra de ``norm`` (prefixo de palavra)."""
    return re.search(r"(?<!\w)" + re.escape(padrao), norm) is not None


def _lista(raw: Any, onde: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
        raise ConfigError(f"espera.yaml {onde}: esperado lista de textos, veio {raw!r}")
    return tuple(x.strip() for x in raw if x.strip())


def _vetadas_gosto(gosto: Path | None) -> tuple[str, ...]:
    if gosto is None or not gosto.is_file():
        return ()
    try:
        raw = tomllib.loads(gosto.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise ConfigError(f"{gosto}: {e}") from e
    sec = raw.get(SECTION) or {}
    if not isinstance(sec, Mapping):
        raise ConfigError(f"{gosto} [{SECTION}] deve ser uma tabela")
    return _lista(sec.get("vetadas"), f"{gosto} [{SECTION}] vetadas")


GERAL = "geral"
JOGO_MAX = 30  # nome do jogo maior que isso → frase sem molde (spec §3.2)
CONTINUACAO_CURTA = 3  # continuação com ≤ 3 palavras não tem frase (spec §3.3)
REPETE = 2  # nenhuma das 2 últimas frases ditas (R3.6)
SEGUIDAS = 2  # 2 turnos seguidos com frase → o 3º não tem (R3.6)


@dataclass(frozen=True, slots=True)
class Topico:
    """Um tópico do catálogo (spec §3.1). ``palavras`` já normalizadas."""

    nome: str
    palavras: tuple[str, ...] = ()
    frases: tuple[str, ...] = ()
    moldes: tuple[str, ...] = ()  # com ``{jogo}``


@dataclass(frozen=True, slots=True)
class Catalogo:
    """``magi/core/espera.yaml`` (spec §3.1): tópicos em ordem, ``geral`` por último."""

    topicos: tuple[Topico, ...] = ()
    demorados: frozenset[str] = frozenset()  # D2: tópicos que contam como pedido demorado
    sinais_demora: tuple[str, ...] = ()  # D2: prefixos de palavra que indicam ferramenta/demora
    vetadas: frozenset[str] = frozenset()  # do yaml ∪ ``condessa-gosto.toml [espera] vetadas``

    @classmethod
    def load(cls, path: Path, gosto: Path | None = None) -> Catalogo:
        """Lê o catálogo e junta as vetadas do gosto (caminho injetável).

        Arquivo do catálogo ausente → catálogo vazio (nunca há frase); estrutura inválida →
        ``ConfigError``. ``vetadas`` guardadas normalizadas.
        """
        if not path.is_file():
            return cls(vetadas=frozenset(_norm(v) for v in _vetadas_gosto(gosto)))
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as e:
            raise ConfigError(f"{path}: {e}") from e
        if not isinstance(raw, Mapping):
            raise ConfigError(f"{path}: esperado um mapeamento")
        tops_raw = raw.get("topicos") or {}
        if not isinstance(tops_raw, Mapping):
            raise ConfigError(f"{path} topicos: esperado um mapeamento")
        topicos: list[Topico] = []
        for nome, t in tops_raw.items():
            if not isinstance(t, Mapping):
                raise ConfigError(f"{path} topicos.{nome}: esperado um mapeamento")
            topicos.append(
                Topico(
                    nome=str(nome),
                    palavras=tuple(_norm(p) for p in _lista(t.get("palavras"), f"{nome}.palavras")),
                    frases=_lista(t.get("frases"), f"{nome}.frases"),
                    moldes=_lista(t.get("moldes"), f"{nome}.moldes"),
                )
            )
        vetadas = _lista(raw.get("vetadas"), "vetadas") + _vetadas_gosto(gosto)
        return cls(
            topicos=tuple(topicos),
            demorados=frozenset(_lista(raw.get("demorados"), "demorados")),
            sinais_demora=tuple(_norm(s) for s in _lista(raw.get("sinais_demora"), "sinais_demora")),
            vetadas=frozenset(_norm(v) for v in vetadas),
        )

    def get(self, nome: str) -> Topico | None:
        return next((t for t in self.topicos if t.nome == nome), None)


def topico(cat: Catalogo, texto: str) -> str:
    """Tópico do pedido por prefixo de palavra, sem acento; vence o de mais acertos, empate pela
    ordem do arquivo; sem acerto → ``geral`` (spec §3.2)."""
    palavras = _norm(texto).split()
    melhor, acertos = GERAL, 0
    for t in cat.topicos:
        if not t.palavras:
            continue
        n = sum(1 for w in palavras if any(w.startswith(p) for p in t.palavras))
        if n > acertos:
            melhor, acertos = t.nome, n
    return melhor


def demorado(cat: Catalogo, texto: str) -> bool:
    """D2: o pedido parece demorado? Tópico em ``cat.demorados`` ou sinal de ``cat.sinais_demora``
    no texto (spec §3.3)."""
    if topico(cat, texto) in cat.demorados:
        return True
    norm = _norm(texto)
    return any(_tem_prefixo(norm, s) for s in cat.sinais_demora)


@dataclass(slots=True)
class Cota:
    """Cota da frase de espera por satélite (R3.6, spec §3.3): sem repetir as 2 últimas; depois
    de 2 turnos de agente seguidos com frase, o 3º não tem."""

    ultimas: list[str] = field(default_factory=list)
    seguidas: int = 0

    def livre(self) -> bool:
        """Este turno pode ter frase (não é a folga)?"""
        return self.seguidas < SEGUIDAS

    def registrar(self, frase: str | None) -> None:
        """Fim de um turno de agente: ``frase`` dita ou ``None`` (zera a sequência)."""
        if frase is None:
            self.seguidas = 0
            return
        self.seguidas += 1
        self.ultimas.append(frase)
        del self.ultimas[:-REPETE]


def escolher(
    cat: Catalogo,
    texto: str,
    cota: Cota,
    rng: random.Random,
    *,
    jogo: str | None = None,
    continuacao: bool = False,
    so_demorado: bool = True,
) -> str | None:
    """A frase de espera do turno, já preenchida (molde com ``{jogo}`` só no tópico ``jogo``), ou
    ``None`` (pedido não demorado com ``so_demorado``, continuação curta, folga, tudo repetido ou
    vetado). Não registra na cota. Tópico sem frases cai nas de ``geral``."""
    if so_demorado and not demorado(cat, texto):
        return None
    if continuacao and len(_norm(texto).split()) <= CONTINUACAO_CURTA:
        return None
    if not cota.livre():
        return None
    nome = topico(cat, texto)
    t = cat.get(nome)
    candidatas: list[tuple[str, str]] = []  # (frase final, texto checado contra as vetadas)
    if t is not None:
        candidatas += [(f, f) for f in t.frases]
        nome_jogo = (jogo or "").strip()
        if nome == "jogo" and nome_jogo and len(nome_jogo) <= JOGO_MAX:
            candidatas += [(m.replace("{jogo}", nome_jogo), m) for m in t.moldes]
    if not candidatas and (g := cat.get(GERAL)) is not None:
        candidatas = [(f, f) for f in g.frases]
    recentes = {_norm(f) for f in cota.ultimas[-REPETE:]}
    ok = [
        f
        for f, base in candidatas
        if _norm(base) not in cat.vetadas and _norm(f) not in cat.vetadas and _norm(f) not in recentes
    ]
    return rng.choice(ok) if ok else None


_ESPERA_VAZIA = (
    "deixa eu ver",
    "deixa eu pensar",
    "deixa eu checar",
    "um segundo",
    "um instante",
    "perai",
    "pera",
    "so um momento",
    "vou ver",
    "hm",
)
ESPERA_VAZIA_MAX = 8


def mesma_espera(frase: str) -> bool:
    """R3.4: frase só de "espera vazia" (≤ 8 palavras, prefixo da spec §3.4)."""
    norm = _norm(frase)
    if not norm or len(norm.split()) > ESPERA_VAZIA_MAX:
        return False
    return norm.startswith(_ESPERA_VAZIA)


# spec §4, por tipo. Padrões normalizados, casados como prefixo de palavra.
_REPROVA: dict[str, tuple[str, ...]] = {
    "acao": (
        "vou pesquisar",
        "vou buscar",
        "to pesquisando",
        "to buscando",
        "abrindo",
        "consultando",
        "olhando aqui na",
    ),
    "resultado": ("achei", "encontrei", "ja sei", "ja vi", "pronto", "aqui esta", "e isso"),
    "certeza": (
        "com certeza",
        "sei sim",
        "garanto",
        "prometo",
        "ja ja",
        "rapidinho",
        "num instante te digo",
    ),
    "fonte": ("de acordo com", "no google", "na wiki", "no site"),
}
# "segundo" é fonte ("segundo a wiki"), mas "um segundo" é espera ("Um segundo de cérebro").
_SEGUNDO_FONTE = re.compile(r"(?<!\bum )(?<!\bso um )(?<!\bmais um )(?<!\bnum )\bsegundo\b")
# Número por extenso, palavra inteira ("dez" não acerta "dezembro"). "um"/"uma" ficam de fora:
# são artigo ("um segundo", "uma ideia").
_NUMEROS = frozenset(
    "zero dois duas tres quatro cinco seis sete oito nove dez onze doze treze catorze quatorze "
    "quinze dezesseis dezessete dezoito dezenove vinte trinta quarenta cinquenta sessenta setenta "
    "oitenta noventa cem cento duzentos duzentas trezentos quatrocentos quinhentos seiscentos "
    "setecentos oitocentos novecentos mil milhao milhoes bilhao bilhoes trilhao".split()
)
HONESTA_MAX_PALAVRAS = 8


def honesta(frase: str) -> list[str]:
    """R4: violações do linter (spec §4); lista vazia = aprovada.

    Cada violação é ``"<tipo>: <padrão>"`` (tipos: acao, resultado, certeza, fonte, numero,
    tamanho)."""
    norm = _norm(frase)
    out: list[str] = []
    for tipo, padroes in _REPROVA.items():
        out += [f"{tipo}: {p}" for p in padroes if _tem_prefixo(norm, p)]
    if _SEGUNDO_FONTE.search(norm):
        out.append("fonte: segundo")
    if any(c.isdigit() for c in frase):
        out.append("numero: digito")
    out += [f"numero: {w}" for w in norm.split() if w in _NUMEROS]
    if len(norm.split()) > HONESTA_MAX_PALAVRAS:
        out.append(f"tamanho: > {HONESTA_MAX_PALAVRAS} palavras")
    if len(_SENT_END.findall(_ELLIPSIS.sub(",", frase.strip()))) > 0:
        out.append("tamanho: > 1 frase")
    return out


__all__: Sequence[str] = (
    "Catalogo",
    "Cota",
    "EsperaCfg",
    "Topico",
    "demorado",
    "escolher",
    "honesta",
    "mesma_espera",
    "topico",
)
