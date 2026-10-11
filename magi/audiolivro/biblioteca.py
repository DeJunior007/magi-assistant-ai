"""Biblioteca de livros (tarefa A1.4; requirements A1, A1.1, A1.2, D3).

Varre ``[audiolivro] pasta`` (``~/Livros``, criada se faltar), cache do índice em
``cache_dir/indice.json`` por mtime; ``achar`` casa o título falado sem acento, sem artigos e por
tokens. Ambíguo = duas notas a < 0,1 (ela pergunta qual, A1.1). PDF sem texto (A1.2) e arquivo
ilegível ficam fora de ``livros()`` e vão para ``ignorados`` (caminho → motivo).
"""

from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from collections.abc import Callable
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from magi.audiolivro.config import ConfigAudiolivro
from magi.audiolivro.contratos import Livro

log = logging.getLogger(__name__)

#: Diferença de nota abaixo da qual dois livros contam como ambíguos (A1.1).
AMBIGUO_DELTA = 0.1
#: Nota mínima para um livro aparecer em ``achar``.
NOTA_MINIMA = 0.5
#: Dois tokens casam com semelhança ≥ isto (tolera erro de reconhecimento de fala).
TOKEN_MINIMO = 0.8
EXTENSOES = {".epub": "epub", ".pdf": "pdf"}
SEM_TEXTO = "sem_texto"
INVALIDO = "invalido"

#: Artigos e ligações que não ajudam a distinguir títulos (pt e en).
VAZIAS = frozenset("o a os as um uma uns umas de do da dos das e the an of and".split())
_NUMEROS = {
    "dois": "2",
    "tres": "3",
    "quatro": "4",
    "cinco": "5",
    "seis": "6",
    "sete": "7",
    "oito": "8",
    "nove": "9",
    "dez": "10",
    "onze": "11",
    "doze": "12",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "ii": "2",
    "iii": "3",
    "iv": "4",
    "vi": "6",
    "vii": "7",
    "viii": "8",
    "ix": "9",
    "primeiro": "1",
    "segundo": "2",
    "terceiro": "3",
}
_SUBTITULO = re.compile(r"\s*(?::|\s[-–—]\s|\()")


def normalizar(texto: str) -> list[str]:
    """Tokens sem acento, minúsculos, sem pontuação e sem artigos; números por extenso/romanos
    viram dígitos."""
    t = unicodedata.normalize("NFKD", texto.casefold())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^\w]+|_", " ", t)
    return [_NUMEROS.get(w, w) for w in t.split() if w not in VAZIAS]


def _casa(a: str, b: str) -> bool:
    if a == b:
        return True
    if a.isdigit() or b.isdigit():
        return False
    return SequenceMatcher(None, a, b).ratio() >= TOKEN_MINIMO


def nota(fala: str, titulo: str) -> float:
    """F1 entre os tokens da fala e os do título (0–1); vale o melhor entre título inteiro e
    título sem subtítulo."""
    f = normalizar(fala)
    if not f:
        return 0.0
    candidatos = {titulo, _SUBTITULO.split(titulo, maxsplit=1)[0]}
    melhor = 0.0
    for c in candidatos:
        t = normalizar(c)
        if not t:
            continue
        acerto_t = sum(1 for x in t if any(_casa(x, y) for y in f))
        acerto_f = sum(1 for y in f if any(_casa(x, y) for x in t))
        if not acerto_t or not acerto_f:
            continue
        r, p = acerto_t / len(t), acerto_f / len(f)
        melhor = max(melhor, 2 * p * r / (p + r))
    return round(melhor, 4)


def _ler(caminho: Path) -> Livro:
    if EXTENSOES[caminho.suffix.lower()] == "epub":
        from magi.audiolivro import epub as leitor
    else:
        from magi.audiolivro import pdf as leitor  # type: ignore[no-redef]
    return leitor.metadados(caminho)


def _motivo(e: Exception) -> str:
    from magi.audiolivro.pdf import SemTexto

    return SEM_TEXTO if isinstance(e, SemTexto) else INVALIDO


def _para_json(lv: Livro) -> dict[str, Any]:
    return {
        "id": lv.id,
        "titulo": lv.titulo,
        "autor": lv.autor,
        "idioma": lv.idioma,
        "formato": lv.formato,
        "capitulos": lv.capitulos,
        "caracteres": lv.caracteres,
    }


def _de_json(caminho: Path, d: dict[str, Any]) -> Livro:
    return Livro(
        id=d["id"],
        caminho=caminho,
        titulo=d["titulo"],
        autor=d.get("autor"),
        idioma=d["idioma"],
        formato=d["formato"],
        capitulos=int(d["capitulos"]),
        caracteres=int(d["caracteres"]),
    )


class Biblioteca:
    def __init__(self, cfg: ConfigAudiolivro, *, ler: Callable[[Path], Livro] = _ler) -> None:
        self.cfg = cfg
        self._ler = ler
        self.ignorados: dict[Path, str] = {}

    @property
    def indice_path(self) -> Path:
        return self.cfg.cache_dir / "indice.json"

    def _carregar_indice(self) -> dict[str, Any]:
        try:
            d = json.loads(self.indice_path.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def _gravar_indice(self, indice: dict[str, Any]) -> None:
        p = self.indice_path
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(indice, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)

    def livros(self) -> list[Livro]:
        """Todos os livros da pasta (EPUB e PDF), do cache quando o mtime não mudou."""
        pasta = self.cfg.garantir_pasta()
        antigo = self._carregar_indice()
        novo: dict[str, Any] = {}
        out: list[Livro] = []
        self.ignorados = {}
        arquivos = sorted(p for p in pasta.rglob("*") if p.suffix.lower() in EXTENSOES and p.is_file())
        for caminho in arquivos:
            st = caminho.stat()
            chave = str(caminho)
            ent = antigo.get(chave)
            if not (
                isinstance(ent, dict)
                and ent.get("mtime_ns") == st.st_mtime_ns
                and ent.get("tamanho") == st.st_size
            ):
                ent = {"mtime_ns": st.st_mtime_ns, "tamanho": st.st_size}
                try:
                    ent["livro"] = _para_json(self._ler(caminho))
                except Exception as e:  # noqa: BLE001 - um arquivo ruim não derruba a biblioteca
                    log.warning("audiolivro: %s ignorado (%s)", caminho.name, e)
                    ent["erro"] = _motivo(e)
            novo[chave] = ent
            if "livro" in ent:
                out.append(_de_json(caminho, ent["livro"]))
            else:
                self.ignorados[caminho] = ent.get("erro", INVALIDO)
        if novo != antigo:
            self._gravar_indice(novo)
        return out

    def achar(self, fala: str) -> list[tuple[Livro, float]]:
        """Livros que casam com o título falado, nota decrescente (0–1)."""
        achados = [(lv, nota(fala, lv.titulo)) for lv in self.livros()]
        achados = [(lv, n) for lv, n in achados if n >= NOTA_MINIMA]
        return sorted(achados, key=lambda x: (-x[1], x[0].titulo))

    @staticmethod
    def ambiguo(achados: list[tuple[Livro, float]]) -> bool:
        """``True`` quando os dois primeiros estão a menos de ``AMBIGUO_DELTA``."""
        return len(achados) >= 2 and achados[0][1] - achados[1][1] < AMBIGUO_DELTA
