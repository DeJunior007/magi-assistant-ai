"""CA-Y58 (R6.8, spec §10.1 *Meta*): ``magi-casa servir`` com 3 ``DriverFalso`` e sondagem real por
10 min → ≤ 1% CPU médio e ≤ 80 MB RSS. Lento: só roda com ``pytest -m lento`` (fora disso é pulado).

A casa roda num processo próprio (como a unit), com ``HOME``/XDG em ``tmp_path``; a medida vem de
``/proc/<pid>``. ``CASA_RECURSOS_S`` encurta a janela (padrão 600 s).
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.lento

JANELA_S = float(os.environ.get("CASA_RECURSOS_S", "600"))
CPU_MAX = 0.01
RSS_MAX_MB = 80.0

SCRIPT = r"""
import asyncio, sys
from magi.casa import log
from magi.casa.config import CasaConfig
from magi.casa.driver import Cap, Capacidades, TvConfig
from magi.casa.falso import DriverFalso
from magi.casa.servir import servir_async

log.configurar("INFO", stream=sys.stderr)
tvs = tuple(TvConfig(id=f"tv{i}", nome=f"TV {i}", driver="falso", ip=f"10.0.0.{i}") for i in range(3))
caps = Capacidades(frozenset(Cap), entradas=("hdmi1",), apps=("netflix",))

def fabrica(tv, ctx):
    return DriverFalso(caps, tv_id=tv.id, tv_nome=tv.nome)

def pronto(h, p):
    print("pronto", p, flush=True)

asyncio.run(servir_async(cfg=CasaConfig(tvs=tvs), porta=0, pronto=pronto, fabrica_driver=fabrica))
"""


def _cpu_s(pid: int) -> float:
    campos = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    return (int(campos[11]) + int(campos[12])) / os.sysconf("SC_CLK_TCK")  # utime + stime


def _rss_mb(pid: int) -> float:
    for linha in Path(f"/proc/{pid}/status").read_text().splitlines():
        if linha.startswith("VmRSS:"):
            return int(linha.split()[1]) / 1024
    raise AssertionError("sem VmRSS")


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="mede por /proc")
async def test_recursos_em_repouso(tmp_path, request):
    if "lento" not in (request.config.getoption("markexpr") or ""):
        pytest.skip("lento: rode com pytest -m lento")
    env = dict(os.environ)
    home = tmp_path / "home"
    env.update(
        HOME=str(home),
        XDG_CONFIG_HOME=str(home / ".config"),
        XDG_DATA_HOME=str(home / ".local" / "share"),
        XDG_STATE_HOME=str(home / ".local" / "state"),
    )
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        SCRIPT,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        linha = await asyncio.wait_for(proc.stdout.readline(), 30)
        assert linha.startswith(b"pronto"), linha
        cpu0, t0 = _cpu_s(proc.pid), time.monotonic()
        await asyncio.sleep(JANELA_S)
        cpu = (_cpu_s(proc.pid) - cpu0) / (time.monotonic() - t0)
        rss = _rss_mb(proc.pid)
    finally:
        proc.terminate()
        await proc.wait()
    print(f"\nCA-Y58: janela {JANELA_S:.0f} s, CPU médio {cpu * 100:.3f}%, RSS {rss:.1f} MB")
    assert cpu <= CPU_MAX
    assert rss <= RSS_MAX_MB
