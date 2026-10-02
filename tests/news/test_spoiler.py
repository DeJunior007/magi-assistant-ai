from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime, timedelta

import pytest

from magi.common.contracts import FranchisePref, NewsItem, Progress
from magi.news import spoiler as S
from magi.news.spoiler import Display

NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)
SECRET = "Himmel volta"


class MemRepo:
    def __init__(self, progress=(), prefs=()):
        self.prefs = {p.franchise: p for p in prefs}
        self.rows = list(progress)

    async def franchise_prefs(self):
        return list(self.prefs.values())

    async def set_franchise_pref(self, pref):
        self.prefs[pref.franchise] = pref

    async def progress(self, franchise):
        return [p for p in self.rows if p.franchise == franchise]


def item(of="Frieren, ep. 20", *, has=True, size=0.5, franchise="Frieren", safe="Frieren tem episódio novo",
         iid=1):
    return NewsItem(
        title=f"Frieren ep. 20: {SECRET} como demônio", summary=f"No episódio, {SECRET} e Frieren chora.",
        franchise=franchise, kind="episodio", id=iid,
        spoiler={"has": has, "of": of, "safe_title": safe, "size": size},
    )


LINK = "https://anime.example.com/news/frieren-ep-20-himmel-volta-como-demonio"


def ep(work, n):
    return Progress(work, "episode", float(n), NOW)


def no_leak(shown):
    for f in fields(shown):
        value = getattr(shown, f.name)
        texts = value if isinstance(value, tuple) else (value,)
        for t in texts:
            if isinstance(t, str):
                assert "himmel" not in t.lower(), (f.name, t)
                assert "demonio" not in t.lower(), (f.name, t)


@pytest.fixture
def store(tmp_path):
    return S.ReleaseStore(tmp_path / "rel.json")


async def show(repo, it, store, now=NOW):
    return (await S.present(repo, [it], now, links={it.id: [LINK]}, store=store))[0]


async def test_obra_em_andamento_nunca_mostra_spoiler(store):
    repo = MemRepo([ep("Frieren", 12)])
    shown = await show(repo, item(), store)
    assert shown.mode is Display.SAFE
    assert shown.title == shown.subtitle == "Frieren tem episódio novo"
    assert shown.summary == ""
    assert shown.links == ("https://anime.example.com/",)
    no_leak(shown)
    big = await show(repo, item(size=0.9), store)
    assert big.mode is Display.HIDDEN and big.title == "Tem notícia de Frieren com spoiler"
    assert big.links == ()
    no_leak(big)
    # manchete "segura" que repete a original não serve
    bad = await show(repo, item(safe=f"Frieren ep. 20: {SECRET} como demônio"), store)
    assert bad.mode is Display.HIDDEN
    no_leak(bad)


async def test_sem_spoiler_mostra_original(store):
    shown = await show(MemRepo(), item(has=False, of=None), store)
    assert shown.mode is Display.ORIGINAL and shown.links == (LINK,)


async def test_obra_concluida_ou_trecho_visto(store):
    repo = MemRepo([ep("Frieren", 28)])  # AniList COMPLETED grava o total de episódios
    shown = await show(repo, item(), store)
    assert shown.mode is Display.ORIGINAL and SECRET in shown.title
    # capítulo de mangá não se compara com episódio: na dúvida, não libera
    manga = await show(repo, item(of="Frieren, mangá cap. 20"), store)
    assert manga.mode is Display.SAFE
    no_leak(manga)


async def test_obra_largada_nao_acompanhada(store):
    repo = MemRepo(prefs=[FranchisePref("Frieren", dropped=True)])
    assert (await show(repo, item(), store)).mode is Display.ORIGINAL


async def test_progresso_desconhecido_esconde(store):
    shown = await show(MemRepo(), item(size=0.1), store)
    assert shown.mode is Display.HIDDEN
    no_leak(shown)
    # jogo só com horas: horas não dizem onde está o spoiler
    game = await show(MemRepo([Progress("Frieren", "hours", 300.0, NOW)]), item(of="Frieren, final"), store)
    assert game.mode is Display.SAFE


async def test_of_ambiguo_ou_nao_classificado_esconde(store):
    repo = MemRepo([ep("Frieren", 12)])
    assert (await show(repo, item(of=None), store)).mode is Display.HIDDEN
    raw = NewsItem(title=f"{SECRET}!", franchise="Frieren", id=1)
    shown = await show(repo, raw, store)
    assert shown.mode is Display.HIDDEN
    no_leak(shown)


async def test_liberacao_por_voz_e_expiracao(store):
    repo = MemRepo([ep("Frieren", 12)])
    work, ttl = S.parse_release("Magui, pode dar spoiler de Frieren por 2 dias.")
    assert (work, ttl) == ("Frieren", timedelta(days=2))
    await S.allow_spoilers(repo, work, NOW, ttl=ttl, store=store)
    assert repo.prefs["Frieren"].spoilers_ok
    assert (await show(repo, item(), store)).mode is Display.ORIGINAL
    # só aquela obra
    other = item(of="One Piece, ep. 1100", franchise="One Piece", iid=2)
    repo.rows.append(ep("One Piece", 1000))
    assert (await show(repo, other, store)).mode is Display.SAFE
    # vence o prazo
    later = NOW + timedelta(days=2, minutes=1)
    expired = await show(repo, item(), store, now=later)
    assert expired.mode is Display.SAFE
    assert not repo.prefs["Frieren"].spoilers_ok
    no_leak(expired)


async def test_liberacao_sem_prazo_e_revogacao(store):
    repo = MemRepo([ep("Frieren", 12)])
    assert S.parse_release("pode dar spoiler do frieren") == ("frieren", None)
    assert S.parse_release("pode dar spoiler de Frieren hoje") == ("Frieren", timedelta(hours=24))
    assert S.parse_release("toca uma música") is None
    await S.allow_spoilers(repo, "frieren", NOW, store=store)
    assert (await show(repo, item(), store, now=NOW + timedelta(days=400))).mode is Display.ORIGINAL
    await S.revoke_spoilers(repo, "Frieren", store=store)
    assert (await show(repo, item(), store)).mode is Display.SAFE


async def test_spoiler_de_obra_relacionada(store):
    it = NewsItem(
        title="Hollow Knight: final de Silksong revela Hornet morta", franchise="Hollow Knight", id=3,
        spoiler={"has": True, "of": "Hollow Knight Silksong, final", "safe_title": "Novidade de Silksong",
                 "size": 0.5},
    )
    repo = MemRepo([Progress("Hollow Knight", "hours", 80.0, NOW)],
                   prefs=[FranchisePref("Hollow Knight", spoilers_ok=True)])
    shown = await show(repo, it, store)
    # liberar Hollow Knight não libera Silksong; sem progresso de Silksong → esconde
    assert shown.mode is Display.HIDDEN
    assert shown.title == "Tem notícia de Hollow Knight com spoiler"
    assert "morta" not in shown.title + shown.summary + shown.subtitle
    repo.prefs["Hollow Knight Silksong"] = FranchisePref("Hollow Knight Silksong", spoilers_ok=True)
    assert (await show(repo, it, store)).mode is Display.ORIGINAL


def test_spoiler_work():
    assert S.spoiler_work(item(of="One Piece, mangá cap. 1120")) == "One Piece"
    assert S.spoiler_work(item(of="Silksong final")) == "Silksong"
    assert S.spoiler_work(item(of="Frieren episódio 3")) == "Frieren"
    assert S.spoiler_work(item(of="  ")) is None


class IndexRepo(MemRepo):
    """Repositório com ``all_progress`` (casamento tolerante de nomes)."""

    async def all_progress(self):
        return list(self.rows)


async def test_progresso_casa_nome_longo_da_anilist(store):
    repo = IndexRepo([ep("Frieren: Beyond Journey's End", 10)])
    shown = await show(repo, item(size=0.1), store)
    assert shown.mode is Display.SAFE
    no_leak(shown)
    repo.rows = [ep("Frieren: Beyond Journey's End", 28)]
    assert (await show(repo, item(), store)).mode is Display.ORIGINAL
    # sem all_progress, só nome exato (comportamento antigo)
    assert (await show(MemRepo(repo.rows), item(), store)).mode is Display.HIDDEN


async def test_progresso_nao_casa_obra_irma_nem_ambiguo(store):
    it = NewsItem(
        title="Hollow Knight: segredo do final revelado", franchise="Hollow Knight", id=4,
        spoiler={"has": True, "of": "Hollow Knight, final", "safe_title": "Novidade de Hollow Knight",
                 "size": 0.3},
    )
    # jogo da Steam com subtítulo é outro jogo
    sibling = IndexRepo([Progress("Hollow Knight: Silksong", "hours", 40.0, NOW)])
    assert (await show(sibling, it, store)).mode is Display.HIDDEN
    # anime: continuação (temporada/parte) não casa; dois candidatos = ambíguo → esconde
    sequel = IndexRepo([ep("Frieren Season 2", 3)])
    assert (await show(sequel, item(size=0.1), store)).mode is Display.HIDDEN
    two = IndexRepo([ep("Frieren: Beyond Journey's End", 28), ep("Frieren: Mahou Tsukai", 28)])
    assert (await show(two, item(), store)).mode is Display.HIDDEN
    assert S.match_progress("Frieren", {}) == ()
