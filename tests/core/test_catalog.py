"""Catálogo de jogos (tarefa 1.7): manifests falsos em diretório temporário."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from magi.common.contracts import GameCatalog, VocabTerm
from magi.core.catalog import (
    JsonAliasStore,
    MemoryAliasStore,
    SteamCatalog,
    library_dirs,
    normalize,
    parse_vdf,
)

MAIN_GAMES = {
    588650: ("Dead Cells", "Dead Cells"),
    292030: ("The Witcher 3: Wild Hunt", "The Witcher 3"),
    367520: ("Hollow Knight", "Hollow Knight"),
    1145350: ("Hades II", "Hades II"),
    620: ("Portal 2", "Portal 2"),
    # ferramentas: devem sumir
    228980: ("Steamworks Common Redistributables", "Steamworks Shared"),
    1493710: ("Proton Experimental", "Proton - Experimental"),
    1628350: ("Steam Linux Runtime 3.0 (sniper)", "SteamLinuxRuntime_sniper"),
    2805730: ("Proton 9.0", "Proton 9.0"),
}
EXTRA_GAMES = {
    1091500: ("Cyberpunk 2077", "Cyberpunk 2077"),
    1086940: ("Baldur's Gate 3", "Baldurs Gate 3"),
    1238840: ("Dead Space", "Dead Space"),
    374320: ("DARK SOULS™ III", "DARK SOULS III"),
}


def _manifest(appid: int, name: str, installdir: str) -> str:
    return (
        '"AppState"\n{\n'
        f'\t"appid"\t\t"{appid}"\n\t"universe"\t\t"1"\n\t"name"\t\t"{name}"\n'
        '\t"StateFlags"\t\t"4"\n'
        f'\t"installdir"\t\t"{installdir}"\n'
        '\t"InstalledDepots"\n\t{\n\t\t"1"\n\t\t{\n\t\t\t"manifest"\t\t"123"\n\t\t}\n\t}\n'
        "}\n"
    )


def _write_lib(steamapps: Path, games: dict[int, tuple[str, str]]) -> None:
    steamapps.mkdir(parents=True, exist_ok=True)
    for appid, (name, installdir) in games.items():
        (steamapps / f"appmanifest_{appid}.acf").write_text(_manifest(appid, name, installdir))


@pytest.fixture
def steam(tmp_path: Path) -> Path:
    root = tmp_path / "Steam"
    extra = tmp_path / "games" / "SteamLibrary"
    _write_lib(root / "steamapps", MAIN_GAMES)
    _write_lib(extra / "steamapps", EXTRA_GAMES)
    (root / "steamapps" / "appmanifest_999.acf").write_text("lixo sem chaves")
    (root / "steamapps" / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n'
        f'\t"0"\n\t{{\n\t\t"path"\t\t"{root}"\n\t\t"apps"\n\t\t{{\n\t\t\t"620"\t\t"1"\n\t\t}}\n\t}}\n'
        f'\t"1"\n\t{{\n\t\t"path"\t\t"{extra}"\n\t}}\n'
        f'\t"2"\n\t{{\n\t\t"path"\t\t"{tmp_path / "desmontado"}"\n\t}}\n'
        "}\n"
    )
    return root


@pytest.fixture
def catalog(steam: Path) -> SteamCatalog:
    return SteamCatalog(steam, aliases=MemoryAliasStore())


def _top(catalog: SteamCatalog, text: str) -> tuple[str, float]:
    results = catalog.find(text)
    assert results, text
    game, score = results[0]
    return game.name, score


def test_implementa_protocolo(catalog: SteamCatalog) -> None:
    assert isinstance(catalog, GameCatalog)


def test_parse_vdf_aninhado_e_escapes() -> None:
    data = parse_vdf('"A"\n{\n "k" "v \\"x\\""\n "B" { "c" "1" }\n}')
    assert data == {"A": {"k": 'v "x"', "B": {"c": "1"}}}


def test_bibliotecas_sem_repetir_raiz(steam: Path, tmp_path: Path) -> None:
    dirs = library_dirs(steam)
    assert dirs[0] == steam / "steamapps"
    assert tmp_path / "games" / "SteamLibrary" / "steamapps" in dirs
    assert len(dirs) == 3  # raiz (listada 2×) + extra + desmontada


def test_le_todas_as_bibliotecas_e_ignora_ferramentas(catalog: SteamCatalog) -> None:
    names = {g.name for g in catalog.all()}
    assert names == {n for n, _ in MAIN_GAMES.values() if not n.startswith(("Proton", "Steam"))} | {
        n for n, _ in EXTRA_GAMES.values()
    }
    game = catalog.get(292030)
    assert game is not None and game.install_dir == "The Witcher 3"
    assert catalog.get(228980) is None and catalog.get(999) is None


def test_sem_steam_catalogo_vazio(tmp_path: Path) -> None:
    cat = SteamCatalog(tmp_path / "nada", aliases=MemoryAliasStore())
    assert cat.all() == [] and cat.find("dead cells") == []


def test_normalize_numeros_por_extenso_e_romanos() -> None:
    assert normalize("The Witcher três") == "the witcher 3"
    assert normalize("DARK SOULS™ III") == "dark souls 3"
    assert normalize("Baldur's Gate Três") == "baldurs gate 3"
    assert normalize("Hades dois") == normalize("Hades II") == "hades 2"


@pytest.mark.parametrize(
    ("spoken", "expected"),
    [
        ("dedi cels", "Dead Cells"),
        ("Dead Cells", "Dead Cells"),
        ("the witcher três", "The Witcher 3: Wild Hunt"),
        ("witcher 3", "The Witcher 3: Wild Hunt"),
        ("ólou naite", "Hollow Knight"),
        ("ciberpunk", "Cyberpunk 2077"),
        ("baldurs gate três", "Baldur's Gate 3"),
        ("dark souls três", "DARK SOULS™ III"),
        ("hades dois", "Hades II"),
        ("portal dois", "Portal 2"),
    ],
)
def test_busca_falada(catalog: SteamCatalog, spoken: str, expected: str) -> None:
    name, score = _top(catalog, spoken)
    assert name == expected
    assert score >= 88, (spoken, score)  # limiar de execução do roteador (§4.2)


def test_dedi_cels_nao_confunde_com_dead_space(catalog: SteamCatalog) -> None:
    (first, s1), (second, s2) = catalog.find("dedi cels", limit=2)
    assert first.name == "Dead Cells" and second.name == "Dead Space"
    assert s1 - s2 >= 15


def test_numero_que_o_nome_nao_tem_fica_na_duvida(tmp_path: Path) -> None:
    root = tmp_path / "Steam"
    _write_lib(root / "steamapps", {400: ("Portal", "Portal")})
    cat = SteamCatalog(root, aliases=MemoryAliasStore())
    _, score = _top(cat, "portal dois")
    assert score < 88


def test_find_ordenado_e_limite(catalog: SteamCatalog) -> None:
    results = catalog.find("dead", limit=2)
    assert len(results) == 2
    assert results[0][1] >= results[1][1]
    assert catalog.find("", limit=3) == [] and catalog.find("dead", limit=0) == []


class _FakeVocab:
    def __init__(self) -> None:
        self.terms: list[VocabTerm] = []

    async def all(self, kind: str | None = None) -> list[VocabTerm]:
        return self.terms

    async def upsert(self, term: VocabTerm) -> None:
        self.terms.append(term)


async def test_apelido_aprendido(steam: Path) -> None:
    store, vocab = MemoryAliasStore(), _FakeVocab()
    cat = SteamCatalog(steam, aliases=store, vocab=vocab)
    assert _top(cat, "jogo do bruxo")[1] < 72
    await cat.add_alias(292030, "jogo do bruxo")
    await cat.add_alias(292030, "Jogo do  Bruxo")  # repetido (normalizado): ignora
    await cat.add_alias(123456, "inexistente")  # appid fora do catálogo: ignora
    assert _top(cat, "jogo do bruxo") == ("The Witcher 3: Wild Hunt", 100.0)
    game = cat.get(292030)
    assert game is not None and game.aliases == ("jogo do bruxo",)
    assert store.load() == {292030: ["jogo do bruxo"]}
    assert vocab.terms == [VocabTerm(term="jogo do bruxo", kind="nickname")]


async def test_apelidos_em_json_sobrevivem_a_recarga(steam: Path, tmp_path: Path) -> None:
    path = tmp_path / "data" / "aliases.json"
    cat = SteamCatalog(steam, aliases=JsonAliasStore(path))
    await cat.add_alias(367520, "rolou naite")
    assert json.loads(path.read_text()) == {"367520": ["rolou naite"]}
    reloaded = SteamCatalog(steam, aliases=JsonAliasStore(path))
    assert _top(reloaded, "rolou naite") == ("Hollow Knight", 100.0)


def test_json_corrompido_nao_quebra(steam: Path, tmp_path: Path) -> None:
    path = tmp_path / "aliases.json"
    path.write_text("{nao é json")
    cat = SteamCatalog(steam, aliases=JsonAliasStore(path))
    assert len(cat.all()) == 9
