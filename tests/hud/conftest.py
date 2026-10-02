"""O HUD não é pacote (o gamerhud importa módulos irmãos): põe `hud/` no sys.path."""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "hud"))

# QApplication (não só QGuiApplication): o gamerhud.HUD é um QWidget. Criada aqui, antes de
# qualquer módulo de teste, ela também serve aos testes que pedem `QGuiApplication.instance()`.
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])
