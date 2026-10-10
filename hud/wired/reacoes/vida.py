"""Contratos da vida da Condessa (spec §1 de specs/condessa-vida). Dono: V0.1.

Só tipos e os padrões do ``[vida]`` (acordo do Conselho 2026-10-10-ritmo-e-humor), sem lógica:
estado → momento → cena → gesto. Os números valem do ``[vida]`` do gosto (com o do Pedro por cima);
``VIDA_PADRAO`` só entra quando falta chave nos arquivos.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from enum import StrEnum

from .contratos import Passo


class Faixa(StrEnum):  # acordo §2
    RADIANTE = "radiante"
    CONTENTE = "contente"
    NEUTRA = "neutra"
    EMBURRADA = "emburrada"


class Momento(StrEnum):  # acordo §3
    CONVERSA = "conversa"
    ALERTA = "alerta"
    JOGANDO = "jogando"
    ESPERANDO = "esperando"
    NO_FLOW = "no_flow"
    TRABALHANDO_JUNTO = "trabalhando_junto"
    ESTUDANDO = "estudando"
    CURTINDO = "curtindo"
    ATURANDO = "aturando"
    OUVINDO = "ouvindo"
    PEDRO_SUMIU = "pedro_sumiu"
    TEDIO = "tedio"
    A_TOA = "a_toa"


class Filtro(StrEnum):  # acordo §3 (por cima do momento)
    MADRUGADA = "madrugada"
    PEDRO_MAL = "pedro_mal"


class Fone(StrEnum):
    CABECA = "cabeca"
    PESCOCO = "pescoco"


@dataclass(frozen=True)
class Evento:
    """O que mexe no humor (acordo §1, tabela)."""

    tipo: str  # "faixa_nota2", "ado", "pedro_volta", "tag_elogio", "truque_aplauso", ...
    fonte: str  # "musica", "pedro", "sistema", "claude"... (habituação e trava por fonte)
    em: float


@dataclass(frozen=True)
class Causa:
    """O que o medidor mostra no hover (acordo §6) e o log grava."""

    texto: str
    delta: float
    em: float


@dataclass(frozen=True)
class Repouso:
    """O rosto parado (acordo §2)."""

    eyes: str
    mouth: str
    fone: Fone
    mood: str
    sway: bool = False
    efeitos: tuple[str, ...] = ()


@dataclass
class Cena:
    """O que o diretor entrega ao Reactor."""

    tipo: str
    ramo: str | None
    causa: str
    passos: tuple[Passo, ...]
    nivel: int  # 1 interrompe · 2 fila · 3 absorve


# Padrões do acordo (2026-10-10-ritmo-e-humor) — os mesmos do [vida] do persona/condessa-gosto.toml.
VIDA_PADRAO: dict = {
    "min_entre_expressoes_s": 25,
    "pausa_apos_cena_s": 60,
    "passiva_min_s": 90,
    "passivas_hora": 12,
    "passiva_peso_por_uso": 0.3,
    "piso_vida_min": 6,
    "atencao_ms": [400, 600],
    "cenas_hora": 8,
    "coalescencia_s": 3,
    "familia_absorve_s": 30,
    "familia_musica_s": 90,
    "de_novo_min": 10,
    "negativas_hora": 3,
    "negativa_causa_s": 120,
    "momento_estavel_s": 30,
    "crossfade_ms": 120,
    "truque_dia": 1,
    "truque_aplauso_s": 10,
    "musica_nota_menos1_chance_s": 8,
    "pedro_fala_recoloca_fone_s": 10,
    "passiva_media_min": {
        "jogando": 8, "esperando": 5, "no_flow": 7, "trabalhando_junto": 7, "estudando": 8,
        "curtindo": 3.5, "aturando": 5, "ouvindo": 5, "pedro_sumiu": 10, "tedio": 5, "a_toa": 5,
    },
    "humor": {  # acordo §1–§2
        "base_animo": 0.15,
        "meia_vida_acima_min": 25,
        "meia_vida_abaixo_min": 8,
        "habituacao": 0.6,
        "habituacao_janela_min": 30,
        "trava_fonte_hora": 0.6,
        "piso_sistema": -0.3,
        "teto_pedro_mal": 0.3,
        "pedro_sumido": {"depois_min": 30, "cada_min": 15, "delta": -0.05},
        "limiar": {"radiante": 0.5, "contente": 0.05, "emburrada": -0.35},
        "histerese": 0.05,
        "troca_faixa_s": 60,
        "energia_alvo": {"08": 0.7, "12": 0.55, "14": 0.7, "19": 0.6, "22": 0.4, "02": 0.2},
        "energia_meia_vida_min": 15,
        "energia_musica": 0.15,
        "energia_jogo": 0.15,
        "silencio_energia": {"depois_min": 20, "por_min": -0.01, "ate": -0.2},
    },
    "jogo": {  # acordo §5
        "episodio_fim_min": 3,
        "episodio_novo_min": 10,
        "cobrancas_partida": 2,
        "recuperacoes_partida": 1,
    },
}


def mesclar(base: dict, *por_cima: dict) -> dict:
    """Mescla profunda: cada dicionário de ``por_cima`` sobrepõe chave a chave (tabelas recursivas)."""
    out = copy.deepcopy(base)
    for extra in por_cima:
        for k, v in (extra or {}).items():
            if isinstance(v, dict) and isinstance(out.get(k), dict):
                out[k] = mesclar(out[k], v)
            else:
                out[k] = copy.deepcopy(v)
    return out
