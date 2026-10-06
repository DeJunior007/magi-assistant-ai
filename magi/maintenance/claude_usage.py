"""Consumo e sessões do Claude Code, lidos dos registros locais (só leitura, sem rede).

O Claude Code grava cada sessão em ``~/.claude/projects/<pasta-codificada>/<sessão>.jsonl``: uma
linha JSON por evento; as respostas do modelo trazem ``message.usage`` (tokens) e ``message.model``,
e todas têm ``timestamp`` (ISO, UTC) e ``cwd``. Este módulo soma o dia e lista as sessões:

- **ativa**: teve evento nos últimos ``ACTIVE_MIN`` minutos;
- **rodando**: há um processo ``claude`` aberto na pasta da sessão. A pasta de abertura vem do nome
  do diretório do registro (``/home/x/proj`` → ``-home-x-proj``), não do ``cwd`` das linhas, que
  muda quando a sessão entra em outra pasta.

**Janela de 5 h** (limite de uso da assinatura): como as ferramentas de uso do Claude Code fazem,
uma janela começa na hora cheia da primeira resposta e dura ``WINDOW_H`` horas; resposta depois do
fim abre outra. O limite em si depende do plano e não fica nos registros, então só se mostra o fim
da janela e o que foi usado nela (tokens novos à parte da leitura de cache, que pesa bem menos).

Leitura incremental: cada arquivo é relido só a partir do byte onde parou (o ``UsageReader`` guarda
o deslocamento), então chamar a cada poucos segundos é barato mesmo com sessões grandes.
Base para o painel "Claude Code" do HUD (proposta em ``docs/design/AUTOCONSERTO.md``).
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

PROJECTS_DIR = Path.home() / ".claude/projects"
ACTIVE_MIN = 10
WINDOW_H = 5
TZ = ZoneInfo("America/Sao_Paulo")


@dataclass(slots=True)
class Tokens:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    replies: int = 0

    def add(self, usage: dict) -> None:
        self.input += int(usage.get("input_tokens") or 0)
        self.output += int(usage.get("output_tokens") or 0)
        self.cache_read += int(usage.get("cache_read_input_tokens") or 0)
        self.cache_write += int(usage.get("cache_creation_input_tokens") or 0)
        self.replies += 1

    @property
    def total(self) -> int:
        return self.input + self.output + self.cache_read + self.cache_write

    @property
    def fresh(self) -> int:
        """Tokens novos (entrada, saída e criação de cache), sem a leitura de cache."""
        return self.input + self.output + self.cache_write


@dataclass(slots=True)
class Session:
    id: str
    folder: str = ""  # diretório do registro: pasta de abertura codificada
    cwd: str = ""
    last: datetime | None = None
    today: Tokens = field(default_factory=Tokens)
    running: bool = False

    @property
    def project(self) -> str:
        return Path(self.cwd).name if self.cwd else "?"


@dataclass(slots=True)
class Summary:
    day: str  # AAAA-MM-DD local
    tokens: Tokens
    by_model: dict[str, Tokens]
    active: list[Session]  # mais recente primeiro
    running: int
    window_start: datetime | None = None  # janela de 5 h em curso (None = nenhuma aberta)
    window_end: datetime | None = None
    window: Tokens = field(default_factory=Tokens)


class UsageReader:
    """Soma o consumo do dia local e as sessões a partir dos ``.jsonl`` (ver docstring do módulo)."""

    def __init__(self, root: Path = PROJECTS_DIR, *, tz: tzinfo = TZ,
                 now: Callable[[], datetime] = lambda: datetime.now(UTC),
                 running_cwds: Callable[[], set[str]] | None = None) -> None:
        self.root = Path(root)
        self.tz = tz
        self.now = now
        self.running_cwds = running_cwds or claude_cwds
        self._offsets: dict[Path, int] = {}
        self._sessions: dict[str, Session] = {}
        self._by_model: dict[str, Tokens] = {}
        self._day: str | None = None
        self._recent: list[tuple[datetime, dict]] = []  # respostas das últimas 2 janelas de 5 h
        self._horizon = datetime.min.replace(tzinfo=UTC)

    def _reset_day(self, day: str) -> None:
        self._day = day
        self._by_model = {}
        for s in self._sessions.values():
            s.today = Tokens()
        self._offsets = {}  # relê tudo para refazer a soma do novo dia
        self._recent = []

    def _files(self) -> Iterable[Path]:
        if not self.root.is_dir():
            return []
        return self.root.glob("*/*.jsonl")

    def _read(self, path: Path, day: str) -> None:
        start = self._offsets.get(path, 0)
        try:
            size = path.stat().st_size
            if size < start:  # arquivo encolheu (reescrito): relê
                start = 0
            if size == start:
                return
            with path.open("rb") as f:
                f.seek(start)
                chunk = f.read(size - start)
        except OSError:
            return
        end = chunk.rfind(b"\n") + 1  # só linhas completas; o resto fica para a próxima
        self._offsets[path] = start + end
        sess = self._sessions.setdefault(path.stem, Session(path.stem, path.parent.name))
        for raw in chunk[:end].splitlines():
            try:
                d = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(d, dict):
                continue
            if cwd := d.get("cwd"):
                sess.cwd = str(cwd)
            when = _parse(d.get("timestamp"))
            if when is not None and (sess.last is None or when > sess.last):
                sess.last = when
            msg = d.get("message")
            usage = msg.get("usage") if isinstance(msg, dict) else None
            if not isinstance(usage, dict) or when is None:
                continue
            model = str(msg.get("model") or "?")
            if model.startswith("<"):  # "<synthetic>": mensagens internas, sem consumo real
                continue
            if when >= self._horizon:
                self._recent.append((when, usage))
            if when.astimezone(self.tz).strftime("%Y-%m-%d") != day:
                continue
            sess.today.add(usage)
            self._by_model.setdefault(model, Tokens()).add(usage)

    def summary(self) -> Summary:
        now = self.now()
        day = now.astimezone(self.tz).strftime("%Y-%m-%d")
        self._horizon = now - timedelta(hours=2 * WINDOW_H)
        if day != self._day:
            self._reset_day(day)
        for path in self._files():
            self._read(path, day)
        try:
            running = self.running_cwds()
        except Exception as e:  # noqa: BLE001 - lista de processos é só um extra
            log.debug("processos do claude indisponíveis: %s", e)
            running = set()
        cutoff = now - timedelta(minutes=ACTIVE_MIN)
        active = []
        for s in self._sessions.values():
            s.running = s.folder in {encode(c) for c in running}
            if s.last is not None and s.last >= cutoff:
                active.append(s)
        active.sort(key=lambda s: s.last or now, reverse=True)
        total = Tokens()
        for t in self._by_model.values():
            total.input += t.input
            total.output += t.output
            total.cache_read += t.cache_read
            total.cache_write += t.cache_write
            total.replies += t.replies
        self._recent = [(w, u) for w, u in self._recent if w >= self._horizon]
        start, end, window = current_window([w for w, _ in self._recent], now)
        if start is not None:
            for w, u in self._recent:
                if start <= w < end:
                    window.add(u)
        return Summary(day, total, dict(self._by_model), active, sum(1 for s in active if s.running),
                       start, end, window)


def current_window(times: list[datetime], now: datetime,
                   hours: int = WINDOW_H) -> tuple[datetime | None, datetime | None, Tokens]:
    """Janela de ``hours`` h em curso: começa na hora cheia da 1ª resposta depois do fim da anterior."""
    start = end = None
    span = timedelta(hours=hours)
    for t in sorted(times):
        if end is None or t >= end:
            start = t.replace(minute=0, second=0, microsecond=0)
            end = start + span
    if end is None or now >= end:
        return None, None, Tokens()
    return start, end, Tokens()


def _parse(ts: object) -> datetime | None:
    if not isinstance(ts, str):
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def claude_cwds(proc: Path = Path("/proc")) -> set[str]:
    """Pastas atuais dos processos ``claude`` do usuário (lê /proc; nada é alterado)."""
    out: set[str] = set()
    uid = os.getuid()
    for pid_dir in proc.iterdir():
        if not pid_dir.name.isdigit():
            continue
        try:
            if pid_dir.stat().st_uid != uid:
                continue
            argv0 = (pid_dir / "cmdline").read_bytes().split(b"\0", 1)[0]
            if Path(argv0.decode(errors="ignore")).name != "claude":
                continue
            out.add(os.readlink(pid_dir / "cwd"))
        except OSError:
            continue
    return out


def encode(path: str) -> str:
    """Pasta como o Claude Code nomeia o diretório do registro: ``/home/x/a.b`` → ``-home-x-a-b``."""
    return "".join(c if c.isalnum() else "-" for c in path)


def human(n: int) -> str:
    """1234 → "1,2 mil"; 3_400_000 → "3,4 mi"."""
    if n >= 1_000_000:
        return f"{n / 1e6:.1f} mi".replace(".", ",")
    if n >= 1_000:
        return f"{n / 1e3:.1f} mil".replace(".", ",")
    return str(n)
