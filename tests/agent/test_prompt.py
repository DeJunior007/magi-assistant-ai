"""Testes da montagem do prompt (tarefa 3.3, R11.1-R11.3, R13.4, R14)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from magi.agent.prompt import (
    MAX_PROMPT_TOKENS,
    MEMORIES_MAX_TOKENS,
    MOOD_TONES,
    PROFILE_MAX_TOKENS,
    TURNS_MAX_TOKENS,
    GameContext,
    PromptTooLarge,
    build_prompt,
    count_message_tokens,
    estimate_tokens,
    load_persona,
    truncate_to_tokens,
)
from magi.common.contracts import MOOD_MAX, MOOD_MIN, ChatMessage, HelpStep, Memory

PROFILE = (
    "Pedro, 30 e poucos, joga à noite depois do trampo. Curte soulslike, JRPG e roguelike; "
    "zerou Elden Ring e Sekiro, platinou Persona 5. Assiste anime de temporada (Frieren, "
    "Dandadan). Fala com gíria, odeia resposta longa e odeia spoiler. Usa Linux com KDE."
)

MEMORIES = [
    Memory(kind="fato", body="Ele travou na Malenia na semana passada e pediu só pista.", score=0.91),
    Memory(kind="gosto", body="Prefere build de destreza com katana.", score=0.88),
    Memory(kind="fato", body="Está esperando a segunda temporada de Frieren.", score=0.70),
    Memory(kind="gosto", body="Não gosta de jogo com microtransação agressiva.", score=0.65),
    Memory(kind="fato", body="Joga com controle de PS5 no PC.", score=0.60),
]

HISTORY = [
    ChatMessage(role="user", content="quem dublou o Gojo em japonês?"),
    ChatMessage(role="assistant", content="Yuichi Nakamura, o mesmo do Gray de Fairy Tail."),
    ChatMessage(role="user", content="e o Sukuna?"),
    ChatMessage(role="assistant", content="Junichi Suwabe. Voz de vilão que dá medo, né?"),
]

GAME = GameContext(
    name="Elden Ring",
    genre="soulslike",
    session_minutes=95,
    help_topic="Malenia",
    help_step=HelpStep.HINT,
)


def _system(prompt) -> str:
    assert prompt.messages[0].role == "system"
    return prompt.messages[0].content


# --- persona ------------------------------------------------------------------------------------


def test_persona_tem_cerca_de_500_tokens():
    # Teto 560 (era 520): a 3.9 juntou a regra "nunca afirmar capacidade sem ferramenta" (~40 tokens).
    # Teto 580: linha do apelido "Condessa" (ativação e vocativo, ~30 tokens).
    # Teto 660: linha de jeito e gosto decidida pelo Conselho da Condessa (~75 tokens).
    # Teto 700: regra da frase de espera antes de ferramenta demorada e resposta em lotes (~45).
    tokens = estimate_tokens(load_persona())
    assert 400 <= tokens <= 700


def test_persona_cobre_os_tracos():
    text = load_persona().lower()
    for termo in ("cultura pop", "casual", "sem papas na língua", "honesta", "pista", "spoiler"):
        assert termo in text


def test_persona_proibe_markdown_e_listas_na_fala():
    linha = next(x for x in load_persona().splitlines() if "nunca use markdown" in x.lower())
    assert "lista" in linha and "voz" in linha


# --- montagem completa --------------------------------------------------------------------------


def test_prompt_completo_cabe_no_limite_com_perfil_e_memorias():
    prompt = build_prompt(mood=2, profile=PROFILE, game=GAME, memories=MEMORIES, history=HISTORY)
    assert prompt.tokens <= MAX_PROMPT_TOKENS
    assert prompt.tokens == count_message_tokens(prompt.messages)
    assert prompt.dropped_memories == 0
    assert prompt.dropped_turns == 0
    assert not prompt.profile_truncated
    system = _system(prompt)
    assert load_persona() in system
    assert PROFILE in system
    assert MOOD_TONES[2] in system
    assert "Elden Ring" in system and "95 min" in system and "soulslike" in system
    for mem in MEMORIES:
        assert mem.body in system
    assert [m.content for m in prompt.messages[1:]] == [m.content for m in HISTORY]


def test_with_user_anexa_a_fala_atual():
    prompt = build_prompt(mood=1, history=HISTORY)
    msgs = prompt.with_user("e o Yuji?")
    assert msgs[-1] == ChatMessage(role="user", content="e o Yuji?")
    assert msgs[:-1] == list(prompt.messages)


def test_sem_perfil_jogo_nem_memorias():
    prompt = build_prompt(mood=0)
    assert len(prompt.messages) == 1
    system = _system(prompt)
    assert "## Perfil" not in system and "## Memórias" not in system and "## Jogo" not in system


# --- humor --------------------------------------------------------------------------------------


@pytest.mark.parametrize("mood", range(MOOD_MIN, MOOD_MAX + 1))
def test_cada_nivel_de_humor_tem_tom_proprio(mood):
    assert estimate_tokens(MOOD_TONES[mood]) <= 45
    assert MOOD_TONES[mood] in _system(build_prompt(mood=mood))


def test_tons_sao_distintos():
    assert len(set(MOOD_TONES.values())) == MOOD_MAX - MOOD_MIN + 1


def test_humor_fora_da_faixa_e_ajustado():
    assert MOOD_TONES[MOOD_MAX] in _system(build_prompt(mood=9))
    assert MOOD_TONES[MOOD_MIN] in _system(build_prompt(mood=-3))
    with pytest.raises(TypeError):
        build_prompt(mood="3")  # type: ignore[arg-type]


# --- degrau de ajuda ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("step", "esperado"),
    [
        (None, "comece pela pista"),
        (HelpStep.HINT, "já deu pista; agora vá para dica direta"),
        (HelpStep.DIRECT, "já deu dica direta; agora vá para solução"),
        (HelpStep.SOLUTION, "já deu a solução"),
    ],
)
def test_degrau_de_ajuda(step, esperado):
    game = GameContext(name="Hollow Knight", help_topic="Hornet", help_step=step)
    assert esperado in _system(build_prompt(mood=2, game=game))


def test_jogo_sem_trecho_nao_fala_de_degrau():
    system = _system(build_prompt(mood=2, game=GameContext(name="Hades")))
    assert system.endswith("## Jogo agora\nJogando: Hades.")


# --- tokens e corte -----------------------------------------------------------------------------


def test_estimativa_de_tokens():
    assert estimate_tokens("") == 0
    assert estimate_tokens("a") == 1
    assert estimate_tokens("x" * 35) == 10
    assert estimate_tokens("x" * 36) == 11


def test_truncate_respeita_o_limite():
    texto = "palavra " * 200
    cortado = truncate_to_tokens(texto, 20)
    assert estimate_tokens(cortado) <= 20
    assert cortado.endswith("…")
    assert truncate_to_tokens("curto", 20) == "curto"
    assert truncate_to_tokens(texto, 0) == ""


def test_perfil_longo_e_cortado_em_300_tokens():
    perfil = "gosta de JRPG e de anime de temporada. " * 100
    prompt = build_prompt(mood=2, profile=perfil)
    assert prompt.profile_truncated
    secao = _system(prompt).split("## Perfil dele\n", 1)[1]
    assert estimate_tokens(secao) <= PROFILE_MAX_TOKENS
    assert prompt.tokens <= MAX_PROMPT_TOKENS


def test_no_maximo_5_memorias_ordenadas_por_similaridade():
    mems = [Memory(kind="fato", body=f"memória número {i}", score=i / 10) for i in range(8)]
    system = _system(build_prompt(mood=2, memories=mems))
    linhas = [ln for ln in system.split("## Memórias\n", 1)[1].splitlines() if ln.startswith("- ")]
    assert linhas == [f"- memória número {i}" for i in (7, 6, 5, 4, 3)]


def test_memorias_longas_respeitam_teto_de_400():
    mems = [Memory(kind="fato", body="detalhe de lore " * 60, score=0.9 - i / 10) for i in range(5)]
    prompt = build_prompt(mood=2, memories=mems)
    secao = _system(prompt).split("## Memórias\n", 1)[1]
    assert estimate_tokens(secao) <= MEMORIES_MAX_TOKENS
    assert 0 < prompt.dropped_memories < 5
    assert prompt.tokens <= MAX_PROMPT_TOKENS


def test_so_os_ultimos_2_turnos_e_teto_de_180():
    hist = []
    for i in range(6):
        hist.append(ChatMessage(role="user", content=f"pergunta {i}"))
        hist.append(ChatMessage(role="tool", content="resultado", tool_call_id="t"))
        hist.append(ChatMessage(role="assistant", content=f"resposta {i}"))
    prompt = build_prompt(mood=2, history=hist)
    esperado = ["pergunta 4", "resposta 4", "pergunta 5", "resposta 5"]
    assert [m.content for m in prompt.messages[1:]] == esperado

    longos = [ChatMessage(role=m.role, content=m.content + " blá" * 300) for m in HISTORY]
    prompt = build_prompt(mood=2, history=longos)
    assert count_message_tokens(prompt.messages[1:]) <= TURNS_MAX_TOKENS
    assert prompt.messages[1].role == "user"


def test_tudo_no_maximo_nunca_passa_do_teto():
    perfil = "x" * 5000
    mems = [Memory(kind="fato", body="y" * 2000, score=0.5) for _ in range(10)]
    hist = [ChatMessage(role=r, content="z" * 2000) for r in ("user", "assistant") * 5]
    game = GameContext(
        name="N" * 500, genre="G" * 500, session_minutes=999, help_topic="T" * 500, help_step=HelpStep.DIRECT
    )
    for mood in range(MOOD_MIN, MOOD_MAX + 1):
        prompt = build_prompt(mood=mood, profile=perfil, game=game, memories=mems, history=hist)
        assert prompt.tokens <= MAX_PROMPT_TOKENS


def test_corte_total_tira_memorias_depois_turnos_depois_perfil():
    persona = "p" * 3500  # 1000 tokens: força o corte global
    prompt = build_prompt(
        mood=2, persona=persona, profile=PROFILE, memories=MEMORIES, history=HISTORY, max_tokens=1_100
    )
    assert prompt.tokens <= 1_100
    assert prompt.dropped_memories == 5
    assert prompt.dropped_turns == 2
    assert prompt.profile_truncated

    # Com folga para os turnos, só as memórias saem (da menos parecida para a mais).
    sem_mem = build_prompt(mood=2, persona=persona, history=HISTORY, max_tokens=1_100)
    prompt = build_prompt(
        mood=2,
        persona=persona,
        memories=MEMORIES,
        history=HISTORY,
        max_tokens=sem_mem.tokens + 25,
    )
    assert prompt.dropped_turns == 0
    assert 0 < prompt.dropped_memories < 5
    assert MEMORIES[0].body in _system(prompt)
    assert MEMORIES[-1].body not in _system(prompt)


def test_persona_grande_demais_falha():
    with pytest.raises(PromptTooLarge):
        build_prompt(mood=2, persona="p" * 7000)


# --- avaliação ----------------------------------------------------------------------------------


def test_eval_persona_tem_10_perguntas():
    data = yaml.safe_load((Path(__file__).with_name("eval_persona.yaml")).read_text(encoding="utf-8"))
    casos = data["cases"]
    assert len(casos) == 10
    assert len({c["id"] for c in casos}) == 10
    for caso in casos:
        assert caso["pergunta"] and caso["esperado"]
        assert MOOD_MIN <= caso.get("humor", 2) <= MOOD_MAX
