"""Leitor de consumo do Claude Code com registros falsos (sem o ~/.claude real)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from magi.maintenance.claude_usage import UsageReader, human

NOW = datetime(2026, 10, 6, 22, 0, tzinfo=UTC)  # 19:00 em São Paulo


def line(ts: str, cwd: str, usage: dict | None = None, model: str = "claude-opus-5-5") -> str:
    d: dict = {"timestamp": ts, "cwd": cwd, "type": "assistant" if usage else "user"}
    if usage:
        d["message"] = {"model": model, "usage": usage}
    return json.dumps(d) + "\n"


U = {"input_tokens": 10, "output_tokens": 100, "cache_read_input_tokens": 1000,
     "cache_creation_input_tokens": 50}


def test_soma_o_dia_e_sessoes_ativas(tmp_path):
    proj = tmp_path / "-home-x-magi"  # aberta em /home/x/magi
    proj.mkdir()
    s1 = proj / "s1.jsonl"
    s1.write_text(
        line("2026-10-06T02:00:00Z", "/home/x/magi", U)  # 23:00 do dia 5 em SP: fica fora
        + line("2026-10-06T21:55:00Z", "/home/x/magi", U)
        + line("2026-10-06T21:58:00Z", "/home/x/magi", U, model="claude-haiku-4-5-20251001")
    )
    old = proj / "s2.jsonl"
    old.write_text(line("2026-10-06T15:00:00Z", "/home/x/outro", U))
    r = UsageReader(tmp_path, now=lambda: NOW, running_cwds=lambda: {"/home/x/magi"})  # processo aberto lá
    s = r.summary()
    assert s.day == "2026-10-06" and s.tokens.replies == 3 and s.tokens.output == 300
    assert set(s.by_model) == {"claude-opus-5-5", "claude-haiku-4-5-20251001"}
    assert [x.id for x in s.active] == ["s1"] and s.active[0].running and s.running == 1
    assert s.active[0].project == "magi"

    # incremental: só as linhas novas entram; linha incompleta espera a próxima leitura
    with s1.open("a") as f:
        f.write(line("2026-10-06T21:59:00Z", "/home/x/magi", U) + '{"timestamp": "2026-10-06T21:59')
    assert r.summary().tokens.replies == 4
    with s1.open("a") as f:
        f.write(':30Z", "cwd": "/home/x/magi"}\n')
    assert r.summary().tokens.replies == 4


def test_vira_o_dia_e_zera(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "s.jsonl").write_text(line("2026-10-06T21:00:00Z", "/a", U))
    now = [NOW]
    r = UsageReader(tmp_path, now=lambda: now[0], running_cwds=set)
    assert r.summary().tokens.replies == 1
    now[0] = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
    s = r.summary()
    assert s.day == "2026-10-07" and s.tokens.replies == 0 and s.active == []


def test_sem_pasta_e_human(tmp_path):
    assert UsageReader(tmp_path / "nada", now=lambda: NOW, running_cwds=set).summary().tokens.total == 0
    assert human(950) == "950" and human(1234) == "1,2 mil" and human(3_400_000) == "3,4 mi"


def test_janela_de_5h():
    from datetime import timedelta

    from magi.maintenance.claude_usage import current_window

    t = datetime(2026, 10, 6, 14, 37, tzinfo=UTC)
    start, end, _ = current_window([t, t + timedelta(hours=1)], t + timedelta(hours=2))
    assert start == datetime(2026, 10, 6, 14, 0, tzinfo=UTC) and end == start + timedelta(hours=5)
    # resposta depois do fim abre outra janela, na hora cheia dela
    later = t + timedelta(hours=6)
    start, end, _ = current_window([t, later], later + timedelta(minutes=5))
    assert start == datetime(2026, 10, 6, 20, 0, tzinfo=UTC)
    # janela já fechada e nenhuma resposta nova: nada em curso
    assert current_window([t], t + timedelta(hours=6))[0] is None


def test_janela_soma_so_o_que_esta_dentro(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "s.jsonl").write_text(
        line("2026-10-06T15:30:00Z", "/a", U)  # janela anterior (15:00-20:00)
        + line("2026-10-06T20:10:00Z", "/a", U)  # abre a janela 20:00-01:00
        + line("2026-10-06T21:50:00Z", "/a", U)
    )
    s = UsageReader(tmp_path, now=lambda: NOW, running_cwds=set).summary()
    assert s.window_start == datetime(2026, 10, 6, 20, 0, tzinfo=UTC)
    assert s.window.replies == 2 and s.window.fresh == 2 * 160 and s.window.cache_read == 2000
