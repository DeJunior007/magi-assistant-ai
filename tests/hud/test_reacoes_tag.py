"""R2.B: tag do turno no ``Snapshot`` e reações 74, 76, 86, 87 no ``det_conversa``."""

from __future__ import annotations

from wired import integration
from wired.main_screen import Snapshot
from wired.reacoes import det_conversa
from wired.reacoes.catalogo import ATIVAS


def tick(ctx: dict, tag: str | None, quando: float, agora: float) -> list[str]:
    snap = Snapshot(turn_tag=None if tag is None else (tag, quando))
    ctx["agora"] = agora
    return [d.chave for d in det_conversa.detectar(Snapshot(), snap, ctx)]


def test_cada_tag_vira_sua_reacao() -> None:
    assert tick({}, "correcao", 100.0, 101.0) == ["desculpa"]
    assert tick({}, "zoeira", 100.0, 101.0) == ["rindo"]
    assert tick({}, "elogio", 100.0, 101.0) == ["tsundere"]
    assert tick({}, "sussurro", 100.0, 101.0) == ["sussurro"]  # 88 (R2.F)


def test_tag_velha_ignorada() -> None:
    assert tick({}, "zoeira", 100.0, 110.0) == ["rindo"]  # 10 s ainda vale
    assert tick({}, "zoeira", 100.0, 110.5) == []
    assert tick({}, None, 0.0, 5.0) == []


def test_mesma_tag_reage_uma_vez() -> None:
    ctx: dict = {}
    assert tick(ctx, "zoeira", 100.0, 101.0) == ["rindo"]
    assert tick(ctx, "zoeira", 100.0, 102.0) == []
    assert tick(ctx, "zoeira", 103.0, 103.5) == ["rindo"]


def test_segundo_elogio_gagueja() -> None:
    ctx: dict = {}
    assert tick(ctx, "elogio", 100.0, 100.5) == ["tsundere"]
    assert tick(ctx, "elogio", 200.0, 200.5) == ["gaguejando"]
    assert tick(ctx, "elogio", 900.0, 900.5) == ["tsundere"]  # passou de 5 min


def test_reacoes_da_tag_ativas() -> None:
    assert {"tsundere", "rindo", "desculpa", "gaguejando"} <= ATIVAS
    assert "sussurro" in ATIVAS  # 88 ativa (R2.F)


class _SemPlayer:
    active = False


class _RedeFalsa:
    down = up = 0.0
    down_series = ()

    def poll(self, now=None):
        pass


class _GitFalso:
    head = None

    def poll(self, mono=None):
        return {"branch": "main", "added": 0, "removed": 0}


def test_integration_guarda_tag_com_hora() -> None:
    ui = integration.WiredUI(now_playing=_SemPlayer(), net=_RedeFalsa(), git=_GitFalso())
    assert ui.build({}).turn_tag is None
    ui.set_turn_tag("elogio", 42.0)
    assert ui.snap.turn_tag == ("elogio", 42.0)
    assert ui.build({}).turn_tag == ("elogio", 42.0)
    ui.set_turn_tag(None)
    assert ui.build({}).turn_tag is None
