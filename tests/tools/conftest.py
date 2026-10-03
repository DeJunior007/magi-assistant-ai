import sys
from pathlib import Path

# ``tools/`` não é instalado com o pacote; os testes o importam a partir da raiz do repositório.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
