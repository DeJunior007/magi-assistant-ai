"""Perguntas sobre novidades (6.12): ``news_query``, "novidades?" local e fallback para pesquisa."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from magi.agent.graph import GraphAgent
from magi.agent.self_model import SelfModel
from magi.agent.tools.news import (
    MAX_ITEMS,
    SAY_ASK_MORE,
    SAY_LAST,
    SAY_RADIO_DECLINED,
    NewsQuery,
    NewsQueryTool,
    WhatsNewHandler,
    topic_matches,
)
from magi.common.contracts import (
    ARG_DECLINED,
    ARG_QUIET,
    ActionRequest,
    ActionResult,
    CardLevel,
    ChatReply,
    Intent,
    IntentId,
    NewsItem,
    NewsLevel,
    TurnContext,
    WakeSource,
)
from magi.core.assemble import _wire_news_agent, _wire_news_query
from magi.core.compose import compose
from magi.news.spoiler import ReleaseStore

NOW = datetime(2026, 10, 3, 12, tzinfo=UTC)
CTX = TurnContext(satellite="desktop", source=WakeSource.WAKE, started_at=NOW)
NO_SPOILER = {"has": False}


def item(i: int, title: str, franchise: str | None = None, *, priority: float = 0.5, hours: float = 1,
         spoiler=NO_SPOILER, level=NewsLevel.NORMAL) -> NewsItem:
    return NewsItem(title=title, summary=f"resumo {i}", franchise=franchise, kind="anuncio", spoiler=spoiler,
                    priority=priority, level=level, first_seen=NOW - timedelta(hours=hours), id=i)


class FakeRepo:
    def __init__(self, items: list[NewsItem]) -> None:
        self.items = items
        self.delivered: list[int] = []

    async def search_items(self, *, franchise=None, embedding=None, limit=5):
        return [i for i in self.items if franchise is None or topic_matches(i, franchise)][:limit]

    async def undelivered(self, levels, limit=5):
        got = [i for i in self.items if i.level in levels and i.id not in self.delivered]
        return sorted(got, key=lambda i: -(i.priority or 0))[:limit]

    async def mark_delivered(self, item_id, at):
        self.delivered.append(item_id)

    async def item_links(self, ids):
        return {i: [f"https://news.example/{i}/manchete-original"] for i in ids}

    async def franchise_prefs(self):
        return []

    async def set_franchise_pref(self, pref):
        pass

    async def progress(self, franchise):
        return []


class FakeSearch:
    def __init__(self) -> None:
        self.questions: list[str] = []

    async def run(self, args, ctx, text=""):
        self.questions.append(args["question"])
        return ActionResult(ok=True, speech="Achei na web.", full_text="Fontes:\n- x — https://web.example/")


def query(items, tmp_path, search=None) -> tuple[NewsQuery, FakeRepo]:
    repo = FakeRepo(items)
    q = NewsQuery(repo, search, now=lambda: NOW, store=ReleaseStore(tmp_path / "rel.json"))
    return q, repo


async def test_silksong_responde_com_links(tmp_path):
    q, _ = query([
        item(1, "Silksong recebe patch 1.1", "Hollow Knight: Silksong", priority=0.9),
        item(2, "Persona 6 anunciado", "Persona"),
    ], tmp_path)
    res = await NewsQueryTool(q).run({"topic": "silksong"}, CTX)
    assert res.ok
    assert "Silksong recebe patch 1.1" in res.speech
    assert res.speech.count(".") <= 3  # ≤ 2 frases (o título pode ter ponto)
    assert "https://news.example/1/manchete-original" in res.full_text
    assert "Persona" not in res.full_text
    assert [(c.level, c.url) for c in res.cards] == [(CardLevel.LINK, "https://news.example/1/manchete-original")]


async def test_casamento_tolerante():
    it = item(1, "Novo trailer", "Pokémon Legends: Z-A")
    assert topic_matches(it, "pokemon legends")
    assert topic_matches(it, "POKÉMON")
    assert not topic_matches(it, "poke")
    assert not topic_matches(it, "")


async def test_spoiler_nunca_vaza(tmp_path):
    secret = "Hornet morre no final de Silksong"
    big = {"has": True, "of": "Silksong, final", "safe_title": "Silksong: detalhe do final", "size": 0.9}
    q, repo = query([item(1, secret, "Hollow Knight: Silksong", spoiler=big)], tmp_path)
    for res in (await NewsQueryTool(q).run({"topic": "silksong"}, CTX), await q.whats_new()):
        dump = " ".join([res.speech, res.full_text or "", *(c.title + c.url for c in res.cards)])
        assert "morre" not in dump and "resumo" not in dump and "manchete-original" not in dump
        assert "spoiler" in dump


async def test_vazio_cai_para_pesquisa(tmp_path):
    search = FakeSearch()
    q, _ = query([item(1, "Persona 6 anunciado", "Persona"),
                  item(2, "Silksong velho", "Silksong", hours=24 * 40)], tmp_path, search)
    res = await NewsQueryTool(q).run({"topic": "Silksong", "days": 7}, CTX)
    assert res.speech == "Achei na web."
    assert search.questions == ["Quais as novidades mais recentes sobre Silksong?"]


async def test_vazio_sem_pesquisa_diz_que_nao_tem(tmp_path):
    q, _ = query([], tmp_path)
    res = await NewsQueryTool(q).run({"topic": "Silksong"}, CTX)
    assert "nada guardado sobre Silksong" in res.speech


async def test_limite_de_5_ordenado(tmp_path):
    items = [item(i, f"Silksong notícia {i}", "Silksong", priority=i / 10) for i in range(1, 9)]
    q, _ = query(items, tmp_path)
    res = await NewsQueryTool(q).run({"topic": "silksong"}, CTX)
    assert len(res.cards) == MAX_ITEMS
    assert [c.title for c in res.cards] == [f"Silksong notícia {i}" for i in (8, 7, 6, 5, 4)]
    assert res.speech.startswith("Tem 5 novidades de silksong. A principal: Silksong notícia 8.")


class FakeNarrator:
    """Chat da tarefa ``news``: devolve a narração "em português" da manchete recebida."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[str] = []

    async def chat(self, messages, *, tools=(), json_mode=False, personal):
        user = messages[-1].content
        self.calls.append(user)
        if self.fail:
            raise TimeoutError
        title = next(line for line in user.splitlines() if line.startswith("Manchete: "))[10:]
        return ChatReply(text=f"Saiu {title} em português")


NEWS_REQ = ActionRequest(intent=Intent(id=IntentId.NEWS_WHATS_NEW.value), ctx=CTX, text="novidades?")


async def test_novidades_modo_radio_uma_por_vez(tmp_path):
    items = [item(i, f"Notícia {i}", "X", priority=i / 10) for i in range(1, 4)]
    items.append(item(9, "Guardada", "X", priority=1.0, level=NewsLevel.GUARDADA))
    q, repo = query(items, tmp_path)
    q.chat = narrator = FakeNarrator()
    h = WhatsNewHandler(q)
    res = await h.run(NEWS_REQ)
    assert res.speech == f"Tem 3 novidades. Saiu Notícia 3 em português. {SAY_ASK_MORE}"
    assert res.long_speech and res.needs_confirmation and len(res.cards) == 1
    assert repo.delivered == [3]  # só a que foi falada
    assert res.on_confirm is not None and res.on_confirm.args[ARG_QUIET]
    assert res.on_confirm.args[ARG_DECLINED] == SAY_RADIO_DECLINED
    nxt = await h.run(res.on_confirm)  # "sim"
    assert nxt.speech == f"Saiu Notícia 2 em português. {SAY_ASK_MORE}"  # sem repetir o "Tem N"
    last = await h.run(nxt.on_confirm)
    assert last.speech == f"Saiu Notícia 1 em português. {SAY_LAST}" and not last.needs_confirmation
    assert sorted(repo.delivered) == [1, 2, 3] and "Guardada" not in " ".join(narrator.calls)
    assert len(narrator.calls) == 3  # a próxima foi narrada adiantada, uma vez só
    assert (await h.run(NEWS_REQ)).speech == "Nada de novo por enquanto."


async def test_novidades_sem_modelo_fala_a_manchete(tmp_path):
    q, _ = query([item(1, "Kena: Scars of Kosmora delayed to 2027", "Kena")], tmp_path)
    q.chat = FakeNarrator(fail=True)
    res = await WhatsNewHandler(q).run(NEWS_REQ)
    assert res.speech == f"Tem uma novidade. Kena: Scars of Kosmora delayed to 2027. {SAY_LAST}"


def test_fala_longa_nao_e_cortada():
    long = ActionResult(ok=True, speech="Um. Dois. Três.", long_speech=True)
    assert compose(long).speech == "Um. Dois. Três."
    assert compose(ActionResult(ok=True, speech="Um. Dois. Três.")).speech == "Um. Dois."


async def test_sem_banco(tmp_path):
    res = await WhatsNewHandler().run(
        ActionRequest(intent=Intent(id=IntentId.NEWS_WHATS_NEW.value), ctx=CTX, text="novidades?"))
    assert not res.ok and "banco" in res.speech


@pytest.mark.parametrize("with_repo", [True, False])
def test_ficha_lista_news_query(with_repo, tmp_path):
    repo = FakeRepo([]) if with_repo else None
    model = SelfModel()
    agent = GraphAgent(SimpleNamespace(), [])
    core = SimpleNamespace(repos=SimpleNamespace(news=repo), news_query=None, self_model=model,
                           providers=None, deps=SimpleNamespace(agent=agent))
    found = _wire_news_query(core, [])
    assert [type(h) for h in found] == [WhatsNewHandler]
    _wire_news_agent(core)
    assert ("news_query" in model.tool_names()) is with_repo
    assert any("novidades" in g for g in model.gaps()) is not with_repo


async def test_narracao_sem_cumprimento(tmp_path):
    class Greeter(FakeNarrator):
        async def chat(self, messages, *, tools=(), json_mode=False, personal):
            return ChatReply(text="Atenção, Pedro, saiu o trailer novo")

    q, _ = query([item(1, "New trailer", "X")], tmp_path)
    q.chat = Greeter()
    res = await WhatsNewHandler(q).run(NEWS_REQ)
    assert res.speech == f"Tem uma novidade. Saiu o trailer novo. {SAY_LAST}"
