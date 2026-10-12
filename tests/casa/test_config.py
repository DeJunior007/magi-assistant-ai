"""CA-Y50: ``casa.toml`` e ``apps.yaml`` (+ override por ``id``); caminhos lidos na hora."""

from __future__ import annotations

import os
import stat

import pytest

from magi.casa import apps, config
from magi.casa.config import CasaConfigErro
from magi.casa.driver import Cap, Capacidades
from magi.elo.mensagens import AppInfo

EXEMPLO = """
[casa]
escuta = "127.0.0.1"
porta = 10760
ayanami = ""
padrao = "sala"
broadcast = "192.168.0.255"
descoberta_min = 10

[[tv]]
id = "sala"
nome = "TV da sala"
apelidos = ["sala", "televisão da sala", "tv grande"]
driver = "samsung"
chave = "samsung:uuid:abc"
ip = "192.168.0.40"
mac = "A4:30:7A:00:00:01"
ano = 2021
zerar_passos = 50
entradas = { console = "hdmi2", pc = "hdmi1" }
adb = false

[[tv]]
id = "quarto"
nome = "TV do quarto"
apelidos = ["quarto", "tcl"]
driver = "androidtv"
chave = "androidtv:9c:00"
ip = "192.168.0.52"
mac = "9c:00:00:00:00:02"
"""


def _grava(texto: str):
    p = config.caminho_casa()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(texto, encoding="utf-8")
    return p


def test_caminhos_lidos_na_hora_da_chamada(casa_isolada, monkeypatch, tmp_path):
    assert config.caminho_casa() == casa_isolada / ".config" / "magi" / "casa.toml"
    assert config.dir_pareamento() == casa_isolada / ".local" / "share" / "magi" / "casa"
    assert config.caminho_estado() == casa_isolada / ".local/state/magi/casa-estado.json"
    assert config.caminho_token_local().name == "casa.token"
    assert config.caminho_token_ayanami().name == "ayanami-casa.token"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "outro"))
    assert config.caminho_apps_override() == tmp_path / "outro" / "magi" / "casa-apps.yaml"
    assert config.caminho_casa(tmp_path / "x.toml") == tmp_path / "x.toml"


def test_ausente_sobe_sem_tvs():
    cfg = config.ler()
    assert cfg.tvs == () and cfg.padrao == ""
    assert (cfg.escuta, cfg.porta) == ("127.0.0.1", 10760)


def test_exemplo_da_spec_le_e_valida():
    _grava(EXEMPLO)
    cfg = config.ler()
    assert [t.id for t in cfg.tvs] == ["sala", "quarto"] and cfg.padrao == "sala"
    sala = cfg.tv("sala")
    assert sala is not None and sala.ano == 2021 and sala.mac == "a4:30:7a:00:00:01"
    assert dict(sala.entradas) == {"console": "hdmi2", "pc": "hdmi1"}
    assert cfg.tv("quarto").zerar_passos == 50 and cfg.tv("quarto").ano is None
    info = config.tv_info(sala, Capacidades(caps=frozenset({Cap.KEY}), apps=("netflix",)), True)
    assert info.padrao and info.caps == ("key",) and info.apps == ("netflix",)


def test_apelido_duplicado_normalizado_erro_claro():
    _grava(EXEMPLO.replace('apelidos = ["quarto", "tcl"]', 'apelidos = ["quarto", "Televisao da Sala"]'))
    with pytest.raises(CasaConfigErro) as e:
        config.ler()
    msg = str(e.value)
    assert "televisao da sala" in msg and "'sala'" in msg and "'quarto'" in msg


def test_driver_desconhecido_ignora_so_aquela_tv(log_casa):
    _grava(EXEMPLO.replace('driver = "androidtv"', 'driver = "lg"'))
    cfg = config.ler()
    assert [t.id for t in cfg.tvs] == ["sala"]
    assert [t.id for t in cfg.ignoradas] == ["quarto"]
    linha = next(x for x in log_casa.linhas() if x["evento"] == "tv_ignorada")
    assert linha["tv"] == "quarto" and linha["driver"] == "lg" and linha["nivel"] == "WARNING"


def test_padrao_em_tv_ignorada_fica_vazio():
    _grava(EXEMPLO.replace('driver = "samsung"', 'driver = "philips"'))
    cfg = config.ler()
    assert cfg.padrao == "" and [t.id for t in cfg.tvs] == ["quarto"]


@pytest.mark.parametrize(
    ("troca", "trecho"),
    [
        (('padrao = "sala"', 'padrao = "cozinha"'), "cozinha"),
        (('escuta = "127.0.0.1"', 'escuta = "0.0.0.0"'), "0.0.0.0"),
        (("porta = 10760", "porta = 70000"), "70000"),
        (('id = "quarto"', 'id = "sala"'), "repetido"),
        (('id = "quarto"', 'id = "Quarto!"'), "[a-z0-9_-]"),
        (('pc = "hdmi1"', 'pc = "hdmi9"'), "hdmi9"),
        (('nome = "TV do quarto"\n', ""), "nome"),
        (("[casa]", "[casa"), "TOML inválido"),
    ],
)
def test_erros_claros(troca, trecho):
    _grava(EXEMPLO.replace(*troca, 1))
    with pytest.raises(CasaConfigErro, match=None) as e:
        config.ler()
    assert trecho in str(e.value)


def test_salvar_atomico_e_ida_e_volta(tmp_path):
    p = _grava(EXEMPLO.replace('driver = "androidtv"', 'driver = "lg"'))
    os.chmod(p, 0o600)
    cfg = config.ler()
    config.salvar(cfg)
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert not [x for x in p.parent.iterdir() if x.name.endswith(".tmp")]
    de_novo = config.ler()
    assert de_novo == cfg and [t.id for t in de_novo.ignoradas] == ["quarto"]
    # caminho novo e texto com aspas/acentos
    alvo = tmp_path / "novo" / "casa.toml"
    from dataclasses import replace

    tv = replace(cfg.tvs[0], nome='TV "grande" da sála')
    config.salvar(replace(cfg, tvs=(tv,), ignoradas=()), alvo)
    assert config.ler(alvo).tvs[0].nome == 'TV "grande" da sála'


def test_salvar_recusa_config_invalida(tmp_path):
    from dataclasses import replace

    _grava(EXEMPLO)
    cfg = config.ler()
    with pytest.raises(CasaConfigErro):
        config.salvar(replace(cfg, padrao="garagem"), tmp_path / "c.toml")
    assert not (tmp_path / "c.toml").exists()


# --- apps.yaml -------------------------------------------------------------------------------
def test_catalogo_base():
    cat = apps.carregar()
    assert {"netflix", "youtube", "prime", "disney"} <= set(cat.ids())
    assert cat.para_driver("netflix", "samsung") == "3201907018807"
    assert cat.para_driver("netflix", "androidtv").pacote == "com.netflix.ninja"
    assert cat.para_driver("disney", "samsung") is None  # [S2]: faltou → APP_DESCONHECIDO
    assert cat.resolver("Netiflix").id == "netflix" and cat.resolver("Prime Vídeo").id == "prime"
    assert cat.por_pacote("com.google.android.youtube.tv").id == "youtube"
    assert "disney" not in cat.ids_para("samsung") and "disney" in cat.ids_para("roku")
    assert AppInfo(id="netflix", nome="Netflix", apelidos=("netflix", "netiflix")) in cat.infos()


def test_override_ganha_por_id():
    p = config.caminho_apps_override()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "apps:\n"
        "  - id: disney\n    nome: Disney Plus\n    apelidos: [disney]\n    samsung: '3201901017640'\n"
        "  - id: plex\n    nome: Plex\n    roku: '13535'\n",
        encoding="utf-8",
    )
    cat = apps.carregar()
    assert cat.get("disney").nome == "Disney Plus"
    assert cat.para_driver("disney", "samsung") == "3201901017640"
    assert cat.resolver("disney mais") is None  # a entrada inteira foi trocada
    assert cat.get("plex") is not None and cat.get("netflix") is not None


def test_override_invalido_erro_claro():
    p = config.caminho_apps_override()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("apps:\n  - id: x\n  - id: x\n    nome: X\n", encoding="utf-8")
    with pytest.raises(CasaConfigErro, match="sem 'nome'"):
        apps.carregar()
