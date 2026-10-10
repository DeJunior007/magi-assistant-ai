"""Ponte entre o `gamerhud.py` e as telas "wired" (U4, R23.6/R23.8/R23.9; termômetro R13.7).

O `gamerhud` continua dono das fontes de dados (`Sensors`, `FpsSource`, `ProcStats`, controles,
OpenRGB, ponte com a Magui) e do ciclo Qt (timers, `paintEvent`, cliques). Aqui fica o que é do
tema novo, sem depender do QWidget, para dar para testar com fontes falsas:

- `build_snapshot(...)`: monta o `Snapshot` a partir das fontes existentes + `data.py` (pura);
- `WiredUI`: as duas telas (mascote compartilhado), os dados novos (rede, histórico, FPS,
  Spotify, log do rodapé), o estado da Magui (expressão, boca, legenda, humor) e do LED, os
  eventos do rodapé, o roteamento de cliques e o painel de detalhes por processo no estilo wired.
"""

from __future__ import annotations

import os
import time
from collections import deque

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize
from PySide6.QtGui import QPainter

from . import data as _data
from . import kit
from . import main_screen as _ms
from .data import (
    ClaudeStats,
    EventLog,
    FpsSnapshot,
    FpsStats,
    LoadHistory,
    NetRate,
    NowPlaying,
    SelfUsage,
    SelfView,
)
from .learning_screen import LearningScreen
from .learning_summary import SummaryCard
from .main_screen import (
    KONSOLE_CWD,
    NA,
    SCENE,
    C,
    MainScreen,
    Pilot,
    R,
    Snapshot,
    Track,
    dev_rect,
    heading,
    label,
    text,
)
from .mascot import EXPRESSIONS, Mascot
from .portrait import make_mascot
from .reactions import Reactor
from .standby_screen import StandbyScreen
from .theme import CPU, GPU, LINE, PANEL, RAM, TEXT, TEXT_DIM, alpha, color

# dados novos do painel (data.py da nova UI); ausentes = campos None no Snapshot
SysExtra = getattr(_data, "SysExtra", None)
net_info = getattr(_data, "net_info", None)
GitStatus = getattr(_data, "GitStatus", None)
Volume = getattr(_data, "Volume", None)  # R2.D: volume do PipeWire (wpctl numa thread)
Notificacoes = getattr(_data, "Notificacoes", None)  # R2.E: dbus-monitor (só escuta) numa thread
Ventoinha = getattr(_data, "Ventoinha", None)  # R2.G: hwmon fan*_input numa thread
Reinicio = getattr(_data, "Reinicio", None)  # R2.G: dnf needs-restarting -r a cada 6 h
Capturas = getattr(_data, "Capturas", None)  # R2.G: mtime da pasta de capturas de tela

CARD_DETAIL = {"card:cpu": "cpu", "card:gpu": "gpu", "card:ram": "mem"}  # alvo → ProcStats.poll
PLAYER = ("prev", "playpause", "next")
ALERT_LEVELS = ("bomba", "alta")  # cards da ponte que viram aviso no rodapé
IDLE_STATES = ("sleeping",)  # parada: as reações do HUD aparecem no rosto (ouvindo, nunca: ela está atenta)
RADIO_SOURCE = "radio"  # cards das notícias contadas no modo rádio (Rádio Ayanami)
DETAIL_RECT = SCENE.adjusted(1, 1, -1, -1)  # painel de detalhes cobre o "cam 01"
DETAIL_INFO = {
    "cpu": ("Melchior", "詳細解析 · cpu por aplicativo", CPU),
    "gpu": ("Balthasar", "詳細解析 · gpu por aplicativo", GPU),
    "mem": ("Casper", "詳細解析 · ram (pss) e vram", RAM),
}


def rgb_hex(rgb) -> str | None:
    """(r, g, b[, nível]) do OpenRGB → "#rrggbb"; preto (LEDs apagados) ou None → None."""
    if not rgb:
        return None
    r, g, b = (max(0, min(255, int(round(v)))) for v in rgb[:3])
    if max(r, g, b) < 10:
        return None
    return f"#{r:02x}{g:02x}{b:02x}"


def short_gpu(spec_gpu: str | None) -> str | None:
    """"AMD RADEON RX 9060 XT · 16 GB" → "AMD RADEON RX 9060 XT" (a VRAM já aparece na Casper)."""
    if not spec_gpu or spec_gpu == "--":
        return None
    return spec_gpu.split(" · ")[0]


def build_snapshot(data: dict, *, spec=(), pads=(), gaming: bool = False, fps: FpsSnapshot | None = None,
                   net: NetRate | None = None, history: LoadHistory | None = None,
                   now_playing: NowPlaying | None = None, events: EventLog | None = None,
                   led_on: bool = False, led_rgb: str | None = None, magui_state: str = "sleeping",
                   mouth_level: float = 0.0, caption: str | None = None, mood: int | None = None,
                   self_usage: SelfView | None = None, now: float | None = None, extra: dict | None = None,
                   netinfo: dict | None = None, git: dict | None = None) -> Snapshot:
    """Snapshot das telas. `data` = `Sensors.data`; `spec` = `system_info()`; `pads` = `controllers()`.
    Sem GPU (`vram_txt == "--"`) as leituras de GPU/VRAM viram None ("– –", R23.3). `extra` =
    `SysExtra.poll()` (clock, swap, disco), `netinfo` = `net_info()` (IP, gateway, DNS), `git` =
    `GitStatus.poll()` (branch e +/- da sessão do KONSOLE)."""
    d = data or {}
    has_gpu = d.get("vram_txt") not in (None, "--")
    sp = dict(spec)
    track = None
    if now_playing is not None and now_playing.active:
        track = Track(now_playing.title, now_playing.artist, now_playing.album, now_playing.year,
                      now_playing.position(now), now_playing.length, now_playing.status == "Playing",
                      now_playing.cover_pixmap())
    snap = Snapshot(
        gaming=gaming,
        cpu=d.get("cpu"), cpu_temp=d.get("cpu_temp"),
        gpu=d.get("gpu") if has_gpu else None, gpu_temp=d.get("gpu_temp"), gpu_w=d.get("gpu_w"),
        ram=d.get("ram"), ram_txt=d.get("ram_txt"),
        vram=d.get("vram") if has_gpu else None, vram_txt=d.get("vram_txt") if has_gpu else None,
        cpu_label=sp.get("CPU") or None, gpu_label=short_gpu(sp.get("GPU")), ram_label=sp.get("RAM") or None,
        specs=list(spec),
        pilots=[Pilot(str(n), b, c or "", bool(ch)) for n, b, c, ch in pads],
        track=track, led_on=bool(led_on), led_rgb=led_rgb if led_on else None,
        magui_state=magui_state if magui_state in EXPRESSIONS else "sleeping",
        mouth_level=mouth_level, caption=caption or None,
        mood=None if mood is None else max(0, min(4, int(mood))),
        self_usage=self_usage,
    )
    ex, ni, gi = extra or {}, netinfo or {}, git or {}
    snap.cpu_mhz, snap.disk_pct = ex.get("cpu_mhz"), ex.get("disk_pct")
    snap.swap_used_gb, snap.swap_total_gb = ex.get("swap_used_gb"), ex.get("swap_total_gb")
    snap.net_ip, snap.net_gateway, snap.net_dns = ni.get("ip"), ni.get("gateway"), ni.get("dns")
    snap.git_branch, snap.git_added, snap.git_removed = gi.get("branch"), gi.get("added"), gi.get("removed")
    if net is not None:
        snap.net_down, snap.net_up = net.down, net.up
        snap.net_series = list(net.down_series)
    if history is not None:
        snap.history = {k: history.series(k) for k in ("cpu", "gpu", "ram")}
        snap.history_axis = history.axis()
    if fps is not None:
        snap.fps, snap.fps_min, snap.fps_avg, snap.fps_max = fps.current, fps.min, fps.avg, fps.max
        snap.fps_series = list(fps.series)
    if events is not None:
        snap.events = events.ticker(3)
    return snap


# ---------------------------------------------------------------- Learning Mode: troca de tela (LM1.7)

LM_RETURN_VIEWS = ("full", "idle")  # views de onde se entra no modo e para onde se volta


def learning_toggle(view: str, retorno: str | None, msg: dict) -> tuple[str, str | None]:
    """Troca de tela do Learning Mode (pura, design §10): ``(view_atual, retorno, msg) → (view,
    retorno)``. O núcleo é a fonte da verdade: o botão só pede (``lm_mode`` sai pelo bridge) e a
    tela muda aqui, ao receber a confirmação — venha ela do botão ou da voz (LM1.4).

    - ``{"t": "lm_mode", "on": True}``: guarda a view atual (``full``/``idle``) e vai para
      ``learning``; já em ``learning`` (reenvio na reconexão, ``learning.start`` repetido) nada muda.
    - ``{"t": "lm_mode", "on": False}``: volta à view guardada (``full`` se não houver); fora do
      modo só esquece o retorno.
    - ``{"t": "view", "view": v}`` (Meta+M / ``settings.json``): fora do modo troca a view como
      antes; durante o modo só muda a view de retorno.
    Qualquer outra mensagem não muda nada."""
    t = msg.get("t")
    if t == "lm_mode":
        if msg.get("on"):
            if view == "learning":
                return view, retorno
            return "learning", view if view in LM_RETURN_VIEWS else "full"
        if view != "learning":
            return view, None
        return (retorno if retorno in LM_RETURN_VIEWS else "full"), None
    if t == "view":
        new = msg.get("view")
        if view == "learning":
            return view, new if new in LM_RETURN_VIEWS else retorno
        return (new or view), retorno
    return view, retorno


class WiredUI:
    """Estado e telas do tema wired. O HUD chama `poll` a 1 Hz, `build` quando algo muda, repassa
    os eventos da Magui e usa `screen(view)` para pintar/invalidar e `hit` para os cliques."""

    def __init__(self, now_playing: NowPlaying | None = None, net: NetRate | None = None,
                 history: LoadHistory | None = None, fps: FpsStats | None = None,
                 events: EventLog | None = None, mascot: Mascot | None = None,
                 claude: ClaudeStats | None = None, self_usage: SelfUsage | None = None,
                 sys_extra=None, git=None, konsole_cwd: str | None = None, volume=None,
                 notif=None, ventoinha=None, reinicio=None, capturas=None):
        self.mascot = mascot or make_mascot("sleeping")  # retrato da Condessa, se houver a arte
        self.main = MainScreen(self.mascot)
        self.standby = StandbyScreen(self.mascot)
        self.learning = LearningScreen(self.mascot)  # view "learning" (LM1.5)
        # cartão LAST SESSION (LM4.6): o resumo e o instante de chegada ficam no learning_model
        self.summary_card = SummaryCard()
        self.main.summary = self.standby.summary = self.summary_now
        self.now_playing = now_playing if now_playing is not None else NowPlaying()
        self.net = net or NetRate()
        self.history = history or LoadHistory()
        self.fps = fps or FpsStats()
        self.events = events or EventLog()
        self.magui_state = "sleeping"
        self.mouth_level = 0.0
        self.caption: str | None = None
        self.mood: int | None = None
        self.turn_tag: tuple[str, float] | None = None  # última TurnTagMsg (tag, monotônico)
        self.led_on = False
        self.led_rgb: str | None = None
        self._game: str | None = None
        self._track: tuple | None = None
        self._led_warned = False
        self.news: deque[tuple[str, str]] = deque(maxlen=8)  # Rádio Ayanami: (HH:MM, manchete)
        self.claude = claude  # ClaudeStats (consumo do Claude Code); None = painel sem dado
        self.self_usage = self_usage or SelfUsage()  # o que a própria Condessa gasta (linha no MAGI)
        # nova UI: clock/swap/disco, IP/gateway/DNS e o git da sessão do KONSOLE
        self.sys_extra = sys_extra if sys_extra is not None else (SysExtra() if SysExtra else None)
        self.konsole_cwd = konsole_cwd or KONSOLE_CWD
        self.git = git if git is not None else (GitStatus(self.konsole_cwd) if GitStatus else None)
        self.extra: dict = {}
        self.netinfo: dict = {}
        self.gitinfo: dict = {}
        self.konsole_online: bool | None = None  # o gamerhud liga: sessão do Claude Code viva
        self.konsole_rev = 0  # o gamerhud incrementa quando o terminal tem tela nova
        self.snap = Snapshot()
        self.reactor = Reactor()  # reações dela ao HUD, à música e aos cliques (só rosto/texto)
        # volume do PipeWire (R2.D): thread de 1 s com wpctl; MAGI_NO_VOLUME=1 desliga (testes)
        if volume is None and Volume is not None and os.environ.get("MAGI_NO_VOLUME") != "1":
            volume = Volume().start()
        self.volume = volume
        # notificações (R2.E): dbus-monitor só escutando Notify; MAGI_NO_NOTIF=1 desliga (testes)
        if notif is None and Notificacoes is not None and os.environ.get("MAGI_NO_NOTIF") != "1":
            notif = Notificacoes().start()
        self.notif = notif
        # sinais menores (R2.G): ventoinha, reinício pendente, capturas; MAGI_NO_EXTRAS=1 desliga
        extras = os.environ.get("MAGI_NO_EXTRAS") != "1"
        if ventoinha is None and Ventoinha is not None and extras:
            ventoinha = Ventoinha().start()
        if reinicio is None and Reinicio is not None and extras:
            reinicio = Reinicio().start()
        if capturas is None and Capturas is not None and extras:
            capturas = Capturas().start()
        self.ventoinha, self.reinicio, self.capturas = ventoinha, reinicio, capturas

    def screen(self, view: str) -> MainScreen | StandbyScreen | LearningScreen:
        self.mascot.layout = "idle" if view == "idle" else "main"  # learning: retrato do painel
        if view == "learning":
            return self.learning
        return self.standby if view == "idle" else self.main

    # ---------------------------------------------------------------- dados (1 Hz)

    def poll(self, data: dict, fps: float | None, game: str | None, mono: float | None = None,
             wall: float | None = None) -> None:
        mono = time.monotonic() if mono is None else mono
        wall = time.time() if wall is None else wall
        self.net.poll(mono)
        has_gpu = (data or {}).get("vram_txt") not in (None, "--")
        self.history.push(data.get("cpu"), data.get("gpu") if has_gpu else None, data.get("ram"), wall)
        self.fps.push(fps, mono)
        self.now_playing.tick(mono)
        self.self_usage.poll(mono)
        self._poll_extra(mono)
        if game != self._game:
            if game:
                self.events.add(f"jogo detectado: {game}")
            elif self._game:
                self.events.add(f"jogo fechado: {self._game}")
            self._game = game
        np = self.now_playing
        key = (np.title, np.artist) if np.active else None
        if key != self._track:
            if key is not None:
                self.events.add(f"♪ {np.title}" + (f" — {np.artist}" if np.artist else ""))
            self._track = key

    def _poll_extra(self, mono: float) -> None:
        """Dados novos do painel; fonte que falha fica sem dado (nunca derruba o poll)."""
        for attr, fn in (("extra", lambda: self.sys_extra.poll() if self.sys_extra else {}),
                         ("netinfo", lambda: net_info(mono) if net_info else {}),
                         ("gitinfo", lambda: self._git_poll(mono))):
            try:
                setattr(self, attr, dict(fn() or {}))
            except Exception:  # noqa: BLE001 - leitura de /sys, rede ou git que falhou
                setattr(self, attr, {})

    def _git_poll(self, mono: float) -> dict:
        """Git da pasta da sessão (a do ``settings.json`` pode não ser a padrão)."""
        cwd = getattr(self.konsole_session(), "cwd", None)
        if cwd and cwd != self.konsole_cwd and GitStatus is not None:
            self.konsole_cwd = str(cwd)
            self.git = GitStatus(self.konsole_cwd)
        return self.git.poll(mono) if self.git else {}

    def konsole_session(self):
        """Sessão do KONSOLE que o gamerhud abriu (``konsole_view.VIEW.session``) ou None."""
        view = getattr(_ms.konsole_view, "VIEW", None)
        return getattr(view, "session", None)

    def konsole_alive(self) -> bool:
        """● ONLINE: ``konsole_online`` se o gamerhud ligou; senão, a sessão do konsole_view viva."""
        if self.konsole_online is not None:
            return bool(self.konsole_online)
        sess = self.konsole_session()
        return bool(sess is not None and getattr(sess, "alive", False))

    def konsole_swap(self, on: bool) -> bool:
        """Konsole expandido na caixa do cam 01: o painel desenha a câmera no slot do card KONSOLE
        (e o card some). ``True`` se mudou; o gamerhud invalida as duas caixas."""
        on = bool(on)
        if self.main.kon_swap == on:
            return False
        self.main.kon_swap = on
        return True

    def konsole_rects(self, size: QSize) -> list[QRect]:
        """Retângulos (dispositivo) do miolo do KONSOLE, para o gamerhud repintar só o terminal."""
        return self.main.group_rects("konsole", size)

    def build(self, data: dict, *, spec=(), pads=(), gaming: bool = False) -> Snapshot:
        self.snap = build_snapshot(
            data, spec=spec, pads=pads, gaming=gaming, fps=self.fps.snapshot(), net=self.net,
            history=self.history, now_playing=self.now_playing, events=self.events,
            led_on=self.led_on, led_rgb=self.led_rgb, magui_state=self.magui_state,
            mouth_level=self.mouth_level, caption=self.caption, mood=self.mood,
            self_usage=self.self_usage.view, extra=self.extra, netinfo=self.netinfo, git=self.gitinfo)
        head = getattr(self.git, "head", None)
        self.snap.git_head = head if isinstance(head, str) else None
        self.snap.turn_tag = self.turn_tag
        self.snap.volume = getattr(self.volume, "atual", None)
        self.snap.notif = getattr(self.notif, "atual", None)
        self.snap.fan = getattr(self.ventoinha, "atual", None)
        self.snap.reinicio = getattr(self.reinicio, "atual", None)
        self.snap.captura = getattr(self.capturas, "atual", None)
        self.snap.project = self.konsole_cwd
        self.snap.konsole_online = self.konsole_alive()
        self.snap.konsole_rev = self.konsole_rev
        self.snap.news = list(self.news)
        self.snap.claude = self.claude.view if self.claude is not None else None
        self.snap.lm_on = bool(getattr(self.learning.info, "mode_on", False))
        self._react(time.monotonic())
        return self.snap

    def _react(self, mono: float) -> None:
        r = self.reactor
        r.observe(self.snap, mono)
        if self.magui_state not in IDLE_STATES:
            r.cancel()
        self.mascot.react(r.active(mono), r.until)
        set_rest = getattr(self.mascot, "set_rest", None)  # o rosto parado pela faixa/momento
        if set_rest is not None and r.repouso is not None:
            set_rest(r.repouso)
        s = self.snap  # o medidor dela (acordo §6): ânimo, cor da faixa, momento e 3 causas
        s.mood_dela, s.mood_dela_cor, s.momento, s.causas = r.medidor(mono)
        if self.caption is None and self.magui_state in IDLE_STATES:
            self.snap.caption = r.caption(mono)  # a fala dela (texto, sem voz)

    def on_click(self, target: str, mono: float | None = None) -> None:
        """Clique do Pedro no HUD: ela olha para lá (e às vezes comenta em texto)."""
        mono = time.monotonic() if mono is None else mono
        self.reactor.on_click(target, mono)
        if self.magui_state in IDLE_STATES:
            self.mascot.react(self.reactor.active(mono), self.reactor.until)

    def on_hover(self, evento: str, mono: float | None = None) -> None:
        """Mouse no retrato (R2.A): ``in``/``move``/``out`` e gestos ``dbl``/``long``/``arrasto``;
        a reação sai no próximo tick pelo ``det_entrada``."""
        self.reactor.on_hover(evento, time.monotonic() if mono is None else mono)

    # ---------------------------------------------------------------- LED (RGB Sync)

    def set_led(self, on: bool, rgb: str | None) -> None:
        """`on` = RGB Sync ligado; `rgb` = cor do OpenRGB ou None se ele não respondeu (visual off)."""
        if on and rgb is None and not self._led_warned:
            self.events.add("openrgb sem resposta · led off")
            self._led_warned = True
        elif rgb is not None or not on:
            self._led_warned = False
        self.led_on, self.led_rgb = bool(on), (rgb if on else None)

    # ---------------------------------------------------------------- Magui (hud_bridge)

    def set_state(self, expr: str) -> None:
        if expr not in EXPRESSIONS:
            return
        if self.magui_state == "sleeping" and expr != "sleeping":
            self.events.add("magui ativada")
        self.magui_state = expr
        self.snap.magui_state = expr
        self.mascot.set_expression(expr)

    def set_mouth(self, level: float) -> None:
        self.mouth_level = min(1.0, max(0.0, float(level)))
        self.snap.mouth_level = self.mouth_level  # o paint repassa o snapshot ao mascote
        self.mascot.set_level(self.mouth_level)

    def set_caption(self, txt: str | None) -> None:
        self.caption = txt or None

    def caption_rects(self, txt: str | None, view: str, size: QSize) -> list[QRect]:
        """Legenda que se escreve conforme ela fala (várias vezes por segundo): troca só o texto,
        sem remontar o Snapshot, e devolve os retângulos do grupo da fala a redesenhar (vazio =
        não mudou)."""
        txt = txt or None
        if txt == self.caption and txt == self.snap.caption:
            return []
        self.caption = self.snap.caption = txt
        return self.screen(view).group_rects("talk", size)

    def stop_readers(self) -> None:
        """Fecha os leitores em thread das reações (volume, notificações, ventoinha, reinício,
        capturas). Chamado no fechamento do HUD; as threads são daemon, isto só adianta o fim."""
        for r in (self.volume, self.notif, self.ventoinha, self.reinicio, self.capturas):
            stop = getattr(r, "stop", None)
            if stop is not None:
                try:
                    stop()
                except Exception:  # noqa: BLE001 - fechando: um leitor com erro não segura os outros
                    pass

    def set_mood(self, v: int | None) -> None:
        self.mood = None if v is None else max(0, min(4, int(v)))

    def set_turn_tag(self, tag: str | None, mono: float | None = None) -> None:
        """Última tag do turno do Pedro (``TurnTagMsg``, R2.B) com a hora de chegada (monotônica)."""
        self.turn_tag = None if not tag else (str(tag), time.monotonic() if mono is None else mono)
        self.snap.turn_tag = self.turn_tag

    def on_card(self, card: dict, wall: float | None = None) -> None:
        title = card.get("title")
        if card.get("source") == RADIO_SOURCE and title:
            hhmm = time.strftime("%H:%M", time.localtime(time.time() if wall is None else wall))
            if not self.news or self.news[0][1] != title:  # "conta mais" repete o card: não duplica
                self.news.appendleft((hhmm, title))
            self.snap.news = list(self.news)
            return
        if card.get("level") in ALERT_LEVELS and title:
            self.events.add(f"⚠ {title}")

    def on_connected(self, up: bool) -> None:
        # núcleo fora do ar: o retrato na GPU mostra interferência de sinal até voltar
        if hasattr(self.mascot, "glitch"):
            self.mascot.glitch = 0.0 if up else 0.6
        if not up:
            self.set_state("sleeping")
            self.set_caption(None)

    # ---------------------------------------------------------------- cliques

    # ---------------------------------------------------------------- cartão LAST SESSION (LM4.6)

    def _lm_now(self) -> float:
        return getattr(self.learning.info, "clock", time.monotonic)()

    def summary_now(self, now: float | None = None) -> dict | None:
        """Resumo da última sessão se o cartão está visível agora (``visible(now)``), senão None."""
        return self.summary_card.current(self.learning.info, self._lm_now() if now is None else now)

    def summary_mode(self, on: bool, now: float | None = None) -> None:
        """``lm_mode`` confirmado: ``off`` marca o instante (descarte do resumo > 10 s); ``on``
        esconde o cartão."""
        self.summary_card.mode(on, self._lm_now() if now is None else now)

    def summary_close(self) -> None:
        """Clique no cartão: fecha (só este resumo)."""
        self.summary_card.close(getattr(self.learning.info, "summary_at", None))

    def summary_deadline(self, now: float | None = None) -> float | None:
        """Instante (monotônico) em que o cartão visível some sozinho; None sem cartão."""
        if self.summary_now(now) is None:
            return None
        return self.summary_card.deadline(getattr(self.learning.info, "summary_at", None))

    def hit(self, pos: QPoint | QPointF, size: QSize, view: str, detail: str | None = None) -> str | None:
        """Alvo do clique: "led", "prev"/"playpause"/"next", "card:cpu|gpu|ram", "detail" (fecha
        o painel aberto), "face" (mascote → push-to-talk), "lm_summary" (cartão LAST SESSION,
        LM4.6: fecha), "learning" (botão LEARNING do topo do painel e ``[ LEARNING ]`` da espera,
        LM1.7: o HUD pede ``lm_mode``), "konsole" (card do
        terminal do Claude Code: o HUD expande) ou None. Na view learning só os alvos
        da ``LearningScreen`` (END SESSION → "learning"): o retrato não é push-to-talk lá; os
        eventos de mouse dessa view vão por ``learning_mouse``."""
        if view == "learning":
            return self.learning.hit_test(pos, size)
        scr = self.screen(view)
        s = scr.scale(size)
        pt = QPointF(pos.x() / s, pos.y() / s)
        if view != "idle" and detail and DETAIL_RECT.contains(pt):
            return "detail"
        if scr.SUMMARY_RECT.contains(pt) and self.summary_now() is not None:
            return "lm_summary"  # cartão LAST SESSION: clique fecha (LM4.6)
        if scr.MASCOT_RECT.contains(pt):
            return "face"
        return scr.hit_test(pos, size)

    def learning_mouse(self, kind: str, pos: QPoint | QPointF, size: QSize,
                       delta: float = 0.0) -> str | None:
        """Despachante único do mouse na view learning (LM1.6): press/move/release/double/wheel
        em pixels do widget → ``LearningScreen.mouse`` em coordenadas lógicas. Devolve o alvo de
        um clique (``"learning"``) ou ``None``. Duplo clique nunca fecha nada (só seleção, LM2.2)."""
        s = self.learning.scale(size)
        return self.learning.mouse(kind, (pos.x() / s, pos.y() / s), delta)

    def player(self, target: str) -> bool:
        """Controles do Spotify (MPRIS). True se `target` era um deles."""
        np = self.now_playing
        action = {"prev": np.previous, "playpause": np.play_pause, "next": np.next}.get(target)
        if action is None:
            return False
        action()
        return True

    # ---------------------------------------------------------------- detalhes por processo

    @staticmethod
    def detail_rect(size: QSize) -> QRect:
        return dev_rect(DETAIL_RECT, size.width() / 1920.0)

    def paint_detail(self, p: QPainter, size: QSize, region: QRect, kind: str, rows) -> None:
        """Painel de detalhes (`ProcStats.poll`) sobre o "cam 01" do painel completo."""
        dev = self.detail_rect(size)
        if not region.intersects(dev):
            return
        name, sub, base = DETAIL_INFO.get(kind, DETAIL_INFO["cpu"])
        col = color(self.led_rgb) if (self.led_on and self.led_rgb) else color(base)
        s = size.width() / 1920.0
        r = DETAIL_RECT
        p.save()
        p.setClipRect(region.intersected(dev))
        p.scale(s, s)
        p.fillRect(r, color(PANEL))
        p.fillRect(r, alpha(col, 14))
        x0, x1 = r.left() + 22, r.right() - 22
        heading(p, x0, r.top() + 42, name, px=26, color_=col)
        label(p, x0, r.top() + 64, sub, upper=False)
        label(p, x1, r.top() + 42, "✕ fechar · 閉じる", color_=TEXT, align=R)
        p.fillRect(QRectF(x0, r.top() + 78, x1 - x0, 1), color(LINE))
        if not rows:
            text(p, r.center().x(), r.center().y(), "解析中 · analisando", key="jp", px=16, color_=TEXT_DIM,
                 align=C)
            p.restore()
            return
        scale = max(rows[0][1], 2.0 if kind == "mem" else 10.0)
        row_h = min(46.0, (r.bottom() - 18 - (r.top() + 90)) / max(8, len(rows)))
        for i, (app, val, extra) in enumerate(rows[:8]):
            y = r.top() + 90 + i * row_h
            cy = y + row_h / 2
            if i % 2 == 0:
                p.fillRect(QRectF(x0 - 8, y, x1 - x0 + 16, row_h - 2), alpha(col, 10))
            label(p, x0, cy + 4.5, f"{i + 1:02d}", color_=col)
            text(p, x0 + 30, cy + 5, app, px=13, max_w=160)
            kit.segments(p, QRectF(x0 + 200, cy - 5, 120, 10), 20, min(100.0, 100.0 * val / scale), col)
            label(p, x0 + 400, cy + 4.5, extra or "", px=11, upper=False, align=R)
            main = f"{val:.1f} GB" if kind == "mem" else f"{val:.1f}%"
            text(p, x1, cy + 5, main, px=14, color_=TEXT, align=R)
        p.restore()


__all__ = ["CARD_DETAIL", "DETAIL_RECT", "LM_RETURN_VIEWS", "NA", "PLAYER", "WiredUI", "build_snapshot",
           "learning_toggle", "rgb_hex", "short_gpu"]
