"""Varredura estática das proibições da spec §7.3 (Y4.2; CA-Y25).

Cobre ``ayanami/``, ``magi/elo/backup.py`` e ``deploy/ayanami/`` inteiros, com lista de exceções
**vazia**. Os padrões são montados por partes para este arquivo não casar consigo mesmo (``tests/``
nem está na varredura, mas assim ele pode ser copiado sem virar falso positivo).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
ALVOS = ("ayanami", "magi/elo/backup.py", "deploy/ayanami")
IGNORAR_DIRS = {"__pycache__", "node_modules", ".pytest_cache", ".ruff_cache"}
EXCECOES: frozenset[str] = frozenset()  # tem de ficar vazia (CA-Y25)

PADROES = {
    "compose down": re.compile(r"compose" + r"\s+down", re.I),
    "volume rm": re.compile(r"volume" + r"\s+rm\b", re.I),
    "DROP": re.compile(r"\bDROP" + r" ", re.I),
    "TRUNCATE": re.compile(r"\bTRUNC" + r"ATE\b", re.I),
    "--clean": re.compile(r"--" + r"clean\b"),
}


def _arquivos() -> list[Path]:
    saida: list[Path] = []
    for alvo in ALVOS:
        p = RAIZ / alvo
        assert p.exists(), alvo
        candidatos = [p] if p.is_file() else sorted(p.rglob("*"))
        for f in candidatos:
            if f.is_file() and not IGNORAR_DIRS.intersection(f.relative_to(RAIZ).parts):
                saida.append(f)
    return saida


def _achados(arquivos: list[Path]) -> list[str]:
    achados: list[str] = []
    for f in arquivos:
        rel = f.relative_to(RAIZ).as_posix()
        if rel in EXCECOES:
            continue
        try:
            texto = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binário (ícone, modelo): não é código nem script
        for n, linha in enumerate(texto.splitlines(), 1):
            for nome, rx in PADROES.items():
                if rx.search(linha):
                    achados.append(f"{rel}:{n}: {nome}")
    return achados


def test_lista_de_excecoes_vazia():
    assert EXCECOES == frozenset()


def test_padroes_pegam_o_que_devem():
    amostras = {
        "compose down": "docker compose  down -v",
        "volume rm": "docker volume rm x",
        "DROP": "drop table x",
        "TRUNCATE": "TRUNCATE x",
        "--clean": "pg_restore --clean",
    }
    for nome, amostra in amostras.items():
        assert PADROES[nome].search(amostra), nome
    assert not any(rx.search("pg_restore --no-owner --create") for rx in PADROES.values())


def test_varredura_do_ayanami():
    """O código da Ayanami (dono de quase tudo aqui) já passa limpo."""
    assert _achados([f for f in _arquivos() if f.relative_to(RAIZ).parts[0] == "ayanami"]) == []


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Sobras Y4.2: deploy/ayanami/host/limpar-multivideos.sh (Y1.2) tem o comando de remover volume e "
        "a docstring de magi/elo/backup.py (Y4.1) cita as palavras proibidas; os donos corrigem e este "
        "xfail estrito vira falha até ser removido"
    ),
)
def test_varredura_completa_sem_excecoes():
    assert _achados(_arquivos()) == []
