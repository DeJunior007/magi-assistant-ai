"""Spike S2: atalho de apertar pra falar (PTT).

Investiga os dois mecanismos do design §3.3:

  kga     KGlobalAccel via D-Bus: registra um componente/ação TEMPORÁRIOS, ouve
          globalShortcutPressed/Released, dispara com invokeShortcut e mede a latência.
          No fim desregistra tudo (unregister + cleanUp) e confere o kglobalshortcutsrc.
          Com --listen N fica N segundos esperando o aperto físico da tecla.
  evdev   Lista os dispositivos de entrada, acha o DualSense (054c:0ce6), mostra dono,
          modo e ACL dos /dev/input/event* e, com --listen N, imprime pressionar/soltar
          dos botões com a latência evento->leitura.
  cleanup Remove sobras do componente do spike (caso uma execução tenha sido interrompida).

Uso:
  uv run python spikes/s2_ptt.py kga [--listen 20] [--key Meta+Ctrl+Alt+F12]
  uv run python spikes/s2_ptt.py evdev [--listen 20]
  uv run python spikes/s2_ptt.py cleanup
"""

from __future__ import annotations

import argparse
import asyncio
import grp
import os
import pwd
import stat
import statistics
import subprocess
import sys
import time
from pathlib import Path

# --------------------------------------------------------------------------- KGlobalAccel

KGA_SERVICE = "org.kde.kglobalaccel"
KGA_PATH = "/kglobalaccel"
KGA_IFACE = "org.kde.KGlobalAccel"
COMP_IFACE = "org.kde.kglobalaccel.Component"

COMPONENT = "magi-spike-ptt"
COMPONENT_FRIENDLY = "Magui spike PTT (temporário)"
ACTION = "ptt"
ACTION_FRIENDLY = "Apertar pra falar (spike)"
ACTION_ID = [COMPONENT, ACTION, COMPONENT_FRIENDLY, ACTION_FRIENDLY]

# flags de setShortcutKeys (KGlobalAccel::SetShortcutFlag)
SET_PRESENT = 2
NO_AUTOLOADING = 4

QT_MODS = {"shift": 0x02000000, "ctrl": 0x04000000, "alt": 0x08000000, "meta": 0x10000000}
QT_KEYS = {f"f{n}": 0x01000030 + n - 1 for n in range(1, 36)}
QT_KEYS.update({"pause": 0x01000008, "scrolllock": 0x01000026, "menu": 0x01000055})
QT_KEYS.update({chr(c): c - 32 for c in range(ord("a"), ord("z") + 1)})

SHORTCUTS_RC = Path.home() / ".config" / "kglobalshortcutsrc"


def parse_key(text: str) -> int:
    """'Meta+Ctrl+Alt+F12' -> inteiro combinado do Qt (tecla | modificadores)."""
    *mods, key = (p.strip().lower() for p in text.split("+"))
    value = QT_KEYS[key]
    for mod in mods:
        value |= QT_MODS[mod]
    return value


def qkeyseq(key: int) -> list[list[int]]:
    """QKeySequence no D-Bus: struct (ai) com EXATAMENTE 4 inteiros (sobras em 0).

    CUIDADO: o operator>> do KF6GlobalAccel lê 4 ints sem checar o tamanho. Mandar (ai) com
    menos de 4 elementos derruba o kwin_wayland inteiro (SIGABRT em libdbus, "type invalid 0
    not a basic type"), e o KGlobalAccel roda dentro do KWin no Plasma 6.
    """
    return [[key, 0, 0, 0]]


def component_path(name: str) -> str:
    return "/component/" + "".join(c if c.isalnum() else "_" for c in name)


class Kga:
    """Cliente mínimo do KGlobalAccel com mensagens D-Bus cruas.

    Uso Message em vez do proxy do dbus-next porque a interface Component tem métodos
    sobrecarregados (invokeShortcut s / ss), que o proxy não distingue.
    """

    def __init__(self, bus):
        self.bus = bus

    async def call(self, path, iface, member, signature="", body=()):
        from dbus_next import Message, MessageType

        reply = await self.bus.call(
            Message(
                destination=KGA_SERVICE,
                path=path,
                interface=iface,
                member=member,
                signature=signature,
                body=list(body),
            )
        )
        if reply.message_type == MessageType.ERROR:
            raise RuntimeError(f"{member}: {reply.error_name}: {reply.body}")
        return reply.body

    async def add_match(self, rule: str) -> None:
        from dbus_next import Message

        await self.bus.call(
            Message(
                destination="org.freedesktop.DBus",
                path="/org/freedesktop/DBus",
                interface="org.freedesktop.DBus",
                member="AddMatch",
                signature="s",
                body=[rule],
            )
        )

    async def signal_names(self, path: str) -> list[str]:
        node = await self.bus.introspect(KGA_SERVICE, path)
        for iface in node.interfaces:
            if iface.name == COMP_IFACE:
                return [s.name for s in iface.signals]
        return []

    async def remove_spike(self) -> None:
        try:
            await self.call(KGA_PATH, KGA_IFACE, "setInactive", "as", [ACTION_ID])
        except RuntimeError as exc:
            print(f"  setInactive: {exc}")
        try:
            (ok,) = await self.call(KGA_PATH, KGA_IFACE, "unregister", "ss", [COMPONENT, ACTION])
            print(f"  unregister({COMPONENT}, {ACTION}) -> {ok}")
        except RuntimeError as exc:
            print(f"  unregister: {exc}")
        path = component_path(COMPONENT)
        try:
            (ok,) = await self.call(path, COMP_IFACE, "cleanUp", "")
            print(f"  cleanUp() -> {ok}")
        except RuntimeError as exc:
            print(f"  cleanUp: componente já não existe ({exc.args[0].split(':')[1].strip()})")
        await asyncio.sleep(1.0)  # o objeto do componente some de forma assíncrona após o cleanUp
        (comps,) = await self.call(KGA_PATH, KGA_IFACE, "allComponents")
        print(f"  componente ainda listado em allComponents: {path in comps}")


def rc_owners(key_text: str) -> list[str]:
    """Ações do kglobalshortcutsrc que já usam a combinação (ordem dos modificadores ignorada)."""
    want = {p.strip().lower() for p in key_text.split("+")}
    found, group = [], ""
    text = SHORTCUTS_RC.read_text(encoding="utf-8") if SHORTCUTS_RC.exists() else ""
    for line in text.splitlines():
        if line.startswith("["):
            group = line.strip("[]")
            continue
        name, _, value = line.partition("=")
        active = value.split(",")[0]
        for seq in active.split("\t"):
            if {p.strip().lower() for p in seq.split("+")} == want:
                found.append(f"{group}/{name}")
    return found


def check_rc(wait: float = 3.0) -> bool:
    """Confere que o kglobalshortcutsrc não guarda nada do spike (a escrita do KDE é adiada)."""
    time.sleep(wait)
    text = SHORTCUTS_RC.read_text(encoding="utf-8") if SHORTCUTS_RC.exists() else ""
    leftovers = [ln for ln in text.splitlines() if COMPONENT in ln or "spike" in ln.lower()]
    print(f"  {SHORTCUTS_RC}: {'SOBRAS: ' + repr(leftovers) if leftovers else 'sem sobras do spike'}")
    return not leftovers


async def run_kga(key_text: str, listen: float, rounds: int) -> int:
    from dbus_next import MessageType
    from dbus_next.aio import MessageBus

    bus = await MessageBus().connect()
    kga = Kga(bus)
    key = parse_key(key_text)
    print(f"Tecla do spike: {key_text} (Qt {key:#x})")

    # Conferência pelo arquivo para não depender de mais chamadas com (ai); ver qkeyseq().
    owners = rc_owners(key_text)
    if owners:
        print(f"  ocupada no kglobalshortcutsrc: {owners} — escolha outra com --key")
        return 1
    print("  livre no kglobalshortcutsrc (o setShortcutKeys também devolve [] se houver conflito)")

    events: asyncio.Queue = asyncio.Queue()
    path = component_path(COMPONENT)

    def on_message(msg):
        if (
            msg.message_type == MessageType.SIGNAL
            and msg.interface == COMP_IFACE
            and msg.path == path
            and msg.member.startswith("globalShortcut")
        ):
            events.put_nowait((time.monotonic(), time.time(), msg.member, msg.body))

    bus.add_message_handler(on_message)
    await kga.add_match(f"type='signal',interface='{COMP_IFACE}',path='{path}'")

    try:
        print("\n[1] Registro")
        await kga.call(KGA_PATH, KGA_IFACE, "doRegister", "as", [ACTION_ID])
        (applied,) = await kga.call(
            KGA_PATH,
            KGA_IFACE,
            "setShortcutKeys",
            "asa(ai)u",
            [ACTION_ID, [qkeyseq(key)], SET_PRESENT | NO_AUTOLOADING],
        )
        print(f"  doRegister + setShortcutKeys -> teclas aplicadas {applied}")
        (comp_path,) = await kga.call(KGA_PATH, KGA_IFACE, "getComponent", "s", [COMPONENT])
        (active,) = await kga.call(comp_path, COMP_IFACE, "isActive")
        print(f"  getComponent -> {comp_path} (isActive={active})")
        print(f"  sinais do componente (introspecção): {await kga.signal_names(comp_path)}")

        print(f"\n[2] invokeShortcut x{rounds} (latência chamada -> sinal)")
        lat: list[float] = []
        for _ in range(rounds):
            t0 = time.monotonic()
            await kga.call(comp_path, COMP_IFACE, "invokeShortcut", "s", [ACTION])
            try:
                t1, wall, member, body = await asyncio.wait_for(events.get(), 2.0)
            except TimeoutError:
                print("  nenhum sinal em 2 s")
                continue
            lat.append((t1 - t0) * 1000)
            # invokeShortcut manda timestamp 0; só tecla física traz o horário do evento
            print(f"  {member} {body[:2]} ts={body[2]} lat={lat[-1]:.2f} ms")
            await asyncio.sleep(0.05)
        # invokeShortcut emite só "pressionar"? confere se veio um "soltar" depois
        extra = []
        try:
            while True:
                extra.append(await asyncio.wait_for(events.get(), 0.5))
        except TimeoutError:
            pass
        print(f"  sinais extras após os invokes (soltar?): {[e[2] for e in extra] or 'nenhum'}")
        if lat:
            print(
                f"  latência: mediana {statistics.median(lat):.2f} ms, "
                f"mín {min(lat):.2f}, máx {max(lat):.2f} (n={len(lat)})"
            )

        if listen > 0:
            print(f"\n[3] Aperte e SEGURE {key_text} algumas vezes nos próximos {listen:.0f} s...")
            deadline = time.monotonic() + listen
            pressed_at: float | None = None
            while (left := deadline - time.monotonic()) > 0:
                try:
                    t1, wall, member, body = await asyncio.wait_for(events.get(), left)
                except TimeoutError:
                    break
                ts = body[2]  # timestamp do evento de entrada vindo do KWin (ms)
                extra_info = ""
                if member.endswith("Pressed"):
                    pressed_at = t1
                elif member.endswith("Released") and pressed_at is not None:
                    extra_info = f" segurou {(t1 - pressed_at) * 1000:.0f} ms"
                    pressed_at = None
                print(f"  {member} ts={ts} recebido(monotônico)={t1 * 1000:.0f} ms{extra_info}")
    finally:
        print("\n[4] Limpeza")
        await kga.remove_spike()
        bus.disconnect()
    return 0 if check_rc() else 2


async def run_cleanup() -> int:
    from dbus_next.aio import MessageBus

    bus = await MessageBus().connect()
    await Kga(bus).remove_spike()
    bus.disconnect()
    return 0 if check_rc() else 2


# --------------------------------------------------------------------------- evdev

DUALSENSE = (0x054C, 0x0CE6)


def describe_node(path: str) -> str:
    st = os.stat(path)
    owner = pwd.getpwuid(st.st_uid).pw_name
    group = grp.getgrgid(st.st_gid).gr_name
    mode = stat.filemode(st.st_mode)
    try:
        acl = subprocess.run(["getfacl", "-cp", path], capture_output=True, text=True, check=False).stdout
        acl_users = [ln for ln in acl.splitlines() if ln.startswith("user:") and not ln.startswith("user::")]
    except FileNotFoundError:
        acl_users = ["(getfacl ausente)"]
    readable = os.access(path, os.R_OK)
    return f"{mode} {owner}:{group} acl={acl_users or '-'} legível={readable}"


def run_evdev(listen: float) -> int:
    import evdev

    groups = [grp.getgrgid(g).gr_name for g in os.getgroups()]
    print(f"Usuário: {pwd.getpwuid(os.getuid()).pw_name}, grupos: {groups}")
    print("\n[1] Nós /dev/input/event* do DualSense (via /sys, não exige permissão)")
    ds_nodes = []
    # evdev.list_devices() só devolve os nós legíveis; /sys mostra todos
    for sys_node in sorted(Path("/sys/class/input").glob("event*"), key=lambda p: int(p.name[5:])):
        dev = sys_node / "device"
        try:
            vendor = int((dev / "id" / "vendor").read_text(), 16)
            product = int((dev / "id" / "product").read_text(), 16)
            name = (dev / "name").read_text().strip()
        except OSError:
            continue
        if (vendor, product) == DUALSENSE:
            node = f"/dev/input/{sys_node.name}"
            ds_nodes.append((node, name))
            print(f"  {node} '{name}': {describe_node(node)}")
    if not ds_nodes:
        print("  DualSense não encontrado (ligue/pareie o controle)")
        return 1

    readable = [p for p in evdev.list_devices()]
    print(f"\n[2] evdev.list_devices() vê {len(readable)} nós legíveis por este usuário:")
    for p in readable:
        d = evdev.InputDevice(p)
        print(f"  {p}: {d.name} ({d.info.vendor:04x}:{d.info.product:04x})")
        d.close()

    pad = next((n for n, name in ds_nodes if name == "DualSense Wireless Controller"), None)
    if pad is None or not os.access(pad, os.R_OK):
        print(
            f"\n  Sem leitura em {pad}: precisa do grupo input ou de regra udev uaccess (docs/spikes/S2.md)"
        )
        return 2
    dev = evdev.InputDevice(pad)
    keys = dev.capabilities(verbose=True).get(("EV_KEY", evdev.ecodes.EV_KEY), [])
    print(f"\n[3] {pad} aberto; botões: {[k[0] if isinstance(k[0], str) else k[0][0] for k in keys]}")

    if listen > 0:
        print(f"\n[4] Aperte e solte botões do controle nos próximos {listen:.0f} s (sem grab)...")
        deadline = time.monotonic() + listen
        down: dict[int, float] = {}
        lat: list[float] = []

        async def reader() -> None:
            async for ev in dev.async_read_loop():
                if ev.type != evdev.ecodes.EV_KEY:
                    continue
                now = time.time()
                delay = (now - ev.timestamp()) * 1000
                lat.append(delay)
                name = evdev.ecodes.BTN.get(ev.code, ev.code)
                state = {1: "pressionou", 0: "soltou", 2: "repetiu"}[ev.value]
                held = ""
                if ev.value == 1:
                    down[ev.code] = ev.timestamp()
                elif ev.value == 0 and ev.code in down:
                    held = f" segurou {(ev.timestamp() - down.pop(ev.code)) * 1000:.0f} ms"
                print(f"  {name} {state} evento->leitura {delay:.2f} ms{held}")

        async def main() -> None:
            try:
                await asyncio.wait_for(reader(), max(0.0, deadline - time.monotonic()))
            except TimeoutError:
                pass

        asyncio.run(main())
        if lat:
            med = statistics.median(lat)
            print(f"  latência evento->leitura: mediana {med:.2f} ms, máx {max(lat):.2f} ms")
        else:
            print("  nenhum botão apertado")
    dev.close()
    return 0


# --------------------------------------------------------------------------- CLI


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("kga")
    k.add_argument("--key", default="Meta+Ctrl+Alt+F12")
    k.add_argument("--listen", type=float, default=0.0)
    k.add_argument("--rounds", type=int, default=20)
    e = sub.add_parser("evdev")
    e.add_argument("--listen", type=float, default=0.0)
    sub.add_parser("cleanup")
    args = ap.parse_args()
    if args.cmd == "kga":
        return asyncio.run(run_kga(args.key, args.listen, args.rounds))
    if args.cmd == "evdev":
        return run_evdev(args.listen)
    return asyncio.run(run_cleanup())


if __name__ == "__main__":
    sys.exit(main())
