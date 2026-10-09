# ruff: noqa: E501  (tabela de dados: uma reação por linha)
"""Catálogo das 110 reações (90 da planilha + I1–I20): só dados. Dono: R0.4.

Fontes: sequências de ``reacoes.md`` e acordo §1–§2 (ajustes aplicados), classes do spec §3 mais a
classe do detector (spec §5), sinais condicionados do spec §5. Reações de variante (spec §1) usam a
chave atual + ``variante``: em ``DEFS`` a chave é ``chave`` (sem variante) ou ``(chave, variante)``,
como o governador procura (``_achar``).

``TODAS``: as 110 ``Def`` em ordem. ``DEFS``: por chave. ``ATIVAS``: chaves de ``DEFS`` sem sinal
pendente e não substituídas (R8, CA-05).

Notação das sequências: passos separados por ``|``; em cada passo, ``B*``/``F*`` = olhos,
``C*``/``V*`` = boca, ``D*`` = efeito (``contratos.EFEITO``), ``E2`` = fone na cabeça (``fone_on``),
``E3`` = fone no pescoço (``fone_off``), ``P*`` = braço (``braco:P*``), ``iris:<olhar>`` = sacada do
O1, ``bob``/``sway``/``tails`` = corpo, número = ms.
"""

from __future__ import annotations

from .contratos import EFEITO, Classe, Def, Passo

_P, _T, _M, _S, _E = Classe.PASSIVA, Classe.TEMPO, Classe.MUSICA, Classe.SISTEMA, Classe.PEDRO
_SONO, _RARA, _DIA, _NOT = Classe.SONO, Classe.RARA, Classe.DIARIA, Classe.NOTURNA
_ZOE, _COB, _VIT, _VOL = Classe.ZOEIRA, Classe.COBRANCA, Classe.VITORIA, Classe.VOLTA


def _passos(seq: str) -> tuple[Passo, ...]:
    out = []
    for parte in seq.split("|"):
        ms, eyes, mouth, efeitos, corpo = 0, None, None, [], []
        for t in parte.split():
            if t.isdigit():
                ms = int(t)
            elif t[0] in "BF":
                eyes = t
            elif t[0] in "CV":
                mouth = t
            elif t[0] == "D":
                efeitos.append(EFEITO[t])
            elif t == "E2":
                corpo.append("fone_on")
            elif t == "E3":
                corpo.append("fone_off")
            elif t[0] == "P":
                corpo.append(f"braco:{t}")
            else:  # bob / sway / tails / iris:<olhar>
                corpo.append(t)
        out.append(Passo(ms, eyes, mouth, efeitos=tuple(efeitos), corpo=tuple(corpo)))
    return tuple(out)


# (n, chave, variante, nome, sequência, classes, sinal, cooldown_s, extras)
_PASSIVA_CD = 120.0
_LINHAS: tuple = (
    (1, "respirar", None, "Respirar e balançar", "B1 C1 bob 4000 | B1 C1 tails 3000", {_P}, None, _PASSIVA_CD, {}),
    (2, "sacada_olhar", None, "Sacada de olhar", "B1 C1 2500 | B1 iris:F1 700 | B1 iris:B1 400", {_P}, None, _PASSIVA_CD, {}),
    (3, "piscada_dupla", None, "Piscada dupla", "B3 80 | B1 120 | B3 80 | B1 C1 200", {_P}, None, _PASSIVA_CD, {}),
    (4, "piscada_gato", None, "Piscada lenta de gato", "B2 150 | B3 C5 500 | B2 150 | B1 C1 200", {_P}, None, _PASSIVA_CD, {}),
    (5, "seguir_cursor", None, "Sacada pro card", "B1 iris:F3 2000", {_P, _E}, None, 60.0, {}),
    (6, "observando_hud", None, "Observando o HUD", "F1 900 | F4 900 | F5 900 | F3 900", {_P}, None, _PASSIVA_CD, {}),
    (7, "sorriso_canto", None, "Micro sorriso de canto", "B1 C10 1500", {_P}, None, _PASSIVA_CD, {}),
    (8, "beicinho", None, "Beicinho passageiro", "B1 C9 1200", {_P, _ZOE}, None, _PASSIVA_CD, {}),
    (9, "suspiro", None, "Suspiro leve", "B2 C4 bob 900 | B1 C1 500", {_P}, None, _PASSIVA_CD, {}),
    (10, "cantarolando", None, "Cantarolando sozinha", "B2 C13 1200 | B1 C1 D6 1000", {_P, _RARA}, None, 3600.0, {}),
    (11, "rindo_sozinha", None, "Rindo sozinha", "B1 C5 800 | B5 C6 1200 | B4 C5 800", {_P, _RARA}, None, 3600.0, {}),
    (12, "corando", None, "Corando sozinha", "F3 C1 600 | B4 C5 D1 1800 | B1 C1 600", {_P, _DIA}, None, 86400.0, {}),
    (13, "falando_sozinha", None, "Falando sozinha em silêncio", "B13 V1 300 | B13 V5 150 | B13 V2 250 | B13 V3 300", {_P, _RARA}, None, 3600.0, {}),
    (14, "brilho_presilha", None, "Brilho da presilha", "B1 C1 D9 900", {_P}, None, _PASSIVA_CD, {}),
    (15, "encarando", None, "Encarando", "B1 C1 iris:B1 3000 | B3 500 | B1 C10 1000", {_P, _E}, None, 600.0, {}),
    (16, "soprando_franja", None, "Soprando a franja", "B13 C1 800 | B2 V4 700 | B1 C1 500", {_P, _ZOE}, None, _PASSIVA_CD, {}),
    (17, "bocejo", None, "Bocejo", "B14 C1 800 | B15 C4 1200 | B14 C1 600 | B1 C1 400", {_P, _T, _SONO}, None, 600.0, {}),
    (18, "cochilo", None, "Cochilo", "B14 C1 1500 | B15 C1 D3 3000", {_P, _T, _SONO}, None, 600.0, {"mood": "sleepy"}),
    (19, "cabeca_pesada", None, "Cabeça pesada", "B14 C1 1500 | B15 C1 500 | B9 C7 400 | B14 C1 800", {_P, _T, _SONO}, None, 600.0, {}),
    (20, "sobressalto", None, "Acordando em sobressalto", "B9 C7 D5 500 | B2 C9 500 | B1 C5 600", {_T, _E, _VOL}, None, 600.0, {}),
    (21, "fone_repouso", None, "Fone em repouso", "B1 C1 E3 3000", {_P}, None, _PASSIVA_CD, {}),
    (22, "ajeitando_fone", None, "Ajeitando o fone", "B5 C5 E2 900 | B1 E2 P11 500", {_P}, None, _PASSIVA_CD, {}),
    (23, "cabeca_ritmo", None, "Cabeça no ritmo", "B2 C1 E2 sway 1500 | B1 C5 E2 1500", {_P}, None, _PASSIVA_CD, {}),
    (24, "colocando_fone", None, "Colocando o fone", "F4 600 | B2 C1 E2 400 | B5 C13 D6 E2 bob 2000", {_M}, None, 180.0, {}),
    (25, "tirando_fone", None, "Tirando o fone", "B9 C7 E3 500 | B1 C1 600", {_M}, None, 600.0, {}),
    (26, "refrao", None, "Essa é das minhas", "B4 C5 E2 500 | B5 C6 D9 D6 E2 bob 2500", {_M}, None, 600.0, {}),
    (27, "cantando_junto", None, "Cantando junto", "B5 V1 400 | B5 V2 300 | B5 V3 400 | B4 V5 300", {_M}, None, 600.0, {}),
    (28, "musica_repetida", None, "Música repetida", "B7 C12 1000 | F7 C11 1200", {_M}, None, 600.0, {}),
    (29, "musica_triste", None, "Música triste", "B10 C9 E2 1200 | F7 C1 D7 2500", {_M, _NOT}, None, 600.0, {}),
    (30, "musica_dancante", None, "Música dançante", "B4 C10 E2 sway 1500 | B5 C6 D6 tails 2000", {_M}, None, 600.0, {}),
    (31, "volume_alto", None, "Volume alto demais", "B9 C4 D2 E3 600 | B7 C9 700", {_M}, None, 600.0, {}),
    (32, "acabou_fila", None, "Acabou a fila", "B5 C5 E2 1200 | B2 C1 1000 | B1 C1 E3 800", {_M}, None, 600.0, {}),
    (33, "music_new", "amou", "Descobriu música que amou", "B13 C7 800 | B9 C7 D5 500 | B5 C13 D9 D6 2500", {_M}, None, 600.0, {}),
    (34, "hot", None, "Temperatura escalando", "F1 C8 D2 3000 | B9 C7 D5 D2 1500", {_S, _COB}, None, 600.0, {}),
    (35, "hot", "alivio", "Alívio térmico", "B3 C4 900 | B4 C5 1500", {_S, _VIT}, None, 600.0, {}),
    (36, "fps_drop", None, "FPS despencando", "F3 C11 1500 | B6 C8 D2 1500", {_S, _COB}, None, 600.0, {}),
    (37, "fps_drop", "recuperou", "FPS recuperou", "F3 500 | B4 C5 1500", {_S, _VIT}, None, 600.0, {}),
    (38, "rede_caiu", None, "Rede caiu", "F3 C7 800 | B10 C9 D4 2000", {_S}, None, 600.0, {}),
    (39, "rede_voltou", None, "Rede voltou", "B9 C7 400 | B4 C5 1500", {_S, _VIT}, None, 600.0, {}),
    (40, "transferencia_acabou", None, "Transferência pesada acabou", "F5 C7 600 | B4 C10 1500", {_S}, None, 600.0, {}),
    (41, "disco_cheio", None, "Disco quase cheio", "F3 C11 D2 1500 | B10 C8 2000", {_S, _COB}, None, 600.0, {}),
    (42, "cleanup", None, "Faxina do SSD em andamento", "F7 C8 2500 | B13 C1 1500", {_S}, None, 600.0, {}),
    (43, "ventoinha", None, "Ventoinha alta", "B7 C9 1200 | F1 C12 D2 1500", {_S}, None, 600.0, {}),
    (44, "game_on", None, "Jogo abriu", "B4 C10 800 | B6 C8 2000", {_S}, None, 600.0, {}),
    (45, "game_off", None, "Jogo fechou em paz", "B2 C5 1000 | B4 C5 1500", {_S}, None, 600.0, {}),
    (46, "notificacao", None, "Notificação chegou", "F5 C7 700 | B1 C1 600", {_S}, None, 600.0, {}),
    (47, "popup_erro", None, "Popup de erro", "B9 C7 D5 600 | B6 C8 D2 1500", {_S}, None, 600.0, {}),
    (48, "hud_acordou", None, "HUD acordou", "B15 C1 800 | B2 C1 600 | B1 C5 1200", {_S}, None, 600.0, {}),
    (49, "pc_desligando", None, "PC desligando", "B1 C5 800 | B14 C1 700 | B15 C1 1200", {_S}, None, 600.0, {"substituida": True}),
    (50, "pede_reinicio", None, "Atualização pedindo reinício", "B7 C12 1200 | F6 C11 1200", {_S}, None, 600.0, {}),
    (51, "posando_print", None, "Posando pra print", "B1 C1 200 | B4 C5 D9 1200", {_E}, None, 600.0, {}),
    (52, "claude", None, "Lendo (Claude Code trabalhando)", "F7 C1 1500 | F5 C1 1500", {_E}, None, 600.0, {}),
    (53, "claude", "terminou", "Claude Code terminou", "B4 C10 1000 | B5 C5 1500", {_E, _VIT}, None, 600.0, {}),
    (54, "claude_erro", None, "Claude Code com erro", "B10 C11 1000 | F7 C8 1800", {_E}, None, 600.0, {}),
    (55, "claude_espera", None, "Claude Code esperando você", "F7 C1 1000 | B1 C7 D4 2000", {_E}, None, 600.0, {}),
    (56, "claude", "demorando", "Claude Code demorando", "B7 C9 1500 | B14 C1 2500", {_E}, None, 600.0, {}),
    (57, "bom_dia", None, "Bom dia", "B14 C1 1000 | B1 C5 P9 800 | B4 C5 1500", {_T, _E, _VOL}, None, 600.0, {}),
    (58, "almoco", None, "Hora do almoço", "B4 C5 800 | F3 C9 1500", {_T}, None, 600.0, {}),
    (59, "meia_noite", None, "Meia-noite", "B7 C12 1200 | F7 C11 1200", {_T}, None, 600.0, {}),
    (60, "madrugada", None, "Madrugada pesada", "B14 C4 1500 | F7 C9 2500", {_T}, None, 600.0, {}),
    (61, "long_session", "pausa", "Sugerindo pausa", "B10 C5 1000 | F1 C5 1200", {_T}, None, 600.0, {}),
    (62, "sentiu_falta", None, "Sentiu sua falta", "B10 C9 800 | B9 C7 500 | B4 C5 D1 1800", {_T, _E, _VOL}, None, 600.0, {}),
    (63, "data_especial", None, "Data especial", "B9 C7 D5 500 | B5 C6 D1 D6 2500", {_T}, None, 600.0, {}),
    (64, "led", None, "Cutucada", "B9 C7 600 | B7 C9 800 | B6 C8 D8 1500 | B1 C1 600", {_E}, None, 3.0, {}),
    (65, "hover", None, "Hover", "B4 C5 D1 1500", {_E}, None, 600.0, {}),
    (66, "led", "fone", "Cutucada com fone", "B10 C7 D4 E3 700 | B1 C1 800", {_E}, None, 3.0, {}),
    (67, "carinho", None, "Carinho", "B2 C1 600 | B5 C5 D1 tails 2000", {_E}, None, 600.0, {}),
    (68, "mouse_sacudido", None, "Mouse sacudido", "B9 C7 D2 600 | B10 C9 sway 1200", {_E}, None, 600.0, {"substituida": True}),
    (69, "clique_duplo", None, "Clique duplo", "B9 D5 400 | B6 C8 1200", {_E}, None, 600.0, {}),
    (70, "segurar_clique", None, "Segurar o clique", "B2 C1 600 | B3 C5 2500", {_E}, None, 86400.0, {}),
    (71, "noticia_boa", None, "Notícia boa", "F5 C7 600 | B4 C5 1500", {_E}, None, 600.0, {}),
    (72, "noticia_ruim", None, "Notícia ruim", "F5 C7 600 | B10 C9 1800", {_E}, None, 600.0, {}),
    (73, "noticia_absurda", None, "Notícia absurda", "B9 C7 600 | B7 C12 1500", {_E}, None, 600.0, {}),
    (74, "tsundere", None, "Tsundere (elogio)", "B6 C9 D1 1500 | F1 C12 D1 1500 | B1 C1 600", {_E}, None, 600.0, {}),
    (75, "ideia", None, "Ideia!", "B13 C7 P10 1200 | B9 C7 D5 500 | B4 C6 tails 1500", {_E, _VIT}, None, 600.0, {}),
    (76, "rindo", None, "Rindo", "B5 C6 bob 1800 | B5 C6 D7 1200 | B4 C5 800", {_E}, None, 600.0, {}),
    (77, "flagrada", None, "Flagrada olhando", "B1 C1 1000 | B1 C1 D2 iris:F1 1200 | B1 C10 D1 iris:B1 1500", {_E}, None, 600.0, {"prio": 2}),
    (78, "desconfiada", None, "Desconfiada", "B7 C12 1200 | F6 C12 1500", {_M, _ZOE}, None, 600.0, {}),
    (79, "triste_leve", None, "Triste leve", "B10 C9 1200 | F7 C9 2000", {_E}, None, 600.0, {}),
    (80, "impaciente", None, "Impaciente", "B7 C9 1500 | F7 C9 1500 | B7 C4 1000", {_S, _COB}, None, 600.0, {}),
    (81, "surpresa_boa", None, "Surpresa boa", "B9 C7 500 | B4 C6 D1 tails 1500", {_M}, None, 600.0, {}),
    (82, "claude", "com_musica", "Foco com fone", "F7 C1 E2 bob 1500 | F5 C1 E2 1500", {_E}, None, 600.0, {}),
    (83, "piscadinha", None, "Provocação com piscadinha", "B4 C10 800 | B16 C10 1200", {_M, _ZOE}, None, 600.0, {}),
    (84, "eu_avisei", None, "Eu avisei", "B6 C1 800 | B4 C10 1800", {_S, _ZOE, _COB}, None, 600.0, {"prio": 2}),
    (85, "indiferente", None, "Indiferente", "F6 C1 1500 | B2 C11 1000", {_M, _ZOE}, None, 600.0, {}),
    (86, "desculpa", None, "Pedindo desculpa", "B10 C9 1000 | B3 C1 1000 | B6 C10 D1 1500", {_E}, None, 600.0, {}),
    (87, "gaguejando", None, "Gaguejando", "B9 V5 D2 400 | B10 V5 D1 400 | B4 C5 D1 1200", {_E}, None, 600.0, {}),
    (88, "sussurro", None, "Sussurrando um segredo", "F1 500 | B1 V4 600 | B4 C10 1200", {_E}, None, 600.0, {}),
    (89, "indecisa", None, "Indecisa", "F1 C11 P10 900 | F6 C11 900 | B13 C7 1200", {_M}, None, 600.0, {}),
    (90, "claude", "pesado", "Concentração extrema", "F7 C8 3000 | B2 C8 300", {_E}, None, 600.0, {}),
    ("I1", "fim_expediente", None, "Fim de expediente", "B4 C5 P9 1200 | B2 C5 800", {_T}, None, 600.0, {}),
    ("I2", "boa_noite", None, "Boa noite", "B1 C5 800 | B14 C1 700 | B15 C1 1200", {_T, _NOT}, None, 600.0, {}),
    ("I3", "skips", "tontura", "Tontura de pulos", "B9 C7 D2 600 | B10 C9 1200", {_M}, None, 600.0, {}),
    ("I4", "fps_drop", "vergonha", "Vergonha de FPS", "F3 C11 1200 | B6 C8 D2 1500 | B7 C12 1000", {_S, _COB}, None, 600.0, {"prio": 2}),
    ("I5", "sufocando", None, "Sistema sufocando", "B9 C7 D5 600 | B6 C8 D2 1500", {_S, _COB}, None, 600.0, {}),
    ("I6", "sem_tropeco", None, "Partida sem tropeço", "B9 C7 400 | B5 C6 D9 2500", {_S, _VIT}, None, 600.0, {}),
    ("I7", "favorita_dia", None, "Favorita do Dia em campo", "B1 C1 200 | B4 C5 D9 1200", {_M}, None, 600.0, {}),
    ("I8", "duelo_ado", None, "Duelo com a Ado", "B7 C12 800 | B6 C8 1200 | B4 C10 1200", {_M}, None, 600.0, {}),
    ("I9", "conta_anonima", None, "A Conta Anônima", "B5 V1 300 | B5 V2 300 | F1 C1 D2 1200 | B4 C10 800", {_M}, None, 600.0, {}),
    ("I10", "diva_diva", None, "Diva contra Diva", "B7 C12 1000 | B4 C10 1200", {_M}, None, 600.0, {}),
    ("I11", "tema_agua", None, "Tema água", "B13 C7 800 | B4 C6 D6 1800", {_M}, None, 600.0, {}),
    ("I12", "musica_triste", "chopin", "Calada pelo Chopin", "B3 C5 3000 | B2 C1 600", {_M, _NOT}, None, 600.0, {}),
    ("I13", "music_love", "chefe", "Modo chefe", "B6 C8 E2 2000 | B4 C10 D9 1500", {_M}, None, 600.0, {}),
    ("I14", "elevador", None, "Música de elevador", "B2 C1 1500 | B7 C4 1200", {_M, _ZOE}, None, 600.0, {}),
    ("I15", "pulou_essa", None, "Você pulou ESSA?", "B9 C7 400 | B6 C8 D8 1500 | B7 C9 1000", {_M, _ZOE}, None, 600.0, {}),
    ("I16", "silencio_longo", None, "Silêncio longo", "B10 C9 2000 | B1 C1 800", {_P, _T, _DIA, _NOT}, None, 86400.0, {}),
    ("I17", "ei_to_aqui", None, "Ei, tô aqui", "B1 C9 1200 | B9 C7 D4 800 | B1 C10 800", {_P, _T}, None, 7200.0, {}),
    ("I18", "esperando_resposta", None, "Esperando resposta", "B1 C1 3000", {_E}, None, 600.0, {}),
    ("I19", "aniversario_dela", None, "Aniversário dela", "B9 C7 D5 500 | B5 C6 D1 D6 D9 3000", {_T}, None, 600.0, {}),
    ("I20", "bracos_cruzados", None, "Braços cruzados", "B7 C9 P13 2000 | B1 C1 600", {_P, _DIA}, "P13", 86400.0, {}),
)

TODAS: tuple[Def, ...] = tuple(
    Def(chave, n, nome, _passos(seq), frozenset(cls), cooldown_s=cd, sinal=sinal, variante=var, **ext)
    for n, chave, var, nome, seq, cls, sinal, cd, ext in _LINHAS
)
DEFS: dict[str | tuple[str, str], Def] = {
    (d.chave if d.variante is None else (d.chave, d.variante)): d for d in TODAS
}
ATIVAS: frozenset[str | tuple[str, str]] = frozenset(
    k for k, d in DEFS.items() if d.sinal is None and not d.substituida
)
