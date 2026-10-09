"""Fatores de humor (spec §4, acordo §4) que pesam as passivas. Dono: R1.1.

``fatores(ctx)`` devolve só os fatores **ativos** agora, com o peso da tabela do acordo §4.
``FAVORECE``/``BLOQUEIA`` dizem que passivas (por chave do catálogo) cada fator mexe; o
``passivas.sortear`` soma: peso = 1 + Σ pesos dos fatores ativos que a favorecem, e zera se algum
fator ativo a bloqueia.

Fontes no ``ctx`` (formato da R0.5, ver *Sobras*): ``humor``, ``madrugada``, ``hora``, ``faixa``,
``musica_nota``, ``claude``, ``jogo``, ``estado`` (``governador.Estado``), ``atividade``,
``agora`` (monotônico) e ``relogio`` (parede). Sem fonte ainda no ``ctx`` (chaves opcionais que o
``Reactor`` pode preencher): ``pc_problema`` (bool), ``favorita_dia`` (chave do artista),
``fps_estavel`` (bool, padrão verdadeiro). Estado próprio do módulo vai em chaves ``_humor_*``.
"""

from __future__ import annotations

# nomes dos 12 fatores (acordo §4) -> peso
SESSAO_LONGA = "sessao_longa"
MUSICA = "musica"
MUSICA_GOSTA = "musica_gosta"
PC_PROBLEMA = "pc_problema"
MANHA = "manha"
MADRUGADA = "madrugada"
PEDRO_MAL = "pedro_mal"
DESEMPENHO_JOGO = "desempenho_jogo"
MUSICA_ODEIA = "musica_odeia"
VITORIA = "vitoria"
SILENCIO = "silencio"
FAVORITA_DIA = "favorita_dia"

PESOS: dict[str, float] = {
    SESSAO_LONGA: 6, MUSICA: 7, MUSICA_GOSTA: 7, PC_PROBLEMA: 7, MANHA: 3, MADRUGADA: 7,
    PEDRO_MAL: 9, DESEMPENHO_JOGO: 7, MUSICA_ODEIA: 5, VITORIA: 6, SILENCIO: 4, FAVORITA_DIA: 8,
}

# fator -> passivas que ele favorece (só as do passivas.py; 17–19, 82, 90 são de outros módulos)
FAVORECE: dict[str, frozenset[str]] = {
    SESSAO_LONGA: frozenset(),  # sono 22h–05h (det_tempo) / 82 e 90 de dia (det_claude)
    MUSICA: frozenset({"ajeitando_fone", "cabeca_ritmo"}),
    MUSICA_GOSTA: frozenset({"cabeca_ritmo", "cantarolando", "sorriso_canto"}),
    PC_PROBLEMA: frozenset({"observando_hud", "suspiro"}),
    MANHA: frozenset({"sacada_olhar", "ajeitando_fone"}),
    MADRUGADA: frozenset({"piscada_gato", "suspiro"}),
    PEDRO_MAL: frozenset({"piscada_gato", "respirar"}),
    DESEMPENHO_JOGO: frozenset({"sorriso_canto", "brilho_presilha"}),
    MUSICA_ODEIA: frozenset({"beicinho", "suspiro", "soprando_franja"}),
    VITORIA: frozenset({"sorriso_canto", "rindo_sozinha"}),
    SILENCIO: frozenset({"suspiro", "beicinho", "soprando_franja"}),
    FAVORITA_DIA: frozenset({"cabeca_ritmo", "sorriso_canto", "cantarolando"}),  # nunca "corando"
}

# zoeira da regra 4 entre as passivas (classe ZOEIRA no catálogo): 8 e 16
ZOEIRA = frozenset({"beicinho", "soprando_franja"})

# fator -> passivas que ele zera enquanto ativo
BLOQUEIA: dict[str, frozenset[str]] = {
    PC_PROBLEMA: frozenset({"sorriso_canto", "cantarolando"}),
    MADRUGADA: ZOEIRA,
    PEDRO_MAL: ZOEIRA,
}

SESSAO_LONGA_S = 3 * 3600.0  # Pedro ativo sem pausa ≥ 30 min por 3 h
PAUSA_S = 30 * 60.0
MANHA_S = 3600.0  # primeira hora depois do 57 (bom dia)
JOGO_S = 5 * 60.0
VITORIA_S = 10 * 60.0
SILENCIO_S = 30 * 60.0

# vitórias que abrem a janela de 10 min: 35, 37, 39, 53, 75 e a faxina (chave, variante)
VITORIAS = frozenset({
    ("hot", "alivio"), ("fps_drop", "recuperou"), ("rede_voltou", None),
    ("claude", "terminou"), ("ideia", None), ("cleanup", None),
})
_VITORIA_SEM_VARIANTE = frozenset(c for c, v in VITORIAS if v is None)


def _desde(ctx: dict, chave: str, ativo: bool, agora: float) -> float:
    """Há quantos segundos a condição ``ativo`` vale sem parar (guardado em ``ctx[chave]``)."""
    if not ativo:
        ctx.pop(chave, None)
        return 0.0
    inicio = ctx.setdefault(chave, agora)
    return agora - inicio


def _ultimo_toque(est, chave: str) -> float | None:
    toques = getattr(est, "toques", None) or {}
    lista = toques.get(chave) if hasattr(toques, "get") else None
    return lista[-1] if lista else None


def _vitoria(ctx: dict, est, agora: float) -> bool:
    ult = getattr(est, "ultimo", None)
    if ult is not None and ult is not ctx.get("_humor_ultimo_visto"):
        ctx["_humor_ultimo_visto"] = ult
        if (ult.chave, ult.variante) in VITORIAS:
            ctx["_humor_vitoria"] = agora
    tempos = [ctx.get("_humor_vitoria")] + [_ultimo_toque(est, c) for c in _VITORIA_SEM_VARIANTE]
    return any(t is not None and 0 <= agora - t < VITORIA_S for t in tempos)


def _sessao_longa(ctx: dict) -> bool:
    ativ = ctx.get("atividade")
    relogio = ctx.get("relogio")
    if ativ is None or relogio is None:
        return False
    try:
        parado = ativ.parado_s(relogio)
    except Exception:  # noqa: BLE001 - arquivo de estado ruim não derruba o humor
        return False
    ativo = parado is not None and parado < PAUSA_S
    return _desde(ctx, "_humor_sessao", ativo, relogio) >= SESSAO_LONGA_S


def fatores(ctx: dict) -> dict[str, float]:
    """Os 12 fatores da tabela do acordo §4 -> peso de cada um **ativo** no ``ctx`` atual."""
    agora = float(ctx.get("agora", 0.0))
    est = ctx.get("estado")
    nota = int(ctx.get("musica_nota", 0) or 0)
    tocando = ctx.get("faixa") is not None
    ativos: list[str] = []

    if _sessao_longa(ctx):
        ativos.append(SESSAO_LONGA)
    if tocando:
        ativos.append(MUSICA)
        if nota >= 1:
            ativos.append(MUSICA_GOSTA)
        if nota == -1:
            ativos.append(MUSICA_ODEIA)
        fav = ctx.get("favorita_dia")
        verd = ctx.get("veredito")
        if fav and verd is not None and getattr(verd, "artist", "") == fav:
            ativos.append(FAVORITA_DIA)
    if ctx.get("pc_problema"):
        ativos.append(PC_PROBLEMA)
    bom_dia = _ultimo_toque(est, "bom_dia")
    if bom_dia is not None and 0 <= agora - bom_dia < MANHA_S:
        ativos.append(MANHA)
    if ctx.get("madrugada"):
        ativos.append(MADRUGADA)
    if int(ctx.get("humor", 3)) <= 1:
        ativos.append(PEDRO_MAL)
    jogo = bool(ctx.get("jogo")) and ctx.get("fps_estavel", True)
    if _desde(ctx, "_humor_jogo", jogo, agora) >= JOGO_S:
        ativos.append(DESEMPENHO_JOGO)
    if _vitoria(ctx, est, agora):
        ativos.append(VITORIA)
    silencio = not tocando and not ctx.get("claude")
    if _desde(ctx, "_humor_silencio", silencio, agora) >= SILENCIO_S:
        ativos.append(SILENCIO)
    return {f: PESOS[f] for f in ativos}


def peso(chave: str, ativos: dict[str, float]) -> float:
    """Peso de uma passiva: 0 se algum fator ativo a bloqueia; senão 1 + Σ dos que a favorecem."""
    if any(chave in BLOQUEIA.get(f, ()) for f in ativos):
        return 0.0
    return 1.0 + sum(p for f, p in ativos.items() if chave in FAVORECE.get(f, ()))
