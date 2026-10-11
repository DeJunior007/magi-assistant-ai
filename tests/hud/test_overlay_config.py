"""O0.1 — contratos do overlay: Config (CA-O1), canto (CA-O4) e decidir_lugar (CA-O9)."""

import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QRect
from wired import overlay
from wired.overlay import Config, Lugar, canto_para_posicao, decidir_lugar

# --- CA-O1 ---------------------------------------------------------------------------------------


def test_ausente_da_os_padroes_das_decisoes(tmp_path):
    cfg = Config.ler(tmp_path / "nao-existe.toml")
    assert cfg == Config()
    assert (cfg.canto, cfg.margem) == ("sup_dir", 24)  # D6
    assert cfg.com_hud == "esconde"  # D2
    assert cfg.em_jogo == "oposto" and cfg.tela_jogo is None  # D3


def test_caminho_padrao_e_lido_na_hora(tmp_path):
    assert overlay.CONFIG_FILE.is_relative_to(tmp_path)  # conftest isola
    overlay.CONFIG_FILE.parent.mkdir(parents=True)
    overlay.CONFIG_FILE.write_text("[overlay]\ntamanho = 300\n", encoding="utf-8")
    assert Config.ler().tamanho == 300


def test_invalido_da_os_padroes(tmp_path):
    f = tmp_path / "o.toml"
    f.write_text("isto não é = = toml [", encoding="utf-8")
    assert Config.ler(f) == Config()
    f.write_bytes(b"\xff\xfe")
    assert Config.ler(f) == Config()


def test_faixa_e_valores_ruins(tmp_path):
    f = tmp_path / "o.toml"
    f.write_text(
        '[overlay]\ntamanho = 9999\nmargem = -5\ncanto = "meio"\nem_jogo = "voa"\n'
        'com_hud = "esconde"\nfundo = "sim"\nrenderer = "gl"\nligado = false\ntela = ""\n',
        encoding="utf-8",
    )
    cfg = Config.ler(f)
    assert cfg.tamanho == 480 and cfg.margem == 0
    assert cfg.canto == "sup_dir" and cfg.em_jogo == "oposto" and cfg.fundo is False
    assert cfg.renderer == "gl" and cfg.ligado is False and cfg.tela is None
    f.write_text("[overlay]\ntamanho = 10\n", encoding="utf-8")
    assert Config.ler(f).tamanho == 120
    f.write_text("[overlay]\ntamanho = true\n", encoding="utf-8")
    assert Config.ler(f).tamanho == 220


def test_chave_desconhecida_ignorada(tmp_path):
    f = tmp_path / "o.toml"
    f.write_text('[overlay]\nbalao = true\ncanto = "inf_esq"\n', encoding="utf-8")
    cfg = Config.ler(f)
    assert cfg.canto == "inf_esq" and not hasattr(cfg, "balao")


def test_gravar_e_ler_de_volta_atomico(tmp_path):
    f = tmp_path / "sub" / "o.toml"
    cfg = Config(tamanho=260, tela='DP-"1"', tela_jogo="HDMI-A-1", em_jogo="fica", x=10, y=-3)
    cfg.gravar(f)
    assert Config.ler(f) == cfg
    assert not list(f.parent.glob("*.tmp"))
    assert "x = 10" in f.read_text(encoding="utf-8")
    Config().gravar(f)
    assert "tela" not in f.read_text(encoding="utf-8")


# --- CA-O4 ---------------------------------------------------------------------------------------

TELA = QRect(1920, 0, 2560, 1440)


@pytest.mark.parametrize(
    "canto, esperado",
    [
        ("sup_esq", QPoint(1920 + 24, 24)),
        ("sup_dir", QPoint(1920 + 2560 - 24 - 220, 24)),
        ("inf_esq", QPoint(1920 + 24, 1440 - 24 - 253)),
        ("inf_dir", QPoint(1920 + 2560 - 24 - 220, 1440 - 24 - 253)),
    ],
)
def test_canto_para_posicao(canto, esperado):
    assert canto_para_posicao(Config(canto=canto), TELA) == esperado


def test_canto_padrao_superior_direito_margem_24():
    p = canto_para_posicao(Config(), QRect(0, 0, 1920, 1080))
    assert p == QPoint(1920 - 24 - 220, 24)
    assert canto_para_posicao(Config(margem=0, tamanho=200), QRect(0, 0, 800, 600)) == QPoint(600, 0)


# --- CA-O9 ---------------------------------------------------------------------------------------

DUAS = ("DP-1", "HDMI-A-1")


def test_normal_vai_para_a_tela_configurada_ou_principal():
    assert decidir_lugar(Config(), DUAS, "DP-1", False, False) == Lugar(True, "DP-1", "normal")
    cfg = Config(tela="HDMI-A-1")
    assert decidir_lugar(cfg, DUAS, "DP-1", False, False).tela == "HDMI-A-1"
    cfg = Config(tela="desligada")
    assert decidir_lugar(cfg, DUAS, "DP-1", False, False).tela == "DP-1"


def test_hud_aberto_esconde_e_ganha_do_jogo():
    assert decidir_lugar(Config(), DUAS, "DP-1", False, True) == Lugar(False, motivo="hud")
    assert decidir_lugar(Config(), DUAS, "DP-1", True, True).motivo == "hud"
    cfg = Config(com_hud="independente")
    assert decidir_lugar(cfg, DUAS, "DP-1", False, True) == Lugar(True, "DP-1", "normal")


def test_jogo_vai_para_o_monitor_oposto():
    assert decidir_lugar(Config(), DUAS, "DP-1", True, False) == Lugar(True, "HDMI-A-1", "jogo_oposto")
    cfg = Config(tela_jogo="HDMI-A-1")
    assert decidir_lugar(cfg, DUAS, "DP-1", True, False).tela == "DP-1"
    tres = ("DP-1", "HDMI-A-1", "DP-2")
    cfg = Config(tela="DP-2")
    assert decidir_lugar(cfg, tres, "DP-1", True, False).tela == "DP-2"


def test_jogo_com_um_monitor_some_e_volta():
    cfg = Config()
    assert decidir_lugar(cfg, ("DP-1",), "DP-1", True, False) == Lugar(False, motivo="jogo")
    assert decidir_lugar(cfg, ("DP-1",), "DP-1", False, False) == Lugar(True, "DP-1", "normal")


def test_em_jogo_esconde_e_fica():
    assert decidir_lugar(Config(em_jogo="esconde"), DUAS, "DP-1", True, False).visivel is False
    assert decidir_lugar(Config(em_jogo="fica"), DUAS, "DP-1", True, False) == Lugar(True, "DP-1", "normal")


# --- importa sem QApplication -------------------------------------------------------------------


def test_modulo_importa_sem_qapplication():
    hud = Path(__file__).resolve().parents[2] / "hud"
    codigo = (
        f"import sys; sys.path.insert(0, {str(hud)!r})\n"
        "import wired.overlay as o\n"
        "from PySide6.QtCore import QCoreApplication\n"
        "assert QCoreApplication.instance() is None\n"
        "assert 'PySide6.QtWidgets' not in sys.modules\n"
        "print(o.Config().canto)\n"
    )
    r = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "sup_dir"
