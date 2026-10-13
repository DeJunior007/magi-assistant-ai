"""Pareamento do celular, lado do PC (ayanami-central Y6.6, R9, spec §2.2 ``/v1/pareamento``).

``pedir_codigo()`` faz ``POST /v1/pareamento`` com o token ``pc`` e devolve o código de 6 dígitos
(5 min, uso único) e a URL ``<ayanami>/app/#/parear?c=<código>`` que o PWA abre. Com ``avisos``
(``AvisosAyanami`` do core) mostra o card "Código de pareamento 123 456" no HUD pelo mesmo
``sink`` da proatividade. O código nunca vai a log.

Rodável: ``uv run python -m magi.elo.parear [--nome celular-pedro]`` imprime o código, a URL e,
se a lib ``qrcode`` já estiver instalada, o QR em texto. Esse processo é separado do
``magi-core``: o card no HUD só sai quando o próprio core chama ``pedir_codigo(avisos=…)``.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from magi.core.proactive.ayanami import AvisosAyanami, formatar_codigo
from magi.elo.credenciais import token_pc, url_ayanami

log = logging.getLogger(__name__)


class ErroPareamento(Exception):
    """Falha ao pedir o código (sem config, token recusado, Ayanami fora). Sem segredo na msg."""


@dataclass(frozen=True, slots=True)
class CodigoPareamento:
    codigo: str
    expira_em: str
    url: str  # .../app/#/parear?c=<código>

    def __repr__(self) -> str:  # o código não aparece em log por acidente
        return f"CodigoPareamento(expira_em={self.expira_em!r})"


def url_app(base: str, codigo: str) -> str:
    return f"{base.rstrip('/')}/app/#/parear?c={codigo}"


async def pedir_codigo(
    url: str,
    token: str,
    *,
    nome_sugerido: str | None = None,
    http: httpx.AsyncClient | None = None,
    avisos: AvisosAyanami | None = None,
) -> CodigoPareamento:
    corpo = {"nome_sugerido": nome_sugerido} if nome_sugerido else {}
    cab = {"Authorization": f"Bearer {token}"}
    alvo = url.rstrip("/") + "/v1/pareamento"
    try:
        if http is not None:
            r = await http.post(alvo, json=corpo, headers=cab)
        else:
            async with httpx.AsyncClient(timeout=15) as cli:
                r = await cli.post(alvo, json=corpo, headers=cab)
    except httpx.HTTPError as e:
        raise ErroPareamento(f"Ayanami fora do ar ({type(e).__name__})") from None
    if r.status_code in (401, 403):
        raise ErroPareamento(f"token do PC recusado ({r.status_code})")
    if r.status_code != 201:
        raise ErroPareamento(f"a Ayanami respondeu {r.status_code}")
    try:
        d = r.json()
        codigo, expira = str(d["codigo"]), str(d.get("expira_em", ""))
    except (ValueError, KeyError, TypeError):
        raise ErroPareamento("resposta inválida da Ayanami") from None
    log.info("ayanami: código de pareamento criado (expira %s)", expira)
    res = CodigoPareamento(codigo, expira, url_app(url, codigo))
    if avisos is not None:
        await avisos.codigo_pareamento(codigo)
    return res


def _qr_texto(texto: str) -> str | None:
    """QR em texto só se ``qrcode`` já estiver instalado (sem dependência nova)."""
    try:
        import io

        import qrcode  # type: ignore[import-not-found]
    except ImportError:
        return None
    qr = qrcode.QRCode(border=1)
    qr.add_data(texto)
    buf = io.StringIO()
    qr.print_ascii(out=buf, invert=True)
    return buf.getvalue()


def main(
    argv: list[str] | None = None,
    *,
    config: Any = None,
    token: Callable[[], str | None] | None = None,
    http: httpx.AsyncClient | None = None,
    out: Any = None,
) -> int:
    ap = argparse.ArgumentParser(prog="python -m magi.elo.parear",
                                 description="Pede à Ayanami um código para parear o celular.")
    ap.add_argument("--nome", default=None, help="nome sugerido do celular (ex.: celular-pedro)")
    args = ap.parse_args(argv)
    out = out or sys.stdout
    if config is None:
        from magi.common.config import load_config

        config = load_config()
    url = url_ayanami(config)
    if url is None:
        print("Falta [ayanami] url no config.toml.", file=sys.stderr)
        return 2
    tok = (token or token_pc)()
    if not tok:
        print("Sem token do PC (keyring magi/ayanami_pc ou ayanami.token).", file=sys.stderr)
        return 2
    try:
        res = asyncio.run(pedir_codigo(url, tok, nome_sugerido=args.nome, http=http))
    except ErroPareamento as e:
        print(f"Não consegui o código: {e}", file=sys.stderr)
        return 1
    print(f"Código de pareamento: {formatar_codigo(res.codigo)} (vale 5 min, uso único)", file=out)
    print(f"No celular: {res.url}", file=out)
    qr = _qr_texto(res.url)
    if qr:
        print(qr, file=out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
