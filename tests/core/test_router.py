"""Roteador local (tarefa 1.8): limiares, slots e frases de ouro (§4.2, §10, R4)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
import yaml

from magi.common.contracts import (
    ROUTER_ASK_SCORE,
    ROUTER_EXECUTE_SCORE,
    IntentId,
    RouteKind,
    Router,
    RouteResult,
    SlotName,
    TurnContext,
    WakeSource,
)
from magi.core.catalog import MemoryAliasStore, SteamCatalog
from magi.core.router import LocalRouter, load_intents, normalize_text, parse_number

UTTERANCES = Path(__file__).parent.parent / "data" / "utterances.yaml"

GAMES = {
    588650: "Dead Cells",
    292030: "The Witcher 3: Wild Hunt",
    367520: "Hollow Knight",
    1145350: "Hades II",
    620: "Portal 2",
    1091500: "Cyberpunk 2077",
    1086940: "Baldur's Gate 3",
    1238840: "Dead Space",
    374320: "DARK SOULS™ III",
}


def _manifest(appid: int, name: str) -> str:
    return (
        '"AppState"\n{\n'
        f'\t"appid"\t\t"{appid}"\n\t"name"\t\t"{name}"\n\t"StateFlags"\t\t"4"\n'
        f'\t"installdir"\t\t"{name}"\n'
        "}\n"
    )


@pytest.fixture(scope="module")
def router(tmp_path_factory: pytest.TempPathFactory) -> LocalRouter:
    root = tmp_path_factory.mktemp("Steam")
    apps = root / "steamapps"
    apps.mkdir()
    for appid, name in GAMES.items():
        (apps / f"appmanifest_{appid}.acf").write_text(_manifest(appid, name))
    catalog = SteamCatalog(root, aliases=MemoryAliasStore({588650: ["joguinho das celas"]}))
    return LocalRouter(catalog)


CTX = TurnContext(satellite="local", source=WakeSource.PTT, started_at=datetime(2026, 1, 1))


def _route(router: LocalRouter, text: str) -> RouteResult:
    return router.route(text, CTX)


def _hit(res: RouteResult, case: dict) -> bool:
    if case["intent"] == "agent":
        return res.kind is RouteKind.AGENT
    if res.kind is not RouteKind.LOCAL or res.intent is None or res.intent.id != case["intent"]:
        return False
    for name, value in (case.get("slots") or {}).items():
        slot = res.intent.slot(name)
        if slot is None or slot.value != str(value):
            return False
    return True


def test_implementa_protocolo(router: LocalRouter) -> None:
    assert isinstance(router, Router)


def test_intents_yaml_usa_ids_do_contrato() -> None:
    specs = load_intents()
    ids = {s.id for s in specs}
    assert ids <= {i.value for i in IntentId}
    assert len(ids) == len(specs)
    danger = {s.id for s in specs if s.danger}
    assert {IntentId.GAME_CLOSE, IntentId.SYSTEM_SHUTDOWN, IntentId.SYSTEM_REBOOT} <= danger
    assert IntentId.GAME_OPEN not in danger


def test_intents_yaml_rejeita_id_inventado(tmp_path: Path) -> None:
    bad = tmp_path / "i.yaml"
    bad.write_text("intents:\n  - id: pizza.order\n    phrases: ['pede pizza']\n")
    with pytest.raises(ValueError, match="IntentId"):
        load_intents(bad)
    bad.write_text("intents:\n  - id: game.open\n    phrases: ['abre {game} agora']\n")
    with pytest.raises(ValueError, match="fim"):
        load_intents(bad)


def test_normaliza_e_numeros() -> None:
    assert normalize_text("Dá PAUSE aí, por favor!") == ["da", "pause", "ai"]
    assert normalize_text("volume em 30%") == ["volume", "em", "30"]
    assert parse_number(["trinta", "e", "cinco"], 0) == (35, 3)
    assert parse_number(["cento", "e", "vinte"], 0) == (120, 3)
    assert parse_number(["uma", "boa"], 0) is None
    assert parse_number(["50"], 0) == (50, 1)


def test_frases_de_ouro_acerto_minimo(router: LocalRouter) -> None:
    cases = yaml.safe_load(UTTERANCES.read_text(encoding="utf-8"))
    assert len(cases) >= 80
    assert sum(c["intent"] == "agent" for c in cases) >= 10
    misses = []
    for case in cases:
        res = _route(router, case["text"])
        if not _hit(res, case):
            got = res.intent.id if res.intent else None
            slots = {s.name: s.value for s in res.intent.slots} if res.intent else {}
            misses.append(f"{case['text']!r}: {res.kind} {got} {slots} ({res.score:.0f})")
    accuracy = 1 - len(misses) / len(cases)
    print(f"\nacerto nas frases de ouro: {accuracy:.1%} ({len(cases) - len(misses)}/{len(cases)})")
    print("\n".join(misses))
    assert accuracy >= 0.90, misses


def test_jogo_pelo_catalogo_e_apelido(router: LocalRouter) -> None:
    res = _route(router, "abre o dedi cels")
    assert res.kind is RouteKind.LOCAL and res.intent is not None
    game = res.intent.slot(SlotName.GAME)
    assert game is not None and game.value == "588650" and game.display == "Dead Cells"
    assert res.intent.reply and "{game}" in res.intent.reply
    alias = _route(router, "abre o joguinho das celas")
    assert alias.intent is not None and alias.intent.slot(SlotName.GAME).value == "588650"


def test_jogo_desconhecido_sai_sem_appid_para_a_acao_sugerir(router: LocalRouter) -> None:
    res = _route(router, "abre o minecraft")
    assert res.kind is RouteKind.LOCAL and res.intent is not None
    assert res.intent.id == IntentId.GAME_OPEN
    slot = res.intent.slot(SlotName.GAME)
    assert slot is not None and slot.value == "" and slot.raw == "minecraft"


def test_fechar_jogo_e_perigoso(router: LocalRouter) -> None:
    res = _route(router, "fecha o jogo")
    assert res.kind is RouteKind.LOCAL and res.intent is not None
    assert res.intent.id == IntentId.GAME_CLOSE and res.intent.danger
    assert res.intent.slot(SlotName.GAME) is None


def test_faixa_de_duvida_pergunta(router: LocalRouter) -> None:
    res = _route(router, "aumenta o volume do fone que tá baixo demais")
    assert ROUTER_ASK_SCORE <= res.score < ROUTER_EXECUTE_SCORE, res
    assert res.kind is RouteKind.ASK and res.intent is not None
    assert res.intent.id == IntentId.VOLUME_SET
    assert res.suggestion == "Você quis dizer aumentar o volume?"


def test_limiares_ajustaveis(router: LocalRouter) -> None:
    strict = LocalRouter(router.catalog, router.intents, execute_score=101, ask_score=100)
    assert strict.route("pausa a música", CTX).kind is RouteKind.ASK
    assert strict.route("pausa a música aí agora mesmo então", CTX).kind is RouteKind.AGENT


def test_vazio_vai_ao_agente(router: LocalRouter) -> None:
    res = _route(router, "  ... ")
    assert res.kind is RouteKind.AGENT and res.score == 0.0


def test_sem_catalogo_jogo_sai_vazio() -> None:
    res = LocalRouter().route("abre o dead cells", CTX)
    assert res.intent is not None and res.intent.id == IntentId.GAME_OPEN
    assert res.intent.slot(SlotName.GAME).value == ""
