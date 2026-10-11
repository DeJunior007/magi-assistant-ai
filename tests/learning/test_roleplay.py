"""Roleplay: cenários e ramo do TopicBuilder (LI4.1; D5; spec imersivo §12; CA-09 núcleo)."""

from __future__ import annotations

import asyncio

import pytest

from magi.learning import roleplay
from magi.learning.contracts import TOPIC_BLOCK_MAX, TOPIC_LABELS, Topic
from magi.learning.topic import NO_SCENARIO, TopicBuilder

IDS = ("doctor_visit", "hotel_checkin", "ordering_food", "support_call")


def _build(requested, scenario=None, **kw):
    return asyncio.run(TopicBuilder(**kw).build(requested, scenario))


def test_os_4_cenarios_carregam_ordenados():
    found = roleplay.scenarios()
    assert tuple(s.id for s in found) == IDS
    for s in found:
        assert all(getattr(s, k) for k in roleplay.KEYS)
        assert 0 < len(s.body) <= roleplay.BODY_MAX


def test_spec_exemplo_hotel():
    s = roleplay.load("hotel_checkin")
    assert s.title == "Hotel check-in"
    assert s.twist == "the room type on the reservation is wrong"


@pytest.mark.parametrize("sid", IDS)
def test_bloco_cabe_e_rotulo(sid):
    ctx = _build("roleplay", sid)
    s = roleplay.load(sid)
    assert ctx.topic is Topic.ROLEPLAY and ctx.requested is Topic.ROLEPLAY
    assert ctx.label == f"ROLEPLAY // {s.title.upper()}"
    assert ctx.detail is None
    assert len(ctx.block) <= TOPIC_BLOCK_MAX and not ctx.block.endswith("…")
    assert "{" not in ctx.block
    assert s.role in ctx.block and s.twist in ctx.block and s.body in ctx.block


@pytest.mark.parametrize("sid", [None, "", "standup", "../hotel_checkin", "Hotel"])
def test_sem_cenario_ou_desconhecido_cai_em_free(sid):
    ctx = _build(Topic.ROLEPLAY, sid)
    assert ctx.topic is Topic.FREE and ctx.requested is Topic.ROLEPLAY
    assert ctx.block is None and ctx.detail == NO_SCENARIO
    assert ctx.label == TOPIC_LABELS[Topic.FREE]


def test_scenario_ignorado_em_outro_tema():
    assert _build("free", "hotel_checkin").topic is Topic.FREE


def _write(tmp_path, name, text):
    (tmp_path / f"{name}.md").write_text(text, encoding="utf-8")


GOOD = ("title: T\nrole: r\nsetting: s\ngoal: g\ntwist: w\n\nBody text.\n")


def test_load_valida(tmp_path):
    _write(tmp_path, "ok", GOOD)
    assert roleplay.load("ok", tmp_path).body == "Body text."
    _write(tmp_path, "falta", GOOD.replace("twist: w\n", ""))
    _write(tmp_path, "extra", GOOD.replace("goal: g\n", "goal: g\nmood: x\n"))
    _write(tmp_path, "vazio", GOOD.replace("Body text.\n", ""))
    _write(tmp_path, "grande", GOOD + "x" * 5000)
    _write(tmp_path, "longo", GOOD + "y" * roleplay.BODY_MAX)
    for bad in ("falta", "extra", "vazio", "grande", "longo", "nada", "Ok", "a-b"):
        with pytest.raises(ValueError):
            roleplay.load(bad, tmp_path)


def test_dir_injetado_no_builder(tmp_path):
    _write(tmp_path, "mini", GOOD)
    ctx = _build("roleplay", "mini", scenarios_dir=tmp_path)
    assert ctx.label == "ROLEPLAY // T" and "Body text." in ctx.block
    assert _build("roleplay", "hotel_checkin", scenarios_dir=tmp_path).topic is Topic.FREE
