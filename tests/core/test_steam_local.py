from __future__ import annotations

import struct
from types import SimpleNamespace

from magi.agent.prompt import GameContext, game_section
from magi.agent.tools.steam import SteamGameTool, describe
from magi.core.steam_local import SteamLocal, parse_binary_vdf

ACCOUNT = "123"
APPID = 1091500
NOW = 1_800_000_000.0


def bvdf(d: dict) -> bytes:
    """Escreve KeyValues binário (o inverso do leitor) para montar arquivos de teste."""
    out = b""
    for k, v in d.items():
        key = k.encode() + b"\0"
        if isinstance(v, dict):
            out += b"\x00" + key + bvdf(v)
        elif isinstance(v, str):
            out += b"\x01" + key + v.encode() + b"\0"
        else:
            out += b"\x02" + key + struct.pack("<i", v)
    return out + b"\x08"


def make_steam(tmp_path):
    root = tmp_path / "Steam"
    (root / "steamapps").mkdir(parents=True)
    (root / "steamapps" / "libraryfolders.vdf").write_text(
        f'"libraryfolders" {{ "0" {{ "path" "{root}" }} }}')
    (root / "steamapps" / f"appmanifest_{APPID}.acf").write_text(
        f'"AppState" {{ "appid" "{APPID}" "name" "Cyberpunk 2077" "installdir" "Cyberpunk 2077" }}')
    cfg = root / "userdata" / ACCOUNT / "config"
    cfg.mkdir(parents=True)
    (cfg / "localconfig.vdf").write_text(
        '"UserLocalConfigStore" { "Software" { "Valve" { "Steam" { "apps" { '
        f'"{APPID}" {{ "LastPlayed" "{int(NOW) - 3600}" "Playtime" "8875" }} }} }} }} }} }}')
    stats = root / "appcache" / "stats"
    stats.mkdir(parents=True)

    def ach(api, pt, desc, hidden=0):
        return {"name": api, "display": {"name": {"english": api, "brazilian": pt},
                                         "desc": {"english": "x", "brazilian": desc}}, "hidden": hidden}

    schema = {str(APPID): {"stats": {"1": {"bits": {
        "0": ach("TheFool", "O Louco", "Siga uma vida mercenária."),
        "1": ach("TheLovers", "Os Enamorados", "Termine o assalto."),
        "2": ach("Secret", "Segredo", "Final escondido.", hidden=1),
        "3": ach("Legend", "Lenda", "Chegue ao nível 50."),
    }}}}}
    (stats / f"UserGameStatsSchema_{APPID}.bin").write_bytes(bvdf(schema))
    user = {"cache": {"1": {"data": 0b0011, "AchievementTimes": {"0": int(NOW) - 5 * 86400,
                                                                 "1": int(NOW) - 3 * 86400}}}}
    (stats / f"UserGameStats_{ACCOUNT}_{APPID}.bin").write_bytes(bvdf(user))
    return SteamLocal(root)


def test_le_vdf_binario():
    data = bvdf({"a": {"b": "c", "n": -5}})
    assert parse_binary_vdf(data) == {"a": {"b": "c", "n": -5}}


def test_horas_e_conquistas_do_disco(tmp_path):
    steam = make_steam(tmp_path)
    st = steam.stats(APPID, "Cyberpunk 2077")
    assert st.minutes == 8875
    assert [a.name for a in st.unlocked] == ["Os Enamorados", "O Louco"]  # mais recente primeiro
    assert {a.name for a in st.locked} == {"Segredo", "Lenda"}
    assert st.summary(NOW) == "148 h no total; conquistas 2/4, a última há 3 dias (Os Enamorados)"
    assert steam.find("cyberpunk") == (APPID, "Cyberpunk 2077")
    assert steam.idle_minutes(APPID, NOW) == 3 * 24 * 60


def test_sem_dados_nao_quebra(tmp_path):
    steam = SteamLocal(tmp_path / "nada")
    assert steam.stats(42).achievements == [] and steam.stats(42).minutes is None
    assert steam.idle_minutes(42) is None
    assert steam.find("qualquer") is None


def test_descricao_sem_spoiler_das_secretas(tmp_path):
    speech, full = describe(make_steam(tmp_path).stats(APPID, "Cyberpunk 2077"), NOW)
    assert speech == "Cyberpunk 2077: 148 horas e 2 de 4 conquistas. A última foi Os Enamorados, há 3 dias."
    assert "Lenda: Chegue ao nível 50." in full
    assert "Segredo" not in full and "1 secretas ainda bloqueadas" in full


async def test_ferramenta_usa_o_jogo_aberto(tmp_path):
    steam = make_steam(tmp_path)
    running = SimpleNamespace(appid=APPID, name="Cyberpunk 2077")
    tool = SteamGameTool(steam, lambda: running)
    res = await tool.run({}, ctx=None)
    assert res.ok and res.speech.startswith("Cyberpunk 2077: 148 horas")
    res = await SteamGameTool(steam, lambda: None).run({"game": "Hollow Knight"}, ctx=None)
    assert not res.ok and "Hollow Knight" in res.speech


def test_linha_da_steam_no_prompt():
    text = game_section(GameContext(name="Cyberpunk 2077", session_minutes=30,
                                    steam="148 h no total; conquistas 2/4"))
    assert "Na Steam: 148 h no total; conquistas 2/4." in text
