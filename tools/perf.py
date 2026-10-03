"""Medição de desempenho da fase 1 (§10; RNF-01, RNF-02, RNF-04, RNF-05).

Só LÊ os serviços em execução: não reinicia, não para, não muda configuração.

    uv run python -m tools.perf idle [--minutes 10] [--json saida.json]
    uv run python -m tools.perf latency [--turns 50] [--phrase "cancela"] [--json saida.json]

``idle``: a cada 5 s lê o cgroup do systemd (``cpu.stat``) e o ``smaps_rollup`` de cada processo de
``magi-satellite`` e ``magi-core`` (RSS e PSS), e o cgroup do container ``magi-pg`` (CPU e memória,
mesma conta do ``docker stats``, que roda só no início e no fim: leva vários segundos por chamada).
Reporta média, p90 e máximo de CPU (% de um núcleo) e RAM (MB).

``latency``: cliente Wyoming próprio (satélite ``perf``, máquina de turno separada no núcleo; o
satélite real não é tocado). Áudio da frase gerado uma vez pelo TTS configurado e cacheado em
``~/.cache/magi/perf/``. Mede do ``audio-stop`` enviado até o primeiro ``audio-chunk`` da resposta.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import time
import wave
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

UNITS = ("magi-satellite", "magi-core")
CONTAINER = "magi-pg"
CGROUP_ROOT = Path("/sys/fs/cgroup")
SATELLITE_ID = "perf"


# -- agregação (testada em tests/tools/test_perf.py) ----------------------------------------------


@dataclass(frozen=True, slots=True)
class Stats:
    n: int
    mean: float
    p90: float
    max: float

    def fmt(self, unit: str = "", digits: int = 2) -> str:
        d = digits
        return f"média {self.mean:.{d}f}{unit} · p90 {self.p90:.{d}f}{unit} · máx {self.max:.{d}f}{unit}"


def percentile(values: Sequence[float], q: float) -> float:
    """Percentil ``q`` (0..100) com interpolação linear entre vizinhos (como ``numpy`` padrão)."""
    if not values:
        raise ValueError("sem amostras")
    if not 0 <= q <= 100:
        raise ValueError("q fora de 0..100")
    xs = sorted(values)
    pos = (len(xs) - 1) * q / 100
    lo, hi = math.floor(pos), math.ceil(pos)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def summarize(values: Sequence[float]) -> Stats:
    return Stats(n=len(values), mean=sum(values) / len(values), p90=percentile(values, 90), max=max(values))


def cpu_percent(prev_usec: int, cur_usec: int, dt_s: float) -> float:
    """CPU entre duas leituras de ``usage_usec``, em % de um núcleo."""
    if dt_s <= 0:
        raise ValueError("intervalo não positivo")
    return max(0, cur_usec - prev_usec) / (dt_s * 1e6) * 100


_SIZE = re.compile(r"^\s*([\d.]+)\s*([KMGT]?i?B)\s*$", re.IGNORECASE)
_FACTOR = {"b": 1, "kb": 1e3, "mb": 1e6, "gb": 1e9, "tb": 1e12,
           "kib": 1024, "mib": 1024**2, "gib": 1024**3, "tib": 1024**4}


def parse_size_mb(text: str) -> float:
    """``"166.8MiB"`` → MB (10^6 bytes)."""
    m = _SIZE.match(text)
    if not m:
        raise ValueError(f"tamanho inválido: {text!r}")
    return float(m.group(1)) * _FACTOR[m.group(2).lower()] / 1e6


def parse_docker_stats(line: str) -> tuple[float, float]:
    """Uma linha JSON de ``docker stats --format '{{json .}}'`` → (CPU %, memória MB)."""
    d = json.loads(line)
    cpu = float(d["CPUPerc"].rstrip("%"))
    mem = parse_size_mb(d["MemUsage"].split("/")[0])
    return cpu, mem


def parse_smaps_rollup(text: str) -> tuple[float, float]:
    """Conteúdo de ``/proc/<pid>/smaps_rollup`` → (RSS MB, PSS MB)."""
    vals: dict[str, float] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0] in ("Rss:", "Pss:") and parts[2] == "kB":
            vals[parts[0]] = int(parts[1]) * 1024 / 1e6
    return vals.get("Rss:", 0.0), vals.get("Pss:", 0.0)


# -- idle ----------------------------------------------------------------------------------------


def unit_cgroup(unit: str) -> Path:
    out = subprocess.run(["systemctl", "--user", "show", "-p", "MainPID", "-p", "ControlGroup", unit],
                         capture_output=True, text=True, check=True).stdout
    props = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    if props.get("MainPID", "0") == "0" or not props.get("ControlGroup"):
        raise RuntimeError(f"{unit} não está rodando")
    return CGROUP_ROOT / props["ControlGroup"].lstrip("/")


def cgroup_usage_usec(cg: Path) -> int:
    for line in (cg / "cpu.stat").read_text().splitlines():
        if line.startswith("usage_usec "):
            return int(line.split()[1])
    raise RuntimeError(f"sem usage_usec em {cg}")


def cgroup_mem_mb(cg: Path) -> tuple[float, float]:
    """Soma RSS e PSS dos processos do cgroup."""
    rss = pss = 0.0
    for pid in (cg / "cgroup.procs").read_text().split():
        with contextlib.suppress(OSError):
            r, p = parse_smaps_rollup(Path(f"/proc/{pid}/smaps_rollup").read_text())
            rss += r
            pss += p
    return rss, pss


def docker_sample(container: str) -> tuple[float, float] | None:
    """``docker stats --no-stream`` → (CPU %, memória MB); ``None`` se falhar. Leva ~2-10 s."""
    try:
        out = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{json .}}", container],
                             capture_output=True, text=True, timeout=30, check=True).stdout
        return parse_docker_stats(out.strip().splitlines()[0])
    except (subprocess.SubprocessError, OSError, ValueError, KeyError, IndexError):
        return None


def container_cgroup(container: str) -> Path:
    cid = subprocess.run(["docker", "inspect", "-f", "{{.Id}}", container],
                         capture_output=True, text=True, check=True).stdout.strip()
    return CGROUP_ROOT / "system.slice" / f"docker-{cid}.scope"


def parse_memory_stat(text: str) -> dict[str, int]:
    return {k: int(v) for k, v in (line.split() for line in text.splitlines() if line.strip())}


def container_mem_mb(cg: Path) -> tuple[float, float]:
    """(memória como o ``docker stats`` mostra, anon+shmem) em MB.

    O ``docker stats`` mostra ``memory.current - inactive_file``: inclui cache de arquivo ativo,
    que o kernel devolve sob pressão. ``anon + shmem`` é o residente do Postgres (heap +
    ``shared_buffers``) sem cache. Os processos do container são de outro usuário, sem PSS legível.
    """
    st = parse_memory_stat((cg / "memory.stat").read_text())
    current = int((cg / "memory.current").read_text())
    return (current - st.get("inactive_file", 0)) / 1e6, (st.get("anon", 0) + st.get("shmem", 0)) / 1e6


def run_idle(minutes: float, interval: float = 5.0) -> dict[str, dict[str, Stats]]:
    """Amostra a cada ``interval`` s. Chaves: ``cpu`` (%), ``rss`` e ``pss`` (MB).

    No ``magi-pg``, ``rss`` = valor do ``docker stats`` e ``pss`` = anon+shmem (ver acima).
    """
    cgs = {u: unit_cgroup(u) for u in UNITS}
    cgs[CONTAINER] = container_cgroup(CONTAINER)
    series: dict[str, dict[str, list[float]]] = {
        name: {"cpu": [], "rss": [], "pss": []} for name in (*cgs, "total")
    }
    prev = {name: cgroup_usage_usec(cg) for name, cg in cgs.items()}
    t_prev = time.monotonic()
    end = t_prev + minutes * 60
    n = 0
    restarts: dict[str, int] = {}
    while time.monotonic() < end:
        time.sleep(max(0.0, interval - (time.monotonic() - t_prev)))
        now = time.monotonic()
        dt, t_prev = now - t_prev, now
        tot = {"cpu": 0.0, "rss": 0.0, "pss": 0.0}
        complete = True
        for name, cg in cgs.items():
            try:
                cur = cgroup_usage_usec(cg)
                rss, pss = container_mem_mb(cg) if name == CONTAINER else cgroup_mem_mb(cg)
            except (OSError, RuntimeError):
                # serviço reiniciou (cgroup recriado) ou caiu: descarta a amostra e tenta de novo
                complete = False
                restarts[name] = restarts.get(name, 0) + 1
                with contextlib.suppress(OSError, RuntimeError, subprocess.SubprocessError):
                    cgs[name] = unit_cgroup(name) if name in UNITS else container_cgroup(name)
                    prev[name] = cgroup_usage_usec(cgs[name])
                continue
            cpu = cpu_percent(prev[name], cur, dt)
            prev[name] = cur
            for k, v in (("cpu", cpu), ("rss", rss), ("pss", pss)):
                series[name][k].append(v)
                tot[k] += v
        n += 1
        if not complete:
            print(f"[{n}] amostra descartada (reinícios: {restarts})", file=sys.stderr, flush=True)
            continue
        for k, v in tot.items():
            series["total"][k].append(v)
        print(f"[{n}] " + " | ".join(f"{name} {s['cpu'][-1]:.2f}% {s['rss'][-1]:.0f}/{s['pss'][-1]:.0f}MB"
                                     for name, s in series.items() if s["cpu"]), file=sys.stderr, flush=True)
    if restarts:
        print(f"amostras descartadas por reinício: {restarts}", file=sys.stderr)
    return {name: {k: summarize(v) for k, v in s.items() if v} for name, s in series.items()}


# -- latency -------------------------------------------------------------------------------------


def cache_dir() -> Path:
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "magi" / "perf"


async def phrase_audio(text: str) -> tuple[bytes, int, int, int]:
    """PCM da frase (TTS configurado, uma vez; depois do cache). → (pcm, rate, width, channels)."""
    key = hashlib.sha256(text.encode()).hexdigest()[:16]
    path = cache_dir() / f"{key}.wav"
    if not path.exists():
        from magi.common.config import load_config
        from magi.core.assemble import NullBudget
        from magi.providers.registry import Registry

        cfg = load_config()
        tts = Registry(cfg, NullBudget(cfg.budget.monthly_usd)).tts()
        pcm = b"".join([c async for c in tts.synthesize(text, personal=False)])
        f = tts.output_format
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(f.channels)
            w.setsampwidth(f.width)
            w.setframerate(f.rate)
            w.writeframes(pcm)
    with wave.open(str(path), "rb") as w:
        return w.readframes(w.getnframes()), w.getframerate(), w.getsampwidth(), w.getnchannels()


async def run_latency(phrase: str, turns: int, host: str, port: int, gap_s: float = 1.5,
                      timeout_s: float = 20.0) -> tuple[list[float], list[float], int]:
    """→ (latências s, duração da resposta s, falhas)."""
    from wyoming.event import async_read_event, async_write_event

    from magi.common.contracts import (
        AudioEnd,
        AudioEndReason,
        PcmFormat,
        PlaybackDone,
        SatelliteHello,
        WakeEvent,
        WakeSource,
    )
    from magi.common.events import audio_chunk, audio_start, split_chunks, to_event

    pcm, rate, width, channels = await phrase_audio(phrase)
    fmt = PcmFormat(rate=rate, width=width, channels=channels)
    reader, writer = await asyncio.open_connection(host, port)
    hello = SatelliteHello(satellite=SATELLITE_ID, name="perf", version="0")
    await async_write_event(to_event(hello), writer)
    events: asyncio.Queue = asyncio.Queue()

    async def pump() -> None:
        while (ev := await async_read_event(reader)) is not None:
            events.put_nowait((time.perf_counter(), ev))

    pump_task = asyncio.create_task(pump())
    lats: list[float] = []
    durs: list[float] = []
    fails = 0
    try:
        for i in range(turns):
            while not events.empty():
                events.get_nowait()
            wake = WakeEvent(source=WakeSource.PTT, satellite=SATELLITE_ID)
            await async_write_event(to_event(wake), writer)
            await async_write_event(audio_start(fmt), writer)
            for chunk in split_chunks(pcm, fmt):
                await async_write_event(audio_chunk(chunk, fmt), writer)
            await async_write_event(to_event(AudioEnd(reason=AudioEndReason.VAD)), writer)
            t0 = time.perf_counter()
            first: float | None = None
            nbytes = 0
            out_fmt = fmt
            try:
                async with asyncio.timeout(timeout_s):
                    while True:
                        t, ev = await events.get()
                        if t < t0:  # ex.: bip da ativação, antes do fim da fala
                            continue
                        if ev.type == "audio-start":
                            d = ev.data or {}
                            out_fmt = PcmFormat(rate=d.get("rate", rate), width=d.get("width", width),
                                                channels=d.get("channels", channels))
                        elif ev.type == "audio-chunk":
                            first = first or t
                            nbytes += len(ev.payload or b"")
                        elif ev.type == "audio-stop" and first is not None:
                            break
            except TimeoutError:
                pass
            if first is None:
                fails += 1
                print(f"[{i + 1}] sem resposta em {timeout_s:.0f} s", file=sys.stderr)
            else:
                lats.append(first - t0)
                durs.append(nbytes / (out_fmt.rate * out_fmt.width * out_fmt.channels))
                print(f"[{i + 1}] {lats[-1] * 1000:.0f} ms (resposta {durs[-1]:.1f} s)", file=sys.stderr)
            await async_write_event(to_event(PlaybackDone(satellite=SATELLITE_ID)), writer)
            await asyncio.sleep(gap_s)
    finally:
        pump_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pump_task
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()
    return lats, durs, fails


# -- CLI -----------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="perf", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    pi = sub.add_parser("idle", help="CPU/RAM ociosos (RNF-01/02)")
    pi.add_argument("--minutes", type=float, default=10.0)
    pi.add_argument("--interval", type=float, default=5.0)
    pl = sub.add_parser("latency", help="latência fim da fala → primeiro áudio (RNF-04/05)")
    pl.add_argument("--turns", type=int, default=50)
    pl.add_argument("--phrase", default="cancela")
    pl.add_argument("--host", default="127.0.0.1")
    pl.add_argument("--port", type=int, default=10750)
    pl.add_argument("--gap", type=float, default=1.5, help="pausa entre turnos (s)")
    for sp in (pi, pl):
        sp.add_argument("--json", type=Path, help="grava o resultado em JSON")
    args = p.parse_args(argv)

    if args.cmd == "idle":
        before = docker_sample(CONTAINER)
        res = run_idle(args.minutes, args.interval)
        after = docker_sample(CONTAINER)
        print(f"docker stats {CONTAINER} (CPU %, MB): antes {before} · depois {after}")
        for name, stats in res.items():
            print(f"{name}:")
            if "cpu" in stats:
                print(f"  CPU  {stats['cpu'].fmt('%')}")
            for k in ("rss", "pss"):
                if k in stats:
                    print(f"  {k.upper()}  {stats[k].fmt(' MB', 1)}")
        out = {name: {k: asdict(s) for k, s in st.items()} for name, st in res.items()}
        out["docker_stats"] = {"before": before, "after": after}
    else:
        lats, durs, fails = asyncio.run(run_latency(args.phrase, args.turns, args.host, args.port, args.gap))
        out = {"phrase": args.phrase, "turns": args.turns, "fails": fails}
        if lats:
            s = summarize(lats)
            print(f"{args.phrase!r}: {s.fmt(' s', 3)} · n={s.n} · falhas={fails}")
            out |= {"latency_s": asdict(s), "reply_s": asdict(summarize(durs)), "samples_s": lats}
        else:
            print(f"{args.phrase!r}: nenhuma resposta ({fails} falhas)")
    if args.json:
        args.json.write_text(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
