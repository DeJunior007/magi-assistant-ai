"""Detecção de call do Discord no satélite (§3.2, R2.1, R2.2).

A cada ``POLL_S`` segundos lista os ``source-output``s do PipeWire (``pulsectl``, numa thread
própria para não bloquear o laço) e procura um fluxo de captura do Discord ativo (não ``corked``).
Em call, desliga o "Condessa" (``WakeSpotter.enabled = False``) e manda
``SatelliteStatus(in_call=True, wake_enabled=False)`` ao núcleo; ao sair, religa e manda o status.
Histerese: o estado só muda depois de ``confirm`` leituras iguais seguidas (2 × 2 s ≤ 5 s, R2.2).
Erro do ``pulsectl`` não derruba o satélite: a leitura é ignorada e a conexão é refeita na próxima.

``DiscordPttMuter`` (5.2, R2.3, R2.4): em call, enquanto o atalho estiver pressionado, muta só os
``source-output``s do Discord (``source_output_mute``; o microfone continua chegando à Magui) e
desmuta ``MUTE_GRACE_S`` depois de soltar, para não cortar o fim da frase. Antes de mutar grava
``{índice, application.name, mudo original}`` em ``$XDG_RUNTIME_DIR/magi/discord-muted``
(o WirePlumber guarda o mudo por app, S1); ``recover()`` na inicialização desfaz o que uma queda
deixou. Fluxo que já estava mutado pelo usuário continua mutado. Fluxo novo do Discord durante o
aperto também é mutado (herda o estado original do fluxo anterior do mesmo app, porque o
WirePlumber o reabre já mutado). Se o fluxo original sumiu, o desmudo fica pendente e vai para o
próximo fluxo daquele app que aparecer mutado.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Protocol

from magi.common.contracts import SatelliteStatus, SatelliteToCore
from magi.satellite.wake import WakeSpotter

log = logging.getLogger("magi.satellite.discord")

POLL_S = 2.0
CONFIRM_READS = 2

#: Trechos de ``application.process.binary`` (minúsculos) que identificam o Discord e clientes dele.
DISCORD_BINARIES = ("discord", "vesktop", "webcord")
#: ``application.name`` da captura de voz da call no Discord (S1).
DISCORD_VOICE_NAME = "WEBRTC VoiceEngine"
#: ``application.name`` da captura de compartilhamento de tela: sozinha não indica call (S1).
DISCORD_SCREEN_CAPTURE_NAME = "discord_capture"
DISCORD_FLATPAK_ID = "com.discordapp.Discord"

#: Folga entre soltar o atalho e desmutar o Discord (não corta o fim da frase para os amigos).
MUTE_GRACE_S = 0.15
#: Enquanto mutado, procura fluxo novo do Discord a cada tanto.
MUTE_POLL_S = 0.25
#: Com desmudo pendente (fluxo original sumiu), procura o fluxo novo do app a cada tanto.
PENDING_POLL_S = 2.0


class PulseLike(Protocol):
    """O pedaço de ``pulsectl.Pulse`` usado aqui (o falso dos testes implementa só isto)."""

    def source_output_list(self) -> list[Any]: ...

    def close(self) -> None: ...


def is_discord_source_output(so: Any) -> bool:
    """``True`` se o ``source-output`` é do Discord (qualquer captura dele, inclusive tela)."""
    props = getattr(so, "proplist", None) or {}
    binary = str(props.get("application.process.binary", "")).lower()
    if any(b in binary for b in DISCORD_BINARIES):
        return True
    if props.get("application.name") == DISCORD_VOICE_NAME:
        return True
    return props.get("pipewire.access.portal.app_id") == DISCORD_FLATPAK_ID


def find_discord_source_outputs(pulse: PulseLike) -> list[Any]:
    """Todos os ``source-output``s do Discord, em pausa ou não (a 5.2 muta todos eles)."""
    return [so for so in pulse.source_output_list() if is_discord_source_output(so)]


def call_active(outputs: Iterable[Any]) -> bool:
    """Há call: alguma captura do Discord ativa (não ``corked``) que não seja só a de tela."""
    for so in outputs:
        props = getattr(so, "proplist", None) or {}
        if getattr(so, "corked", False):
            continue
        if props.get("application.name") == DISCORD_SCREEN_CAPTURE_NAME:
            continue
        return True
    return False


def _default_pulse() -> PulseLike:
    import pulsectl

    return pulsectl.Pulse("magi-satellite-discord")


Sender = Callable[[SatelliteToCore], Awaitable[bool]]


class DiscordCallMonitor:
    """Liga/desliga o wake word conforme a call do Discord e avisa o núcleo (R2.1, R2.2).

    ``send`` é ``CoreClient.send``; se o envio falhar (sem conexão), o status é reenviado na
    próxima leitura até chegar. ``pulse_factory`` cria a conexão ``pulsectl`` (testes: falso).
    """

    def __init__(
        self,
        spotter: WakeSpotter,
        send: Sender,
        satellite: str,
        *,
        pulse_factory: Callable[[], PulseLike] = _default_pulse,
        poll_s: float = POLL_S,
        confirm: int = CONFIRM_READS,
    ) -> None:
        self.spotter = spotter
        self.send = send
        self.satellite = satellite
        self.pulse_factory = pulse_factory
        self.poll_s = poll_s
        self.confirm = max(1, confirm)
        self.in_call = False
        self._candidate: bool | None = None
        self._streak = 0
        self._pending: SatelliteStatus | None = None
        self._pulse: PulseLike | None = None
        self._failing = False
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="magi-discord")

    # --- leitura (thread do executor; a conexão pulsectl fica sempre na mesma thread) ---

    def _read_blocking(self) -> bool:
        if self._pulse is None:
            self._pulse = self.pulse_factory()
        try:
            return call_active(find_discord_source_outputs(self._pulse))
        except Exception:
            self._close_blocking()
            raise

    def _close_blocking(self) -> None:
        p, self._pulse = self._pulse, None
        if p is not None:
            try:
                p.close()
            except Exception:  # noqa: BLE001 - fechar nunca derruba o satélite
                pass

    async def read(self) -> bool | None:
        """Uma leitura; ``None`` se o ``pulsectl`` falhou (estado fica como está)."""
        loop = asyncio.get_running_loop()
        try:
            active = await loop.run_in_executor(self._executor, self._read_blocking)
        except Exception as e:  # noqa: BLE001 - qualquer erro do PipeWire vira "sem leitura"
            if not self._failing:
                log.warning("não consegui ler os fluxos do PipeWire (%s); tento de novo", e)
            self._failing = True
            return None
        if self._failing:
            log.info("leitura do PipeWire voltou")
        self._failing = False
        return active

    # --- decisão ---

    async def step(self) -> None:
        """Lê uma vez, aplica a histerese e, se mudou, alterna o wake word e avisa o núcleo."""
        active = await self.read()
        if active is not None:
            if active == self.in_call:
                self._candidate, self._streak = None, 0
            elif active == self._candidate:
                self._streak += 1
            else:
                self._candidate, self._streak = active, 1
            if self._candidate is not None and self._streak >= self.confirm:
                self._candidate, self._streak = None, 0
                self._set_in_call(active)
        if self._pending is not None and await self.send(self._pending):
            self._pending = None

    def _set_in_call(self, in_call: bool) -> None:
        self.in_call = in_call
        if not in_call:
            self.spotter.detector.reset()  # não reaproveita áudio de antes da call
        self.spotter.enabled = not in_call
        log.info("call do Discord %s: wake word %s", "começou" if in_call else "acabou",
                 "desligado" if in_call else "religado")
        self._pending = SatelliteStatus(satellite=self.satellite, in_call=in_call,
                                        wake_enabled=not in_call)

    async def run(self) -> None:
        """Laço de verificação; termina quando a tarefa é cancelada."""
        try:
            while True:
                await self.step()
                await asyncio.sleep(self.poll_s)
        finally:
            await self.close()

    async def close(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(self._executor, self._close_blocking)
        finally:
            self._executor.shutdown(wait=False)


# --- mudo só do Discord no atalho (5.2, R2.3, R2.4) ---


class MutePulseLike(PulseLike, Protocol):
    def source_output_mute(self, index: int, mute: bool) -> None: ...


def mute_file_path(env: Mapping[str, str] | None = None) -> Path:
    """``$XDG_RUNTIME_DIR/magi/discord-muted`` (sem a variável, ``/run/user/<uid>``)."""
    env = os.environ if env is None else env
    base = env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(base) / "magi" / "discord-muted"


def _app(so: Any) -> str:
    return str((getattr(so, "proplist", None) or {}).get("application.name", ""))


def _is_index_error(e: Exception) -> bool:
    return type(e).__name__ == "PulseIndexError"


class DiscordPttMuter:
    """Muta só o Discord enquanto o atalho está pressionado numa call (R2.3) e se recupera de
    queda (R2.4). Ligação: ``ptt.subscribe(muter.on_ptt)``; ``in_call`` lê
    ``DiscordCallMonitor.in_call``. Fora de call não mexe em nada."""

    def __init__(
        self,
        in_call: Callable[[], bool],
        *,
        pulse_factory: Callable[[], Any] = _default_pulse,
        path: Path | None = None,
        grace_s: float = MUTE_GRACE_S,
        poll_s: float = MUTE_POLL_S,
        pending_poll_s: float = PENDING_POLL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.in_call = in_call
        self.pulse_factory = pulse_factory
        self.path = path or mute_file_path()
        self.grace_s = grace_s
        self.poll_s = poll_s
        self.pending_poll_s = pending_poll_s
        self.clock = clock
        self.muting = False
        self._pressed = False
        self._released_at = 0.0
        self._entries: list[dict[str, Any]] = []
        self._pulse: MutePulseLike | None = None
        self._wake = asyncio.Event()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="magi-discord-mute")

    # --- arquivo de recuperação ---

    def _load(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self.path.read_text())
            return [e for e in data.get("streams", [])
                    if isinstance(e, dict) and {"index", "app", "was_muted"} <= e.keys()]
        except FileNotFoundError:
            return []
        except (OSError, ValueError, AttributeError) as e:
            log.error("arquivo de recuperação do mudo ilegível (%s): %s", self.path, e)
            return []

    def _save(self) -> None:
        if not self._entries:
            self.path.unlink(missing_ok=True)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump({"streams": self._entries}, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)

    # --- pulsectl (sempre na thread do executor) ---

    def _conn(self) -> MutePulseLike:
        if self._pulse is None:
            self._pulse = self.pulse_factory()
        return self._pulse

    def _close_blocking(self) -> None:
        p, self._pulse = self._pulse, None
        if p is not None:
            try:
                p.close()
            except Exception:  # noqa: BLE001 - fechar nunca derruba o satélite
                pass

    def _set_mute(self, pulse: MutePulseLike, index: int, mute: bool) -> bool:
        try:
            pulse.source_output_mute(index, mute)
            return True
        except Exception as e:
            if _is_index_error(e):  # o fluxo sumiu entre a listagem e o mudo
                return False
            raise

    def mute_blocking(self) -> int:
        """Muta os fluxos do Discord ainda não tratados (grava o arquivo ANTES). Devolve quantos."""
        pulse = self._conn()
        try:
            known = {e["index"] for e in self._entries if not e.get("pending")}
            new: list[tuple[Any, dict[str, Any]]] = []
            for so in find_discord_source_outputs(pulse):
                if so.index in known:
                    continue
                app = _app(so)
                # fluxo novo do mesmo app (troca de stream, ou pendente de queda): o WirePlumber o
                # abre já mutado por nós, então vale o estado original do anterior
                prev = next((e for e in self._entries if e["app"] == app), None)
                was = bool(getattr(so, "mute", False)) if prev is None else prev["was_muted"]
                new.append((so, {"index": so.index, "app": app, "was_muted": was}))
            if not new:
                return 0
            apps = {e["app"] for _, e in new}
            self._entries = [e for e in self._entries if not (e.get("pending") and e["app"] in apps)]
            self._entries += [e for _, e in new]
            self._save()
            n = 0
            for so, _e in new:
                if not getattr(so, "mute", False) and self._set_mute(pulse, so.index, True):
                    n += 1
            if n:
                log.info("Discord mutado no atalho (%d fluxo(s))", n)
            return n
        except Exception:
            self._close_blocking()
            raise

    def restore_blocking(self) -> int:
        """Desfaz o mudo (do arquivo também, após queda). Devolve quantos fluxos desmutou."""
        if not self._entries:
            self._entries = self._load()
        if not self._entries:
            return 0
        pulse = self._conn()
        try:
            live = {so.index: so for so in find_discord_source_outputs(pulse)}
            n = 0
            done_apps: set[str] = set()
            lost: list[dict[str, Any]] = []
            for e in self._entries:
                so = live.get(e["index"])
                if e.get("pending") or so is None or _app(so) != e["app"]:
                    lost.append(e)
                elif e["was_muted"]:
                    done_apps.add(e["app"])  # já estava mutado pelo usuário: continua
                elif self._set_mute(pulse, e["index"], False):
                    done_apps.add(e["app"])
                    n += 1
                else:
                    lost.append(e)
            keep: list[dict[str, Any]] = []
            for e in lost:
                if e["was_muted"] or e["app"] in done_apps or any(k["app"] == e["app"] for k in keep):
                    continue
                keep.append({"index": e["index"], "app": e["app"], "was_muted": False, "pending": True})
            self._entries = keep
            n += self._apply_pending(pulse, list(live.values()))
            self._save()
            if self._entries:
                log.warning("desmudo do Discord (%s) fica pendente até o fluxo voltar",
                            ", ".join(repr(e["app"]) for e in self._entries))
            elif n:
                log.info("Discord desmutado (%d fluxo(s))", n)
            return n
        except Exception:
            self._close_blocking()
            raise

    def _apply_pending(self, pulse: MutePulseLike, sos: list[Any]) -> int:
        """Fluxo original sumiu: desmuta o fluxo novo do mesmo app, que o WirePlumber reabre
        mutado; se ele voltou desmutado, não há o que fazer."""
        n = 0
        for e in [e for e in self._entries if e.get("pending")]:
            same = [so for so in sos if _app(so) == e["app"]]
            if not same:
                continue
            for so in same:
                if getattr(so, "mute", False) and self._set_mute(pulse, so.index, False):
                    n += 1
            self._entries.remove(e)
        return n

    # --- async ---

    async def _run(self, fn: Callable[[], int], what: str) -> int:
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(self._executor, fn)
        except Exception as e:  # noqa: BLE001 - erro do PipeWire não derruba o satélite
            log.warning("%s falhou: %s", what, e)
            return 0

    async def recover(self) -> int:
        """Ao iniciar: desmuta o que uma execução anterior deixou mutado (R2.4)."""
        if not self.path.exists():
            return 0
        log.warning("achei %s: desmutando o Discord de uma queda anterior", self.path)
        return await self._run(self.restore_blocking, "recuperação do mudo do Discord")

    def on_ptt(self, pressed: bool) -> None:
        """Ouvinte de ``PushToTalk.subscribe`` (chamado no laço de eventos)."""
        self._pressed = pressed
        if not pressed:
            self._released_at = self.clock()
        self._wake.set()

    async def step(self) -> float | None:
        """Uma decisão; devolve em quanto tempo olhar de novo (``None``: só no próximo atalho)."""
        if self._pressed and (self.muting or self.in_call()):
            self.muting = True
            await self._run(self.mute_blocking, "mudo do Discord")
            return self.poll_s
        if self.muting:
            left = self._released_at + self.grace_s - self.clock()
            if left > 0:
                return left
            self.muting = False
        if self._entries:
            await self._run(self.restore_blocking, "desmudo do Discord")
        return self.pending_poll_s if self._entries else None

    async def run(self) -> None:
        """Laço do mudo; ao ser cancelado desmuta o que estiver mutado e fecha a conexão."""
        try:
            while True:
                self._wake.clear()
                timeout = await self.step()
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout)
                except TimeoutError:
                    pass
        finally:
            await self.close()

    async def close(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            if any(not e.get("pending") for e in self._entries):
                await self._run(self.restore_blocking, "desmudo do Discord ao sair")
            await loop.run_in_executor(self._executor, self._close_blocking)
        finally:
            self._executor.shutdown(wait=False)
