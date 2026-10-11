"""A0.1: contratos, config e esqueleto do audiolivro."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from magi.audiolivro import config as acfg
from magi.audiolivro.contratos import (
    Emocao,
    Livro,
    OpcoesVoz,
    Posicao,
    Tipo,
    Trecho,
    livro_id,
)
from magi.common.config import ConfigError, parse_config

MODULOS = [
    "contratos",
    "config",
    "epub",
    "pdf",
    "frases",
    "biblioteca",
    "marcas",
    "marcas_llm",
    "vozes",
    "custo",
    "marcador",
    "leitor",
    "handler",
]


@pytest.mark.parametrize("nome", MODULOS)
def test_modulos_importam(nome: str) -> None:
    importlib.import_module(f"magi.audiolivro.{nome}")


def test_tomls_existem() -> None:
    base = Path(importlib.import_module("magi.audiolivro").__file__).parent
    for nome in ("verbos.toml", "vozes.toml"):
        assert (base / nome).read_text().startswith("#")


def test_pymupdf_disponivel() -> None:
    import pymupdf  # noqa: F401  (D6)


def _cfg(raw: dict) -> object:
    prov = {n: {"keys": []} for n in ("kokoro", "openai", "qwen")}
    base = {"providers": prov, "tasks": {}}
    base.update(raw)
    return parse_config(base)


def test_config_sem_secao_usa_padroes(_isola_casa: Path) -> None:
    c = acfg.audiolivro_config(_cfg({}))
    assert c.pasta == _isola_casa / "Livros"  # D3
    assert c.marcacao == "qwen" and c.musica == "pausa"  # D2, D4
    assert c.qwen_container == "magi-qwen"
    assert c.marcador_path == _isola_casa / ".local/state/magi/audiolivro.json"
    assert c.cache_dir == _isola_casa / ".cache/magi/audiolivro"
    assert not c.pasta.exists()
    assert c.garantir_pasta().is_dir()


def test_config_com_secao() -> None:
    c = acfg.parse_audiolivro(
        {
            "audiolivro": {
                "pasta": "/tmp/x",
                "marcacao": "regras",
                "chars_por_minuto": 800,
                "vozes": {"en-GB": {"f": ["bf_emma"]}},
            }
        }
    )
    assert c.pasta == Path("/tmp/x") and c.marcacao == "regras" and c.chars_por_minuto == 800
    assert c.vozes == {"en-gb": {"f": ("bf_emma",)}}


@pytest.mark.parametrize(
    "sec",
    [
        {"marcacao": "llm"},
        {"musica": "alto"},
        {"chars_por_minuto": 0},
        {"retomar_apos_comando": "sim"},
        {"vozes": {"pt-br": {"f": "pf_dora"}}},
    ],
)
def test_config_invalida(sec: dict) -> None:
    with pytest.raises(ConfigError):
        acfg.parse_audiolivro({"audiolivro": sec})


def test_voz_dela_do_kokoro() -> None:
    c = _cfg(
        {
            "tasks": {
                "tts": {"provider": "kokoro", "model": "kokoro-v1.0", "voice": "bf_isabella", "lang": "en-gb"}
            },
            "speech": {"language": "pt-br"},
        }
    )
    assert acfg.voz_dela(c) == "bf_isabella" and acfg.idioma_dela(c) == "en-gb"
    assert acfg.tts_livro(c).provider == "kokoro"


def test_tts_pago_vira_kokoro_no_livro() -> None:
    c = _cfg(
        {
            "tasks": {"tts": {"provider": "openai", "model": "gpt-4o-mini-tts", "voice": "marin"}},
            "speech": {"language": "pt-br"},
        }
    )
    t = acfg.tts_livro(c)
    assert t.provider == "kokoro" and t.options == {"voice": "pf_dora", "lang": "pt-br"}


def test_marcacao_so_local() -> None:
    assert acfg.tarefa_marca(_cfg({})).provider == "qwen"  # padrão
    pago = _cfg({"tasks": {"audiolivro_marca": {"provider": "openai", "model": "gpt-5.4-mini"}}})
    assert acfg.tarefa_marca(pago) is None  # D2: nunca LLM pago
    so_regras = _cfg({"audiolivro": {"marcacao": "regras"}})
    assert acfg.tarefa_marca(so_regras) is None


def test_contratos() -> None:
    t = Trecho("— Vem.", Tipo.FALA, Emocao.SUSSURRO, falante="Paul", genero="m", idade="jovem")
    assert t.texto == "— Vem." and Tipo("fala") is Tipo.FALA
    o = OpcoesVoz(voice="bm_george", speed=0.92, pausa_ms=450)
    assert o.tts() == {"voice": "bm_george", "speed": 0.92}
    assert Posicao(1, 2, 3).velocidade == 1.0
    lid = livro_id(Path("/l/a.epub"), 10)
    assert len(lid) == 12 and lid == livro_id(Path("/l/a.epub"), 10)
    livro = Livro(lid, Path("/l/a.epub"), "A", None, "pt-br", "epub", 1, 10)
    with pytest.raises(FileNotFoundError):
        livro.capitulo(0)  # extração (A1.1) lê o arquivo, que não existe
