# ruff: noqa: E501  (texto gravado do dbus-monitor tem linhas longas)
"""R2.E: notificações (``data.Notificacoes``, ``dbus-monitor`` falso) e reações 46/47 no ``det_notif``.

Nunca roda o ``dbus-monitor`` de verdade: o processo é sempre falso (texto gravado abaixo).
"""

from __future__ import annotations

import io
import subprocess
import threading
from pathlib import Path

from wired import data, integration
from wired.data import Notificacoes
from wired.main_screen import Snapshot
from wired.reacoes import det_notif
from wired.reacoes.catalogo import ATIVAS

# saída gravada de `dbus-monitor --session "interface='org.freedesktop.Notifications',member='Notify'"`
GRAVADO = """\
signal time=1696851230.000001 sender=org.freedesktop.DBus -> destination=:1.99 serial=2 path=/org/freedesktop/DBus; interface=org.freedesktop.DBus; member=NameAcquired
   string ":1.99"
signal time=1696851230.000002 sender=org.freedesktop.DBus -> destination=:1.99 serial=4 path=/org/freedesktop/DBus; interface=org.freedesktop.DBus; member=NameLost
   string ":1.99"
method call time=1696851234.123456 sender=:1.50 -> destination=:1.20 serial=7 path=/org/freedesktop/Notifications; interface=org.freedesktop.Notifications; member=Notify
   string "notify-send"
   uint32 0
   string ""
   string "Download concluído"
   string "arquivo.iso
segunda linha do corpo"
   array [
   ]
   array [
      dict entry(
         string "sender-pid"
         variant             int64 12345
      )
      dict entry(
         string "urgency"
         variant             byte 1
      )
   ]
   int32 -1
method call time=1696851240.000000 sender=:1.51 -> destination=:1.20 serial=9 path=/org/freedesktop/Notifications; interface=org.freedesktop.Notifications; member=Notify
   string "org.kde.kdeconnect"
   uint32 0
   string "dialog-error"
   string "Falhou"
   string "disco cheio"
   array [
      string "default"
      string "Abrir"
   ]
   array [
      dict entry(
         string "urgency"
         variant             byte 2
      )
   ]
   int32 5000
"""


class _ProcFalso:
    def __init__(self, texto: str = GRAVADO, bloquear: threading.Event | None = None):
        self._texto = texto
        self._bloquear = bloquear
        self.terminado = self.morto = False
        self.stdout = self._linhas()

    def _linhas(self):
        yield from io.StringIO(self._texto)
        if self._bloquear is not None:
            self._bloquear.wait(5.0)  # processo vivo, sem mais saída

    def poll(self):
        return 0 if self.terminado else None

    def terminate(self):
        self.terminado = True
        if self._bloquear is not None:
            self._bloquear.set()

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.morto = True


def test_parse_do_texto_gravado() -> None:
    n = Notificacoes(clock=lambda: 42.0)
    n.ler(io.StringIO(GRAVADO))
    assert n.contador == 2
    assert n.atual == (2, 2, 42.0)
    assert n.ultima == {"app": "org.kde.kdeconnect", "titulo": "Falhou", "urgencia": 2}


def test_notificacao_fecha_no_int32_sem_esperar_a_proxima() -> None:
    n = Notificacoes(clock=lambda: 1.0)
    linhas = GRAVADO.splitlines(keepends=True)
    fim = next(i for i, ln in enumerate(linhas) if ln.startswith("   int32 -1"))
    fechou = [n.linha(ln) for ln in linhas[: fim + 1]]
    assert fechou[-1] is True and n.atual == (1, 1, 1.0)
    assert n.ultima["titulo"] == "Download concluído"


def test_sem_urgencia_e_normal_e_sinais_ignorados() -> None:
    n = Notificacoes(clock=lambda: 0.0)
    n.ler(io.StringIO(GRAVADO.split("method call")[0]))  # só os sinais do próprio dbus-monitor
    assert n.atual is None and n.contador == 0
    txt = ("method call time=1 sender=:1.5 -> destination=:1.2 serial=3 path=/x; "
           "interface=org.freedesktop.Notifications; member=Notify\n"
           '   string "app"\n   uint32 0\n   string ""\n   string "Oi"\n   string ""\n'
           "   array [\n   ]\n   array [\n   ]\n   int32 -1\n")
    n.ler(io.StringIO(txt))
    assert n.atual == (1, 1, 0.0)


def test_thread_le_e_o_processo_morre_no_stop() -> None:
    bloquear = threading.Event()
    proc = _ProcFalso(bloquear=bloquear)
    n = Notificacoes(spawn=lambda: proc, clock=lambda: 7.0).start()
    try:
        for _ in range(500):
            if n.contador == 2:
                break
            threading.Event().wait(0.01)
        assert n.atual == (2, 2, 7.0)
        assert n._thread.is_alive() and not proc.terminado
    finally:
        n.stop()
    n._thread.join(5.0)
    assert not n._thread.is_alive()
    assert proc.terminado


def test_processo_que_acaba_e_spawn_ausente() -> None:
    proc = _ProcFalso()
    n = Notificacoes(spawn=lambda: proc).start()
    n._thread.join(5.0)
    assert n.contador == 2 and not n._thread.is_alive()
    n = Notificacoes(spawn=lambda: None).start()  # sem dbus-monitor
    n._thread.join(5.0)
    assert n.atual is None


def test_spawn_padrao_so_escuta_e_morre_com_o_pai() -> None:
    chamado = {}

    def popen(argv, **kw):
        chamado["argv"], chamado["kw"] = argv, kw
        return "proc"

    assert data._dbus_monitor(popen=popen) == "proc"
    assert chamado["argv"] == ["dbus-monitor", "--session",
                               "interface='org.freedesktop.Notifications',member='Notify'"]
    assert chamado["kw"]["preexec_fn"] is data._morrer_com_o_pai
    assert chamado["kw"]["stdout"] is subprocess.PIPE

    def falta(argv, **kw):
        raise FileNotFoundError("dbus-monitor")

    assert data._dbus_monitor(popen=falta) is None


def test_nenhuma_chamada_ativa_ao_dbus_no_codigo() -> None:
    raiz = Path(__file__).resolve().parents[2] / "hud"
    proibidos = ("q" + "dbus", "g" + "dbus", "dbus" + "-send")
    achados = [f"{p}: {w}" for p in raiz.rglob("*.py") for w in proibidos
               if w in p.read_text(encoding="utf-8", errors="replace")]
    assert achados == []


def tick(ctx: dict, notif, agora: float) -> list[str]:
    ctx["agora"] = agora
    return [d.chave for d in det_notif.detectar(Snapshot(), Snapshot(notif=notif), ctx)]


def test_46_no_maximo_1_a_cada_10_min() -> None:
    ctx: dict = {}
    assert tick(ctx, None, 0.0) == []
    assert tick(ctx, (1, 1, 10.0), 10.5) == ["notificacao"]
    assert tick(ctx, (1, 1, 10.0), 11.5) == []  # a mesma
    assert tick(ctx, (2, 1, 100.0), 100.5) == []  # < 10 min
    assert tick(ctx, (3, 0, 611.0), 611.0) == ["notificacao"]


def test_47_critica_e_velha_ignorada() -> None:
    ctx: dict = {}
    assert tick(ctx, (1, 1, 10.0), 10.0) == ["notificacao"]
    assert tick(ctx, (2, 2, 20.0), 20.0) == ["popup_erro"]  # crítica passa mesmo < 10 min do 46
    assert tick(ctx, (3, 2, 30.0), 60.0) == []  # chegou há 30 s: só marca vista
    assert tick(ctx, (3, 2, 30.0), 61.0) == []


def test_46_e_47_ativas() -> None:
    assert "notificacao" in ATIVAS and "popup_erro" in ATIVAS


class _SemPlayer:
    active = False


class _RedeFalsa:
    down = up = 0.0
    down_series = ()

    def poll(self, now=None):
        pass


class _GitFalso:
    head = None

    def poll(self, mono=None):
        return {"branch": "main", "added": 0, "removed": 0}


def test_integration_poe_notif_no_snapshot() -> None:
    n = Notificacoes(clock=lambda: 3.0)
    ui = integration.WiredUI(now_playing=_SemPlayer(), net=_RedeFalsa(), git=_GitFalso(), notif=n)
    assert ui.build({}).notif is None
    n.ler(io.StringIO(GRAVADO))
    assert ui.build({}).notif == (2, 2, 3.0)


def test_testes_nao_ligam_a_thread() -> None:
    ui = integration.WiredUI(now_playing=_SemPlayer(), net=_RedeFalsa(), git=_GitFalso())
    assert ui.notif is None  # MAGI_NO_NOTIF=1 no conftest
    assert ui.build({}).notif is None
