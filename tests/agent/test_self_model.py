"""Autoconhecimento (3.9): ficha viva, "Sobre você", ``self_info`` e ``magi.help``."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from magi.agent.graph import GraphAgent, short_speech
from magi.agent.prompt import MAX_PROMPT_TOKENS, SELF_MAX_TOKENS, build_prompt, estimate_tokens
from magi.agent.self_model import TOPICS, HelpHandler, SelfInfoTool, SelfModel, wake_word_name
from magi.agent.tools.system import system_tools
from magi.common.contracts import (
    ActionRequest,
    ActionResult,
    BudgetStatus,
    ChatReply,
    Intent,
    IntentId,
    ProviderTask,
    RouteKind,
    ToolCall,
    TurnContext,
    WakeSource,
)
from magi.core.actions import Registry
from magi.core.catalog import MemoryAliasStore, SteamCatalog
from magi.core.router import LocalRouter

CTX = TurnContext(satellite="local", source=WakeSource.PTT, started_at=datetime(2026, 1, 1))
RAW = {
    "satellite": {"wake_model": "hey_jarvis_v0.1", "ptt_key": "Pause"},
    "tasks": {"tts": {"provider": "openai", "model": "x", "voice": "<escolher>"}},
    "alerts": {"enabled": True},
    "news": {"delivery": {"enabled": False}},
}


class Handler:
    def __init__(self, *intents: str) -> None:
        self.intents = frozenset(intents)

    async def run(self, req: ActionRequest) -> ActionResult:
        return ActionResult(ok=True, speech="ok")


def _model(**kw) -> SelfModel:
    async def budget() -> BudgetStatus:
        return BudgetStatus(spent_usd=1.25, cap_usd=5.0)

    base = dict(raw=RAW, spotify=lambda: False, missing_keys=lambda: ["search (gemini)"], budget=budget)
    base.update(kw)
    return SelfModel(**base)


def test_wake_word_pelo_arquivo_do_modelo() -> None:
    assert wake_word_name("hey_jarvis") == ("hey Jarvis", True)
    assert wake_word_name("/x/hey_jarvis_v0.1.onnx") == ("hey Jarvis", True)
    assert wake_word_name("~/m/ei_magui.onnx") == ("ei Magui", False)


def test_ficha_vem_do_intents_yaml_e_do_registro() -> None:
    reg = Registry([Handler(IntentId.GAME_OPEN, IntentId.VOLUME_SET)])
    m = _model(registry=reg)
    names = {a.name: [c.id for c in a.commands] for a in m.areas()}
    assert names["Jogos"] == [IntentId.GAME_OPEN]
    assert names["Volume"] == [IntentId.VOLUME_SET]
    assert "confirm.yes" not in str(names)  # controle do turno não é comando
    gaps = " ".join(m.gaps())
    assert "fechar o jogo" in gaps  # sem handler: vira limite
    assert "ver a tela" in gaps and "pesquisar na internet" in gaps  # sem ferramenta


def test_intent_novo_aparece_na_ficha(tmp_path: Path) -> None:
    y = tmp_path / "intents.yaml"
    y.write_text(
        "intents:\n"
        "  - id: game.open\n    label: 'abrir {game}'\n    phrases: ['abre {game}']\n"
        "  - id: pizza.order\n    label: 'pedir pizza'\n    phrases: ['pede uma pizza', 'quero pizza']\n",
        encoding="utf-8",
    )
    m = _model(intents_path=y)
    areas = {a.name: a for a in m.areas()}
    assert areas["Pizza"].commands[0].examples == ("pede uma pizza", "quero pizza")
    assert areas["Jogos"].commands[0].examples == ("abre <jogo>",)
    assert "Pizza" in m.about_section()
    assert "pedir pizza" in m.commands_text()


def test_estado_reflete_config_e_leituras() -> None:
    s = _model(in_call=lambda: True).state()
    assert s.spotify_connected is False and s.in_call is True
    assert s.wake_word == "hey Jarvis" and s.wake_provisional
    assert s.ptt == ("tecla Pause", "PS+Share no DualSense")
    assert s.voice is None  # placeholder do exemplo
    assert s.alerts_on and not s.news_on
    assert s.missing_keys == ("search (gemini)",)
    # leitura que falha vira "não sei", não derruba
    assert _model(spotify=lambda: 1 / 0).state().spotify_connected is None


def test_sobre_voce_cabe_e_diz_o_essencial() -> None:
    reg = Registry([Handler(IntentId.GAME_OPEN, IntentId.MUSIC_PLAY)])
    m = _model(registry=reg)
    about = m.about_section()
    assert estimate_tokens(about) <= SELF_MAX_TOKENS
    assert "Magui" in about and "hey Jarvis" in about and "Pause" in about
    assert "Spotify desconectado" in about
    assert "Ainda não sabe" in about and "self_info" in about
    prompt = build_prompt(mood=2, about=about)
    assert about in prompt.messages[0].content
    assert prompt.tokens <= MAX_PROMPT_TOKENS


def test_sobre_voce_gigante_e_cortado() -> None:
    prompt = build_prompt(mood=2, about="x " * 2000)
    assert "## Sobre você" in prompt.messages[0].content
    assert prompt.tokens <= MAX_PROMPT_TOKENS


@pytest.mark.parametrize("topic", TOPICS)
async def test_self_info_por_topico(topic: str) -> None:
    m = _model(registry=Registry([Handler(IntentId.GAME_OPEN)]))
    res = await SelfInfoTool(m).run({"topic": topic}, CTX)
    assert res.ok and res.speech and res.full_text and res.cards
    assert short_speech(res.speech) == res.speech  # ≤ 2 frases


async def test_self_info_conteudo() -> None:
    m = _model(registry=Registry([Handler(IntentId.GAME_OPEN)]))
    gasto = await m.info("gasto", CTX)
    assert "1,25" in gasto.speech and "5,00" in gasto.speech and "25%" in gasto.speech
    estado = await m.info("estado", CTX)
    assert "Spotify desconectado" in estado.speech and "fora de call" in estado.speech
    assert "Chaves faltando: search (gemini)" in estado.full_text
    assert "hey Jarvis" in (await m.info("ativacao", CTX)).speech
    assert "ver a tela" in (await m.info("limites", CTX)).full_text
    assert "abre <jogo>" in (await m.info("comandos", CTX)).full_text
    assert (await m.info("qualquer", CTX)).cards[0].title.endswith("capacidades")
    sem = await SelfModel().info("gasto", CTX)
    assert "Não consigo" in sem.speech


@pytest.mark.parametrize(
    "texto",
    ["o que você sabe fazer?", "quais são seus comandos", "me ajuda com os comandos", "quem é você",
     "como eu te chamo"],
)
def test_magi_help_e_local(texto: str, tmp_path: Path) -> None:
    (tmp_path / "steamapps").mkdir()
    router = LocalRouter(SteamCatalog(tmp_path, aliases=MemoryAliasStore({})))
    res = router.route(texto, CTX)
    assert res.kind is RouteKind.LOCAL and res.intent is not None
    assert res.intent.id == IntentId.HELP


async def test_magi_help_responde_sem_llm() -> None:
    m = _model()
    reg = Registry([Handler(IntentId.GAME_OPEN), HelpHandler(m)])
    m.registry = reg
    res = await reg.run(ActionRequest(intent=Intent(IntentId.HELP.value), ctx=CTX))
    assert res.ok and "Magui" in res.speech and "hey Jarvis" in res.speech
    assert short_speech(res.speech) == res.speech
    assert "Jogos:" in res.full_text and "Sobre mim:" in res.full_text
    assert res.cards


class _Chat:
    def __init__(self, replies: list[ChatReply]) -> None:
        self.replies = replies
        self.seen: list = []

    async def chat(self, messages, *, tools=(), json_mode=False, personal):
        self.seen.append((list(messages), tools))
        return self.replies.pop(0)


class _Providers:
    def __init__(self, chat: _Chat) -> None:
        self._chat = chat

    def chat(self, task: ProviderTask = ProviderTask.AGENT) -> _Chat:
        return self._chat


async def test_agente_recebe_sobre_voce_e_self_info() -> None:
    m = _model()
    reg = Registry([Handler(IntentId.GAME_OPEN)])
    m.registry = reg
    tools = [*system_tools(reg), SelfInfoTool(m)]
    m.tools = tuple(t.spec for t in tools)
    chat = _Chat([
        ChatReply(text="", tool_calls=(ToolCall(id="1", name="self_info", arguments={"topic": "comandos"}),)),
        ChatReply(text="Tá na tela a lista. Pede aí."),
    ])
    agent = GraphAgent(_Providers(chat), tools, about=m.about_section)
    res = await agent.answer("quais comandos você tem fora os básicos?", CTX)
    system = chat.seen[0][0][0].content
    assert "## Sobre você" in system and "self_info" in system
    assert "self_info" in [t.name for t in chat.seen[0][1]]
    assert res.speech == "Tá na tela a lista. Pede aí."
    assert "Jogos:" in res.full_text and res.cards
