"""Contratos e config do Learning Mode (tarefa LM0.1; spec §1–§3)."""

from __future__ import annotations

import json
import tomllib
from dataclasses import fields
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from magi.common.config import ConfigError, parse_config
from magi.learning import contracts as c
from magi.learning.config import (
    LearningConfig,
    learning_config,
    learning_tasks,
    parse_learning,
)

ROOT = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 10, 7, 21, 3, 15, tzinfo=UTC)
T1 = datetime(2026, 10, 7, 21, 31, 2, tzinfo=UTC)


def _msg(i: int = 3, text: str = "I have went to the store yesterday") -> c.LearningMessage:
    return c.LearningMessage(
        id=i, session_id="LS-20261007-01", author=c.Author.YOU, source=c.Source.VOICE, text=text, at=T0
    )


def _samples() -> list[c._Wire]:
    m = _msg()
    sel = c.Selection(message_id=3, start=2, end=11, text="have went")
    return [
        m,
        sel,
        c.ActionRequest(
            id="ACT-1f9a02c4", kind=c.ActionKind.IMPROVE, selection=sel, context=[_msg(2, "hi"), m]
        ),
        c.ActionResult(
            id="ACT-1f9a02c4", kind=c.ActionKind.IMPROVE, ok=True,
            data={"original": "have went", "suggestion": "went", "why": ["grammar"]},
            error=None, cached=False, ms=812, cost_usd=0.0004,
        ),
        c.ActionResult(
            id="ACT-00000000", kind=c.ActionKind.TRANSLATE, ok=False, data=None,
            error="timeout", cached=False, ms=8000, cost_usd=0.0,
        ),
        c.Observation(
            id=None, session_id="LS-20261007-01", message_id=3, category=c.ObsCategory.GRAMMAR,
            rule_key="grammar.past_simple.irregular", label="Past tense", span="have went", suggestion="went",
        ),
        c.TopicContext(
            topic=c.Topic.FREE, requested=c.Topic.GAME, label=c.TOPIC_LABELS[c.Topic.FREE],
            block=None, detail="no game detected",
        ),
        c.TopicContext(
            topic=c.Topic.NEWS, requested=c.Topic.NEWS, label="TODAY'S NEWS", block="ç" * 1500, detail=None
        ),
        c.SessionSummary(
            session_id="LS-20261007-02", n=2, started_at=T0, ended_at=T1, duration_s=1667,
            end_reason="button", n_msgs=24, n_you=12, obs_count=5,
            practiced=["Past tense"], new_words=["repository", "deploy"], saved=["deploy"],
            more_practiced=0, more_words=1, topics=["free", "game"],
        ),
        c.SavedWord(
            id=7, norm="deploy", term="Deploy", meaning="publicar uma versão", pos="verb", cefr="B2",
            example="We deploy on Fridays.", session_id="LS-20261007-02", message_id=9,
            action_id="ACT-1f9a02c4", saved_at=T0, removed_at=None,
        ),
        c.SavedWord(
            id=None, norm="ship it", term="ship it", meaning="lançar", pos=None, cefr=None,
            example="Let's ship it.", session_id="LS-20261007-02", message_id=10,
            action_id="ACT-abcdef01", saved_at=T0, removed_at=T1,
        ),
    ]


@pytest.mark.parametrize("obj", _samples(), ids=lambda o: type(o).__name__)
def test_json_ida_e_volta(obj: c._Wire) -> None:
    line = obj.to_json()
    assert "\n" not in line
    back = type(obj).from_json(line)
    assert back == obj
    assert back.to_json() == line


def test_none_omitido_no_fio_e_enums_como_texto() -> None:
    obs = _samples()[5]
    d = json.loads(obs.to_json())
    assert "id" not in d
    assert d["category"] == "grammar"
    req = json.loads(_samples()[2].to_json())
    assert req["kind"] == "improve"
    assert req["context"][0]["author"] == "you"
    assert req["context"][0]["at"] == T0.isoformat()


def test_campo_obrigatorio_ausente() -> None:
    d = _msg().to_dict()
    del d["text"]
    with pytest.raises(ValueError, match="text"):
        c.LearningMessage.from_dict(d)
    with pytest.raises(ValueError):
        c.LearningMessage.from_json("[1]")


def test_enum_invalido_recusado() -> None:
    d = _msg().to_dict() | {"author": "magui"}
    with pytest.raises(ValueError):
        c.LearningMessage.from_dict(d)


def test_ask_e_future() -> None:
    assert {k.value for k in c.ActionKind} == {"improve", "explain", "translate", "vocabulary"}


def test_selection_validada() -> None:
    m = _msg()
    sel = c.Selection(message_id=3, start=2, end=11, text="have went")
    assert sel.matches(m)
    assert not sel.matches(_msg(text="I have gone to the store"))
    with pytest.raises(ValueError):
        c.Selection(message_id=3, start=5, end=5, text="")
    with pytest.raises(ValueError):
        c.Selection(message_id=3, start=0, end=4, text="I have")


def test_topic_block_limitado() -> None:
    with pytest.raises(ValueError):
        c.TopicContext(topic=c.Topic.GAME, requested=c.Topic.GAME, label="X", block="a" * 1501, detail=None)
    assert set(c.TOPIC_LABELS) == set(c.Topic)


def test_ids() -> None:
    sid = c.make_session_id(date(2026, 10, 7), 1)
    assert sid == "LS-20261007-01"
    assert c.session_day_n(sid) == 1
    assert c.session_day_n("LS-20261007-123") == 123
    with pytest.raises(ValueError):
        c.session_day_n("LS-2026-01")
    with pytest.raises(ValueError):
        c.make_session_id(date(2026, 10, 7), 0)
    a = c.new_action_id()
    assert c.ACTION_ID_RE.match(a)
    assert a != c.new_action_id()


def test_contratos_citam_requisito() -> None:
    import re

    req = re.compile(r"\b(?:[A-Z]{2,4}-\d{3}|LM-\d{3})\b")
    tipos = [c.Author, c.Source, c.ActionKind, c.ObsCategory, c.Topic] + [type(o) for o in _samples()]
    for t in tipos:
        assert t.__doc__ and req.search(t.__doc__), t.__name__
    for t in (LearningConfig,):
        assert t.__doc__ and req.search(t.__doc__)


def test_dataclasses_imutaveis() -> None:
    m = _msg()
    with pytest.raises(AttributeError):
        m.text = "x"  # type: ignore[misc]
    assert [f.name for f in fields(c.SavedWord)][:3] == ["id", "norm", "term"]


# ---------------------------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------------------------


def test_config_padroes_sem_secao() -> None:
    cfg = parse_learning({})
    assert cfg == LearningConfig()
    assert cfg.default_topic is c.Topic.FREE
    assert (cfg.topic_picker_s, cfg.summary_show_s, cfg.idle_end_min) == (10, 60, 20)
    assert cfg.level_label == "B2 · CONVERSATION"


def test_config_valores_lidos() -> None:
    cfg = parse_learning({"learning": {
        "level": "c1", "track": "interview", "explain_language": "PT-BR", "default_topic": "game",
        "topic_picker_s": 5, "summary_show_s": 30, "storage": "jsonl", "observe": False,
    }})
    assert cfg.level == "C1" and cfg.track == "INTERVIEW"
    assert cfg.explain_language == "pt-br"
    assert cfg.default_topic is c.Topic.GAME
    assert (cfg.topic_picker_s, cfg.summary_show_s) == (5, 30)
    assert cfg.storage == "jsonl" and cfg.observe is False


@pytest.mark.parametrize("sec", [
    {"default_topic": "music"},
    {"level": "B3"},
    {"explain_language": "es"},
    {"storage": "sqlite"},
    {"topic_picker_s": 0},
    {"summary_show_s": "60"},
    {"enabled": "yes"},
    {"idle_end_min": True},
])
def test_config_invalida(sec: dict) -> None:
    with pytest.raises(ConfigError):
        parse_learning({"learning": sec})


def test_exemplo_tem_learning_e_tarefas() -> None:
    data = tomllib.loads((ROOT / "config.example.toml").read_text(encoding="utf-8"))
    assert parse_learning(data) == LearningConfig()
    assert set(data["learning"]) == {f.name for f in fields(LearningConfig)}
    cfg = parse_config(data)
    assert learning_config(cfg) == LearningConfig()
    t = learning_tasks(cfg)
    assert t.actions is not None and t.observe is not None
    assert (t.actions.provider, t.actions.model, t.actions.timeout_s) == ("openai", "gpt-5.4-mini", 8.0)
    assert t.observe.timeout_s == 20.0
    assert t.actions.reasoning_effort == "none"


def test_tarefas_ausentes_e_prazo_padrao() -> None:
    base = {"providers": {"openai": {"keys": ["openai-main"]}}}
    t = learning_tasks(parse_config(base))
    assert t.actions is None and t.observe is None
    cfg = parse_config(base | {"tasks": {"learning_observe": {"provider": "openai", "model": "m"}}})
    t = learning_tasks(cfg)
    assert t.actions is None
    assert t.observe is not None and t.observe.timeout_s == 20.0 and t.observe.reasoning_effort is None
    zero = {"provider": "openai", "model": "m", "timeout_s": 0}
    bad = parse_config(base | {"tasks": {"learning_actions": zero}})
    with pytest.raises(ConfigError):
        learning_tasks(bad)
