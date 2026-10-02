"""Ducking de Spotify e jogo enquanto a Magui fala (§5, R12.4, ``docs/spikes/S1.md``).

``Ducker.duck()`` baixa para ``DUCK_LEVEL`` (0,30) os ``sink-input``s do Spotify e de jogos
(processo com ``SteamAppId`` ou binário Wine); ``Ducker.restore()`` devolve o volume original
(``PulseVolumeInfo`` por canal). Nunca aumenta um volume que já esteja abaixo de 0,30 e nunca
mexe nos nossos fluxos (``application.name`` começando por ``magi``).

Recuperação após queda (S1, Limitações 2): o WirePlumber guarda o volume por ``application.name``;
se o satélite cair durante o ducking, o Spotify (ou todos os jogos Wine, que se chamam ``' '``)
ficariam a 30% para sempre. Por isso, ANTES de alterar qualquer volume, o original é gravado em
``$XDG_RUNTIME_DIR/magi/duck-restore.json``; ``restore()`` e ``recover()`` (chamado ao iniciar)
restauram a partir dele. Se o fluxo original sumiu, a entrada fica pendente e o volume original é
aplicado ao próximo fluxo do mesmo ``application.name`` que aparecer ainda no nível do ducking
(o WirePlumber então salva o valor certo). O arquivo só é apagado quando não sobra nada a restaurar.

O ``pulsectl`` é bloqueante: tudo roda numa thread própria (a conexão fica sempre nela).
Erro do PipeWire nunca derruba o satélite (log e segue).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Protocol

from magi.common.contracts import DUCK_LEVEL

log = logging.getLogger("magi.satellite.ducking")

SPOTIFY_FLATPAK_ID = "com.spotify.Client"
WINE_BINARIES = frozenset({"wine64-preloader", "wine-preloader", "wine64", "wine"})
OWN_PREFIX = "magi"
#: Tolerância ao comparar volumes (o PipeWire arredonda para a escala inteira do Pulse).
VOL_EPS = 0.02


class PulseLike(Protocol):
    """O pedaço de ``pulsectl.Pulse`` usado aqui (o falso dos testes implementa só isto)."""

    def sink_input_list(self) -> list[Any]: ...

    def volume_set_all_chans(self, obj: Any, vol: float) -> None: ...

    def sink_input_volume_set(self, index: int, vol: Any) -> None: ...

    def close(self) -> None: ...


def restore_file_path(env: Mapping[str, str] | None = None) -> Path:
    """``$XDG_RUNTIME_DIR/magi/duck-restore.json`` (sem a variável, ``/run/user/<uid>``)."""
    env = os.environ if env is None else env
    base = env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(base) / "magi" / "duck-restore.json"


def _props(si: Any) -> Mapping[str, Any]:
    return getattr(si, "proplist", None) or {}


def _read_environ(pid: int) -> bytes:
    return Path(f"/proc/{pid}/environ").read_bytes()


def is_own(si: Any) -> bool:
    return str(_props(si).get("application.name", "")).lower().startswith(OWN_PREFIX)


def is_spotify(si: Any) -> bool:
    p = _props(si)
    if p.get("pipewire.access.portal.app_id") == SPOTIFY_FLATPAK_ID:
        return True
    name = str(p.get("application.name", "")).lower()
    binary = str(p.get("application.process.binary", "")).lower()
    return "spotify" in name or "spotify" in binary


def is_game(si: Any, read_environ: Callable[[int], bytes] = _read_environ) -> bool:
    """Jogo: binário Wine/Proton, ou processo com ``SteamAppId`` (≠ 0) no ambiente (S1)."""
    p = _props(si)
    if str(p.get("application.process.binary", "")).lower() in WINE_BINARIES:
        return True
    pid = p.get("application.process.id")
    if not pid:
        return False
    try:
        env = read_environ(int(pid))
    except (OSError, ValueError):
        return False
    for entry in env.split(b"\0"):
        if entry.startswith(b"SteamAppId="):
            return entry.split(b"=", 1)[1] not in (b"", b"0")
    return False


def should_duck(si: Any, read_environ: Callable[[int], bytes] = _read_environ) -> bool:
    if is_own(si):
        return False
    return is_spotify(si) or is_game(si, read_environ)


def _values(si: Any) -> list[float]:
    return [float(v) for v in si.volume.values]


def _default_pulse() -> PulseLike:
    import pulsectl

    return pulsectl.Pulse("magi-satellite-ducking")


def _default_volume(values: Sequence[float]) -> Any:
    import pulsectl

    return pulsectl.PulseVolumeInfo(list(values))


def _is_index_error(e: Exception) -> bool:
    return type(e).__name__ == "PulseIndexError"


class Ducker:
    """Abaixa e restaura Spotify/jogo, com arquivo de recuperação (ver módulo).

    Métodos ``*_blocking`` rodam na thread do ``pulsectl``; os ``async`` os despacham para lá.
    """

    def __init__(
        self,
        *,
        level: float = DUCK_LEVEL,
        path: Path | None = None,
        pulse_factory: Callable[[], PulseLike] = _default_pulse,
        volume_factory: Callable[[Sequence[float]], Any] = _default_volume,
        read_environ: Callable[[int], bytes] = _read_environ,
    ) -> None:
        self.level = level
        self.path = path or restore_file_path()
        self.pulse_factory = pulse_factory
        self.volume_factory = volume_factory
        self.read_environ = read_environ
        self._pulse: PulseLike | None = None
        #: entradas do arquivo: index, app, binary, values, ducked_to, pending
        self._entries: list[dict[str, Any]] = []
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="magi-duck")

    # --- arquivo de recuperação ---

    def _load(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self.path.read_text())
            return [e for e in data.get("streams", []) if isinstance(e, dict) and "values" in e]
        except FileNotFoundError:
            return []
        except (OSError, ValueError, AttributeError) as e:
            log.error("arquivo de recuperação de volume ilegível (%s): %s", self.path, e)
            return []

    def _save(self) -> None:
        if not self._entries:
            self.path.unlink(missing_ok=True)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"streams": self._entries}, ensure_ascii=False, indent=1))
        os.replace(tmp, self.path)

    # --- pulsectl ---

    def _conn(self) -> PulseLike:
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

    def _set_values(self, pulse: PulseLike, index: int, values: Sequence[float]) -> bool:
        try:
            pulse.sink_input_volume_set(index, self.volume_factory(values))
            return True
        except Exception as e:
            if _is_index_error(e):
                return False
            raise

    # --- operações (thread do pulsectl) ---

    def duck_blocking(self) -> int:
        """Abaixa os fluxos ainda não abaixados; devolve quantos foram abaixados agora.
        Idempotente: pode ser chamado de novo durante a fala para pegar fluxos novos (S1, item 3)."""
        pulse = self._conn()
        try:
            sis = pulse.sink_input_list()
            if self._apply_pending(pulse, sis):
                sis = pulse.sink_input_list()  # volumes mudaram: relê antes de guardar originais
            done = {e["index"] for e in self._entries if not e.get("pending")}
            targets = [si for si in sis if si.index not in done and should_duck(si, self.read_environ)
                       and max(_values(si), default=0.0) > self.level + VOL_EPS]
            if not targets:
                return 0
            for si in targets:  # grava ANTES de alterar (crash-safe)
                p = _props(si)
                self._entries.append({
                    "index": si.index,
                    "app": str(p.get("application.name", "")),
                    "binary": str(p.get("application.process.binary", "")),
                    "values": _values(si),
                    "ducked_to": self.level,
                })
            self._save()
            n = 0
            for si in targets:
                try:
                    pulse.volume_set_all_chans(si, self.level)
                    n += 1
                except Exception as e:
                    if not _is_index_error(e):
                        raise
                    self._entries = [x for x in self._entries if x["index"] != si.index]
            self._save()
            if n:
                log.info("ducking: %d fluxo(s) a %.0f%%", n, self.level * 100)
            return n
        except Exception:
            self._close_blocking()
            raise

    def restore_blocking(self) -> int:
        """Restaura todos os volumes guardados (do arquivo também). Devolve quantos restaurou."""
        if not self._entries:
            self._entries = self._load()
        if not self._entries:
            return 0
        pulse = self._conn()
        try:
            sis = pulse.sink_input_list()
            live = {si.index: si for si in sis}
            n = 0
            keep: list[dict[str, Any]] = []
            for e in self._entries:
                si = live.get(e["index"])
                if (not e.get("pending") and si is not None
                        and str(_props(si).get("application.name", "")) == e["app"]
                        and self._set_values(pulse, e["index"], e["values"])):
                    n += 1
                else:
                    keep.append({**e, "pending": True})
            self._entries = keep
            n += self._apply_pending(pulse, sis)
            self._save()
            if self._entries:
                log.warning("volume de %s fica pendente até o app abrir de novo",
                            ", ".join(repr(e["app"]) for e in self._entries))
            elif n:
                log.info("ducking desfeito (%d fluxo(s))", n)
            return n
        except Exception:
            self._close_blocking()
            raise

    def _apply_pending(self, pulse: PulseLike, sis: Sequence[Any]) -> int:
        """Fluxo original sumiu: aplica o volume ao fluxo novo do mesmo app ainda no nível do
        ducking (o WirePlumber o reabriu assim). Remove a entrada quando aplicou."""
        pend = [e for e in self._entries if e.get("pending")]
        if not pend:
            return 0
        n = 0
        used: set[int] = set()
        for e in pend:
            for si in sis:
                if si.index in used or str(_props(si).get("application.name", "")) != e["app"]:
                    continue
                vals = _values(si)
                if vals and max(abs(v - e["ducked_to"]) for v in vals) <= VOL_EPS:
                    if self._set_values(pulse, si.index, e["values"]):
                        used.add(si.index)
                        self._entries.remove(e)
                        n += 1
                        break
        if n:
            self._save()
        return n

    # --- async ---

    async def _run(self, fn: Callable[[], int], what: str) -> int:
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(self._executor, fn)
        except Exception as e:  # noqa: BLE001 - erro do PipeWire não derruba o satélite
            log.warning("%s falhou: %s", what, e)
            return 0

    async def duck(self) -> int:
        return await self._run(self.duck_blocking, "ducking")

    async def restore(self) -> int:
        return await self._run(self.restore_blocking, "restauração do volume")

    async def recover(self) -> int:
        """Ao iniciar: restaura o que uma execução anterior deixou abaixado."""
        if not self.path.exists():
            return 0
        log.warning("achei %s: restaurando volumes de uma queda anterior", self.path)
        return await self.restore()

    async def close(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(self._executor, self._close_blocking)
        finally:
            self._executor.shutdown(wait=False)
