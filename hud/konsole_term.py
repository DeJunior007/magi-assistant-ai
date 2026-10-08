"""Konsole do painel (KONSOLE // CLAUDE CODE): o ``claude`` num pty + emulador VT (pyte), sem Qt.

``KonsoleSession`` sobe o comando (padrão ``["claude"]``) num pseudo-terminal com
``start_new_session`` (grupo próprio, pty como terminal de controle → ``SIGWINCH`` no resize),
lê sem bloquear (``fileno()`` para o ``QSocketNotifier`` do gamerhud; ``pump()`` drena o que houver
para o ``pyte``) e expõe as células com atributos e o cursor para a pintura
(``wired/konsole_view.py``). ``close()`` manda SIGTERM ao grupo, depois SIGKILL, e colhe o filho:
nunca fica zumbi.

Persistente (``persist``): com tmux instalado o comando roda num servidor tmux próprio
(``tmux -L magi``, config ``hud/tmux-magi.conf``) na sessão ``persist``; o pty do HUD só tem o
cliente. ``close()`` derruba o cliente (desconecta) e o ``claude`` segue vivo; abrir de novo
reconecta (``new-session -A``). Sem tmux, cai no pty direto.

``qt_key_to_bytes`` traduz uma tecla do Qt (constantes numéricas, sem importar o Qt) na sequência
que um xterm mandaria. Ver ``docs/design/nova-ui/KONSOLE.md``.

Em runtime o HUD usa o Python do sistema: sem ``pyte`` o módulo importa do mesmo jeito
(``HAVE_PYTE`` falso) e o card mostra ``instale python3-pyte``.
"""

from __future__ import annotations

import errno
import fcntl
import os
import shutil
import signal
import struct
import subprocess
import termios
import time
from dataclasses import dataclass
from pathlib import Path

try:
    import pyte
except ImportError:   # HUD no Python do sistema sem python3-pyte
    pyte = None

HAVE_PYTE = pyte is not None
MISSING_PYTE = "instale python3-pyte"

REPO = Path(__file__).resolve().parent.parent   # cwd padrão: o repositório da MAGI
DEFAULT_CMD = ("claude",)
HISTORY = 3000           # linhas guardadas acima da tela (rolagem com a roda)
READ_CHUNK = 65536
READ_BUDGET = 1 << 20    # por pump(): não segura o laço do Qt com uma enxurrada de saída
# o HUD sobe pelo login, às vezes sem ~/.local/bin no PATH
EXTRA_PATH = ("~/.local/bin", "~/.claude/local", "~/.npm-global/bin", "~/bin")
# variáveis de uma sessão do Claude Code que não podem vazar para o claude filho
# (TMUX/TMUX_PANE: o HUD aberto de dentro de um tmux não pode virar tmux aninhado)
DROP_ENV = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT", "TMUX", "TMUX_PANE")
TMUX_SOCKET = "magi"                     # servidor tmux só do HUD (não mexe nos tmux do usuário)
TMUX_SESSION = "magi-claude"
TMUX_CONF = Path(__file__).resolve().parent / "tmux-magi.conf"

# modos privados do DEC no pyte (guardados como n << 5)
MODE_APP_CURSOR = 1 << 5          # DECCKM: setas/Home/End como ESC O x
MODE_BRACKETED = 2004 << 5        # colagem entre ESC[200~ e ESC[201~


@dataclass(frozen=True, slots=True)
class Cell:
    """Uma célula da tela: caractere ("" na metade direita de um caractere largo) e atributos
    como o pyte dá (cores: "default", nome ANSI tipo "red"/"brightred" ou hex "rrggbb")."""
    char: str
    fg: str = "default"
    bg: str = "default"
    bold: bool = False
    reverse: bool = False
    italics: bool = False
    underscore: bool = False


BLANK = Cell(" ")


def resolve_cmd(cmd) -> list[str]:
    """Acha o executável no PATH (mais as pastas de usuário de ``EXTRA_PATH``)."""
    cmd = list(cmd)
    if cmd and os.sep not in cmd[0]:
        path = os.pathsep.join([os.environ.get("PATH", ""), *(os.path.expanduser(p) for p in EXTRA_PATH)])
        found = shutil.which(cmd[0], path=path)
        if found:
            cmd[0] = found
    return cmd


def tmux_bin() -> str | None:
    """Caminho do tmux, ou None se não estiver instalado."""
    path = resolve_cmd(["tmux"])[0]
    return path if os.path.isabs(path) else None


def tmux_has_session(name: str = TMUX_SESSION) -> bool:
    """A sessão persistente ``name`` existe no servidor do HUD? (False sem tmux)."""
    tmux = tmux_bin()
    if not tmux:
        return False
    try:
        r = subprocess.run([tmux, "-L", TMUX_SOCKET, "has-session", "-t", f"={name}"],
                           capture_output=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def tmux_kill_session(name: str = TMUX_SESSION) -> None:
    """Encerra de vez a sessão persistente (o ``claude`` dentro dela morre junto)."""
    tmux = tmux_bin()
    if tmux:
        subprocess.run([tmux, "-L", TMUX_SOCKET, "kill-session", "-t", f"={name}"],
                       capture_output=True, timeout=2)


def tmux_wrap(cmd, cwd: str, name: str) -> list[str] | None:
    """O comando dentro da sessão tmux ``name`` (cria ou reconecta). None sem tmux."""
    tmux = tmux_bin()
    if not tmux:
        return None
    return [tmux, "-L", TMUX_SOCKET, "-f", str(TMUX_CONF), "new-session", "-A", "-s", name,
            "-c", cwd, "--", *cmd]


def git_status(cwd) -> dict:
    """Projeto, branch e linhas +/− do ``cwd`` para a barra de status (git rápido, 1 s no máximo).
    Chamado ao abrir o expandido, nunca na pintura."""
    cwd = Path(cwd)
    home = str(Path.home())
    proj = str(cwd)
    if proj.startswith(home):
        proj = "~" + proj[len(home):]
    out = {"project": proj, "branch": "", "added": 0, "removed": 0}
    try:
        b = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--abbrev-ref", "HEAD"],
                           capture_output=True, text=True, timeout=1)
        out["branch"] = b.stdout.strip() if b.returncode == 0 else ""
        d = subprocess.run(["git", "-C", str(cwd), "diff", "--numstat", "HEAD"],
                           capture_output=True, text=True, timeout=1)
        for line in d.stdout.splitlines():
            a, r, *_ = line.split("\t") + ["", ""]
            out["added"] += int(a) if a.isdigit() else 0
            out["removed"] += int(r) if r.isdigit() else 0
    except (OSError, subprocess.SubprocessError):
        pass
    return out


if HAVE_PYTE:
    class _Screen(pyte.HistoryScreen):
        """HistoryScreen que guarda as respostas ao programa (DA, posição do cursor) para a
        sessão devolvê-las ao pty."""

        def __init__(self, cols, rows, history):
            super().__init__(cols, rows, history=history, ratio=0.5)
            self.replies: list[str] = []

        def write_process_input(self, data):
            self.replies.append(data)

        def report_device_status(self, mode=0, private=False, **kw):
            """O tmux pergunta ``ESC[?…n`` (privado) e o pyte quebraria: só responde os ANSI."""
            if not private:
                super().report_device_status(mode)


class KonsoleSession:
    """Um programa num pty com a tela emulada pelo pyte.

    ``cmd`` (padrão ``["claude"]``), ``cwd`` (padrão o repositório), tamanho inicial em células.
    ``persist``: nome da sessão tmux (ver o topo do módulo); ``persistent`` diz se pegou.
    Lança ``RuntimeError`` sem pyte e ``FileNotFoundError`` se o comando não existir."""

    def __init__(self, cmd=None, cwd=None, cols: int = 80, rows: int = 24, env: dict | None = None,
                 history: int = HISTORY, persist: str | None = None):
        if not HAVE_PYTE:
            raise RuntimeError(MISSING_PYTE)
        self.cmd = resolve_cmd(cmd or DEFAULT_CMD)
        self.cwd = str(Path(cwd).expanduser()) if cwd else str(REPO)
        if not os.path.isdir(self.cwd):   # o tmux não reclamaria: falha aqui, como sem ele
            raise FileNotFoundError(errno.ENOENT, "pasta inexistente", self.cwd)
        wrapped = tmux_wrap(self.cmd, self.cwd, persist) if persist else None
        self.persistent = wrapped is not None
        self.reattached = self.persistent and tmux_has_session(persist)
        if wrapped:
            if not os.path.isabs(self.cmd[0]) or not os.access(self.cmd[0], os.X_OK):
                raise FileNotFoundError(errno.ENOENT, "comando não encontrado", self.cmd[0])
            self.cmd = wrapped
        self.cols, self.rows = max(2, int(cols)), max(2, int(rows))
        self.screen = _Screen(self.cols, self.rows, history)
        self.stream = pyte.ByteStream(self.screen)
        self.scroll = 0            # linhas de histórico acima da tela (0 = acompanhando o fim)
        self.started = time.monotonic()
        self.exit_code: int | None = None
        self._eof = False
        self._cursor_row = 0
        self._dirty: set[int] = set(range(self.rows))
        e = dict(os.environ if env is None else env)
        for k in DROP_ENV:
            e.pop(k, None)
        e.update(TERM="xterm-256color", COLORTERM="truecolor",
                 COLUMNS=str(self.cols), LINES=str(self.rows))
        master, slave = os.openpty()
        try:
            self._set_winsize(slave)
            self.proc = subprocess.Popen(
                self.cmd, stdin=slave, stdout=slave, stderr=slave, cwd=self.cwd, env=e,
                start_new_session=True, close_fds=True, preexec_fn=_take_ctty)
        except BaseException:
            os.close(master)
            raise
        finally:
            os.close(slave)
        os.set_blocking(master, False)
        self.fd: int | None = master

    # -- processo
    def fileno(self) -> int:
        return -1 if self.fd is None else self.fd

    @property
    def pid(self) -> int:
        return self.proc.pid

    @property
    def alive(self) -> bool:
        """Processo rodando e pty aberto."""
        return self.fd is not None and not self._eof and self.proc.poll() is None

    def pump(self) -> bool:
        """Lê tudo o que houver no pty (sem bloquear) e alimenta a tela. True se algo mudou
        (saída nova ou o processo saiu)."""
        if self.fd is None:
            return False
        got = 0
        changed = False
        while got < READ_BUDGET:
            try:
                data = os.read(self.fd, READ_CHUNK)
            except BlockingIOError:
                break
            except OSError as ex:   # EIO: o lado escravo fechou (o programa saiu)
                if ex.errno != errno.EIO:
                    raise
                data = b""
            if not data:
                self._eof = True
                changed = True
                break
            self.stream.feed(data)
            got += len(data)
            changed = True
        if self.screen.replies:
            # no tmux quem responde ao claude é o próprio tmux; as respostas do pyte às perguntas
            # do cliente (DA) viravam texto digitado no painel
            if not self.persistent:
                self.write("".join(self.screen.replies).encode())
            self.screen.replies.clear()
        if changed and got:
            self.scroll = 0 if self.scroll == 0 else min(self.scroll, self.history_len())
        if self._eof:
            self._reap()
        return changed

    def _reap(self) -> None:
        """Colhe o filho que saiu (sem esperar se ele ainda não terminou)."""
        if self.exit_code is None:
            try:
                self.exit_code = self.proc.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                pass

    def write(self, data: bytes) -> None:
        """Manda bytes ao programa (teclas, colagem). Ignora se a sessão acabou."""
        if not data or not self.alive:
            return
        try:
            while data:
                n = os.write(self.fd, data)
                data = data[n:]
        except BlockingIOError:
            pass   # buffer do pty cheio: perde o resto em vez de travar o HUD
        except OSError:
            self._eof = True

    def paste(self, text: str) -> None:
        """Colagem; com o modo bracketed ligado vai entre ESC[200~ … ESC[201~."""
        data = text.replace("\r\n", "\r").replace("\n", "\r").encode()
        if MODE_BRACKETED in self.screen.mode:
            data = b"\x1b[200~" + data + b"\x1b[201~"
        self.write(data)

    def resize(self, cols: int, rows: int) -> bool:
        """Ajusta a tela e o pty (TIOCSWINSZ → SIGWINCH no programa). True se mudou."""
        cols, rows = max(2, int(cols)), max(2, int(rows))
        if (cols, rows) == (self.cols, self.rows):
            return False
        self.cols, self.rows = cols, rows
        self.screen.resize(rows, cols)
        self._dirty = set(range(rows))
        if self.fd is not None:
            try:
                self._set_winsize(self.fd)
            except OSError:
                pass
        return True

    def _set_winsize(self, fd: int) -> None:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", self.rows, self.cols, 0, 0))

    def close(self, grace: float = 1.0) -> None:
        """Encerra (persistente: só o cliente tmux, ou seja, desconecta): SIGTERM ao grupo, espera ``grace`` s, SIGKILL; colhe o filho e fecha o pty."""
        proc = self.proc
        if proc.poll() is None:
            _killpg(proc.pid, signal.SIGHUP)
            _killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                _killpg(proc.pid, signal.SIGKILL)
                proc.wait()
        else:
            _killpg(proc.pid, signal.SIGTERM)   # netos que tenham ficado no grupo
        self.exit_code = proc.returncode
        self._eof = True
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None

    def __del__(self):
        try:
            if getattr(self, "proc", None) is not None and self.proc.poll() is None:
                self.close(grace=0.2)
        except Exception:
            pass

    # -- tela
    @property
    def app_cursor(self) -> bool:
        return MODE_APP_CURSOR in self.screen.mode

    def cursor(self) -> tuple[int, int, bool]:
        """(coluna, linha, visível) do cursor na tela (sem a rolagem)."""
        c = self.screen.cursor
        return c.x, c.y, not c.hidden

    def history_len(self) -> int:
        return len(self.screen.history.top)

    def scroll_by(self, lines: int) -> bool:
        """Rola o histórico (positivo = para cima). True se mudou."""
        new = max(0, min(self.history_len(), self.scroll + int(lines)))
        if new == self.scroll:
            return False
        self.scroll = new
        self._dirty = set(range(self.rows))
        return True

    def _row(self, line) -> list[Cell]:
        out = []
        default = self.screen.default_char
        for x in range(self.cols):
            ch = line[x] if x in line else default
            if ch is default or (ch.data == " " and ch.fg == "default" and ch.bg == "default"
                                 and not ch.reverse):
                out.append(BLANK)
            else:
                out.append(Cell(ch.data, ch.fg, ch.bg, ch.bold, ch.reverse, ch.italics, ch.underscore))
        return out

    def rows_view(self) -> list[list[Cell]]:
        """As ``rows`` linhas visíveis (com a rolagem do histórico aplicada)."""
        if self.scroll <= 0:
            return [self._row(self.screen.buffer[y]) for y in range(self.rows)]
        top = list(self.screen.history.top)[-self.scroll:]
        lines = top + [self.screen.buffer[y] for y in range(self.rows)]
        return [self._row(ln) for ln in lines[:self.rows]]

    def lines(self) -> list[str]:
        """Texto da tela, linha a linha (sem espaços à direita)."""
        return [ln.rstrip() for ln in self.screen.display]

    def last_used_row(self) -> int:
        """Última linha com algo (texto ou o cursor): o compacto mostra até ela."""
        y = self.screen.cursor.y
        for row in range(self.rows - 1, y, -1):
            if self.screen.display[row].strip():
                return row
        return y

    def take_dirty(self) -> set[int]:
        """Linhas da tela que mudaram desde a última chamada (inclui a do cursor antes e agora)."""
        rows = set(self.screen.dirty) | self._dirty
        self.screen.dirty.clear()
        self._dirty = set()
        y = self.screen.cursor.y
        rows |= {y, self._cursor_row}
        self._cursor_row = y
        if self.scroll:
            return set(range(self.rows))
        return {r for r in rows if 0 <= r < self.rows}

    def elapsed(self) -> float:
        return time.monotonic() - self.started


def _take_ctty():
    """No filho, depois do setsid: o pty vira o terminal de controle (SIGWINCH, Ctrl+C)."""
    try:
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)
    except OSError:
        pass


def _killpg(pid: int, sig: int) -> None:
    try:
        os.killpg(pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


# ------------------------------------------------------------------ teclado

# constantes do Qt (Qt.Key_*, Qt.*Modifier) — números, para não importar o Qt aqui
K_ESC, K_TAB, K_BACKTAB, K_BACKSPACE, K_RETURN, K_ENTER, K_INSERT, K_DELETE = range(0x01000000, 0x01000008)
K_HOME, K_END, K_LEFT, K_UP, K_RIGHT, K_DOWN, K_PGUP, K_PGDN = range(0x01000010, 0x01000018)
K_F1 = 0x01000030
K_SPACE = 0x20
SHIFT, CTRL, ALT, META = 0x02000000, 0x04000000, 0x08000000, 0x10000000
KEYPAD = 0x20000000

_CSI_LETTER = {K_UP: "A", K_DOWN: "B", K_RIGHT: "C", K_LEFT: "D", K_HOME: "H", K_END: "F"}
_CSI_TILDE = {K_INSERT: 2, K_DELETE: 3, K_PGUP: 5, K_PGDN: 6}
_FKEYS = {0: "P", 1: "Q", 2: "R", 3: "S"}                 # F1–F4: ESC O P..S
_FTILDE = {4: 15, 5: 17, 6: 18, 7: 19, 8: 20, 9: 21, 10: 23, 11: 24}   # F5–F12
_CTRL_PUNCT = {0x40: 0, 0x5B: 0x1B, 0x5C: 0x1C, 0x5D: 0x1D, 0x5E: 0x1E, 0x5F: 0x1F, K_SPACE: 0,
               0x32: 0, 0x36: 0x1E, 0x2D: 0x1F, 0x2F: 0x1F}


def qt_key_to_bytes(key: int, text: str = "", modifiers=0, app_cursor: bool = False) -> bytes:
    """Bytes de xterm para a tecla ``key`` (``Qt.Key_*`` como int) com ``text`` (o que o Qt
    digitaria) e ``modifiers`` (int ou flags do Qt). ``app_cursor``: modo DECCKM (setas como
    ESC O x). Teclas sem tradução (Meta/Super, modificador sozinho) → b""."""
    mods = int(getattr(modifiers, "value", modifiers)) & ~KEYPAD
    key = int(getattr(key, "value", key))
    shift, ctrl, alt = bool(mods & SHIFT), bool(mods & CTRL), bool(mods & ALT)
    if mods & META:
        return b""   # Super/Meta é do KDE (Meta+M etc.), nunca do terminal
    m = 1 + shift + 2 * alt + 4 * ctrl   # parâmetro de modificador do xterm
    esc = b"\x1b" if alt else b""
    if key in (K_RETURN, K_ENTER):
        return b"\x1b\r" if (shift or alt) else b"\r"   # Shift/Alt+Enter: nova linha no Claude
    if key == K_BACKSPACE:
        return esc + (b"\x08" if ctrl else b"\x7f")
    if key == K_BACKTAB or (key == K_TAB and shift):
        return b"\x1b[Z"
    if key == K_TAB:
        return esc + b"\t"
    if key == K_ESC:
        return b"\x1b"
    if key in _CSI_LETTER:
        ch = _CSI_LETTER[key]
        if m > 1:
            return f"\x1b[1;{m}{ch}".encode()
        return f"\x1b{'O' if app_cursor else '['}{ch}".encode()
    if key in _CSI_TILDE:
        n = _CSI_TILDE[key]
        return (f"\x1b[{n};{m}~" if m > 1 else f"\x1b[{n}~").encode()
    if K_F1 <= key < K_F1 + 12:
        i = key - K_F1
        if i in _FKEYS:
            return (f"\x1b[1;{m}{_FKEYS[i]}" if m > 1 else f"\x1bO{_FKEYS[i]}").encode()
        return (f"\x1b[{_FTILDE[i]};{m}~" if m > 1 else f"\x1b[{_FTILDE[i]}~").encode()
    if ctrl:
        if 0x41 <= key <= 0x5A:   # Ctrl+letra (Qt dá a maiúscula)
            return esc + bytes([key - 0x40])
        if key in _CTRL_PUNCT:
            return esc + bytes([_CTRL_PUNCT[key]])
        if text and len(text) == 1 and ord(text) < 0x20:
            return esc + text.encode()
        return b""
    if text:
        if any(ord(c) < 0x20 and c not in "\t\r" for c in text):
            return b""
        return esc + text.encode("utf-8", "replace")
    return b""
