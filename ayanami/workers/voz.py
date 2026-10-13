"""Cache de frases Kokoro (dono: Y3.5; spec §5.4, §6.5; corpo chamado por ``ayanami.fila``).

``voz.cache_frases`` (lenta, cron ``0 6 * * 1``, ``lock="voz"``) lê as frases fixas do modo nuvem
e grava ``<dados>/modelos/cache-voz/<sha1>.ogg`` (:func:`chave` = SHA-1 do texto em UTF-8) para
as que ainda não têm arquivo; frase com ``sha1`` existente não é regenerada.

Injeção por ``deps.extras`` (os testes passam falsos; padrões de produção entre parênteses):

- ``voz_frases``: caminho do YAML (``ayanami/frases.yaml``). Aceita ``{nome: texto}`` ou lista de
  textos; arquivo ausente → nada a fazer.
- ``voz_sintetizar``: ``async (texto, voz) -> (pcm_s16le, taxa)`` (``POST`` ao ``ayanami-voz``
  em ``$AYANAMI_VOZ_URL``, padrão ``http://ayanami-voz:8741``: o worker não carrega o Kokoro).
- ``voz_ffmpeg``: ``async (pcm, taxa, destino) -> None`` (``ffmpeg`` → Opus em OGG).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from procrastinate import JobContext

from ayanami.deps import Deps

log = logging.getLogger(__name__)

FRASES_PADRAO = Path(__file__).resolve().parent.parent / "frases.yaml"
URL_PADRAO = "http://ayanami-voz:8741"

Sintetizar = Callable[[str, str], Awaitable[tuple[bytes, int]]]
Ffmpeg = Callable[[bytes, int, Path], Awaitable[None]]


def chave(texto: str) -> str:
    return hashlib.sha1(texto.encode("utf-8")).hexdigest()


def ler_frases(caminho: Path) -> list[str]:
    if not caminho.exists():
        return []
    import yaml

    dados = yaml.safe_load(caminho.read_text(encoding="utf-8")) or []
    itens = list(dados.values()) if isinstance(dados, dict) else dados
    if not isinstance(itens, list):
        raise ValueError(f"{caminho}: esperava mapa nome→texto ou lista de textos")
    frases: list[str] = []
    for t in itens:
        if not isinstance(t, str) or not t.strip():
            raise ValueError(f"{caminho}: frase inválida: {t!r}")
        if t not in frases:
            frases.append(t)
    return frases


async def sintetizar_http(texto: str, voz: str, *, url: str | None = None) -> tuple[bytes, int]:
    import httpx

    base = url or os.environ.get("AYANAMI_VOZ_URL", URL_PADRAO)
    async with httpx.AsyncClient(base_url=base, timeout=120) as c:
        r = await c.post("/falar", json={"texto": texto, "voz": voz})
        r.raise_for_status()
        return r.content, int(r.headers.get("X-Taxa", "24000"))


async def ffmpeg_ogg(pcm: bytes, taxa: int, destino: Path) -> None:
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "s16le", "-ar", str(taxa),
        "-ac", "1", "-i", "pipe:0", "-c:a", "libopus", "-b:a", "32k", "-f", "ogg", str(destino),
        stdin=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, err = await proc.communicate(pcm)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg saiu com {proc.returncode}: {err.decode(errors='replace')[-300:]}")


async def cache_frases(deps: Deps, contexto: JobContext, *, timestamp: int) -> dict[str, Any] | None:
    """``voz.cache_frases``: gera só as frases sem ``<sha1>.ogg`` (dono: Y3.5)."""
    frases = ler_frases(Path(deps.extras.get("voz_frases", FRASES_PADRAO)))
    sintetizar: Sintetizar = deps.extras.get("voz_sintetizar", sintetizar_http)
    ffmpeg: Ffmpeg = deps.extras.get("voz_ffmpeg", ffmpeg_ogg)
    voz = deps.cfg.voz.voz
    destino = deps.dados / "modelos" / "cache-voz"
    destino.mkdir(parents=True, exist_ok=True)

    geradas: list[str] = []
    existentes: list[str] = []
    falhas: list[str] = []
    for texto in frases:
        k = chave(texto)
        final = destino / f"{k}.ogg"
        if final.exists():
            existentes.append(k)
            continue
        tmp = destino / f".{k}.ogg.tmp"
        try:
            pcm, taxa = await sintetizar(texto, voz)
            await ffmpeg(pcm, taxa, tmp)
            tmp.replace(final)
            geradas.append(k)
        except Exception as e:  # uma frase ruim não impede as outras
            log.error("voz.cache_frases: %s falhou: %s", k, e)
            falhas.append(k)
        finally:
            tmp.unlink(missing_ok=True)
    if falhas:
        raise RuntimeError(f"voz.cache_frases: {len(falhas)} frase(s) falharam: {falhas}")
    return {"texto": f"{len(geradas)} frase(s) gerada(s), {len(existentes)} já em cache",
            "dados": {"geradas": geradas, "existentes": existentes}}
