"""Roteiro de gravação do wake word "Condessa" (spike S4).

Uso::

    uv run python -m tools.wakeword.record            # tudo: positivas, negativas, ruído
    uv run python -m tools.wakeword.record --section positive
    uv run python -m tools.wakeword.record --list-devices

Grava WAV 16 kHz mono em ``~/.local/share/magi/wakeword-data/<word>/{positive,negative,noise}/``
(``--word``, padrão ``condessa``). Positivas: "Condessa" sozinha ou com "hey/oi/oh" na frente.
Retoma de onde parou (conta os arquivos que já existem). Em cada passo: Enter grava,
``r`` + Enter apaga e regrava a última, ``p`` + Enter pula, ``q`` + Enter sai.
Pode rodar com o ``magi-satellite`` ligado: o PipeWire entrega o microfone aos dois.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from tools.wakeword.common import (
    AUDIO_RATE,
    DEFAULT_WORD,
    data_dir,
    dbfs,
    next_index,
    trim_silence,
    write_wav,
)

APP_NAME = "magi-wakeword-rec"


@dataclass(frozen=True, slots=True)
class Take:
    section: str  # positive | negative | noise
    label: str  # vai no nome do arquivo
    say: str  # o que falar
    how: str  # instrução
    seconds: float


# (rótulo, instrução, quantidade)
POSITIVE_STYLES = [
    ("normal", "voz normal, como se chamasse alguém do lado", 8),
    ("baixo", "baixinho, quase sussurrando", 6),
    ("alto", "alto, chamando de longe", 6),
    ("rapido", "rápido, emendado", 6),
    ("lento", "devagar, arrastado", 5),
    ("longe", "a 1–2 m do microfone (ou de costas para ele)", 6),
    ("fundo", "com jogo ou música tocando alto nas caixas", 7),
    ("cansado", "cansado, bocejando, voz de sono", 5),
    ("rindo", "rindo ou sorrindo enquanto fala", 5),
]

#: Formas que o Pedro usa para chamar; o modelo dispara com "Condessa" em qualquer uma.
#: "Condessa" nunca entra nas negativas (ensinaria o modelo a ignorá-la).
POSITIVE_FORMS = ["Condessa", "Hey Condessa", "Oi Condessa", "Oh Condessa"]

NEGATIVE_PHRASES = [
    "Condensa o texto.", "Confessa logo!", "Com dez reais dá.", "Concessão de rua.", "Que promessa!",
    "Vai, depressa!", "Põe na mesa.", "A mesa tá cheia.", "Comece agora.", "Boa conversa.",
    "Com essa condição, não.", "Oi, vovó!", "Hey, você!", "Oi, tudo bem?", "Oh, que isso!",
    "Com certeza.", "Professora chegou.", "Condomínio novo.", "Confesso que gostei.",
    "Com pressa não dá.", "Essa sobremesa é boa.", "Hey, Siri.", "Oi, Clara!", "Oh, Vanessa!",
    "Começa a partida.", "Contesta o juiz.", "Bora jogar Valorant.", "Abre o Minecraft aí.",
    "Partida de League of Legends.", "Vou jogar Elden Ring.", "Hollow Knight é muito bom.",
    "Counter-Strike de noite.", "Me passa a munição.", "Cadê o mapa?", "Hoje tem jogo do Brasil.",
    "Que condição, hein?",
]

FREE_TALK = [
    "conte como foi o seu dia",
    "descreva o jogo que você mais jogou esta semana",
    "leia em voz alta qualquer texto da tela",
]


def build_takes() -> list[Take]:
    styles = [(label, how) for label, how, n in POSITIVE_STYLES for _ in range(n)]
    # as formas se alternam, então cada jeito de falar pega todas (ou quase todas) elas
    takes = [
        Take("positive", label, POSITIVE_FORMS[i % len(POSITIVE_FORMS)], how, 2.5)
        for i, (label, how) in enumerate(styles)
    ]
    takes += [Take("negative", "frase", p, "voz normal", 3.5) for p in NEGATIVE_PHRASES]
    takes += [Take("negative", "livre", "(fala livre)", t, 20.0) for t in FREE_TALK]
    takes.append(
        Take("noise", "quarto", "(silêncio)", "fique quieto; deixe PC/ventilador como de costume", 60.0)
    )
    return takes


SECTION_PREFIX = {"positive": "pos", "negative": "neg", "noise": "noise"}


def take_path(base: Path, take: Take) -> Path:
    d = base / take.section
    prefix = f"{SECTION_PREFIX[take.section]}_{take.label}"
    return d / f"{prefix}_{next_index(d, prefix):03d}.wav"


def count_done(base: Path, section: str) -> int:
    d = base / section
    return len(list(d.glob("*.wav"))) if d.is_dir() else 0


Recorder = Callable[[float], np.ndarray]


def sounddevice_recorder(device: str | int | None = None, target: str | None = None) -> Recorder:
    """Grava ``seconds`` do microfone (PortAudio → plugin ALSA do PipeWire), int16 mono 16 kHz."""
    from magi.satellite.capture import pipewire_alsa_props

    os.environ["PIPEWIRE_ALSA"] = pipewire_alsa_props(APP_NAME, target)
    import sounddevice as sd

    def rec(seconds: float) -> np.ndarray:
        data = sd.rec(int(seconds * AUDIO_RATE), samplerate=AUDIO_RATE, channels=1, dtype="int16",
                      device=device)
        sd.wait()
        return np.asarray(data, dtype=np.int16).reshape(-1)

    return rec


def process(take: Take, pcm: np.ndarray) -> np.ndarray:
    """Corta silêncio das bordas (menos no ruído do quarto)."""
    return pcm if take.section == "noise" else trim_silence(pcm)


def pending_queue(takes: list[Take], base: Path) -> tuple[dict[str, list[int]], list[int]]:
    """Agrupa os passos por seção e monta a fila do que falta (retoma: em cada seção, pula os
    passos que já têm arquivo). Devolve ``(índices por seção, fila de índices em ``takes``)``."""
    by_section: dict[str, list[int]] = {}
    for i, t in enumerate(takes):
        by_section.setdefault(t.section, []).append(i)
    queue: list[int] = []
    for section, idxs in by_section.items():
        queue += idxs[count_done(base, section):]
    return by_section, queue


@dataclass(frozen=True, slots=True)
class Saved:
    path: Path | None  # None: não ouviu nada (mudo/curto demais), nada foi salvo
    seconds: float
    level: float  # dBFS do trecho salvo (ou do bruto, se não salvou)
    note: str  # aviso de saturação/volume baixo ("" se ok)


def save_take(take: Take, base: Path, raw: np.ndarray) -> Saved:
    """Corta o silêncio, recusa gravação muda/curta (< 0,2 s de som) e grava o WAV."""
    pcm = process(take, raw)
    if len(pcm) < AUDIO_RATE // 5:
        return Saved(None, 0.0, dbfs(raw), "")
    peak = int(np.abs(pcm.astype(np.int32)).max())
    level = dbfs(pcm)
    path = take_path(base, take)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_wav(path, pcm)
    note = ""
    if peak >= 32000:
        note = "saturou: fale um pouco mais longe/baixo"
    elif take.section != "noise" and level < -45:
        note = "muito baixo: confira o microfone"
    return Saved(path, len(pcm) / AUDIO_RATE, level, note)


def run(
    takes: list[Take],
    base: Path,
    recorder: Recorder,
    *,
    ask: Callable[[str], str] = input,
    out: Callable[[str], None] = print,
) -> int:
    """Executa o roteiro. Devolve quantos arquivos foram salvos nesta sessão."""
    by_section, queue = pending_queue(takes, base)
    saved = 0
    last: tuple[int, Path] | None = None  # (posição na fila, arquivo)
    pos = 0
    while pos < len(queue):
        take = takes[queue[pos]]
        total = len(by_section[take.section])
        done = count_done(base, take.section)
        out(f"\n[{take.section} {done + 1}/{total}] {take.how}")
        out(f'  Fale: "{take.say}"   ({take.seconds:g} s)')
        cmd = ask("  Enter grava · r regrava a última · p pula · q sai > ").strip().lower()
        if cmd == "q":
            break
        if cmd == "p":
            pos += 1
            continue
        if cmd == "r":
            if last is None:
                out("  nada para regravar nesta sessão")
                continue
            pos, path = last
            path.unlink(missing_ok=True)
            saved -= 1
            last = None
            out(f"  apagado {path.name}; regravando")
            continue
        out("  >>> gravando... fale agora" if take.section != "noise" else "  >>> gravando silêncio...")
        res = save_take(take, base, recorder(take.seconds))
        if res.path is None:
            out(f"  não ouvi nada (pico {res.level:.0f} dBFS); vamos repetir")
            continue
        saved += 1
        last = (pos, res.path)
        note = f"  ({res.note})" if res.note else ""
        out(f"  ok: {res.seconds:.2f} s, {res.level:.0f} dBFS -> {res.path.name}{note}")
        pos += 1
    for section in by_section:
        out(f"{section}: {count_done(base, section)}/{len(by_section[section])}")
    return saved


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--section", choices=["all", "positive", "negative", "noise"], default="all")
    ap.add_argument("--word", default=DEFAULT_WORD, help="palavra/modelo (pasta dos dados); padrão: condessa")
    ap.add_argument("--data-dir", type=Path, default=None,
                    help="padrão: ~/.local/share/magi/wakeword-data/<word>")
    ap.add_argument("--device", default=None, help="dispositivo do PortAudio (nome ou número)")
    ap.add_argument("--target", default=None, help="source do PipeWire (como [satellite] mic_target)")
    ap.add_argument("--list-devices", action="store_true")
    args = ap.parse_args(argv)
    if args.list_devices:
        import sounddevice as sd

        print(sd.query_devices())
        return 0
    takes = build_takes()
    if args.section != "all":
        takes = [t for t in takes if t.section == args.section]
    base = args.data_dir or data_dir(args.word)
    device = int(args.device) if args.device and args.device.isdigit() else args.device
    print(f"Gravando em {base}. Leva ~15 min no total. Use o microfone de sempre (headset).")
    try:
        run(takes, base, sounddevice_recorder(device, args.target))
    except (KeyboardInterrupt, EOFError):
        print("\ninterrompido; o que já foi gravado ficou salvo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
