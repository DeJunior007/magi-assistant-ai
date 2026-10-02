"""Importação do gosto musical do Spotify para ``taste`` (tarefa 2.3, R8.2, §7).

Lê (só GET) os artistas e faixas mais ouvidos em ``short_term``/``medium_term``/``long_term`` e os
tocados recentemente, e grava um peso por artista:

- artista no top de artistas: ``peso_do_prazo × peso_da_posição``;
- faixa no top de faixas: metade disso para o artista principal, um quarto para os participantes;
- cada execução recente: ``RECENT_PLAY`` para o artista principal.

O prazo curto pesa mais (gosto do momento); a posição cai linearmente (1º = 1, 50º = 0,02). A soma
é normalizada para o maior peso valer 1. Gravação por ``upsert`` (substitui): rodar de novo não
duplica.

Apps novos do Spotify em modo de desenvolvimento (verificado em 2026-10): o top de artistas vem sem
``genres``/``popularity``/``followers``; ``GET /artists`` em lote, ``related-artists`` e
``audio-features`` dão 403 e ``recommendations`` dá 404. Por isso o gênero é opcional (vazio quando
ausente) e cada fonte que falhar é só registrada no relatório, sem derrubar a importação.

Uso: ``uv run python -m magi.core.music.import_taste [--dsn ...] [--dry-run]``. O núcleo roda
:func:`refresh_loop` em segundo plano (tarefa 2.4): ao subir e depois a cada hora verifica se a
última importação (data em ``taste-import.json`` no diretório de dados) tem mais de 24 h ou se a
tabela está vazia, e só então reimporta. Reimportar não apaga sinais nem ajustes: o upsert troca só
o peso base, e o peso efetivo (base + ``bonus`` + sinais) sai da view ``taste_effective``.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import time
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from magi.common.contracts import TasteEntry, TasteRepo
from magi.core.actions.spotify_api import SpotifyApi, SpotifyApiError, SpotifyAuthError

log = logging.getLogger(__name__)

RANGES: dict[str, float] = {"short_term": 1.0, "medium_term": 0.7, "long_term": 0.5}
LIMIT = 50
TRACK_MAIN = 0.5
TRACK_FEAT = 0.25
RECENT_PLAY = 0.02  # 50 execuções = 1 artista em 1º no prazo curto
REFRESH_S = 24 * 3600.0  # reimportação 1×/dia
CHECK_S = 3600.0
STATE_FILE = "taste-import.json"


class SpotifyGetter(Protocol):
    async def get(self, path: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]: ...


@dataclass
class TasteData:
    """Itens crus de cada fonte (``fonte -> itens``) e fontes que falharam (``fonte -> motivo``)."""

    top_artists: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    top_tracks: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    recent: list[dict[str, Any]] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)

    def counts(self) -> dict[str, int]:
        c = {f"artists/{r}": len(v) for r, v in self.top_artists.items()}
        c |= {f"tracks/{r}": len(v) for r, v in self.top_tracks.items()}
        c["recent"] = len(self.recent)
        return c


@dataclass
class ImportReport:
    entries: list[TasteEntry]
    data: TasteData


def position_weight(i: int) -> float:
    return max(0.0, 1.0 - i / LIMIT)


async def fetch(api: SpotifyGetter) -> TasteData:
    """Busca as 7 fontes. ``SpotifyAuthError`` sobe; erros de API viram ``failed``."""
    data = TasteData()

    async def items(source: str, path: str, params: dict[str, Any]) -> list[dict[str, Any]] | None:
        try:
            d = await api.get(path, params)
        except SpotifyApiError as e:
            log.warning("gosto: %s indisponível (%s)", source, e)
            data.failed[source] = str(e)
            return None
        return [x for x in d.get("items") or [] if x]

    for rng in RANGES:
        params = {"time_range": rng, "limit": LIMIT}
        if (a := await items(f"artists/{rng}", "/me/top/artists", params)) is not None:
            data.top_artists[rng] = a
        if (t := await items(f"tracks/{rng}", "/me/top/tracks", params)) is not None:
            data.top_tracks[rng] = t
    if (r := await items("recent", "/me/player/recently-played", {"limit": LIMIT})) is not None:
        data.recent = r
    return data


def compute(data: TasteData) -> list[TasteEntry]:
    """Pesos por artista (normalizados para o maior = 1), maior primeiro."""
    score: dict[str, float] = defaultdict(float)
    genre: dict[str, str] = {}

    for rng, artists in data.top_artists.items():
        for i, a in enumerate(artists):
            name = (a.get("name") or "").strip()
            if not name:
                continue
            score[name] += RANGES.get(rng, 0.5) * position_weight(i)
            genres = a.get("genres") or []  # vazio/ausente em apps novos
            if genres and name not in genre:
                genre[name] = str(genres[0])

    def track_artists(track: Mapping[str, Any]) -> list[str]:
        return [n for a in track.get("artists") or [] if (n := (a.get("name") or "").strip())]

    for rng, tracks in data.top_tracks.items():
        for i, t in enumerate(tracks):
            w = RANGES.get(rng, 0.5) * position_weight(i)
            for j, name in enumerate(track_artists(t)):
                score[name] += w * (TRACK_MAIN if j == 0 else TRACK_FEAT)

    for play in data.recent:
        names = track_artists(play.get("track") or {})
        if names:
            score[names[0]] += RECENT_PLAY

    if not score:
        return []
    top = max(score.values())
    entries = [TasteEntry(n, genre.get(n, ""), round(s / top, 4)) for n, s in score.items()]
    entries.sort(key=lambda e: (-e.weight, e.artist))
    return entries


async def import_taste(api: SpotifyGetter, repo: TasteRepo | None) -> ImportReport:
    """Busca, calcula e grava (se ``repo``). Sem nada para gravar, não toca no banco."""
    data = await fetch(api)
    entries = compute(data)
    if repo is not None and entries:
        await repo.upsert(entries)
    log.info("gosto: %d artistas de %s; falhas: %s", len(entries), data.counts(), data.failed or "-")
    return ImportReport(entries, data)


async def import_if_empty(repo: Any, api: SpotifyApi | None = None) -> ImportReport | None:
    """Ponto do núcleo: importa na primeira configuração (tabela vazia e Spotify conectado).
    Nunca levanta (roda em segundo plano)."""
    own = api is None
    api = api or SpotifyApi()
    try:
        if await repo.count() > 0:
            return None
        if not api.connected():
            log.info("gosto: Spotify não conectado; importação adiada")
            return None
        return await import_taste(api, repo)
    except Exception:
        log.exception("gosto: importação falhou")
        return None
    finally:
        if own:
            await api.aclose()


def last_import(state_path: Path) -> float | None:
    """Epoch da última importação gravada em ``state_path`` (``None`` se não houver)."""
    try:
        return float(json.loads(state_path.read_text(encoding="utf-8"))["last_import"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _save_last(state_path: Path, at: float) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = state_path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"last_import": at}), encoding="utf-8")
    tmp.replace(state_path)


async def import_if_stale(
    repo: Any,
    state_path: Path,
    api: SpotifyGetter | None = None,
    *,
    now: Callable[[], float] = time.time,
    max_age_s: float = REFRESH_S,
) -> ImportReport | None:
    """Reimporta se a tabela está vazia ou a última importação tem mais de ``max_age_s``.
    Grava a data só quando algo foi importado. Nunca levanta (roda em segundo plano)."""
    own = api is None
    try:
        last = last_import(state_path)
        if last is not None and now() - last < max_age_s and await repo.count() > 0:
            return None
        if own:
            api = SpotifyApi()
        if hasattr(api, "connected") and not api.connected():
            log.info("gosto: Spotify não conectado; importação adiada")
            return None
        rep = await import_taste(api, repo)
        if rep.entries:
            _save_last(state_path, now())
        return rep
    except Exception:
        log.exception("gosto: reimportação falhou")
        return None
    finally:
        if own and api is not None:
            with contextlib.suppress(Exception):
                await api.aclose()


async def refresh_loop(repo: Any, state_path: Path, *, check_s: float = CHECK_S) -> None:
    """Tarefa leve do núcleo: verifica a cada ``check_s`` e reimporta 1×/dia."""
    while True:
        await import_if_stale(repo, state_path)
        await asyncio.sleep(check_s)


def _print_top(entries: Sequence[TasteEntry], n: int = 10) -> None:
    for i, e in enumerate(entries[:n], 1):
        g = f" [{e.genre}]" if e.genre else ""
        print(f"{i:2}. {e.artist}{g}  {e.weight:.3f}")


async def _amain(dsn: str | None, dry_run: bool) -> int:
    api = SpotifyApi()
    try:
        if dry_run:
            rep = await import_taste(api, None)
        else:
            import psycopg

            from magi.memory.migrate import dsn_from_env
            from magi.memory.taste_repo import TasteRepo as PgTasteRepo

            conn = await psycopg.AsyncConnection.connect(dsn or dsn_from_env(), autocommit=True)
            try:
                repo = PgTasteRepo(conn)
                rep = await import_taste(api, repo)
                print(f"taste: {await repo.count()} linhas no banco")
            finally:
                await conn.close()
    except SpotifyAuthError as e:
        print(f"{e}: rode o login do Spotify primeiro")
        return 1
    finally:
        await api.aclose()
    print(f"fontes: {rep.data.counts()}")
    if rep.data.failed:
        print(f"falharam: {sorted(rep.data.failed)}")
    print(f"{len(rep.entries)} artistas{' (dry-run, nada gravado)' if dry_run else ' gravados'}")
    _print_top(rep.entries)
    return 0 if rep.entries else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="magi.core.music.import_taste", description=__doc__.split("\n")[0])
    parser.add_argument("--dsn", default=None, help="padrão: $MAGI_DB_DSN ou o Postgres de desenvolvimento")
    parser.add_argument("--dry-run", action="store_true", help="só mostra, não grava")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return asyncio.run(_amain(args.dsn, args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
