"""R2.C: hook do Claude Code → arquivo de eventos → ClaudeStats.last_event → det_claude (54/55)."""

import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace

from hud.wired.data import ClaudeStats, ClaudeView
from hud.wired.reacoes import catalogo, det_claude

_SPEC = importlib.util.spec_from_file_location(
    "claude_hook", Path(__file__).resolve().parents[2] / "hud" / "tools" / "claude_hook.py")
claude_hook = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(claude_hook)


def _rodar(caminho, arg, dados, agora=1000.0):
    texto = dados if isinstance(dados, str) else json.dumps(dados)
    return claude_hook.main([arg] if arg else [], io.StringIO(texto), caminho, agora)


def _linhas(caminho):
    return [json.loads(x) for x in caminho.read_text().splitlines()]


def test_hook_falso_grava_linha(tmp_path, capsys):
    f = tmp_path / "ev.jsonl"
    assert _rodar(f, "notify", {"hook_event_name": "Notification", "cwd": "/home/p/magi"}) == 0
    assert _rodar(f, "stop", {}) == 0
    assert _linhas(f) == [{"t": 1000.0, "ev": "notify", "proj": "magi"},
                          {"t": 1000.0, "ev": "stop", "proj": Path.cwd().name}]
    assert capsys.readouterr().out == ""


def test_hook_post_tool_use_so_grava_erro(tmp_path):
    f = tmp_path / "ev.jsonl"
    ok = {"hook_event_name": "PostToolUse", "cwd": "/a/b", "tool_response": {"stdout": "x"}}
    _rodar(f, "fail", ok)
    assert not f.exists()
    for resp in ({"is_error": True}, {"exit_code": 2}, {"error": "boom"}, "Error: nope"):
        _rodar(f, "fail", {**ok, "tool_response": resp})
    _rodar(f, "fail", {"hook_event_name": "PostToolUseFailure", "cwd": "/a/b"})
    assert [x["ev"] for x in _linhas(f)] == ["fail"] * 5


def test_hook_defensivo(tmp_path, capsys):
    f = tmp_path / "ev.jsonl"
    assert _rodar(f, None, "isto não é json") == 0  # sem argumento nem hook_event_name: nada
    assert _rodar(f, "xyz", "[1, 2]") == 0
    assert not f.exists()
    assert _rodar(f, None, {"hook_event_name": "Stop", "cwd": 42}) == 0  # cai no nome do hook
    assert _linhas(f)[0]["ev"] == "stop"
    assert claude_hook.main(["notify"], io.StringIO("{}"), tmp_path / "ev.jsonl" / "nao_da") == 0
    assert capsys.readouterr().out == ""


def test_hook_gira_em_1_mb(tmp_path):
    f = tmp_path / "ev.jsonl"
    f.write_bytes(b"x" * claude_hook.MAX_BYTES)
    _rodar(f, "notify", {})
    assert (tmp_path / "ev.jsonl.1").stat().st_size == claude_hook.MAX_BYTES
    assert len(_linhas(f)) == 1


class _Reader:
    def summary(self):
        raise RuntimeError("sem registros")


def test_claude_stats_le_so_o_novo_e_segue_a_rotacao(tmp_path):
    f = tmp_path / "ev.jsonl"
    _rodar(f, "fail", {"hook_event_name": "PostToolUseFailure"}, agora=1.0)  # antigo: não reage
    st = ClaudeStats(reader=_Reader(), events_file=f)
    assert st.events() is None
    _rodar(f, "notify", {"cwd": "/p/magi"}, agora=2.0)
    assert st.events() == (2.0, "notify", "magi")
    with f.open("a") as h:
        h.write("lixo\n{\"t\": 3, \"ev\": \"???\"}\n{\"t\": 4, \"ev\": \"st")  # inválidas e meia linha
    assert st.events() == (2.0, "notify", "magi")
    with f.open("a") as h:
        h.write("op\"}\n")
    assert st.events() == (4.0, "stop", "")
    f.write_bytes(b"x" * claude_hook.MAX_BYTES)
    _rodar(f, "fail", {"hook_event_name": "PostToolUseFailure", "cwd": "/q"}, agora=5.0)  # girou
    assert st.events() == (5.0, "fail", "q")
    try:
        st.refresh()
    except RuntimeError:
        pass
    assert st.view.last_event == (5.0, "fail", "q")


def test_claude_stats_sem_arquivo(tmp_path):
    f = tmp_path / "nao" / "ev.jsonl"
    st = ClaudeStats(reader=_Reader(), events_file=f)
    assert st.events() is None
    _rodar(f, "notify", {}, agora=7.0)  # criado depois do HUD abrir: é novo
    assert st.events()[:2] == (7.0, "notify")


def _snap(ev):
    return SimpleNamespace(claude=ClaudeView(last_event=ev), track=None, cpu=None, git_head=None)


def test_det_claude_54_55_uma_vez_e_so_recente():
    ctx = {"agora": 10.0, "relogio": 1000.0}
    assert det_claude.detectar(None, _snap(None), ctx) == []
    d = det_claude.detectar(None, _snap((990.0, "fail", "magi")), ctx)
    assert [x.chave for x in d] == ["claude_erro"]
    assert det_claude.detectar(None, _snap((990.0, "fail", "magi")), ctx) == []  # mesmo evento
    d = det_claude.detectar(None, _snap((995.0, "notify", "magi")), ctx)
    assert [x.chave for x in d] == ["claude_espera"]
    assert det_claude.detectar(None, _snap((996.0, "stop", "magi")), ctx) == []
    assert det_claude.detectar(None, _snap((500.0, "fail", "magi")), ctx) == []  # velho


def test_54_55_ativas():
    assert "claude_erro" in catalogo.ATIVAS and "claude_espera" in catalogo.ATIVAS
