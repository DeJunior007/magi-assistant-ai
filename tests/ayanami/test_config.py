"""CA-Y28 (spec §9.2) + segredos (§9.1), relógio falso e despacho do ``ayanami`` (Y0.2)."""

from __future__ import annotations

import ast
import sys
import tomllib
import types
from pathlib import Path

import pytest

from ayanami import cli, config
from ayanami.config import ConfigError
from ayanami.relogio import Relogio, RelogioFalso, RelogioReal

RAIZ = Path(__file__).resolve().parents[2]
EXEMPLO = RAIZ / "deploy" / "ayanami" / "ayanami.example.toml"
ENV_EXEMPLO = RAIZ / "deploy" / "ayanami" / "env.example"


def _dados() -> dict:
    return tomllib.loads(EXEMPLO.read_text(encoding="utf-8"))


def _gravar(tmp_path: Path, texto: str) -> Path:
    p = tmp_path / "ayanami.toml"
    p.write_text(texto, encoding="utf-8")
    return p


# --------------------------------------------------------------------------- CA-Y28


def test_exemplo_valido():
    cfg = config.ler(EXEMPLO)
    assert cfg.geral.url_base.startswith("https://")
    assert cfg.rede.offline_apos_s >= 3 * cfg.rede.batimento_s
    assert cfg.mcp.escopos == ("ler", "tarefas")
    # as duas correções do cabeçalho do tasks.md
    assert cfg.nuvem.stt_modelo == "gpt-transcribe"
    from magi.memory.migrate import DEFAULT_NEWS_DIM

    assert cfg.noticias.dim == DEFAULT_NEWS_DIM
    with pytest.raises(AttributeError):
        cfg.rede.batimento_s = 5  # type: ignore[misc]  # frozen


def test_stt_modelo_igual_ao_do_pc():
    pc = tomllib.loads((RAIZ / "config.example.toml").read_text(encoding="utf-8"))
    assert config.ler(EXEMPLO).nuvem.stt_modelo == pc["tasks"]["stt"]["model"]


def test_minimo_so_url_base_usa_padroes(tmp_path):
    cfg = config.ler(_gravar(tmp_path, '[geral]\nurl_base = "https://x.exemplo"\n'))
    assert cfg == config.ler(EXEMPLO).__class__(geral=cfg.geral)
    assert cfg.noticias.dim == 768 and cfg.budget.teto_nuvem_usd == 2.0


@pytest.mark.parametrize(
    ("mexer", "caminho"),
    [
        (lambda d: d["rede"].__setitem__("batimento", 10), "rede.batimento"),
        (lambda d: d["budget"].update(teto_nuvem_usd=6.0), "budget.teto_nuvem_usd"),
        (lambda d: d["rede"].update(batimento_s=20, offline_apos_s=59), "rede.offline_apos_s"),
        (lambda d: d["mcp"].update(escopos=["ler", "admin"]), "mcp.escopos"),
        (lambda d: d["geral"].update(url_base="http://ayanami.exemplo.ts.net"), "geral.url_base"),
    ],
    ids=["chave-desconhecida", "teto-nuvem-maior", "offline-curto", "escopo-invalido", "http"],
)
def test_ca_y28_erros_com_caminho(mexer, caminho):
    d = _dados()
    mexer(d)
    with pytest.raises(ConfigError) as e:
        config.de_dict(d)
    assert e.value.caminho == caminho
    assert str(e.value).startswith(caminho + ":")


@pytest.mark.parametrize(
    ("secao", "chave", "valor", "caminho"),
    [
        ("rede", "batimento_s", "10", "rede.batimento_s"),  # tipo errado
        ("rede", "batimento_s", True, "rede.batimento_s"),  # bool não é int
        ("rede", "longpoll_s", 60, "rede.longpoll_s"),  # faixa
        ("fila", "lenta_concorrencia", 3, "fila.lenta_concorrencia"),
        ("nuvem", "contexto_turnos", 51, "nuvem.contexto_turnos"),
        ("push", "silencio_padrao", "23h-7h", "push.silencio_padrao"),
        ("geral", "fuso", "Marte/Olympus", "geral.fuso"),
        ("budget", "teto_geral_usd", -1, "budget.teto_geral_usd"),
    ],
)
def test_tipos_e_faixas(secao, chave, valor, caminho):
    d = _dados()
    d[secao][chave] = valor
    with pytest.raises(ConfigError) as e:
        config.de_dict(d)
    assert e.value.caminho == caminho


def test_secao_desconhecida_e_url_ausente():
    d = _dados()
    d["extra"] = {}
    with pytest.raises(ConfigError) as e:
        config.de_dict(d)
    assert e.value.caminho == "extra"
    d = _dados()
    del d["geral"]["url_base"]
    with pytest.raises(ConfigError) as e:
        config.de_dict(d)
    assert e.value.caminho == "geral.url_base"


def test_noticias_aceita_chaves_do_news_do_pc():
    d = _dados()
    d["noticias"].update(fontes=["a", "b"], timeout_s=10, embedder={"provider": "x"})
    cfg = config.de_dict(d)
    assert cfg.noticias.fontes == ("a", "b") and cfg.noticias.timeout_s == 10.0


def test_arquivo_ausente_e_toml_quebrado(tmp_path):
    with pytest.raises(ConfigError):
        config.ler(tmp_path / "nao-existe.toml")
    with pytest.raises(ConfigError):
        config.ler(_gravar(tmp_path, "[geral\n"))


# --------------------------------------------------------------------------- segredos


def test_segredos_faltando_so_nomes(tmp_path):
    cfg = config.ler(EXEMPLO)
    env_arq = tmp_path / ".env"
    env_arq.write_text('POSTGRES_PASSWORD="valor-falso-1"\n# B2_BUCKET=comentado\nB2_BUCKET=\n')
    s = config.ler_segredos(cfg, arquivo=env_arq, env={"GEMINI_API_KEY": "valor-falso-2", "OUTRA": "x"})
    assert s["POSTGRES_PASSWORD"] == "valor-falso-1"
    assert "OUTRA" not in s  # só por nome
    assert "B2_BUCKET" in s.faltando and "POSTGRES_PASSWORD" not in s.faltando
    assert "valor-falso" not in repr(s) and "valor-falso" not in str(s)


def test_segredos_por_fase():
    d = _dados()
    d["backup"]["ligado"] = False
    d["budget"]["teto_nuvem_usd"] = 0.0
    cfg = config.de_dict(d)
    s = config.ler_segredos(cfg, env={})
    assert "B2_BUCKET" not in s.faltando and "OPENAI_API_KEY" not in s.faltando
    assert "POSTGRES_PASSWORD" in s.faltando


def test_env_example_tem_todos_os_nomes():
    nomes = {
        linha.split("=", 1)[0]
        for linha in ENV_EXEMPLO.read_text().splitlines()
        if linha and not linha.startswith("#")
    }
    # NTFY_BASE_URL só é lido pelo compose (serviço ntfy, M1.6), não pela Ayanami
    assert nomes - {"NTFY_BASE_URL"} == set(config.NOMES_SEGREDOS)


# --------------------------------------------------------------------------- relógio


async def test_relogio_falso_nao_dorme():
    r = RelogioFalso()
    assert isinstance(r, Relogio) and isinstance(RelogioReal(), Relogio)
    t0, m0 = r.agora(), r.monotonico()
    await r.dormir(30)
    assert (r.agora() - t0).total_seconds() == 30 and r.monotonico() - m0 == 30
    assert r.dormidas == [30]


# --------------------------------------------------------------------------- cli


def test_help_lista_subcomandos(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--help"])
    assert e.value.code == 0
    saida = capsys.readouterr().out
    for nome in ("migrar", "worker", "batimento", "voz", "dispositivo", "backup", "push"):
        assert nome in saida


def test_modulo_ausente_diz_o_dono(monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "SUBCOMANDOS", (cli.Sub("migrar", "ayanami._nao_existe_xyz", "cli", "Y9.9", "x"),)
    )
    assert cli.main(["migrar"]) == 2
    assert "dono: Y9.9" in capsys.readouterr().err


def test_despacha_args_para_o_dono(monkeypatch):
    recebidos: list[list[str]] = []
    falso = types.ModuleType("ayanami._falso_dono")
    falso.cli_batimento = lambda args: recebidos.append(args) or 7  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ayanami._falso_dono", falso)
    monkeypatch.setattr(
        cli, "SUBCOMANDOS", (cli.Sub("batimento", "ayanami._falso_dono", "cli_batimento", "Y3.1", "x"),)
    )
    assert cli.main(["batimento", "rapida", "--max", "90", "--help"]) == 7
    assert cli.main(["batimento", "--dsn", "x"]) == 7
    assert recebidos == [["rapida", "--max", "90", "--help"], ["--dsn", "x"]]


def test_cli_imports_preguicosos():
    """A cli.py e a config.py não importam nada dos grupos opcionais no topo."""
    pesados = {
        "fastapi",
        "uvicorn",
        "procrastinate",
        "mcp",
        "pywebpush",
        "kokoro_onnx",
        "faster_whisper",
        "fastembed",
        "websockets",
        "psycopg_pool",
    }
    for nome in ("cli.py", "config.py", "relogio.py", "__init__.py"):
        arvore = ast.parse((RAIZ / "ayanami" / nome).read_text())
        for no in ast.walk(arvore):
            if isinstance(no, ast.Import):
                mods = [a.name for a in no.names]
            elif isinstance(no, ast.ImportFrom):
                mods = [no.module or ""]
            else:
                continue
            assert not {m.split(".")[0] for m in mods} & pesados, (nome, mods)
