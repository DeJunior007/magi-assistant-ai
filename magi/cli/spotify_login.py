"""Conecta o Spotify (OAuth PKCE) e guarda os tokens no keyring (R7.2).

    uv run python -m magi.cli.spotify_login [--client-id ID] [--port 8765] [--no-browser]

Antes: crie um app em https://developer.spotify.com/dashboard com a Redirect URI exata
``http://127.0.0.1:8765/callback`` (ou a porta escolhida em ``--port``) e marque "Web API".
O Client ID é pedido na primeira vez e fica no keyring (``spotify-client-id``). O comando sobe
um servidor só em 127.0.0.1, abre o navegador na página de autorização, recebe o ``code`` no
callback, troca pelo token e grava ``spotify-token`` no keyring.
"""

from __future__ import annotations

import argparse
import asyncio
import secrets as _rand
import sys
import time
import webbrowser
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import httpx

from magi.core.actions import spotify_api as sa

_PAGE = "<!doctype html><meta charset=utf-8><title>Magui</title><p>{msg}</p>"


class _CallbackServer(HTTPServer):
    params: dict[str, str] | None = None


class _Handler(BaseHTTPRequestHandler):
    server: _CallbackServer

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        if url.path != "/callback":
            self.send_error(404)
            return
        self.server.params = {k: v[0] for k, v in parse_qs(url.query).items()}
        ok = "code" in self.server.params
        msg = "Spotify conectado. Pode fechar esta aba." if ok else "Autorização recusada."
        body = _PAGE.format(msg=msg).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:  # silencioso
        pass


def wait_callback(server: _CallbackServer, timeout_s: float) -> dict[str, str] | None:
    deadline = time.monotonic() + timeout_s
    server.timeout = 0.5
    while server.params is None and time.monotonic() < deadline:
        server.handle_request()
    return server.params


def main(
    argv: list[str] | None = None,
    *,
    opener: Callable[[str], object] = webbrowser.open,
    store: sa.TokenStore | None = None,
    client: httpx.AsyncClient | None = None,
) -> int:
    p = argparse.ArgumentParser(prog="magi-spotify-login", description=__doc__.splitlines()[0])
    p.add_argument("--client-id", help="Client ID do app (grava no keyring)")
    p.add_argument("--port", type=int, default=sa.DEFAULT_PORT, help="porta do callback local")
    p.add_argument("--no-browser", action="store_true", help="só imprime a URL")
    p.add_argument("--timeout", type=float, default=300.0, help="segundos esperando o callback")
    args = p.parse_args(argv)

    store = store or sa.TokenStore()
    if args.client_id:
        store.set_client_id(args.client_id)
    client_id = store.client_id()
    if not client_id:
        client_id = input("Client ID do app do Spotify: ").strip()
        if not client_id:
            print("Client ID vazio.", file=sys.stderr)
            return 1
        store.set_client_id(client_id)

    try:
        server = _CallbackServer(("127.0.0.1", args.port), _Handler)
    except OSError as e:
        print(f"Não consegui abrir 127.0.0.1:{args.port}: {e}", file=sys.stderr)
        return 1
    with server:
        redirect = sa.redirect_uri(server.server_address[1])
        verifier, state = sa.make_verifier(), _rand.token_urlsafe(16)
        url = sa.authorize_url(client_id, redirect, sa.code_challenge(verifier), state)
        print(f"Redirect URI (deve estar cadastrada no app): {redirect}")
        print(f"Abra para autorizar:\n{url}")
        if not args.no_browser:
            opener(url)
        params = wait_callback(server, args.timeout)

    if params is None:
        print("Tempo esgotado esperando a autorização.", file=sys.stderr)
        return 1
    if params.get("state") != state:
        print("State inválido no callback; tente de novo.", file=sys.stderr)
        return 1
    if "code" not in params:
        print(f"Autorização recusada: {params.get('error', '?')}", file=sys.stderr)
        return 1

    async def _exchange() -> sa.Token:
        if client is not None:
            return await sa.exchange_code(client, client_id, params["code"], verifier, redirect)
        async with httpx.AsyncClient(timeout=15.0) as c:
            return await sa.exchange_code(c, client_id, params["code"], verifier, redirect)

    try:
        token = asyncio.run(_exchange())
    except (sa.SpotifyAuthError, sa.SpotifyApiError, httpx.HTTPError) as e:
        print(f"Falha ao obter o token: {e}", file=sys.stderr)
        return 1
    store.save(token)
    print(f"Spotify conectado. Escopos: {token.scope or '?'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
