"""O HUD não é pacote (o gamerhud importa módulos irmãos): põe `hud/` no sys.path."""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["GAMERHUD_NO_WALLPAPER"] = "1"   # testes nunca tocam no papel de parede real (U5)
os.environ["MAGI_PORTRAIT_DIR"] = "/nonexistent/magi-portrait"  # sem a arte real do PC: mascote vetorial
os.environ["MAGI_NO_CLAUDE_STATS"] = "1"  # sem ler o ~/.claude real
os.environ["MAGI_NO_VOLUME"] = "1"  # sem a thread do wpctl real (R2.D)
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "hud"))

# QApplication (não só QGuiApplication): o gamerhud.HUD é um QWidget. Criada aqui, antes de
# qualquer módulo de teste, ela também serve aos testes que pedem `QGuiApplication.instance()`.
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _reacoes_isoladas(tmp_path, monkeypatch):
    """As reações da Condessa nunca leem nem gravam os arquivos reais (gosto, artistas, faxina)."""
    from wired import reactions

    for name in ("GENRES_FILE", "CLEANUP_FILE", "TASTE_FILE", "SEEN_FILE", "FAVORITES_FILE", "SPEECH_FILE"):
        monkeypatch.setattr(reactions, name, tmp_path / "reacoes" / name.lower())
    from wired.reacoes import atividade, registro

    monkeypatch.setattr(registro, "REGISTRO_FILE", tmp_path / "reacoes" / "reacoes.jsonl")
    monkeypatch.setattr(atividade, "ESTADO_FILE", tmp_path / "reacoes" / "atividade.json")
    from wired.reacoes import det_tempo

    monkeypatch.setattr(det_tempo, "GIT", lambda: None)  # nunca o git do repositório real
    monkeypatch.setattr(det_tempo, "_CACHE", {})
