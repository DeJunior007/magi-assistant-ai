#!/usr/bin/env python3
"""Alterna o MAGI entre o painel completo e a tela de ociosidade (atalho Meta+M).
Leve de propósito (sem Qt): o MAGI aberto percebe a troca em ~0,3 s."""
import json
import os

path = os.path.expanduser("~/.config/gamerhud/settings.json")
try:
    with open(path) as f:
        cfg = json.load(f)
except (OSError, ValueError):
    cfg = {}
cfg["view"] = "full" if cfg.get("view", "full") == "idle" else "idle"
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w") as f:
    json.dump(cfg, f)
