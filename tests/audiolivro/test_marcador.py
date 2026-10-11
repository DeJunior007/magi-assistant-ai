"""A1.4: marcador (CA-A5) e registro de sessões (A10)."""

from __future__ import annotations

import json
from pathlib import Path

from magi.audiolivro import marcador as mod
from magi.audiolivro.config import ConfigAudiolivro
from magi.audiolivro.contratos import Posicao
from magi.audiolivro.marcador import Marcador


class _Relogio:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def _cfg(tmp_path: Path) -> ConfigAudiolivro:
    return ConfigAudiolivro(estado_dir=tmp_path / "estado")


def test_padrao_no_estado_isolado(tmp_path: Path) -> None:
    assert str(ConfigAudiolivro().marcador_path).startswith(str(tmp_path))


def test_grava_e_sobrevive_a_reabrir(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    m = Marcador(cfg, relogio=_Relogio())
    assert m.posicao("abc") is None
    m.avancar("abc", Posicao(2, 5, 1, 1.25))
    m.avancar("xyz", Posicao(0, 1, 0), forcar=True)
    m2 = Marcador(cfg)
    assert m2.posicao("abc") == Posicao(2, 5, 1, 1.25)
    assert m2.posicao("xyz") == Posicao(0, 1, 0)


def test_no_maximo_uma_escrita_a_cada_2s(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    rel = _Relogio()
    m = Marcador(cfg, relogio=rel)
    escritas = []
    real = m.gravar

    def contar() -> None:
        escritas.append(rel.t)
        real()

    monkeypatch.setattr(m, "gravar", contar)
    for i in range(100):  # uma frase a cada 0,3 s por 30 s
        rel.t = i * 0.3
        m.avancar("abc", Posicao(0, i, 0))
    assert all(b - a >= mod.INTERVALO_S for a, b in zip(escritas, escritas[1:], strict=False))
    assert len(escritas) <= 30 / mod.INTERVALO_S + 1
    assert m.posicao("abc") == Posicao(0, 99, 0)  # pendente na memória
    m.gravar()
    assert Marcador(cfg).posicao("abc") == Posicao(0, 99, 0)


def test_truncado_usa_bak_do_inicio_do_capitulo(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    m = Marcador(cfg, relogio=_Relogio())
    m.avancar("abc", Posicao(3, 7, 2, 1.1), forcar=True)
    m.avancar("abc", Posicao(4, 2, 0, 1.1), forcar=True)
    assert m.bak.is_file()
    assert json.loads(m.bak.read_text())["abc"]["cap"] == 3
    cfg.marcador_path.write_text('{"abc": {"cap": 4, "pa')  # escrita interrompida
    assert Marcador(cfg).posicao("abc") == Posicao(3, 0, 0, 1.1)
    cfg.marcador_path.unlink()
    assert Marcador(cfg).posicao("abc") == Posicao(3, 0, 0, 1.1)
    m3 = Marcador(cfg, relogio=_Relogio())  # volta a gravar normalmente
    m3.avancar("abc", Posicao(3, 1, 0), forcar=True)
    assert Marcador(cfg).posicao("abc") == Posicao(3, 1, 0)
    assert not list(cfg.estado_dir.glob("*.tmp"))


def test_registro_jsonl_e_giro(tmp_path: Path, monkeypatch) -> None:
    cfg = _cfg(tmp_path)
    m = Marcador(cfg)
    reg = {
        "livro": "abc",
        "de": [0, 0],
        "ate": [1, 4],
        "caracteres": 1234,
        "segundos": 80.5,
        "marcacao": "qwen",
        "personagens_novos": ["Capitu"],
    }
    m.registrar_sessao(reg)
    linhas = cfg.registro_path.read_text().splitlines()
    assert len(linhas) == 1
    d = json.loads(linhas[0])
    assert d["personagens_novos"] == ["Capitu"] and "ts" in d
    monkeypatch.setattr(mod, "GIRO_BYTES", 10)
    m.registrar_sessao(reg)
    girado = cfg.registro_path.with_name("audiolivro.jsonl.1")
    assert girado.is_file()
    assert len(cfg.registro_path.read_text().splitlines()) == 1
