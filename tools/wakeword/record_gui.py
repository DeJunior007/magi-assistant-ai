"""Gravador do wake word com interface (PySide6): o mesmo roteiro do ``record``, sem terminal.

Uso::

    uv run python -m tools.wakeword.record_gui            # tudo: positivas, negativas, ruído
    uv run python -m tools.wakeword.record_gui --section positive

Segure Espaço (ou o botão grande) enquanto fala e solte para salvar. ``A`` liga o modo
automático: grava sozinho quando você fala e fecha com 0,6 s de silêncio. ``R``/Backspace
regrava a última, ``P`` pula, ``O`` ouve a última, Esc fecha. Mesmas pastas, mesmo formato
(WAV 16 kHz mono) e mesma retomada do ``record``. Usa o microfone padrão (PipeWire): pode
rodar com o ``magi-satellite`` ligado.
"""

from __future__ import annotations

import argparse
import os
import queue
import sys
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from tools.wakeword import record
from tools.wakeword.common import AUDIO_RATE, DEFAULT_WORD, data_dir, dbfs, read_wav

SECTION_NAME = {"positive": "Positivas", "negative": "Negativas", "noise": "Ruído"}
SECTION_ONE = {"positive": "POSITIVA", "negative": "NEGATIVA", "noise": "RUÍDO"}

CHUNK = 480  # 30 ms
PREROLL = int(0.3 * AUDIO_RATE)  # guarda 0,3 s antes do Espaço/da voz (não corta o começo)
COOLDOWN = int(0.5 * AUDIO_RATE)  # automático: ignora o bip de confirmação
SILENCE_CLOSE = 0.6  # automático: silêncio que fecha a gravação (s)
SILENCE_CLOSE_FREE = 1.5  # ... na fala livre


# ---------------------------------------------------------------------------------------------
# Sessão (sem Qt): fila do roteiro, salvar, regravar, pular
# ---------------------------------------------------------------------------------------------


class Session:
    """Estado do roteiro, com a mesma retomada e o mesmo salvamento do CLI."""

    def __init__(self, takes: list[record.Take], base: Path):
        self.takes, self.base = takes, base
        self.by_section, self.queue = record.pending_queue(takes, base)
        self.pos = 0
        self.last: tuple[int, Path] | None = None  # (posição na fila, arquivo)
        self.skipped = 0

    def current(self) -> record.Take | None:
        return self.takes[self.queue[self.pos]] if self.pos < len(self.queue) else None

    def progress(self) -> list[tuple[str, int, int]]:
        return [(s, min(record.count_done(self.base, s), len(ix)), len(ix))
                for s, ix in self.by_section.items()]

    def step(self) -> tuple[int, int]:
        """(número do passo atual na seção, total da seção)."""
        take = self.current()
        if take is None:
            return 0, 0
        total = len(self.by_section[take.section])
        return min(record.count_done(self.base, take.section) + 1, total), total

    def complete(self) -> bool:
        return all(done >= total for _s, done, total in self.progress())

    def submit(self, raw: np.ndarray) -> record.Saved:
        take = self.current()
        assert take is not None
        res = record.save_take(take, self.base, raw)
        if res.path is not None:
            self.last = (self.pos, res.path)
            self.pos += 1
        return res

    def redo_last(self) -> Path | None:
        """Apaga a última gravação desta sessão e volta para ela."""
        if self.last is None:
            return None
        self.pos, path = self.last
        path.unlink(missing_ok=True)
        self.last = None
        return path

    def skip(self) -> None:
        if self.current() is not None:
            self.pos += 1
            self.skipped += 1


# ---------------------------------------------------------------------------------------------
# Microfone e som
# ---------------------------------------------------------------------------------------------


class Mic(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def drain(self) -> list[np.ndarray]: ...


class SoundDeviceMic:
    """Microfone padrão (PortAudio → PipeWire) em blocos int16 mono 16 kHz de 30 ms."""

    def __init__(self, device: str | int | None = None, target: str | None = None):
        from magi.satellite.capture import pipewire_alsa_props

        os.environ["PIPEWIRE_ALSA"] = pipewire_alsa_props(record.APP_NAME, target)
        import sounddevice as sd

        self._q: queue.SimpleQueue[np.ndarray] = queue.SimpleQueue()
        self._stream = sd.InputStream(samplerate=AUDIO_RATE, channels=1, dtype="int16",
                                      blocksize=CHUNK, device=device, callback=self._cb)

    def _cb(self, indata, frames, t, status) -> None:  # thread do PortAudio
        self._q.put(np.array(indata[:, 0], dtype=np.int16))

    def start(self) -> None:
        self._stream.start()

    def stop(self) -> None:
        self._stream.stop()
        self._stream.close()

    def drain(self) -> list[np.ndarray]:
        out = []
        while True:
            try:
                out.append(self._q.get_nowait())
            except queue.Empty:
                return out


def sd_play(pcm: np.ndarray) -> None:
    try:
        import sounddevice as sd

        sd.play(pcm, AUDIO_RATE)
    except Exception:  # noqa: BLE001 - som é cortesia; nunca derruba a gravação
        pass


def beep_pcm() -> np.ndarray:
    t = np.arange(int(0.09 * AUDIO_RATE)) / AUDIO_RATE
    env = np.minimum(1.0, np.minimum(t, t[-1] - t) / 0.01)
    return (np.sin(2 * np.pi * 1320 * t) * env * 6000).astype(np.int16)


# ---------------------------------------------------------------------------------------------
# Janela
# ---------------------------------------------------------------------------------------------


def _wired():
    """Tokens e fontes do tema wired (``hud/wired``); None se não der para carregar."""
    hud = Path(__file__).resolve().parents[2] / "hud"
    if str(hud) not in sys.path:
        sys.path.append(str(hud))
    try:
        from wired import fonts, theme

        return theme, fonts
    except Exception:  # noqa: BLE001
        return None


class RecorderWindow(QWidget):
    def __init__(
        self,
        session: Session,
        mic: Mic,
        *,
        beep: Callable[[], None] | None = None,
        play: Callable[[np.ndarray], None] = sd_play,
    ):
        super().__init__()
        self.session, self.mic, self.play = session, mic, play
        self.beep = beep or (lambda: play(beep_pcm()))
        self.state = "idle"  # idle | hold | auto | noise
        self.buf: list[np.ndarray] = []
        self.pre: deque[np.ndarray] = deque()
        self.t = 0  # amostras recebidas (relógio da janela, determinístico nos testes)
        self.cooldown_until = 0
        self.floor = -60.0  # nível do silêncio (automático)
        self.loud = 0
        self.quiet = 0
        self.thr = -45.0
        self._build()
        self.refresh()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(30)
        self.mic.start()

    # --- montagem ------------------------------------------------------------------------

    def _build(self) -> None:
        w = _wired()
        tok = {"bg": "#09080d", "panel": "#0f0e15", "line-strong": "#3a3646", "text": "#d8d3e6",
               "text-dim": "#8f89a6", "gpu": "#5fd38d", "warn": "#e8b04a", "hot": "#e5695b",
               "cpu": "#b392f0"} | (w[0].TOKENS if w else {})
        bg, panel, line = tok["bg"], tok["panel"], tok["line-strong"]
        text, dim, accent = tok["text"], tok["text-dim"], tok["cpu"]
        self.c_ok, self.c_warn, self.c_hot = tok["gpu"], tok["warn"], tok["hot"]

        def font(key: str, px: float, weight: int | None = None) -> QFont:
            if w:
                return w[1].font(key, px, weight)
            f = QFont()
            f.setPixelSize(int(px))
            return f

        self.setWindowTitle("Gravar voz da Condessa")
        self.resize(900, 560)
        self.setStyleSheet(f"""
            QWidget {{ background: {bg}; color: {text}; }}
            QPushButton {{ background: {panel}; border: 1px solid {line}; padding: 8px 14px; }}
            QPushButton:pressed, QPushButton[rec="true"] {{ background: {self.c_hot}; color: {bg}; }}
            QPushButton:disabled {{ color: {dim}; }}
            QProgressBar {{ background: {panel}; border: 1px solid {line}; height: 14px; }}
            QProgressBar::chunk {{ background: {self.c_ok}; }}
            QCheckBox {{ color: {text}; }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 22, 28, 22)
        lay.setSpacing(12)

        head = QLabel("MAGI · VOZ DA CONDESSA")
        head.setFont(font("mono", 13, 500))
        head.setStyleSheet(f"color: {dim}; letter-spacing: 2px;")
        self.progress_lbl = QLabel()
        self.progress_lbl.setFont(font("mono", 16))
        self.step_lbl = QLabel()
        self.step_lbl.setFont(font("cond", 22, 600))
        self.step_lbl.setStyleSheet(f"color: {accent};")
        self.say_lbl = QLabel()
        self.say_lbl.setFont(font("mincho", 52))
        self.say_lbl.setWordWrap(True)
        self.how_lbl = QLabel()
        self.how_lbl.setFont(font("cond", 26))
        self.how_lbl.setWordWrap(True)
        self.level = QProgressBar()
        self.level.setRange(0, 100)
        self.level.setTextVisible(False)
        self.status_lbl = QLabel(" ")
        self.status_lbl.setFont(font("cond", 22, 600))
        self.status_lbl.setWordWrap(True)

        self.big = QPushButton()
        self.big.setFont(font("cond", 24, 600))
        self.big.setMinimumHeight(72)
        self.big.pressed.connect(self.press)
        self.big.released.connect(self.release)

        self.redo_btn = QPushButton("Regravar última (R)")
        self.redo_btn.clicked.connect(self.redo)
        self.skip_btn = QPushButton("Pular (P)")
        self.skip_btn.clicked.connect(self.skip)
        self.play_btn = QPushButton("Ouvir a última (O)")
        self.play_btn.clicked.connect(self.play_last)
        self.auto_chk = QCheckBox("Automático (A)")
        self.auto_chk.toggled.connect(lambda _on: self.refresh())
        row = QHBoxLayout()
        for b in (self.redo_btn, self.skip_btn, self.play_btn):
            b.setFont(font("cond", 18))
            row.addWidget(b)
        self.auto_chk.setFont(font("cond", 18))
        row.addStretch(1)
        row.addWidget(self.auto_chk)
        # o teclado fica com a janela (Espaço não "clica" o botão que estiver com foco)
        for wd in (self.big, self.redo_btn, self.skip_btn, self.play_btn, self.auto_chk):
            wd.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        for wd in (head, self.progress_lbl, self.step_lbl, self.say_lbl, self.how_lbl):
            lay.addWidget(wd)
        lay.addStretch(1)
        lay.addWidget(self.level)
        lay.addWidget(self.status_lbl)
        lay.addWidget(self.big)
        lay.addLayout(row)

    # --- tela ------------------------------------------------------------------------------

    def set_status(self, msg: str, color: str | None = None) -> None:
        self.status_lbl.setText(msg)
        self.status_lbl.setStyleSheet(f"color: {color};" if color else "")

    def refresh(self) -> None:
        s = self.session
        self.progress_lbl.setText(" · ".join(f"{SECTION_NAME.get(sec, sec)} {d}/{t}"
                                             for sec, d, t in s.progress()))
        take = s.current()
        self.redo_btn.setEnabled(s.last is not None and self.state == "idle")
        self.play_btn.setEnabled(s.last is not None)
        if take is None:
            self.step_lbl.setText("FIM")
            if s.complete():
                self.say_lbl.setText("Pronto! Pode avisar o Claude")
            else:
                self.say_lbl.setText("Fim do roteiro (alguns passos foram pulados)")
            self.how_lbl.setText(f"Arquivos em: {s.base}"
                                 + ("" if s.complete() else "\nAbra de novo para gravar o que faltou."))
            self.big.hide()
            self.skip_btn.setEnabled(False)
            self.auto_chk.setEnabled(False)
            return
        n, total = s.step()
        self.step_lbl.setText(f"{SECTION_ONE.get(take.section, take.section)} {n}/{total}")
        self.skip_btn.setEnabled(self.state == "idle")
        if take.section == "noise":
            self.say_lbl.setText(f"Silêncio por {take.seconds:g} s")
            self.how_lbl.setText(f"— {take.how}")
            if self.state != "noise":
                self.big.setText(f"Gravar {take.seconds:g} s de silêncio")
        elif take.say.startswith("("):
            self.say_lbl.setText(take.how[:1].upper() + take.how[1:])
            self.how_lbl.setText("— fala livre, à vontade (até uns 20 s)")
        else:
            self.say_lbl.setText(f"Diga: {take.say}")
            self.how_lbl.setText(f"— {take.how}")
        if take.section != "noise" and self.state == "idle":
            self.big.setText("Ouvindo… é só falar" if self.auto_chk.isChecked()
                             else "Segure Espaço (ou aqui) para gravar · solte para salvar")
        self.big.setProperty("rec", self.state in ("hold", "auto", "noise"))
        self.big.style().unpolish(self.big)
        self.big.style().polish(self.big)

    # --- áudio -----------------------------------------------------------------------------

    def poll(self) -> None:
        chunks = self.mic.drain()
        for c in chunks:
            self.feed(c)
        if chunks:
            self.level.setValue(int(np.clip((dbfs(chunks[-1]) + 60.0) / 60.0 * 100.0, 0, 100)))

    def _cap(self, take: record.Take) -> int:
        return int(max(take.seconds * 2, 6.0) * AUDIO_RATE)

    def feed(self, c: np.ndarray) -> None:
        self.t += len(c)
        take = self.session.current()
        n = sum(len(b) for b in self.buf)
        if self.state == "hold" and take is not None:
            self.buf.append(c)
            if n + len(c) >= self._cap(take):
                self.finish()
        elif self.state == "noise" and take is not None:
            self.buf.append(c)
            need = int(take.seconds * AUDIO_RATE)
            left = max(0.0, (need - n - len(c)) / AUDIO_RATE)
            self.big.setText(f"Silêncio… {left:.0f} s")
            if n + len(c) >= need:
                self.finish()
        elif self.state == "auto" and take is not None:
            self.buf.append(c)
            self.quiet = self.quiet + len(c) if dbfs(c) < self.thr - 3 else 0
            close = SILENCE_CLOSE_FREE if take.say.startswith("(") else SILENCE_CLOSE
            if self.quiet >= int(close * AUDIO_RATE) or n + len(c) >= self._cap(take):
                self.finish()
        elif (self.state == "idle" and self.auto_chk.isChecked() and take is not None
              and take.section != "noise" and self.t >= self.cooldown_until):
            db = dbfs(c)
            self.thr = max(-48.0, self.floor + 12.0)
            if db >= self.thr:
                self.loud += 1
            else:
                self.loud = 0
                self.floor = 0.9 * self.floor + 0.1 * db if db < self.floor + 6 else self.floor
            if self.loud >= 2:
                self.loud, self.quiet = 0, 0
                self.state = "auto"
                self.buf = list(self.pre) + [c]
                self.set_status("● gravando…", self.c_hot)
                self.refresh()
        self.pre.append(c)
        while sum(len(b) for b in self.pre) > PREROLL:
            self.pre.popleft()

    def finish(self) -> None:
        raw = np.concatenate(self.buf) if self.buf else np.zeros(0, np.int16)
        self.buf, self.state = [], "idle"
        self.pre.clear()  # o pré-roll da próxima não pode trazer o fim desta
        self.cooldown_until = self.t + COOLDOWN
        res = self.session.submit(raw)
        if res.path is None:
            self.set_status("⚠ não ouvi nada (mudo ou curto demais) — não salvei; tente de novo",
                            self.c_warn)
        else:
            self.beep()
            note = f" · {res.note}" if res.note else ""
            self.set_status(f"✓ salvo ({res.seconds:.1f} s){note}", self.c_warn if note else self.c_ok)
        self.refresh()

    # --- ações -----------------------------------------------------------------------------

    def press(self) -> None:
        take = self.session.current()
        if take is None or self.state != "idle":
            return
        self.state = "noise" if take.section == "noise" else "hold"
        self.buf = [] if take.section == "noise" else list(self.pre)
        self.set_status("● gravando silêncio — fique quieto" if take.section == "noise"
                        else "● gravando… solte para salvar", self.c_hot)
        self.refresh()

    def release(self) -> None:
        if self.state == "hold":
            self.finish()

    def redo(self) -> None:
        if self.state != "idle":
            return
        path = self.session.redo_last()
        self.set_status(f"apaguei {path.name}; grave de novo" if path else "nada para regravar nesta sessão")
        self.refresh()

    def skip(self) -> None:
        if self.state != "idle":
            return
        self.session.skip()
        self.set_status("pulado")
        self.refresh()

    def play_last(self) -> None:
        if self.session.last is None:
            self.set_status("nada gravado ainda nesta sessão")
            return
        try:
            self.play(read_wav(self.session.last[1]))
        except OSError as e:
            self.set_status(f"não consegui tocar: {e}", self.c_warn)

    def keyPressEvent(self, e: QKeyEvent) -> None:  # noqa: N802
        if e.isAutoRepeat():
            return
        k = e.key()
        if k == Qt.Key.Key_Space:
            self.press()
        elif k in (Qt.Key.Key_R, Qt.Key.Key_Backspace):
            self.redo()
        elif k == Qt.Key.Key_P:
            self.skip()
        elif k == Qt.Key.Key_O:
            self.play_last()
        elif k == Qt.Key.Key_A:
            self.auto_chk.toggle()
        elif k == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(e)

    def keyReleaseEvent(self, e: QKeyEvent) -> None:  # noqa: N802
        if e.key() == Qt.Key.Key_Space and not e.isAutoRepeat():
            self.release()
        else:
            super().keyReleaseEvent(e)

    def closeEvent(self, e) -> None:  # noqa: N802
        self.timer.stop()
        try:
            self.mic.stop()
        except Exception:  # noqa: BLE001
            pass
        super().closeEvent(e)


def build_session(section: str = "all", word: str = DEFAULT_WORD, base: Path | None = None) -> Session:
    takes = record.build_takes()
    if section != "all":
        takes = [t for t in takes if t.section == section]
    return Session(takes, base or data_dir(word))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--section", choices=["all", "positive", "negative", "noise"], default="all")
    ap.add_argument("--word", default=DEFAULT_WORD, help="palavra/modelo (pasta dos dados); padrão: condessa")
    ap.add_argument("--data-dir", type=Path, default=None,
                    help="padrão: ~/.local/share/magi/wakeword-data/<word>")
    ap.add_argument("--device", default=None, help="dispositivo do PortAudio (nome ou número)")
    ap.add_argument("--target", default=None, help="source do PipeWire (como [satellite] mic_target)")
    args = ap.parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    session = build_session(args.section, args.word, args.data_dir)
    device = int(args.device) if args.device and args.device.isdigit() else args.device
    try:
        mic = SoundDeviceMic(device, args.target)
    except Exception as e:  # noqa: BLE001
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.critical(None, "Gravar voz da Condessa", f"Não consegui abrir o microfone:\n{e}")
        return 1
    win = RecorderWindow(session, mic)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
