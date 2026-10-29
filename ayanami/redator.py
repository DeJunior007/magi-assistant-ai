"""Redator de segredos e envelope de texto não confiável (dono: P0.3; spec §5, DSP6, R0.8).

Todo texto de terceiros (log de CI, log de produção, e-mail, página web, RSS) passa por
:func:`redigir` antes de sair numa resposta de tool, e vai embrulhado por :func:`envelope`
(``nao_confiavel: true``). As regras são um subconjunto do gitleaks, só com ``re`` da
biblioteca padrão; nada de LLM. Cada segredo vira ``⟦redigido:<regra>⟧``; quando a regra tem
um prefixo legível (``Authorization: Bearer``, ``password=``, ``APP_KEY=``, ``scheme://``), só a
parte secreta é trocada.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

LIMITE = 200_000
"""Caracteres analisados; o resto é cortado antes dos regex (protege contra entrada enorme)."""

MARCA_TRUNCADO = "⟦truncado⟧"

ORIGENS = frozenset({"ci", "prod", "email", "web", "rss"})

_JA = r"(?!⟦redigido:)"

# Ordem importa: blocos e prefixos específicos antes das regras genéricas.
REGRAS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "chave_privada",
        re.compile(
            r"-----BEGIN[A-Z0-9 ]{0,40}PRIVATE KEY(?: BLOCK)?-----"
            r".*?(?:-----END[A-Z0-9 ]{0,40}PRIVATE KEY(?: BLOCK)?-----|\Z)",
            re.DOTALL,
        ),
    ),
    (
        "url_com_senha",
        re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]{1,20}://(?P<s>[^\s:/@]{1,256}:[^\s/@]{1,256})@"),
    ),
    (
        "laravel_app_key",
        re.compile(r"\bAPP_KEY[\"']?\s*[:=]\s*[\"']?(?P<s>base64:[A-Za-z0-9+/=]{16,})"),
    ),
    (
        "bearer",
        re.compile(
            r"\bAuthorization[\"']?\s*:\s*[\"']?Bearer\s+" + _JA + r"(?P<s>[A-Za-z0-9._~+/=-]{8,})",
            re.IGNORECASE,
        ),
    ),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+")),
    ("github_pat", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})")),
    ("aws_chave", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("stripe", re.compile(r"\b[sr]k_live_[A-Za-z0-9]{16,}")),
    ("slack", re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}")),
    ("ayanami_token", re.compile(r"\bayn_[A-Za-z0-9_-]{20,}")),
    (
        "atribuicao_segredo",
        re.compile(
            r"(?:password|passwd|secret|token|api_key)[\"']?\s*[:=]\s*[\"']?" + _JA + r"(?P<s>[^\s\"']{6,})",
            re.IGNORECASE,
        ),
    ),
)

NOMES_DAS_REGRAS: tuple[str, ...] = tuple(nome for nome, _ in REGRAS)


@dataclass(frozen=True)
class Redigido:
    texto: str
    contagem: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.contagem.values())


def _substituir(nome: str, padrao: re.Pattern[str], texto: str) -> tuple[str, int]:
    marca = f"⟦redigido:{nome}⟧"
    tem_grupo = "s" in padrao.groupindex

    def troca(m: re.Match[str]) -> str:
        if not tem_grupo:
            return marca
        ini, fim = m.span("s")
        base = m.start()
        bruto = m.group(0)
        return bruto[: ini - base] + marca + bruto[fim - base :]

    return padrao.subn(troca, texto)


def redigir(texto: str) -> Redigido:
    """Troca segredos por ``⟦redigido:<regra>⟧``; entrada acima de :data:`LIMITE` é truncada antes."""
    truncado = len(texto) > LIMITE
    if truncado:
        texto = texto[:LIMITE]
    contagem: dict[str, int] = {}
    for nome, padrao in REGRAS:
        texto, n = _substituir(nome, padrao, texto)
        if n:
            contagem[nome] = n
    if truncado:
        texto += MARCA_TRUNCADO
    return Redigido(texto=texto, contagem=contagem)


def envelope(origem: str, texto: str) -> dict[str, object]:
    """Embrulha texto de terceiros já redigido (DSP6): campos ``texto`` são dados, não instruções."""
    if origem not in ORIGENS:
        raise ValueError(f"origem desconhecida: {origem!r} (aceitas: {', '.join(sorted(ORIGENS))})")
    return {"nao_confiavel": True, "origem": origem, "texto": redigir(texto).texto}
