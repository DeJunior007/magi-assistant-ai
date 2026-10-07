"""Dados da interface wired (U2): rede, histórico, FPS, MPRIS falso, capas e log do rodapé."""

import os
import time

import pytest
from wired.data import (
    CoverCache,
    EventLog,
    FpsStats,
    LoadHistory,
    NetRate,
    NowPlaying,
    SelfUsage,
    _plain,
    fmt_rate,
    normalize_art_url,
)

HEADER = ("Inter-|   Receive                            |  Transmit\n"
          " face |bytes    packets errs drop fifo frame compressed multicast|bytes ...\n")


def net_dev(path, rows):
    lines = [f"{name}: {rx} 0 0 0 0 0 0 0 {tx} 0 0 0 0 0 0 0" for name, rx, tx in rows]
    path.write_text(HEADER + "\n".join(lines) + "\n")


def test_net_rate_soma_fisicas_e_ignora_virtuais(tmp_path):
    dev = tmp_path / "dev"
    virt = [("lo", 0, 0), ("veth1a", 0, 0), ("docker0", 0, 0), ("br-123", 0, 0), ("virbr0", 0, 0)]
    net_dev(dev, [("enp8s0", 1000, 500), ("wlo1", 0, 0), *virt])
    n = NetRate(str(dev), sys_net=None)
    n.poll(10.0)
    assert n.down is None and n.up is None
    big = [(name, 10**9, 10**9) for name, _, _ in virt]
    net_dev(dev, [("enp8s0", 3000, 1500), ("wlo1", 1000, 0), *big])
    n.poll(12.0)
    assert n.down == pytest.approx(1500.0)  # (2000 + 1000) / 2 s
    assert n.up == pytest.approx(500.0)
    assert list(n.down_series) == [pytest.approx(1500.0)]
    net_dev(dev, [("enp8s0", 0, 0), ("wlo1", 0, 0)])  # contador zerado
    n.poll(13.0)
    assert n.down == 0 and n.up == 0


def test_net_rate_sysfs_descarta_sem_device(tmp_path):
    sysnet = tmp_path / "net"
    (sysnet / "enp8s0" / "device").mkdir(parents=True)
    (sysnet / "weird0").mkdir()
    n = NetRate(str(tmp_path / "x"), sys_net=str(sysnet))
    assert n.physical("enp8s0") and not n.physical("weird0") and n.physical("eth9")
    n.poll(1.0)  # arquivo inexistente: sem exceção
    assert n.down is None


def test_fmt_rate():
    assert fmt_rate(None) == "– –"
    assert fmt_rate(512) == "512 B/s"
    assert fmt_rate(1_500_000) == "1.5 MB/s"


def test_load_history_120_pontos_e_media():
    h = LoadHistory()
    t0 = 1_700_000_000.0
    assert h.push(10, 20, 30, t0)  # primeiro ponto entra na hora
    assert not h.push(50, None, 30, t0 + 10)
    assert not h.push(70, None, 30, t0 + 20)
    assert h.push(90, 40, 30, t0 + 30)
    assert h.points[-1][1:] == (pytest.approx(70.0), 40.0, 30.0)
    for i in range(2, 300):
        h.push(i % 100, None, 50, t0 + 30 * i)
    assert len(h.points) == 120
    assert len(h.series("cpu")) == 120 and h.series("gpu")[-1] is None
    assert h.times()[-1] - h.times()[0] == 30 * 119
    axis = h.axis(5)
    assert [f for f, _ in axis] == [0, 0.25, 0.5, 0.75, 1.0]
    assert axis[-1][1] == time.strftime("%H:%M", time.localtime(h.times()[-1]))
    assert axis[0][1] == time.strftime("%H:%M", time.localtime(h.times()[0]))


def test_fps_stats_janela_e_sem_jogo():
    f = FpsStats(window=60)
    assert f.snapshot() is None
    for i, v in enumerate([100, 50, 150]):
        f.push(v, float(i))
    s = f.snapshot()
    assert (s.current, s.min, s.avg, s.max) == (150, 50, 100, 150)
    f.push(120, 61.5)  # 0 e 1 saem da janela
    s = f.snapshot()
    assert (s.min, s.max, s.series) == (120, 150, [150.0, 120.0])
    f.push(None, 62)
    assert f.snapshot() is None


def test_event_log_ticker():
    log = EventLog(maxlen=3)
    t = time.mktime((2026, 10, 3, 19, 11, 5, 0, 0, -1))
    for i, txt in enumerate(["a", "b", "c", "d"]):
        log.add(txt, t + i)
    assert log.ticker(2) == ["[19:11:07] c", "[19:11:08] d"]
    assert len(log.ticker(10)) == 3 and log.ticker(0) == []


class FakeMpris:
    def __init__(self):
        self.res = None
        self.calls = []
        self.fetches = 0

    def fetch(self):
        self.fetches += 1
        return self.res

    def call(self, method):
        self.calls.append(method)


class Clock:
    def __init__(self, t=100.0):
        self.t = t

    def __call__(self):
        return self.t


def track(status="Playing", pos=42_000_000):
    return {"PlaybackStatus": status, "Position": pos, "Metadata": {
        "xesam:title": "Duvet", "xesam:artist": ["bôa", "X"], "xesam:album": "Twilight",
        "xesam:contentCreated": "2001-05-01T00:00:00Z",
        "mpris:artUrl": "https://open.spotify.com/image/abc", "mpris:length": 205_000_000}}


@pytest.fixture
def player(tmp_path):
    fake, clock = FakeMpris(), Clock()
    covers = CoverCache(str(tmp_path / "covers"), fetch=lambda url: b"img", threaded=False)
    return NowPlaying(fake, covers, threaded=False, clock=clock), fake, clock


def test_now_playing_fechado_fica_vazio(player):
    np_, fake, clock = player
    np_.tick()
    assert not np_.active and np_.status is None and np_.title is None
    assert np_.position() is None and np_.cover_path is None and np_.cover_pixmap() is None
    fake.fetch = lambda: (_ for _ in ()).throw(RuntimeError("dbus"))
    clock.t += 5
    np_.tick()  # exceção do backend não vaza
    assert not np_.active


def test_now_playing_metadados_e_interpolacao(player):
    np_, fake, clock = player
    fake.res = track()
    np_.tick()
    assert (np_.title, np_.artist, np_.album, np_.year) == ("Duvet", "bôa, X", "Twilight", "2001")
    assert np_.art_url == "https://i.scdn.co/image/abc"
    assert np_.length == 205 and np_.status == "Playing"
    assert np_.position() == pytest.approx(42)
    clock.t += 1
    np_.tick()  # sem nova leitura (poll = 3 s), posição anda sozinha
    assert fake.fetches == 1 and np_.position() == pytest.approx(43)
    clock.t += 1.5
    assert np_.position() == pytest.approx(44.5)
    clock.t += 1000
    assert np_.position() == 205  # não passa da duração
    fake.res = track("Paused", 60_000_000)
    np_.tick()
    clock.t += 10
    assert np_.status == "Paused" and np_.position() == pytest.approx(60)


def test_now_playing_controles(player):
    np_, fake, clock = player
    fake.res = track()
    np_.tick()
    clock.t += 2
    np_.play_pause()
    assert np_.status == "Paused" and np_.position() == pytest.approx(44)
    clock.t += 0.2
    assert np_.position() == pytest.approx(44)  # pausado: congela
    clock.t += 0.1  # 102.3 < 103 (poll normal)
    n = fake.fetches
    np_.tick()  # releitura antecipada depois do comando
    assert fake.fetches == n + 1 and np_.status == "Playing"
    np_.next()
    np_.previous()
    assert fake.calls == ["PlayPause", "Next", "Previous"]


def test_now_playing_capa_em_cache(player, tmp_path):
    np_, fake, _ = player
    fake.res = track()
    np_.tick()
    path = np_.cover_path
    assert path and os.path.dirname(path) == str(tmp_path / "covers")
    assert open(path, "rb").read() == b"img"
    assert np_.cover_pixmap() is None  # b"img" não é imagem válida: None, sem exceção


def test_now_playing_cover_pixmap_valida(tmp_path):
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QColor, QImage

    img = QImage(8, 8, QImage.Format.Format_RGB32)
    img.fill(QColor("red"))
    raw = QByteArray()
    buf = QBuffer(raw)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    fake = FakeMpris()
    fake.res = track()
    covers = CoverCache(str(tmp_path), fetch=lambda url: bytes(raw), threaded=False)
    np_ = NowPlaying(fake, covers, threaded=False, clock=Clock())
    np_.tick()
    pix = np_.cover_pixmap()
    assert pix is not None and (pix.width(), pix.height()) == (8, 8)
    assert np_.cover_pixmap() is pix  # memorizado


def test_cover_cache_limite_e_falha(tmp_path):
    calls = []

    def fetch(url):
        calls.append(url)
        if "bad" in url:
            raise OSError("404")
        return b"x"

    c = CoverCache(str(tmp_path), limit=3, fetch=fetch, threaded=False)
    for i in range(5):
        p = c.path_for(f"https://i.scdn.co/image/{i}")
        os.utime(p, (1000 + i, 1000 + i))
    assert len(os.listdir(tmp_path)) == 3
    assert c.path_for("https://i.scdn.co/image/bad") is None
    assert c.path_for("https://i.scdn.co/image/bad") is None
    assert calls.count("https://i.scdn.co/image/bad") == 1  # não insiste antes do RETRY
    assert c.path_for("spotify:image:zzz") is None
    assert normalize_art_url("file:///x.jpg") == "file:///x.jpg"


def test_plain_json_do_busctl():
    node = {"type": "a{sv}", "data": {"xesam:artist": {"type": "as", "data": ["a"]},
                                      "mpris:length": {"type": "t", "data": 5}}}
    assert _plain(node) == {"xesam:artist": ["a"], "mpris:length": 5}


def test_claude_stats_monta_o_painel(tmp_path):
    from datetime import UTC, datetime, timedelta
    from types import SimpleNamespace

    from wired.data import ClaudeStats

    now = datetime(2026, 10, 6, 22, 0, tzinfo=UTC)
    sess = [SimpleNamespace(project="magi-assistant-ai", running=True, last=now - timedelta(seconds=20)),
            SimpleNamespace(project="KPCeramica", running=False, last=now - timedelta(minutes=7))]
    summary = SimpleNamespace(tokens=SimpleNamespace(fresh=5_800_000, output=1_500_000, replies=1209),
                              active=sess, running=1, window_end=datetime(2026, 10, 7, 4, 0, tzinfo=UTC),
                              window=SimpleNamespace(fresh=236_000, cache_read=31_000_000))
    state = tmp_path / "state.json"
    state.write_text('{"line": "conserto pronto: roteador (aguardando ok)"}')
    st = ClaudeStats(autofix_state=state, reader=SimpleNamespace(summary=lambda: summary))
    v = st.refresh(now)
    assert (v.tokens, v.output, v.replies, v.running) == (5_800_000, 1_500_000, 1209, 1)
    assert (v.window_fresh, v.window_cache) == (236_000, 31_000_000) and v.window_end
    assert v.sessions == [("magi-assistant-ai", True, 0), ("KPCeramica", False, 7)]
    assert v.autofix == "conserto pronto: roteador (aguardando ok)"


# ---------------------------------------------------------------- consumo da Condessa (/proc falso)


def fake_proc(root, pid, cmd, *, ppid=1, ticks=(0, 0), rss_kb=None, start=100, fdinfo=None, uid_ok=True):
    """`/proc/<pid>` sintético: cmdline, stat (utime/stime/starttime), status (VmRSS) e fdinfo."""
    d = root / str(pid)
    (d / "fdinfo").mkdir(parents=True, exist_ok=True)
    (d / "cmdline").write_bytes("\0".join(cmd).encode() + b"\0")
    rest = ["S", str(ppid)] + ["0"] * 9 + [str(ticks[0]), str(ticks[1])] + ["0"] * 6 + [str(start), "0"]
    (d / "stat").write_text(f"{pid} (proc (x)) " + " ".join(rest) + "\n")
    (d / "status").write_text("Name:\tx\n" + (f"VmRSS:\t  {rss_kb} kB\n" if rss_kb is not None else ""))
    for fd, txt in (fdinfo or {}).items():
        (d / "fdinfo" / str(fd)).write_text(txt)


def drm(cid, gfx_ns, vram, unit="KiB", compute_ns=0):
    return (f"pos:\t0\nflags:\t02\ndrm-driver:\tamdgpu\ndrm-client-id:\t{cid}\ndrm-pdev:\t0000:04:00.0\n"
            f"drm-engine-gfx:\t{gfx_ns} ns\ndrm-engine-compute:\t{compute_ns} ns\n"
            f"drm-memory-vram:\t{vram} {unit}\ndrm-resident-vram:\t{vram} {unit}\n")


def test_self_usage_cpu_ram_gpu_vram(tmp_path):
    venv = "/repo/.venv/bin/"
    fake_proc(tmp_path, 10, ["/repo/.venv/bin/python3", venv + "magi-core"], ticks=(100, 50), rss_kb=512_000)
    fake_proc(tmp_path, 11, ["/usr/bin/ffmpeg", "-i", "x"], ppid=10, ticks=(10, 0), rss_kb=10_240)  # filho
    fake_proc(tmp_path, 20, ["python3", "/home/u/.local/share/gamerhud/gamerhud.py"], ticks=(20, 0),
              rss_kb=102_400, fdinfo={5: drm(7, 1_000_000_000, 81_920), 6: drm(7, 1_000_000_000, 81_920),
                                      7: drm(8, 0, 10, "MiB")})
    fake_proc(tmp_path, 30, ["python3", "/x/gamerhud-watch.py"], ticks=(0, 0), rss_kb=20_480)
    fake_proc(tmp_path, 40, ["/usr/bin/firefox"], ticks=(9999, 0), rss_kb=9_999_999,
              fdinfo={3: drm(99, 5_000_000_000, 999_999)})  # de fora
    fake_proc(tmp_path, 41, ["grep", "magi-core"], ticks=(5, 0), rss_kb=1000)  # só cita o nome
    (tmp_path / "self").mkdir()  # entradas não numéricas são ignoradas
    su = SelfUsage(str(tmp_path), rescan=60, hz=100, ncpu=4)
    v = su.poll(0.0)
    assert v.procs == 4 and v.cpu is None and v.gpu is None  # 1ª leitura: sem delta
    assert v.ram_mb == pytest.approx((512_000 + 10_240 + 102_400 + 20_480) / 1024)
    assert v.vram_mb == pytest.approx(80 + 10)  # client 7 aparece em 2 FDs e conta uma vez
    # 2 s depois: +100 ticks no núcleo, +20 no filho, +80 no HUD = 200 ticks = 2 s de CPU em 2 s
    fake_proc(tmp_path, 10, ["/repo/.venv/bin/python3", venv + "magi-core"], ticks=(180, 70), rss_kb=512_000)
    fake_proc(tmp_path, 11, ["/usr/bin/ffmpeg"], ppid=10, ticks=(30, 0), rss_kb=10_240)
    fake_proc(tmp_path, 20, ["python3", "/home/u/.local/share/gamerhud/gamerhud.py"], ticks=(100, 0),
              rss_kb=102_400, fdinfo={5: drm(7, 1_300_000_000, 81_920, compute_ns=100_000_000),
                                      6: drm(7, 1_300_000_000, 81_920, compute_ns=100_000_000),
                                      7: drm(8, 0, 10, "MiB")})
    v = su.poll(2.0)
    assert v.cpu == pytest.approx(100.0)  # 1 núcleo inteiro
    assert v.cpu_total == pytest.approx(25.0)
    assert v.gpu == pytest.approx(20.0)  # (300 + 100) ms de engine em 2 s; sem contar o FD repetido
    assert su.view is v


def test_self_usage_tolera_processo_que_some(tmp_path):
    import shutil
    fake_proc(tmp_path, 10, ["python3", "/r/.venv/bin/magi-satellite"], ticks=(10, 0), rss_kb=1024)
    su = SelfUsage(str(tmp_path), rescan=60, hz=100)
    assert su.poll(0.0).procs == 1
    shutil.rmtree(tmp_path / "10")
    assert su.poll(1.0) is None and su.view is None
    assert SelfUsage(str(tmp_path / "nada")).poll(0.0) is None
    # processo novo (mesmo pid, outro starttime) não gera delta falso; o rescan acha o novo
    fake_proc(tmp_path, 10, ["python3", "/r/.venv/bin/magi-ayanami"], ticks=(500, 0), rss_kb=1024, start=999)
    su.rescan = 0
    assert su.poll(2.0).cpu is None
    assert su.poll(3.0).cpu == pytest.approx(0.0)
