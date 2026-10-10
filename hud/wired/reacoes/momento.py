"""Momento da Condessa (spec §3, acordo §3). Dono: V0.3 (esqueleto: V0.1).

Função ``decidir`` com prioridade e histerese, os ``filtros`` por cima, os grupos de passivas
(``GRUPOS`` + regras de cada linha em ``passivas``) e ``sinais``, que monta os sinais novos do ``ctx``
a partir do que o ``Reactor`` já tem.

Sinais do ``ctx`` (todos opcionais; ausente = falso/sem):
``magui_ativa``, ``turno_pedro_ha_s``, ``alerta``, ``jogo``, ``claude_esperando``, ``claude_rodando``,
``claude_demorando``, ``lm_on``, ``musica_nota`` (None = sem música), ``dancante``,
``sem_musica_ha_s``, ``pedro_inativo_s``, ``hora`` (0–23 local), ``humor_pedro`` (0–4 do núcleo),
``animo``, ``energia``, ``momento_ha_s``, contadores (``franja_na_espera``, ``franja_na_faixa``,
``cantando_na_faixa``), a escada do Tédio (``encarando_feito``, ``ei_to_aqui_ha_s``,
``ei_ignorado``), ``vida`` (o ``[vida]`` mesclado; padrão ``VIDA_PADRAO``) e ``memo`` (dicionário
do chamador, mantido entre ticks, onde ``decidir`` guarda o candidato da histerese).
"""

from __future__ import annotations

from .vida import VIDA_PADRAO, Filtro, Momento

# Limiares da tabela do acordo §3: ``[vida.momentos]`` (o ``ctx["vida"]`` é o ``Taste.vida()``, gosto
# + Pedro por cima de ``VIDA_PADRAO``); estes são os padrões.
LIMIARES_PADRAO: dict = VIDA_PADRAO["momentos"]

IMEDIATOS = frozenset({Momento.CONVERSA, Momento.ALERTA, Momento.JOGANDO})

GRUPOS: dict[Momento, tuple[str, ...]] = {
    Momento.CONVERSA: (),
    Momento.ALERTA: (),
    Momento.JOGANDO: ("sacada_olhar", "piscada_dupla", "cabeca_ritmo"),
    Momento.ESPERANDO: ("impaciente", "encarando", "soprando_franja"),
    Momento.NO_FLOW: ("cabeca_ritmo", "piscada_gato", "observando_hud"),
    Momento.TRABALHANDO_JUNTO: (
        "observando_hud", "sacada_olhar", "piscada_dupla", "soprando_franja",
    ),
    Momento.ESTUDANDO: ("piscada_gato", "sacada_olhar", "ideia"),
    Momento.CURTINDO: (
        "cabeca_ritmo", "sorriso_canto", "piscada_gato", "ajeitando_fone", "cantando_junto",
    ),
    Momento.ATURANDO: ("indiferente", "soprando_franja"),
    Momento.OUVINDO: ("ajeitando_fone", "sacada_olhar", "cabeca_ritmo"),
    Momento.PEDRO_SUMIU: (
        "brilho_presilha", "observando_hud", "falando_sozinha", "cantarolando", "bocejo", "cochilo",
    ),
    Momento.TEDIO: (
        "brilho_presilha", "observando_hud", "cantarolando",
        "encarando", "ei_to_aqui", "beicinho",
    ),
    Momento.A_TOA: (
        "piscada_dupla", "piscada_gato", "sacada_olhar", "observando_hud",
        "sorriso_canto", "rindo_sozinha",
    ),
}

RARAS = frozenset({"ideia", "falando_sozinha", "cantarolando", "rindo_sozinha"})
ZOEIRA = frozenset({"flagra_no_forum", "soprando_franja", "beicinho", "ei_to_aqui"})
NEGATIVAS = frozenset({"impaciente", "indiferente", "beicinho", "encarando"})

MEDIA_MIN: dict[Momento, float] = {
    Momento(k): float(v) for k, v in VIDA_PADRAO["passiva_media_min"].items()
}


def _vida(ctx: dict) -> dict:
    return ctx.get("vida") or VIDA_PADRAO


def limiar(ctx: dict, chave: str):
    """Limiar da tabela: ``[vida.momentos]`` do gosto por cima de ``LIMIARES_PADRAO``."""
    return (_vida(ctx).get("momentos") or {}).get(chave, LIMIARES_PADRAO[chave])


def media_min(momento: Momento, vida: dict | None = None) -> float | None:
    """Média entre passivas (min) do ``[vida.passiva_media_min]``; None nos momentos sem passiva."""
    tabela = (vida or VIDA_PADRAO).get("passiva_media_min") or {}
    v = tabela.get(momento.value, MEDIA_MIN.get(momento))
    return None if v is None else float(v)


def bruto(ctx: dict) -> Momento:
    """Primeira linha da tabela que bate (sem histerese)."""
    nota = ctx.get("musica_nota")
    rodando = bool(ctx.get("claude_rodando"))
    lm = bool(ctx.get("lm_on"))
    turno = ctx.get("turno_pedro_ha_s")
    inativo = ctx.get("pedro_inativo_s") or 0.0
    if ctx.get("magui_ativa") or (turno is not None and turno < limiar(ctx, "conversa_turno_s")):
        return Momento.CONVERSA
    if ctx.get("alerta"):
        return Momento.ALERTA
    if ctx.get("jogo"):
        return Momento.JOGANDO
    if ctx.get("claude_esperando"):
        return Momento.ESPERANDO
    if (rodando or lm) and nota is not None and nota >= 0:
        return Momento.NO_FLOW
    if rodando and nota is None:
        return Momento.TRABALHANDO_JUNTO
    if lm and nota is None:
        return Momento.ESTUDANDO
    if nota is not None and nota >= 1:
        return Momento.CURTINDO
    if nota is not None and nota <= -1:
        return Momento.ATURANDO
    if nota is not None:
        return Momento.OUVINDO
    if inativo >= limiar(ctx, "pedro_sumiu_s"):
        return Momento.PEDRO_SUMIU
    if not rodando and not lm and (ctx.get("sem_musica_ha_s") or 0.0) >= limiar(
        ctx, "tedio_sem_musica_s"
    ):
        return Momento.TEDIO
    return Momento.A_TOA


def decidir(ctx: dict, anterior: Momento | None, agora: float) -> Momento:
    """Momento pela prioridade da tabela; troca só depois de ``momento_estavel_s`` estável.

    Conversa, Alerta e Jogando entram na hora. O candidato e desde quando fica em ``ctx["memo"]``.
    """
    novo = bruto(ctx)
    memo = ctx.get("memo")
    if memo is None:
        memo = {}
    if anterior is None or novo == anterior or novo in IMEDIATOS:
        memo.pop("candidato", None)
        memo.pop("desde", None)
        return novo
    if memo.get("candidato") != novo:
        memo["candidato"], memo["desde"] = novo, agora
        return anterior
    if agora - memo["desde"] >= float(_vida(ctx).get("momento_estavel_s", 30)):
        memo.pop("candidato", None)
        memo.pop("desde", None)
        return novo
    return anterior


def filtros(ctx: dict) -> set[Filtro]:
    """Madrugada (22h–04h) e Pedro mal (humor do Pedro 0–1 do núcleo)."""
    out: set[Filtro] = set()
    hora = ctx.get("hora")
    if hora is not None:
        ini, fim = limiar(ctx, "madrugada")
        if (hora >= ini or hora < fim) if ini > fim else (ini <= hora < fim):
            out.add(Filtro.MADRUGADA)
    hp = ctx.get("humor_pedro")
    if hp is not None and hp <= limiar(ctx, "pedro_mal_max"):
        out.add(Filtro.PEDRO_MAL)
    return out


def escada_tedio(ctx: dict) -> str | None:
    """O degrau da escada do Tédio que cabe agora (acordo §3, A)."""
    if bool(ctx.get("ei_ignorado")):
        return "beicinho"
    ha = ctx.get("momento_ha_s") or 0.0
    ei_ha = ctx.get("ei_to_aqui_ha_s")
    if ha >= limiar(ctx, "escada_ei_s") and (
        ei_ha is None or ei_ha >= limiar(ctx, "escada_ei_intervalo_s")
    ):
        return "ei_to_aqui"
    if ha >= limiar(ctx, "escada_encarando_s") and not ctx.get("encarando_feito"):
        return "encarando"
    return None


def _cabe(nome: str, momento: Momento, ctx: dict) -> bool:  # noqa: PLR0911
    nota = ctx.get("musica_nota")
    animo = ctx.get("animo") or 0.0
    energia = ctx.get("energia", 1.0)
    if nome == "cabeca_ritmo":
        if momento == Momento.OUVINDO:
            return bool(ctx.get("dancante"))
        return nota is not None and nota >= 1
    if nome == "soprando_franja":
        if momento == Momento.ESPERANDO:
            return not ctx.get("franja_na_espera")
        if momento == Momento.TRABALHANDO_JUNTO:
            return bool(ctx.get("claude_demorando"))
        return not ctx.get("franja_na_faixa")
    if nome == "cantando_junto":
        return not ctx.get("cantando_na_faixa")
    if nome == "mao_no_queixo":
        return (ctx.get("momento_ha_s") or 0.0) >= limiar(ctx, "p10_apos_s")
    if nome == "sorriso_canto" and momento == Momento.A_TOA:
        return animo > limiar(ctx, "sorriso_animo")
    if nome == "rindo_sozinha":
        return animo > limiar(ctx, "rindo_animo")
    if nome == "cantarolando":
        return nota is None
    if nome == "bocejo":
        return energia < limiar(ctx, "bocejo_energia")
    if nome == "cochilo":
        return (
            (ctx.get("pedro_inativo_s") or 0.0) >= limiar(ctx, "cochilo_apos_s")
            and energia < limiar(ctx, "cochilo_energia")
            and not (nota is not None and nota >= 1)
        )
    if momento == Momento.TEDIO and nome in ("encarando", "ei_to_aqui", "beicinho"):
        return escada_tedio(ctx) == nome
    return True


def passivas(momento: Momento, ctx: dict, fs: set[Filtro] | None = None) -> tuple[str, ...]:
    """Passivas do grupo do momento que cabem agora, já com os filtros por cima."""
    fs = filtros(ctx) if fs is None else fs
    out = []
    for nome in GRUPOS.get(momento, ()):
        if not _cabe(nome, momento, ctx):
            continue
        if Filtro.MADRUGADA in fs and nome in ZOEIRA:
            continue
        if Filtro.PEDRO_MAL in fs and (nome in ZOEIRA or nome in NEGATIVAS):
            continue
        out.append(nome)
    return tuple(out)


def sinais(  # noqa: PLR0913
    agora: float,
    *,
    parado_s: float | None,
    ultimo_turno_pedro: float | None,
    ultima_musica: float | None,
    magui_ativa: bool = False,
    lm_on: bool = False,
    musica_nota: int | None = None,
    claude_esperando: bool = False,
    claude_rodando: bool = False,
    alerta: str | None = None,
    faixa_agua: str | None = None,
) -> dict:
    """Sinais novos do ``ctx`` a partir do que o ``Reactor`` tem.

    ``parado_s`` vem de ``Atividade.parado_s``; os demais o ``Reactor`` passa por parâmetro.
    """
    return {
        "pedro_inativo_s": parado_s or 0.0,
        "turno_pedro_ha_s": None if ultimo_turno_pedro is None else max(0.0, agora - ultimo_turno_pedro),
        "sem_musica_ha_s": (
            0.0 if musica_nota is not None
            else (float("inf") if ultima_musica is None else max(0.0, agora - ultima_musica))
        ),
        "magui_ativa": magui_ativa,
        "lm_on": lm_on,
        "musica_nota": musica_nota,
        "claude_esperando": claude_esperando,
        "claude_rodando": claude_rodando,
        "alerta": alerta,
        "faixa_agua": faixa_agua,
    }
