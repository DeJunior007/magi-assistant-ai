#!/usr/bin/env python3
"""Atalho Meta+M: HUD fechado → abre o MAGI; aberto → alterna painel completo ↔ tela de
ociosidade (o MAGI aberto percebe a troca em ~0,3 s). Lógica em ``alternar.py`` (O4.3), sem Qt."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from alternar import meta_m  # noqa: E402

meta_m()
