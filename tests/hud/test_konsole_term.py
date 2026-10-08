"""Konsole do painel: sessão num pty de verdade (bash/printf, nunca o claude) e o teclado."""

import os
import select
import time

import konsole_term as kt
import pytest
from konsole_term import qt_key_to_bytes

pytestmark = pytest.mark.skipif(not kt.HAVE_PYTE, reason="sem pyte")

# constantes do Qt (iguais às de Qt.Key_* / Qt.*Modifier)
SHIFT, CTRL, ALT, META = 0x02000000, 0x04000000, 0x08000000, 0x10000000


def wait_for(sess, pred, timeout=5.0):
    """Bombeia o pty até `pred()` ou estourar o tempo."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        if sess.fd is not None:
            select.select([sess.fd], [], [], 0.05)
        sess.pump()
    return pred()


def text(sess):
    return "\n".join(sess.lines())


@pytest.fixture
def sessions():
    made = []

    def make(script, **kw):
        s = kt.KonsoleSession(["bash", "-c", script], **kw)
        made.append(s)
        return s

    yield make
    for s in made:
        s.close(grace=0.3)


def test_le_saida_e_escreve(sessions):
    s = sessions("printf 'ola\\n'; cat", cols=40, rows=10)
    assert s.alive and s.fileno() >= 0
    assert wait_for(s, lambda: "ola" in text(s))
    s.write(b"abc\r")
    assert wait_for(s, lambda: text(s).count("abc") >= 2)   # eco do tty + saída do cat


def test_cores_atributos_e_cursor(sessions):
    s = sessions("printf '\\e[31mR\\e[0m\\e[1;7mB\\e[0m\\e[38;5;196mX\\e[0m'; sleep 5", cols=20, rows=5)
    assert wait_for(s, lambda: "RBX" in text(s))
    row = s.rows_view()[0]
    assert row[0].char == "R" and row[0].fg == "red"
    assert row[1].bold and row[1].reverse
    assert len(row[2].fg) == 6   # 256 cores → hex
    x, y, vis = s.cursor()
    assert (x, y, vis) == (3, 0, True)
    assert s.last_used_row() == 0
    assert 0 in s.take_dirty()


def test_resize_chega_ao_programa(sessions):
    s = sessions("stty size; read x; stty size; sleep 5", cols=80, rows=24)
    assert wait_for(s, lambda: "24 80" in text(s))
    assert s.resize(100, 30)
    assert not s.resize(100, 30)
    assert (s.screen.columns, s.screen.lines) == (100, 30)
    s.write(b"\r")
    assert wait_for(s, lambda: "30 100" in text(s))


def test_ambiente_e_cwd(sessions, tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")   # sessão do Claude Code não vaza para o filho
    s = sessions('echo "T=$TERM C=[$CLAUDECODE] D=$PWD L=$LINES"; sleep 5', cwd=tmp_path, cols=200, rows=8)
    assert wait_for(s, lambda: "L=8" in text(s))
    t = text(s)
    assert "T=xterm-256color" in t and "C=[]" in t and f"D={tmp_path}" in t


def test_cwd_padrao_e_o_repositorio(sessions):
    s = sessions("sleep 5")
    assert s.cwd == str(kt.REPO)


def test_responde_consulta_de_cursor(sessions):
    s = sessions("printf '\\e[6n'; read -rs -d R r; echo \"got${r#?}\"; sleep 5", cols=40, rows=5)
    assert wait_for(s, lambda: "got[1;1" in text(s))


def test_fim_do_programa_sem_zumbi(sessions):
    s = sessions("printf fim", cols=20, rows=4)
    assert wait_for(s, lambda: not s.alive)
    assert "fim" in text(s)
    s.close()
    assert s.exit_code == 0 and s.fd is None
    with pytest.raises(ChildProcessError):
        os.waitpid(s.pid, os.WNOHANG)


def test_close_mata_quem_ignora_sigterm(sessions):
    s = sessions("trap '' TERM HUP; echo pronto; sleep 30", cols=20, rows=4)
    assert wait_for(s, lambda: "pronto" in text(s))
    t0 = time.monotonic()
    s.close(grace=0.3)
    assert time.monotonic() - t0 < 3
    assert not s.alive and s.exit_code is not None
    assert not os.path.exists(f"/proc/{s.pid}")   # colhido: nem zumbi
    s.write(b"x")   # depois de fechado: ignora
    assert not s.pump()


def test_historico_e_rolagem(sessions):
    s = sessions("seq 1 60; sleep 5", cols=20, rows=10)
    assert wait_for(s, lambda: "60" in text(s))
    assert s.history_len() > 0
    assert s.scroll_by(5) and s.scroll == 5
    assert len(s.rows_view()) == 10
    assert s.take_dirty() == set(range(10))
    assert s.scroll_by(-100) and s.scroll == 0


def test_comando_inexistente():
    with pytest.raises(FileNotFoundError):
        kt.KonsoleSession(["/nao/existe/claude"])


def test_resolve_cmd_acha_no_path():
    assert kt.resolve_cmd(["bash", "-c", "x"])[0].endswith("/bash")
    assert kt.resolve_cmd(["comando-que-nao-existe-xyz"]) == ["comando-que-nao-existe-xyz"]


def test_paste_bracketed(sessions):
    s = sessions("printf '\\e[?2004h'; cat -v", cols=60, rows=5)
    assert wait_for(s, lambda: kt.MODE_BRACKETED in s.screen.mode)
    s.paste("a\nb")
    assert wait_for(s, lambda: "^[[200~" in text(s))


# ------------------------------------------------------------------ teclado

K = 0x01000000


@pytest.mark.parametrize("key,mods,expected", [
    (K + 4, 0, b"\r"),                 # Return
    (K + 5, 0, b"\r"),                 # Enter (teclado numérico)
    (K + 4, SHIFT, b"\x1b\r"),         # Shift+Enter: nova linha no Claude
    (K + 3, 0, b"\x7f"),               # Backspace
    (K + 3, ALT, b"\x1b\x7f"),
    (K + 1, 0, b"\t"),                 # Tab
    (K + 2, SHIFT, b"\x1b[Z"),         # Backtab
    (K + 1, SHIFT, b"\x1b[Z"),
    (K + 0, 0, b"\x1b"),               # Esc
    (K + 0x13, 0, b"\x1b[A"),          # setas
    (K + 0x15, 0, b"\x1b[B"),
    (K + 0x14, 0, b"\x1b[C"),
    (K + 0x12, 0, b"\x1b[D"),
    (K + 0x12, CTRL, b"\x1b[1;5D"),
    (K + 0x13, SHIFT, b"\x1b[1;2A"),
    (K + 0x10, 0, b"\x1b[H"),          # Home/End
    (K + 0x11, 0, b"\x1b[F"),
    (K + 0x16, 0, b"\x1b[5~"),         # PgUp/PgDn
    (K + 0x17, 0, b"\x1b[6~"),
    (K + 7, 0, b"\x1b[3~"),            # Delete
    (K + 0x30, 0, b"\x1bOP"),          # F1
    (K + 0x34, 0, b"\x1b[15~"),        # F5
])
def test_teclas_especiais(key, mods, expected):
    assert qt_key_to_bytes(key, "", mods) == expected


def test_setas_em_modo_aplicacao():
    assert qt_key_to_bytes(K + 0x13, "", 0, app_cursor=True) == b"\x1bOA"
    assert qt_key_to_bytes(K + 0x10, "", 0, app_cursor=True) == b"\x1bOH"


def test_ctrl_letra_e_texto():
    assert qt_key_to_bytes(ord("C"), "\x03", CTRL) == b"\x03"
    assert qt_key_to_bytes(ord("D"), "", CTRL) == b"\x04"
    assert qt_key_to_bytes(ord("["), "", CTRL) == b"\x1b"
    assert qt_key_to_bytes(0x20, " ", CTRL) == b"\x00"
    assert qt_key_to_bytes(ord("A"), "a", 0) == b"a"
    assert qt_key_to_bytes(ord("A"), "A", SHIFT) == b"A"
    assert qt_key_to_bytes(0, "ç", 0) == "ç".encode()
    assert qt_key_to_bytes(0, "日本", 0) == "日本".encode()
    assert qt_key_to_bytes(ord("B"), "b", ALT) == b"\x1bb"


def test_ignora_meta_e_teclas_mudas():
    assert qt_key_to_bytes(ord("M"), "m", META) == b""
    assert qt_key_to_bytes(0x01000020, "", SHIFT) == b""   # Shift sozinho
    assert qt_key_to_bytes(ord("X"), "", 0) == b""


def test_aceita_flags_com_value():
    class Flags:
        value = CTRL

    assert qt_key_to_bytes(ord("C"), "", Flags()) == b"\x03"


@pytest.mark.skipif(kt.tmux_bin() is None, reason="sem tmux")
def test_tmux_sobrevive_ao_close_e_reconecta(tmp_path):
    name = f"magi-teste-{os.getpid()}"
    script = "printf 'vivo\\n'; exec cat"
    try:
        s = kt.KonsoleSession(["bash", "-c", script], cwd=tmp_path, cols=40, rows=10, persist=name)
        assert s.persistent and not s.reattached
        assert wait_for(s, lambda: "vivo" in text(s))
        s.write(b"marca\r")
        assert wait_for(s, lambda: text(s).count("marca") >= 2)
        s.close(grace=0.5)
        assert kt.tmux_has_session(name)   # fechar o HUD só desconecta

        s2 = kt.KonsoleSession(["bash", "-c", script], cwd=tmp_path, cols=40, rows=10, persist=name)
        assert s2.reattached
        assert wait_for(s2, lambda: "marca" in text(s2))   # a mesma tela de antes
        s2.close(grace=0.5)
    finally:
        kt.tmux_kill_session(name)
    assert not kt.tmux_has_session(name)


@pytest.mark.skipif(kt.tmux_bin() is None, reason="sem tmux")
def test_tmux_comando_ou_pasta_inexistente(tmp_path):
    with pytest.raises(FileNotFoundError):
        kt.KonsoleSession(["/nao/existe/claude"], cwd=tmp_path, persist="magi-teste-x")
    with pytest.raises(FileNotFoundError):
        kt.KonsoleSession(["bash"], cwd=tmp_path / "nada", persist="magi-teste-x")
    assert not kt.tmux_has_session("magi-teste-x")


def test_token_meter_le_o_ultimo_uso(tmp_path):
    (tmp_path / "sessions").mkdir()
    (tmp_path / "sessions" / "123.json").write_text(
        '{"pid": 123, "sessionId": "abc", "cwd": "/home/x/meu.proj"}')
    proj = tmp_path / "projects" / "-home-x-meu-proj"
    proj.mkdir(parents=True)
    tr = proj / "abc.jsonl"
    use = '{"type":"assistant","isSidechain":%s,"message":{"usage":{"input_tokens":%d,' \
          '"cache_read_input_tokens":1000,"cache_creation_input_tokens":200,"output_tokens":9}}}\n'
    tr.write_text(use % ("false", 5) + use % ("true", 99) + '{"type":"user"}\n')
    m = kt.TokenMeter(123, root=tmp_path)
    assert m.read() == 1205              # o da sub-tarefa (sidechain) não conta
    with tr.open("a") as f:
        f.write(use % ("false", 40000))
    assert m.read() == 41200
    assert kt.TokenMeter(999, root=tmp_path).read() is None
    assert kt.TokenMeter(None, root=tmp_path).read() is None


def test_format_tokens():
    assert [kt.format_tokens(n) for n in (950, 1234, 38219, 2_400_000)] == ["950", "1.2k", "38k", "2.4M"]
