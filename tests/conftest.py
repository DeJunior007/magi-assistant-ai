"""Vale para todos os testes: leitores em thread do HUD que chamam programas do sistema ficam
desligados (os testes de cada leitor injetam o subprocesso falso)."""

import os

for _var in ("MAGI_NO_VOLUME", "MAGI_NO_NOTIF", "MAGI_NO_EXTRAS"):
    os.environ.setdefault(_var, "1")
