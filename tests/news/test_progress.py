"""Tarefa 6.8: progresso de anime (AniList falso) e de jogos (VDF de exemplo)."""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import psycopg
import pytest
from psycopg import sql

from magi.common.contracts import FranchisePref, NewsRepo, Progress
from magi.memory import migrate as mig
from magi.news import progress as P
from magi.news.collect.anilist import AniListError
from magi.news.repo import PgNewsRepo
from magi.news.sources import SourceConfig

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
URL = "https://graphql.test"


def media(mid, title, episodes=None):
    return {"id": mid, "episodes": episodes, "title": {"english": title, "romaji": title + " (r)"}}


PAGE1 = [
    {"status": "CURRENT", "progress": 5, "media": media(1, "Frieren", 28)},
    {"status": "COMPLETED", "progress": 0, "media": media(2, "Mob Psycho 100", 12)},
    {"status": "DROPPED", "progress": 3, "media": media(3, "Overlord", 13)},
]
PAGE2 = [{"status": "PLANNING", "progress": 0, "media": {"id": 4, "title": {"romaji": "Kusuriya"}}}]


def anilist_transport(pages=(PAGE1, PAGE2), *, status=200, errors=None, calls=None):
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        if calls is not None:
            calls.append(body["variables"])
        if errors:
            return httpx.Response(status, json={"data": None, "errors": [{"message": errors}]})
        n = body["variables"]["page"]
        page = {"pageInfo": {"hasNextPage": n < len(pages)}, "mediaList": list(pages[n - 1])}
        return httpx.Response(200, json={"data": {"Page": page}})

    return httpx.MockTransport(handler)


def steam_root(tmp: Path, *, playtime=True) -> Path:
    root = tmp / "Steam"
    apps = root / "steamapps"
    apps.mkdir(parents=True)
    for appid, name in ((292030, "The Witcher 3: Wild Hunt"), (1245620, "ELDEN RING"),
                        (1493710, "Proton Experimental"), (570, "Dota 2")):
        (apps / f"appmanifest_{appid}.acf").write_text(
            f'"AppState"\n{{\n\t"appid"\t\t"{appid}"\n\t"name"\t\t"{name}"\n}}\n')
    if playtime:
        old = root / "userdata" / "111" / "config"
        old.mkdir(parents=True)
        (old / "localconfig.vdf").write_text('"UserLocalConfigStore" { "Software" { "Valve" { "Steam" {'
                                             ' "apps" { "292030" { "Playtime" "6000" } } } } } }')
        os.utime(old / "localconfig.vdf", (1, 1))
        cfg = root / "userdata" / "222" / "config"
        cfg.mkdir(parents=True)
        (cfg / "localconfig.vdf").write_text(
            '"UserLocalConfigStore"\n{\n\t"software"\n\t{\n\t\t"Valve"\n\t\t{\n\t\t\t"Steam"\n\t\t\t{\n'
            '\t\t\t\t"apps"\n\t\t\t\t{\n'
            '\t\t\t\t\t"292030"\n\t\t\t\t\t{\n\t\t\t\t\t\t"LastPlayed"\t\t"1710630260"\n'
            '\t\t\t\t\t\t"Playtime"\t\t"375"\n\t\t\t\t\t}\n'
            '\t\t\t\t\t"7"\n\t\t\t\t\t{\n\t\t\t\t\t\t"cloud"\n\t\t\t\t\t\t{\n\t\t\t\t\t\t}\n\t\t\t\t\t}\n'
            '\t\t\t\t\t"570"\n\t\t\t\t\t{\n\t\t\t\t\t\t"Playtime"\t\t"abc"\n\t\t\t\t\t}\n'
            '\t\t\t\t}\n'  # arquivo cortado no meio: o parser devolve o que leu
        )
    return root


class MemRepo:
    def __init__(self):
        self.prog: dict[tuple[str, str], Progress] = {}
        self.prefs: dict[str, FranchisePref] = {}

    async def franchise_prefs(self):
        return list(self.prefs.values())

    async def set_franchise_pref(self, pref):
        self.prefs[pref.franchise] = pref

    async def progress(self, franchise):
        return [p for (f, _), p in self.prog.items() if f == franchise]

    async def set_progress(self, progress):
        self.prog[(progress.franchise, progress.kind)] = progress

    async def progress_updated_at(self):
        return max((p.updated_at for p in self.prog.values()), default=None)


def values(repo, kind):
    return {f: p.value for (f, k), p in repo.prog.items() if k == kind}


# --- AniList ---------------------------------------------------------------------------------


async def test_fetch_anilist_pagina_e_normaliza():
    calls = []
    async with httpx.AsyncClient(transport=anilist_transport(calls=calls)) as http:
        got = await P.fetch_anilist(http, "DiltoZord", url=URL)
    assert [c["page"] for c in calls] == [1, 2] and calls[0]["user"] == "DiltoZord"
    assert [(e.franchise, e.status, e.episode) for e in got] == [
        ("Frieren", "CURRENT", 5), ("Mob Psycho 100", "COMPLETED", 12),
        ("Overlord", "DROPPED", 3), ("Kusuriya", "PLANNING", 0)]


async def test_lista_vazia_e_usuario_inexistente():
    async with httpx.AsyncClient(transport=anilist_transport(pages=([],))) as http:
        assert await P.fetch_anilist(http, "DiltoZord", url=URL) == []
    async with httpx.AsyncClient(transport=anilist_transport(status=404, errors="Not Found")) as http:
        with pytest.raises(AniListError):
            await P.fetch_anilist(http, "ninguem", url=URL)


# --- Steam -----------------------------------------------------------------------------------


def test_read_playtime_robusto(tmp_path):
    root = steam_root(tmp_path)
    path = P.find_localconfig(root)
    assert path is not None and path.parent.parent.name == "222"  # o mais recente
    before = path.read_bytes()
    assert P.read_playtime(path) == {292030: 375}
    assert path.read_bytes() == before
    assert P.read_playtime(tmp_path / "nao-existe.vdf") == {}
    assert P.find_localconfig(tmp_path / "vazio") is None


def test_steam_progress(tmp_path):
    got = {p.franchise: p.value for p in P.steam_progress(steam_root(tmp_path), NOW)}
    assert got == {"The Witcher 3: Wild Hunt": 6.25, "ELDEN RING": 0.0, "Dota 2": 0.0}
    assert P.steam_progress(steam_root(tmp_path / "b", playtime=False), NOW) == []


# --- sincronização ---------------------------------------------------------------------------


async def test_update_progress(tmp_path):
    repo = MemRepo()
    repo.prefs["Overlord"] = FranchisePref("Overlord", weight=2.0, spoilers_ok=True)
    async with httpx.AsyncClient(transport=anilist_transport()) as http:
        rep = await P.update_progress(repo, http, NOW, anilist_user="DiltoZord", anilist_url=URL,
                                      steam_root=steam_root(tmp_path))
    assert (rep.anime, rep.games, rep.dropped, rep.errors) == (4, 3, ["Overlord"], [])
    assert values(repo, "episode") == {"Frieren": 5, "Mob Psycho 100": 12, "Overlord": 3,
                                       "Kusuriya": 0}
    assert values(repo, "hours")["The Witcher 3: Wild Hunt"] == 6.25
    assert repo.prefs["Overlord"] == FranchisePref("Overlord", 2.0, dropped=True, spoilers_ok=True)
    assert "largados" in rep.summary()


async def test_erro_no_anilist_nao_impede_steam(tmp_path):
    repo = MemRepo()
    async with httpx.AsyncClient(transport=anilist_transport(status=404, errors="Not Found")) as http:
        rep = await P.update_progress(repo, http, NOW, anilist_user="x", anilist_url=URL,
                                      steam_root=steam_root(tmp_path))
    assert rep.anime == 0 and rep.games == 3 and "anilist" in rep.errors[0]


async def test_update_if_due_intervalo(tmp_path):
    repo = MemRepo()
    src = SourceConfig(name="AniList", kind="anilist", url=URL, trust=3,
                       options={"username": "DiltoZord"})
    settings = {"steam_root": str(steam_root(tmp_path))}
    calls: list = []
    async with httpx.AsyncClient(transport=anilist_transport(calls=calls)) as http:
        assert await P.update_if_due(repo, http, [src], settings, NOW) is not None
        assert len(calls) == 2
        assert await P.update_if_due(repo, http, [src], settings, NOW + timedelta(hours=5)) is None
        assert len(calls) == 2
        rep = await P.update_if_due(repo, http, [src], settings, NOW + timedelta(hours=6))
        assert rep is not None and len(calls) == 4
        assert await P.update_if_due(repo, http, [src], {"progress": False}, NOW + timedelta(days=1)) is None
        rep = await P.update_if_due(repo, http, [], {**settings, "progress_interval_h": 0},
                                    NOW + timedelta(hours=7))
        assert rep is not None and rep.anime == 0 and len(calls) == 4


# --- banco -----------------------------------------------------------------------------------


@pytest.fixture
def schema():
    name = f"test_prog_{uuid.uuid4().hex[:10]}"
    try:
        admin = psycopg.connect(mig.dsn_from_env(), autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres indisponível: {exc}")
    try:
        with psycopg.connect(mig.dsn_from_env()) as c:
            mig.migrate(c, schema=name)
        yield name
    finally:
        admin.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name)))
        admin.close()


@pytest.mark.db
async def test_pg_repo_progresso(schema, tmp_path):
    repo = await PgNewsRepo.connect(mig.dsn_from_env(), schema=schema)
    try:
        assert isinstance(repo, NewsRepo)
        assert await repo.progress_updated_at() is None
        await repo.set_progress(Progress("Frieren", "episode", 5.0, NOW))
        await repo.set_progress(Progress("Frieren", "episode", 6.0, NOW + timedelta(hours=1)))
        await repo.set_progress(Progress("Frieren", "hours", 1.5, NOW))
        got = await repo.progress("Frieren")
        assert [(p.kind, p.value) for p in got] == [("episode", 6.0), ("hours", 1.5)]
        assert await repo.progress_updated_at() == NOW + timedelta(hours=1)
        await repo.set_franchise_pref(FranchisePref("Overlord", dropped=True))
        await repo.set_franchise_pref(FranchisePref("Overlord", weight=0.5, dropped=True))
        assert await repo.franchise_prefs() == [FranchisePref("Overlord", 0.5, True, False)]

        async with httpx.AsyncClient(transport=anilist_transport()) as http:
            rep = await P.update_if_due(
                repo, http, [SourceConfig("AniList", "anilist", URL, 3, options={"username": "u"})],
                {"steam_root": str(steam_root(tmp_path))}, NOW + timedelta(hours=8))
        assert rep is not None and rep.dropped == []  # já estava largado
        assert [(p.kind, p.value) for p in await repo.progress("Mob Psycho 100")] == [("episode", 12.0)]
        assert [p.value for p in await repo.progress("The Witcher 3: Wild Hunt")] == [6.25]
    finally:
        await repo.close()
