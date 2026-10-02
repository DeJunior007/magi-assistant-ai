"""Spike S1 — áudio no PipeWire (tarefa 0.4).

Prova, no PipeWire do Nobara, os mecanismos que o satélite vai usar:

  capture   microfone padrão a 16 kHz mono em blocos de 80 ms (só mede RMS, nada vai a disco)
  list      pipewire-pulse responde ao pulsectl; lista source-outputs e sink-inputs e classifica
  discord   procura o source-output de captura do Discord (mostra as regras se não houver)
  control   muta/desmuta um source-output e baixa/restaura um sink-input — em fluxos PRÓPRIOS
            (silêncio), ou num sink-input de terceiro com --sink-input N (sempre restaura)
  latency   tempo para abrir/iniciar um stream de reprodução e até o primeiro callback
  all       tudo acima, em ordem

Uso:  uv run python spikes/s1_audio.py all
      uv run python spikes/s1_audio.py discord --mute-test      (com o Discord em call)
Outra fonte:  PIPEWIRE_ALSA='{ application.name = "magi-s1" target.object = "<source>" }' ...
Requer a biblioteca do sistema PortAudio (`sudo dnf install portaudio`).
"""

from __future__ import annotations

import argparse
import contextlib
import os
import re
import statistics
import sys
import threading
import time

# Nomeia os nossos fluxos no PipeWire (lido pelo plugin pipewire-alsa ao abrir o PCM).
# Precisa estar no ambiente antes de abrir qualquer stream do PortAudio.
SELF_APP = "magi-s1"  # nome fixo: o WirePlumber guarda uma entrada por application.name
os.environ.setdefault("PIPEWIRE_ALSA", f'{{ application.name = "{SELF_APP}" media.role = "Assistant" }}')

import numpy as np  # noqa: E402
import pulsectl  # noqa: E402

try:
    import sounddevice as sd  # noqa: E402
except OSError as exc:  # libportaudio.so não instalada (o wheel Linux não a embute)
    sys.exit(f"sounddevice indisponível: {exc}. Instale: sudo dnf install portaudio")

RATE = 16_000
BLOCK = RATE * 80 // 1000  # 1280 amostras = 80 ms
DUCK = 0.30

# Regras de identificação (ver docs/spikes/S1.md).
DISCORD_BINARIES = re.compile(r"discord|vesktop|webcord", re.I)
DISCORD_APP_NAMES = re.compile(r"discord|webrtc voiceengine", re.I)
SPOTIFY = re.compile(r"spotify", re.I)
WINE_BINARIES = {"wine64-preloader", "wine-preloader", "wine64", "wine", "wineserver"}

PROPS = (
    "application.name",
    "application.process.binary",
    "application.process.id",
    "pipewire.access.portal.app_id",
    "media.name",
    "media.role",
    "node.name",
)


def pulse() -> pulsectl.Pulse:
    return pulsectl.Pulse("magi-s1-spike")


def _steam_app_id(pid: str | None) -> str | None:
    if not pid:
        return None
    try:
        with open(f"/proc/{pid}/environ", "rb") as fh:
            for item in fh.read().split(b"\0"):
                if item.startswith(b"SteamAppId="):
                    return item.split(b"=", 1)[1].decode()
    except OSError:
        return None
    return None


def _comm(pid: str | None) -> str | None:
    if not pid:
        return None
    try:
        with open(f"/proc/{pid}/comm") as fh:
            return fh.read().strip()
    except OSError:
        return None


def classify(stream) -> str:
    """Rótulo do fluxo: self, discord, spotify, game ou other."""
    pr = stream.proplist
    name = pr.get("application.name", "")
    binary = pr.get("application.process.binary", "")
    app_id = pr.get("pipewire.access.portal.app_id", "") or pr.get("application.id", "")
    if name.startswith("magi-s1"):
        return "self"
    if DISCORD_BINARIES.search(binary) or DISCORD_APP_NAMES.search(name) or "discord" in app_id:
        return "discord"
    if SPOTIFY.search(binary) or SPOTIFY.search(name) or SPOTIFY.search(app_id):
        return "spotify"
    pid = pr.get("application.process.id")
    if binary in WINE_BINARIES or _steam_app_id(pid):
        return "game"
    return "other"


def describe(stream) -> str:
    pr = stream.proplist
    props = {k: pr[k] for k in PROPS if k in pr}
    pid = pr.get("application.process.id")
    extra = {"comm": _comm(pid), "SteamAppId": _steam_app_id(pid)}
    extra = {k: v for k, v in extra.items() if v}
    corked = getattr(stream, "corked", None)
    return (
        f"  #{stream.index:<6} [{classify(stream):7}] mute={stream.mute} "
        f"vol={[round(v, 2) for v in stream.volume.values]} corked={corked}\n"
        f"           {props} {extra}"
    )


# --- a) captura -------------------------------------------------------------


def cmd_capture(seconds: float = 2.0) -> None:
    print(f"\n== a) captura: microfone padrão, {RATE} Hz mono, blocos de {BLOCK} (80 ms)")
    print(f"   dispositivo padrão de entrada: {sd.query_devices(kind='input')['name']!r}")
    rms: list[float] = []
    stamps: list[float] = []
    sizes: set[int] = set()
    flags: list[str] = []

    def cb(indata, frames, _time, status):
        stamps.append(time.perf_counter())
        sizes.add(frames)
        if status:
            flags.append(str(status))
        rms.append(float(np.sqrt(np.mean(np.square(indata[:, 0])))))

    t0 = time.perf_counter()
    with sd.InputStream(samplerate=RATE, channels=1, dtype="float32", blocksize=BLOCK, callback=cb) as st:
        t_open = time.perf_counter() - t0
        with pulse() as p:
            so = _find_self(p, "source-output")
            source = p.source_info(so.source).name
        print(f"   ligado no PipeWire a: {source}")
        time.sleep(seconds)
        latency = st.latency
    gaps = np.diff(stamps) * 1000 if len(stamps) > 1 else np.array([0.0])
    print(f"   abrir+iniciar: {t_open * 1000:.0f} ms; latência informada: {latency * 1000:.0f} ms")
    print(f"   blocos: {len(rms)} (esperado ~{int(seconds / 0.08)}), tamanhos: {sorted(sizes)}")
    print(f"   intervalo entre callbacks: média {gaps.mean():.1f} ms, máx {gaps.max():.1f} ms")
    print(f"   RMS: min {min(rms):.5f}  média {statistics.mean(rms):.5f}  máx {max(rms):.5f}")
    print(f"   status (overflow etc.): {flags or 'nenhum'}")


# --- b) listagem ------------------------------------------------------------


def cmd_list() -> None:
    print("\n== b) pulsectl contra pipewire-pulse")
    with pulse() as p:
        info = p.server_info()
        print(f"   servidor: {info.server_name} {info.server_version}")
        print(f"   sink padrão: {info.default_sink_name}")
        print(f"   source padrão: {info.default_source_name}")
        outs = p.source_output_list()
        ins = p.sink_input_list()
    print(f"   source-outputs (capturas): {len(outs)}")
    for s in outs:
        print(describe(s))
    print(f"   sink-inputs (reproduções): {len(ins)}")
    for s in ins:
        print(describe(s))


# --- c) Discord --------------------------------------------------------------


def discord_capture(p: pulsectl.Pulse):
    """Source-outputs do Discord que estão capturando (não pausados)."""
    return [s for s in p.source_output_list() if classify(s) == "discord" and not getattr(s, "corked", False)]


def cmd_discord(mute_test: bool = False) -> None:
    print("\n== c) fluxo de captura do Discord")
    with pulse() as p:
        found = discord_capture(p)
        if not found:
            print("   nenhum source-output do Discord agora (Discord fechado ou fora de call).")
            print(f"   regra: application.process.binary ~ /{DISCORD_BINARIES.pattern}/i")
            print(f"       ou application.name ~ /{DISCORD_APP_NAMES.pattern}/i, e não corked.")
            print("   teste manual: entre numa call e rode `... s1_audio.py discord --mute-test`.")
            return
        for s in found:
            print(describe(s))
        if mute_test:
            for s in found:
                _mute_cycle(p, s.index)


# --- d) controle -------------------------------------------------------------


def _mute_cycle(p: pulsectl.Pulse, index: int, probe=None) -> None:
    before = p.source_output_info(index).mute
    if probe:
        print(f"   RMS antes do mudo: {probe():.6f}")
    try:
        p.source_output_mute(index, True)
        now = p.source_output_info(index).mute
        print(f"   source-output #{index}: mute {before} -> {now}")
        if probe:
            print(f"   RMS com mudo:      {probe():.6f}")
        else:
            time.sleep(0.5)
    finally:
        p.source_output_mute(index, before)
        print(f"   source-output #{index}: restaurado mute={p.source_output_info(index).mute}")


def _duck_cycle(p: pulsectl.Pulse, index: int) -> None:
    original = p.sink_input_info(index).volume
    try:
        t0 = time.perf_counter()
        p.volume_set_all_chans(p.sink_input_info(index), DUCK)
        dt = (time.perf_counter() - t0) * 1000
        now = p.sink_input_info(index).volume.values
        print(f"   sink-input #{index}: vol {original.values} -> {now} ({dt:.1f} ms)")
        time.sleep(0.5)
    finally:
        p.sink_input_volume_set(index, original)
        print(f"   sink-input #{index}: restaurado vol={p.sink_input_info(index).volume.values}")


def _find_self(p: pulsectl.Pulse, kind: str, timeout: float = 2.0):
    lister = p.sink_input_list if kind == "sink-input" else p.source_output_list
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        mine = [s for s in lister() if classify(s) == "self"]
        if mine:
            return mine[0]
        time.sleep(0.05)
    raise RuntimeError(f"nosso {kind} não apareceu no pipewire-pulse")


def cmd_control(sink_input: int | None = None) -> None:
    print(f"\n== d) mudo de source-output e ducking de sink-input (fluxos {SELF_APP})")
    silence = np.zeros((BLOCK * 3, 1), dtype="float32")
    with (
        sd.OutputStream(samplerate=48_000, channels=1, dtype="float32") as out,
        sd.InputStream(samplerate=RATE, channels=1, dtype="float32", blocksize=BLOCK) as inp,
        pulse() as p,
    ):
        out.write(silence)
        so = _find_self(p, "source-output")
        si = _find_self(p, "sink-input")
        print(describe(so))
        print(describe(si))

        def probe() -> float:
            inp.read(inp.read_available)  # descarta o que estava no buffer
            data, _ = inp.read(BLOCK * 4)
            return float(np.sqrt(np.mean(np.square(data[BLOCK:, 0]))))

        _mute_cycle(p, so.index, probe)
        print(f"   RMS depois:        {probe():.6f}")
        _duck_cycle(p, si.index)
        if sink_input is not None:
            try:
                target = p.sink_input_info(sink_input)
            except pulsectl.PulseIndexError:
                print(f"   sink-input #{sink_input} não existe mais (fluxos vêm e vão).")
                return
            print("   sink-input de terceiro:")
            print(describe(target))
            _duck_cycle(p, sink_input)


# --- e) latência de reprodução ------------------------------------------------


def cmd_latency(runs: int = 3) -> None:
    print("\n== e) latência de abrir stream de reprodução (48 kHz mono, silêncio)")
    for i in range(runs):
        first = threading.Event()

        def cb(outdata, frames, _time, status, first=first):
            outdata.fill(0)
            first.set()

        t0 = time.perf_counter()
        st = sd.OutputStream(samplerate=48_000, channels=1, dtype="float32", callback=cb)
        t_open = time.perf_counter() - t0
        st.start()
        t_start = time.perf_counter() - t0
        first.wait(2)
        t_first = time.perf_counter() - t0
        lat = st.latency
        st.stop()
        st.close()
        print(
            f"   #{i + 1}: abrir {t_open * 1000:.0f} ms, iniciar {t_start * 1000:.0f} ms, "
            f"1º callback {t_first * 1000:.0f} ms, latência informada {lat * 1000:.0f} ms"
        )
    with sd.OutputStream(samplerate=48_000, channels=1, dtype="float32", latency="low") as st:
        print(f"   latency='low': {st.latency * 1000:.0f} ms")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("cmd", choices=["capture", "list", "discord", "control", "latency", "all"])
    ap.add_argument("--seconds", type=float, default=2.0)
    ap.add_argument("--mute-test", action="store_true", help="discord: muta 0,5 s e desmuta")
    ap.add_argument("--sink-input", type=int, help="control: também baixa e restaura este índice")
    a = ap.parse_args()
    with contextlib.suppress(KeyboardInterrupt):
        if a.cmd in ("capture", "all"):
            cmd_capture(a.seconds)
        if a.cmd in ("list", "all"):
            cmd_list()
        if a.cmd in ("discord", "all"):
            cmd_discord(a.mute_test)
        if a.cmd in ("control", "all"):
            cmd_control(a.sink_input)
        if a.cmd in ("latency", "all"):
            cmd_latency()


if __name__ == "__main__":
    main()
