"""Registro de provedores: rodízio com troca de chave, dados pessoais, orçamento (3.1, R21)."""

from __future__ import annotations

import pytest

from magi.common.config import ConfigError
from magi.common.contracts import (
    BudgetExceeded,
    ChatMessage,
    ChatProvider,
    ChatReply,
    EmbeddingProvider,
    NoKeyAvailable,
    PcmFormat,
    PersonalDataRefused,
    ProviderRegistry,
    ProviderTask,
    QuotaExhausted,
    SearchProvider,
    SearchResult,
    SttProvider,
    Transcript,
    TtsProvider,
    VisionProvider,
)
from magi.providers.base import CallCtx
from magi.providers.keypool import FreeQuotaExhausted, KeyRejected
from magi.providers.registry import Registry, tts_segments


class FakeBackend:
    """Backend falso: ``reject[nome_da_chave] = status`` faz a chave ser recusada."""

    def __init__(self, cfg, log: list[str]) -> None:
        self.cfg = cfg
        self.log = log
        self.reject: dict[str, int] = {}
        self.keys: list[str] = []
        self.ctxs: list[CallCtx] = []
        self.segments: list[str] = []

    def _use(self, key, ctx) -> None:
        self.keys.append(key.name)
        self.ctxs.append(ctx)
        self.log.append(f"call:{key.name}")
        if key.name in self.reject:
            raise KeyRejected(self.reject[key.name])

    async def transcribe(self, key, ctx, audio, fmt, hint, language):
        self._use(key, ctx)
        return Transcript.raw("oi"), ctx.usage(1.0)

    def tts_format(self, ctx):
        return PcmFormat(rate=24_000)

    async def synthesize(self, key, ctx, text):
        self._use(key, ctx)
        self.segments.append(text)
        yield text.encode()[:2]
        yield b"|"

    async def chat(self, key, ctx, messages, tools, json_mode):
        self._use(key, ctx)
        return ChatReply(text="ok", usage=ctx.usage(10, 2))

    async def ask(self, key, ctx, question, image, mime):
        self._use(key, ctx)
        return ChatReply(text="vejo", usage=ctx.usage(5, 1))

    def embed_dimensions(self, ctx):
        return int(ctx.options.get("dimensions", 4))

    async def embed(self, key, ctx, texts):
        self._use(key, ctx)
        return [[0.0] * self.embed_dimensions(ctx) for _ in texts], ctx.usage(len(texts))

    async def search(self, key, ctx, query):
        self._use(key, ctx)
        return SearchResult(answer="achei", usage=ctx.usage(3, 3))


@pytest.fixture
def env(make_config, budget, clock, get_secret):
    log = budget.log
    fakes: dict[str, FakeBackend] = {}

    def factory(cfg):
        fakes[cfg.name] = FakeBackend(cfg, log)
        return fakes[cfg.name]

    reg = Registry(
        make_config(),
        budget,
        backends={"openai": factory, "gemini": factory},
        get_secret=get_secret,
        clock=clock,
    )

    class Env:
        pass

    e = Env()
    e.reg, e.budget, e.clock, e.log, e.fakes = reg, budget, clock, log, fakes
    return e


def _msgs():
    return [ChatMessage(role="user", content="oi")]


async def test_objetos_satisfazem_os_contratos(env):
    reg = env.reg
    assert isinstance(reg, ProviderRegistry)
    assert isinstance(reg.stt(), SttProvider)
    assert isinstance(reg.tts(), TtsProvider)
    assert isinstance(reg.chat(), ChatProvider)
    assert isinstance(reg.vision(), VisionProvider)
    assert isinstance(reg.embeddings(), EmbeddingProvider)
    assert isinstance(reg.search(), SearchProvider)


async def test_monta_por_tarefa_conforme_config(env):
    reg = env.reg
    assert (reg.chat().name, reg.chat().model, reg.chat().free_tier) == ("openai", "chat-x", False)
    news = reg.chat(ProviderTask.NEWS)
    assert (news.name, news.model, news.free_tier) == ("gemini", "news-x", True)
    assert reg.search().name == "gemini"
    assert reg.embeddings().dimensions == 8
    assert reg.embeddings(ProviderTask.NEWS).model == "gemb-x"
    assert reg.tts().output_format.rate == 24_000
    assert reg.chat() is reg.chat()
    with pytest.raises(ValueError):
        reg.chat(ProviderTask.STT)
    with pytest.raises(ValueError):
        reg.embeddings(ProviderTask.AGENT)


async def test_429_troca_de_chave(env):
    chat = env.reg.chat()
    await chat.chat(_msgs(), personal=True)  # inicializa o backend
    fake = env.fakes["openai"]
    fake.keys.clear()
    fake.reject["openai-2"] = 429
    reply = await chat.chat(_msgs(), personal=True)  # rodízio: openai-2 recusa -> openai-1
    assert reply.text == "ok"
    assert fake.keys == ["openai-2", "openai-1"]
    pool = env.reg.pool("openai")
    assert pool.available() == 1
    fake.keys.clear()
    for _ in range(3):
        await chat.chat(_msgs(), personal=True)
    assert fake.keys == ["openai-1"] * 3  # a chave em espera fica fora do rodízio
    env.clock.advance(60)
    del fake.reject["openai-2"]
    assert pool.available() == 2


async def test_todas_as_chaves_recusadas(env):
    chat = env.reg.chat()
    await chat.chat(_msgs(), personal=False)
    fake = env.fakes["openai"]
    fake.reject.update({"openai-1": 401, "openai-2": 403})
    with pytest.raises(NoKeyAvailable):
        await chat.chat(_msgs(), personal=False)
    fake.keys.clear()
    with pytest.raises(NoKeyAvailable):  # todas em espera: nem chega a chamar
        await chat.chat(_msgs(), personal=False)
    assert fake.keys == []


async def test_cota_gratuita_esgotada_e_quota_exhausted(env):
    news = env.reg.chat(ProviderTask.NEWS)
    await news.chat(_msgs(), personal=False)
    env.fakes["gemini"].reject.update({"gemini-1": 429, "gemini-2": 429})
    with pytest.raises(FreeQuotaExhausted) as exc:
        await news.chat(_msgs(), personal=False)
    assert isinstance(exc.value, QuotaExhausted) and isinstance(exc.value, NoKeyAvailable)


async def test_sem_chaves_no_keyring(make_config, budget):
    reg = Registry(make_config(), budget, get_secret=lambda name: None)
    with pytest.raises(NoKeyAvailable):
        await reg.chat().chat(_msgs(), personal=False)


async def test_bloqueia_dados_pessoais_em_cota_gratuita(env):
    reg = env.reg
    with pytest.raises(PersonalDataRefused):
        await reg.search().search("onde fica X", personal=True)
    with pytest.raises(PersonalDataRefused):
        await reg.chat(ProviderTask.NEWS).chat(_msgs(), personal=True)
    with pytest.raises(PersonalDataRefused):
        await reg.embeddings(ProviderTask.NEWS).embed(["memória"], personal=True)
    assert env.log == []  # nem orçamento nem backend foram tocados
    res = await reg.search().search("onde fica X", personal=False)
    assert res.answer == "achei"


async def test_bloqueia_tudo_que_e_pessoal_quando_o_provedor_e_gratuito(make_config, budget, get_secret):
    free_openai = {"keys": ["openai-1"], "free_tier": True}
    cfg = make_config(providers={"openai": free_openai, "gemini": {"keys": ["gemini-1"], "free_tier": True}})
    log: list[str] = []
    reg = Registry(cfg, budget, backends={"openai": lambda c: FakeBackend(c, log)}, get_secret=get_secret)
    with pytest.raises(PersonalDataRefused):
        await reg.stt().transcribe(b"\0\0", PcmFormat(), personal=True)
    with pytest.raises(PersonalDataRefused):
        reg.tts().synthesize("oi", personal=True)  # recusa na chamada, antes de iterar
    with pytest.raises(PersonalDataRefused):
        await reg.vision().ask("o que é isso?", b"png", personal=True)
    assert log == []


async def test_ordem_ensure_allowed_chamada_record(env):
    await env.reg.chat().chat(_msgs(), personal=True)
    assert env.log == ["ensure:agent", "call:openai-1", "record:agent"]
    u = env.budget.recorded[0]
    got = (u.provider, u.task, u.model, u.input_units, u.output_units)
    assert got == ("openai", "agent", "chat-x", 10, 2)


async def test_record_uma_vez_mesmo_com_troca_de_chave(env):
    chat = env.reg.chat()
    await chat.chat(_msgs(), personal=False)
    env.log.clear()
    env.fakes["openai"].reject["openai-2"] = 429
    await chat.chat(_msgs(), personal=False)
    assert env.log == ["ensure:agent", "call:openai-2", "call:openai-1", "record:agent"]


async def test_budget_exceeded_nao_chama_o_provedor(env):
    env.budget.blocked = True
    with pytest.raises(BudgetExceeded):
        await env.reg.vision().ask("e aí?", b"img", personal=True)
    assert env.log == ["ensure:vision"]


async def test_provedor_gratuito_nao_passa_pelo_orcamento(env):
    env.budget.blocked = True
    await env.reg.search().search("x", personal=False)
    assert env.log == ["call:gemini-1"]


async def test_stt_e_embeddings(env):
    t = await env.reg.stt().transcribe(b"\0" * 32000, PcmFormat(), hint="Magui", personal=True)
    assert t.heard == "oi"
    vecs = await env.reg.embeddings().embed(["a", "b"], personal=True)
    assert len(vecs) == 2 and len(vecs[0]) == 8
    assert await env.reg.embeddings().embed([], personal=True) == []
    assert env.log == ["ensure:stt", "call:openai-1", "record:stt", "ensure:embeddings", "call:openai-2",
                       "record:embeddings"]  # fmt: skip


async def test_tts_em_frases_com_troca_de_chave(env):
    async def fluxo():
        for p in ["Olá, ", "tudo bem? ", "Eu sou ", "a Magui."]:
            yield p

    tts = env.reg.tts()
    out = b"".join([c async for c in tts.synthesize("Oi.", personal=True)])
    assert out == b"Oi|"
    fake = env.fakes["openai"]
    fake.reject["openai-2"] = 429
    env.log.clear()
    chunks = [c async for c in tts.synthesize(fluxo(), personal=True)]
    assert fake.segments[1:] == ["Olá, tudo bem?", "Eu sou a Magui."]
    assert b"".join(chunks) == b"Ol|Eu|"
    assert env.log == ["ensure:tts", "call:openai-2", "call:openai-1", "record:tts", "call:openai-1",
                       "record:tts"]  # fmt: skip
    assert [u.input_units for u in env.budget.recorded[-2:]] == [14, 15]  # caracteres


async def test_segmentos_longos_sem_pontuacao():
    async def fluxo():
        for _ in range(100):
            yield "palavra "

    segs = [s async for s in tts_segments(fluxo())]
    assert len(segs) > 1 and all(len(s) <= 400 for s in segs)
    assert " ".join(segs).split() == ["palavra"] * 100


async def test_reload_troca_provedor_e_mantem_espera(env, make_config):
    reg = env.reg
    chat = reg.chat()
    await chat.chat(_msgs(), personal=False)
    env.fakes["openai"].reject["openai-2"] = 429
    await chat.chat(_msgs(), personal=False)
    assert reg.pool("openai").available() == 1
    cfg = make_config()
    tasks = dict(cfg.raw["tasks"])
    tasks["agent"] = {"provider": "openai", "model": "chat-novo"}
    reg.reload(make_config(tasks=tasks))
    assert reg.chat().model == "chat-novo"
    assert reg.pool("openai").available() == 1  # mesmas chaves: estado de espera preservado
    reg.reload(make_config(providers={"openai": {"keys": ["openai-3"]}, "gemini": {"keys": []}}))
    assert reg.pool("openai").available() == 1
    assert reg.pool("openai").acquire().name == "openai-3"


async def test_kind_permite_api_compativel(make_config, budget, get_secret):
    log: list[str] = []
    cfg = make_config(
        providers={"local": {"keys": ["openai-1"], "kind": "openai", "base_url": "http://x"}},
        tasks={"agent": {"provider": "local", "model": "m"}},
    )
    reg = Registry(cfg, budget, backends={"openai": lambda c: FakeBackend(c, log)}, get_secret=get_secret)
    assert (await reg.chat().chat(_msgs(), personal=True)).text == "ok"
    bad = make_config(providers={"x": {"keys": []}}, tasks={"agent": {"provider": "x", "model": "m"}})
    with pytest.raises(ConfigError, match="desconhecido"):
        Registry(bad, budget, backends={}).chat()
    with pytest.raises(ConfigError):
        Registry(bad, budget, backends={}).stt()
