"""Intents ``tv.*`` no roteador (ayanami-central C2.1, spec §13.1, §13.2, CA-Y51, DS12)."""

from __future__ import annotations

from datetime import datetime

import pytest
import yaml

from magi.common.contracts import IntentId, RouteKind, RouteResult, SlotName, TurnContext, WakeSource
from magi.core import i18n
from magi.core.router import CasaCatalogo, LocalRouter
from magi.core.tts import Phrases
from magi.elo.mensagens import AppInfo, TvInfo

CTX = TurnContext(satellite="local", source=WakeSource.PTT, started_at=datetime(2026, 1, 1))

CASA = CasaCatalogo(
    tvs=(
        TvInfo(
            id="sala",
            nome="TV da sala",
            driver="samsung",
            apelidos=("sala", "televisão da sala", "tv grande"),
        ),
        TvInfo(id="quarto", nome="TV do quarto", driver="androidtv", apelidos=("quarto", "tcl")),
    ),
    apps=(
        AppInfo(id="netflix", nome="Netflix"),
        AppInfo(id="youtube", nome="YouTube", apelidos=("you tube",)),
        AppInfo(id="prime", nome="Prime Video", apelidos=("amazon",)),
    ),
    entradas={"console": "hdmi2", "videogame": "hdmi2"},
)


@pytest.fixture(scope="module")
def router() -> LocalRouter:
    return LocalRouter(casa=CASA)


@pytest.fixture(scope="module")
def sem_casa() -> LocalRouter:
    return LocalRouter()


def _local(r: LocalRouter, text: str) -> RouteResult:
    res = r.route(text, CTX)
    assert res.kind is RouteKind.LOCAL, (text, res)
    assert res.intent is not None
    return res


def _slot(res: RouteResult, name: str) -> str | None:
    assert res.intent is not None
    s = res.intent.slot(name)
    return None if s is None else s.value


# -- CA-Y51 ---------------------------------------------------------------------------------------


def test_ca_y51_liga_a_tv_da_sala(router: LocalRouter) -> None:
    res = _local(router, "liga a tv da sala")
    assert res.intent.id == IntentId.TV_POWER_ON
    assert _slot(res, SlotName.TV) == "sala"
    assert res.intent.slot(SlotName.TV).display == "TV da sala"


def test_ca_y51_aumenta_o_volume_e_do_pc(router: LocalRouter) -> None:
    res = _local(router, "aumenta o volume")
    assert res.intent.id == IntentId.VOLUME_SET
    assert _slot(res, SlotName.VOLUME) == "+10"


def test_ca_y51_aumenta_o_volume_da_tv(router: LocalRouter) -> None:
    res = _local(router, "aumenta o volume da tv")
    assert res.intent.id == IntentId.TV_VOLUME
    assert _slot(res, SlotName.VOLUME) == "+3"


def test_ca_y51_abre_a_netflix_na_tv(router: LocalRouter) -> None:
    res = _local(router, "abre a netflix na tv")
    assert res.intent.id == IntentId.TV_APP
    assert _slot(res, SlotName.APP) == "netflix"


def test_ca_y51_desliga_a_tv_e_perigosa(router: LocalRouter) -> None:
    res = _local(router, "desliga a tv")
    assert res.intent.id == IntentId.TV_POWER_OFF
    assert res.intent.danger


def test_ca_y51_entrada_hdmi_2(router: LocalRouter, sem_casa: LocalRouter) -> None:
    for r in (router, sem_casa):  # "hdmi N" casa mesmo sem catálogo
        res = _local(r, "entrada hdmi 2")
        assert res.intent.id == IntentId.TV_INPUT
        assert _slot(res, SlotName.INPUT) == "hdmi2"


# -- mais frases da §13.1 -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "intent", "slots"),
    [
        ("liga a tv", IntentId.TV_POWER_ON, {}),
        ("liga a televisão", IntentId.TV_POWER_ON, {}),
        ("liga a tv do quarto", IntentId.TV_POWER_ON, {"tv": "quarto"}),
        ("desliga a tv grande", IntentId.TV_POWER_OFF, {"tv": "sala"}),
        ("abaixa o volume da tv", IntentId.TV_VOLUME, {"volume": "-3"}),
        ("aumenta muito o volume da tv", IntentId.TV_VOLUME, {"volume": "+8"}),
        ("aumenta 5 o volume da tv", IntentId.TV_VOLUME, {"volume": "+5"}),
        ("volume da tv em 20", IntentId.TV_VOLUME, {"volume": "20"}),
        ("coloca o volume da tv do quarto em 15", IntentId.TV_VOLUME, {"volume": "15", "tv": "quarto"}),
        ("muta a tv", IntentId.TV_MUTE, {}),
        ("tv no mudo", IntentId.TV_MUTE, {}),
        ("silencia a tv da sala", IntentId.TV_MUTE, {"tv": "sala"}),
        ("tira a tv do mudo", IntentId.TV_UNMUTE, {}),
        ("desmuta a tv", IntentId.TV_UNMUTE, {}),
        ("volta o som da tv do quarto", IntentId.TV_UNMUTE, {"tv": "quarto"}),
        ("coloca youtube na tv", IntentId.TV_APP, {"app": "youtube"}),
        ("abre o prime video na tv do quarto", IntentId.TV_APP, {"app": "prime", "tv": "quarto"}),
        ("muda a tv para hdmi 1", IntentId.TV_INPUT, {"input": "hdmi1"}),
        ("tv no hdmi3", IntentId.TV_INPUT, {"input": "hdmi3"}),
        ("coloca a tv da sala no console", IntentId.TV_INPUT, {"input": "hdmi2", "tv": "sala"}),
    ],
)
def test_frases_tv(router: LocalRouter, text: str, intent: IntentId, slots: dict[str, str]) -> None:
    res = _local(router, text)
    assert res.intent.id == intent
    for name, value in slots.items():
        assert _slot(res, name) == value, (text, name)


# -- regra de colisão (DS12) ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("aumenta o volume", IntentId.VOLUME_SET),
        ("abaixa o volume", IntentId.VOLUME_SET),
        ("volume em 30", IntentId.VOLUME_SET),
        ("muta", IntentId.VOLUME_MUTE),
        ("tira do mudo", IntentId.VOLUME_UNMUTE),
        ("liga as luzes", IntentId.RGB_BRIGHTNESS),
    ],
)
def test_sem_tv_continua_o_do_pc(router: LocalRouter, text: str, intent: IntentId) -> None:
    assert _local(router, text).intent.id == intent


def test_abre_youtube_sem_na_tv_segue_o_de_hoje(router: LocalRouter, sem_casa: LocalRouter) -> None:
    com = router.route("abre o youtube", CTX)
    sem = sem_casa.route("abre o youtube", CTX)
    assert (com.kind, com.intent and com.intent.id) == (sem.kind, sem.intent and sem.intent.id)
    assert not (com.intent and com.intent.id.startswith("tv."))


def test_app_fora_do_catalogo_nao_vira_tv_app(router: LocalRouter) -> None:
    res = router.route("abre o crunchyroll na tv", CTX)
    assert not (res.intent and res.intent.id == IntentId.TV_APP)


def test_hdmi_fora_de_1_a_4_nao_casa(sem_casa: LocalRouter) -> None:
    res = sem_casa.route("entrada hdmi 7", CTX)
    assert not (res.kind is RouteKind.LOCAL and res.intent and res.intent.id == IntentId.TV_INPUT)


def test_casa_trocada_em_tempo_de_execucao() -> None:
    r = LocalRouter()
    assert _slot(_local(r, "liga a tv"), SlotName.TV) is None
    r.casa = CASA
    assert _slot(_local(r, "liga a tv do quarto"), SlotName.TV) == "quarto"


# -- frases da §13.2 ------------------------------------------------------------------------------

FALAS_FIXAS = [
    "Pronto, TV ligada.", "TV desligada.", "Não consegui ligar a TV.", "A TV não respondeu.",
    "A casa está fora do ar.", "Essa TV não faz isso.", "Não conheço esse app nessa TV.", "Qual TV?",
    "Mudo alternado.", "A TV recusou o comando.", "Essa TV ainda não foi pareada.",
    "Ligando a TV.", "Desligar a TV? Confirma?", "Volume da TV ajustado.", "TV no mudo.",
    "Som da TV de volta.", "Abrindo na TV.", "Entrada trocada.",
]  # fmt: skip
FALAS_MOLDE = [
    "Desligar a TV da sala? Confirma?",
    "Abrindo Netflix na TV.",
    "Não consegui ligar a TV da sala; ela precisa do Ligar com celular ativo.",
    "Não consegui ligar a TV da sala; ative o Início rápido da TV.",
    "Não consegui ligar a TV do quarto; ela está em espera profunda.",
    "A TV da sala está bloqueando o controle; ative o Acesso à rede.",
    "A TV do quarto está desligada.",
    "Mais de uma TV: sala ou quarto?",
]


def test_falas_da_13_2_em_cache() -> None:
    p = Phrases.load()
    assert [f for f in FALAS_FIXAS + FALAS_MOLDE if not p.cacheable(f)] == []


def test_replies_tv_em_cache() -> None:
    p = Phrases.load()
    replies = [s.reply for s in LocalRouter().intents if s.id.startswith("tv.") and s.reply]
    assert len(replies) == 7
    assert [r for r in replies if not p.cacheable(r)] == []


def test_falas_tv_em_ingles() -> None:
    i18n.configure("en-gb")
    try:
        assert i18n.tr("Qual TV?") == "Which TV?"
        assert i18n.tr("A casa está fora do ar.") == "The house is offline."
        assert i18n.tr("A TV do quarto está desligada.") == "TV do quarto is off."
    finally:
        i18n.configure("pt-br")
    tabela = yaml.safe_load((i18n.TABLES_DIR / "en-gb.yaml").read_text(encoding="utf-8"))
    for f in FALAS_FIXAS:
        assert f in tabela["fixed"], f
    for f in ("Desligar a {nome}? Confirma?", "Mais de uma TV: {nome}?"):
        assert f in tabela["templates"], f
