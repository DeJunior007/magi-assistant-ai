"""Spike S3 — MCP ``mcp`` 2.3, parte local (tarefa Y0.5 de ``specs/ayanami-central``).

Confirma, sem rede de fora e sem o Claude Code, o desenho da spec §8:

  - ``MCPServer`` montado num FastAPI em ``/mcp`` (``streamable_http_app(streamable_http_path="/")``);
  - ``TokenVerifier`` próprio (tipo ``mcp``, não revogado → ``AccessToken.scopes``);
  - ``AuthSettings(required_scopes=["ler"])`` barrando token sem ``ler`` no HTTP;
  - ``get_access_token()`` dentro da tool para checar o escopo por chamada (``exigir``);
  - cliente MCP da própria lib (``mcp.Client`` + ``streamable_http_client``) contra o ASGI em
    memória (``httpx2.ASGITransport``) e contra ``uvicorn`` em ``127.0.0.1`` (porta efêmera).

A parte "pelo tailnet" (``claude mcp add``, ``mcp-remote``) fica na Y1.6.

Uso:  uv run --with 'mcp==2.3.*' python spikes/ayanami_s3_mcp.py
Sai com código 0 se todas as verificações passarem; imprime uma linha por verificação.
Tokens aqui são falsos (``tok-…``), só deste script.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket
import sys
import warnings
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx2
import uvicorn
from fastapi import FastAPI
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

URL_BASE = "https://ayanami.exemplo.ts.net"
HOST_TAILNET = "ayanami.exemplo.ts.net"


# ---------------------------------------------------------------- verificador (falso, sem banco)


@dataclass(frozen=True)
class Disp:
    nome: str
    tipo: str
    escopos: tuple[str, ...]
    revogado: bool = False


TOKENS: dict[str, Disp] = {
    "tok-ler": Disp("claude-code", "mcp", ("ler",)),
    "tok-tarefas": Disp("claude-desktop", "mcp", ("ler", "tarefas")),
    "tok-so-tarefas": Disp("sem-ler", "mcp", ("tarefas",)),
    "tok-pc": Disp("pc", "pc", ("ler", "tarefas")),
    "tok-revogado": Disp("velho", "mcp", ("ler",), revogado=True),
}


class VerificadorAyanami:
    """``TokenVerifier`` (Protocol): só tipo ``mcp`` e não revogado; ``scopes`` = escopos."""

    def __init__(self, tabela: dict[str, Disp]) -> None:
        self.tabela = tabela
        self.chamadas = 0

    async def verify_token(self, token: str) -> AccessToken | None:
        self.chamadas += 1
        d = self.tabela.get(token)
        if d is None or d.tipo != "mcp" or d.revogado:
            return None
        return AccessToken(token=token, client_id=d.nome, scopes=list(d.escopos))


def exigir(escopo: str) -> AccessToken:
    tok = get_access_token()
    if tok is None or escopo not in tok.scopes:
        raise ToolError(f"escopo: falta '{escopo}'")
    return tok


# ---------------------------------------------------------------- servidor


def montar(*, escopos_ligados: tuple[str, ...] = ("ler", "tarefas")) -> tuple[FastAPI, MCPServer]:
    mcp = MCPServer(
        "ayanami",
        token_verifier=VerificadorAyanami(TOKENS),
        auth=AuthSettings(
            issuer_url=URL_BASE,
            resource_server_url=f"{URL_BASE}/mcp",
            required_scopes=["ler"],
            validate_token_resource=False,  # o verificador já checa tipo/revogação; sem isto avisa
        ),
    )
    auditoria: list[tuple[str, str, bool]] = []

    @mcp.tool()
    def estado() -> dict[str, Any]:
        """Estado (escopo ler)."""
        tok = exigir("ler")
        auditoria.append(("estado", tok.client_id, True))
        return {"pc_online": True, "quem": tok.client_id, "escopos": tok.scopes}

    if "tarefas" in escopos_ligados:

        @mcp.tool()
        def tarefa_criar(titulo: str) -> dict[str, Any]:
            """Cria tarefa (escopo tarefas)."""
            try:
                tok = exigir("tarefas")
            except ToolError:
                tok_atual = get_access_token()
                auditoria.append(("tarefa_criar", tok_atual.client_id if tok_atual else "?", False))
                raise
            auditoria.append(("tarefa_criar", tok.client_id, True))
            return {"id": "01TAREFA", "titulo": titulo, "por": tok.client_id}

    if "casa" in escopos_ligados:

        @mcp.tool()
        def tv_acao(intent: str) -> dict[str, Any]:
            """Ação de TV (escopo casa)."""
            exigir("casa")
            return {"ok": True, "intent": intent}

    mcp.auditoria = auditoria  # type: ignore[attr-defined]

    # O app Starlette do MCP tem lifespan próprio (session_manager.run()), mas um Mount no FastAPI
    # NÃO roda o lifespan do sub-app: quem roda é o lifespan do FastAPI.
    sub = mcp.streamable_http_app(
        streamable_http_path="/",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1", "127.0.0.1:*", "localhost:*", HOST_TAILNET],
            allowed_origins=[
                "http://127.0.0.1",
                "http://127.0.0.1:*",
                "http://localhost:*",
                f"https://{HOST_TAILNET}",
            ],
        ),
    )

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        async with mcp.session_manager.run():
            yield

    app = FastAPI(lifespan=lifespan)

    @app.get("/saude")
    def saude() -> dict[str, bool]:
        return {"ok": True}

    app.mount("/mcp", sub)
    return app, mcp


# ---------------------------------------------------------------- verificações

RESULTADOS: list[tuple[str, bool, str]] = []


def marca(nome: str, ok: bool, detalhe: str = "") -> None:
    RESULTADOS.append((nome, ok, detalhe))
    print(f"[{'ok' if ok else 'FALHA'}] {nome}{' — ' + detalhe if detalhe else ''}", flush=True)


def _texto(res: Any) -> str:
    return " ".join(getattr(c, "text", "") for c in res.content)


async def sessao_mcp(
    url: str, token: str, *, transporte: httpx2.AsyncBaseTransport | None = None
) -> dict[str, Any]:
    """Abre o cliente MCP da lib, lista e chama tools; devolve o que viu."""
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx2.AsyncClient(transport=transporte, headers=headers, timeout=10) as http:
        async with Client(streamable_http_client(url, http_client=http)) as cli:
            tools = sorted(t.name for t in (await cli.list_tools()).tools)
            est = await cli.call_tool("estado", {})
            criar = (
                await cli.call_tool("tarefa_criar", {"titulo": "ler o PR"})
                if "tarefa_criar" in tools
                else None
            )
    return {
        "tools": tools,
        "estado": (est.is_error, est.structured_content or _texto(est)),
        "criar": None if criar is None else (criar.is_error, criar.structured_content or _texto(criar)),
    }


async def bateria(rotulo: str, url: str, transporte_fn: Any) -> None:
    # 1) sem token / token pc / revogado / sem 'ler' → 401/403 no HTTP, antes do MCP
    async with httpx2.AsyncClient(transport=transporte_fn(), timeout=10) as http:
        corpo = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
        h = {"Accept": "application/json, text/event-stream"}
        for tok, esperado in (("", 401), ("tok-pc", 401), ("tok-revogado", 401), ("tok-so-tarefas", 403)):
            hh = dict(h, **({"Authorization": f"Bearer {tok}"} if tok else {}))
            r = await http.post(url, json=corpo, headers=hh)
            marca(
                f"{rotulo}: token {tok or '(nenhum)'} → {esperado}",
                r.status_code == esperado,
                f"{r.status_code} {r.headers.get('www-authenticate', '')[:90]}",
            )
        # /mcp sem barra: Starlette redireciona 307 para /mcp/ (o cliente MCP segue: mesma origem)
        r = await http.post(url.rstrip("/"), json=corpo, headers=dict(h, Authorization="Bearer tok-ler"))
        marca(
            f"{rotulo}: POST /mcp (sem barra) → 307 /mcp/",
            r.status_code == 307,
            f"{r.status_code} {r.headers.get('location', '')}",
        )
        r = await http.get(url.rsplit("/mcp", 1)[0] + "/saude")
        marca(f"{rotulo}: rota FastAPI vizinha (/saude)", r.status_code == 200)

    # 2) cliente MCP da lib com escopos diferentes
    v = await sessao_mcp(url, "tok-ler", transporte=transporte_fn())
    marca(f"{rotulo}: tok-ler list_tools", v["tools"] == ["estado", "tarefa_criar"], str(v["tools"]))
    marca(
        f"{rotulo}: tok-ler estado (get_access_token na tool)",
        v["estado"][0] is False and "claude-code" in str(v["estado"][1]),
        str(v["estado"][1])[:90],
    )
    marca(
        f"{rotulo}: tok-ler tarefa_criar → erro de escopo",
        v["criar"] is not None and v["criar"][0] is True and "escopo" in str(v["criar"][1]),
        str(v["criar"]),
    )
    v = await sessao_mcp(url, "tok-tarefas", transporte=transporte_fn())
    marca(
        f"{rotulo}: tok-tarefas tarefa_criar ok",
        v["criar"] is not None and v["criar"][0] is False and "claude-desktop" in str(v["criar"][1]),
        str(v["criar"])[:90],
    )

    # 3) a URL sem barra também funciona com o cliente (segue o 307 de mesma origem)
    try:
        v = await sessao_mcp(url.rstrip("/"), "tok-ler", transporte=transporte_fn())
        marca(f"{rotulo}: cliente em .../mcp (sem barra)", "estado" in v["tools"])
    except Exception as e:  # noqa: BLE001
        marca(f"{rotulo}: cliente em .../mcp (sem barra)", False, repr(e)[:120])


async def em_memoria() -> None:
    app, _mcp = montar()
    # ASGITransport não roda lifespan: entra no do FastAPI à mão (como o TestClient faria)
    async with app.router.lifespan_context(app):
        await bateria("asgi", "http://127.0.0.1/mcp/", lambda: httpx2.ASGITransport(app=app))

        # Host do tailnet aceito; Host estranho recusado (DNS rebinding)
        async with httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), timeout=10) as http:
            h = {"Accept": "application/json, text/event-stream", "Authorization": "Bearer tok-ler"}
            corpo = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "spike", "version": "0"},
                },
            }
            r = await http.post(f"https://{HOST_TAILNET}/mcp/", json=corpo, headers=h)
            marca("asgi: Host do tailnet aceito", r.status_code == 200, str(r.status_code))
            r = await http.post("http://malvado.exemplo/mcp/", json=corpo, headers=h)
            marca("asgi: Host estranho → 421", r.status_code == 421, str(r.status_code))
            r = await http.get("http://127.0.0.1/mcp/.well-known/oauth-protected-resource/mcp")
            r2 = await http.get("http://127.0.0.1/.well-known/oauth-protected-resource/mcp")
            marca(
                "asgi: metadado RFC 9728 fica em /mcp/.well-known/… (não na raiz)",
                r.status_code == 200 and r2.status_code == 404,
                f"{r.status_code}/{r2.status_code}",
            )

    # escopo desligado não é registrado
    _app2, mcp2 = montar(escopos_ligados=("ler",))
    nomes = sorted(t.name for t in await mcp2.list_tools())
    marca("registro: escopo 'tarefas' desligado some do list_tools", nomes == ["estado"], str(nomes))
    _app3, mcp3 = montar(escopos_ligados=("ler", "tarefas", "casa"))
    nomes = sorted(t.name for t in await mcp3.list_tools())
    marca("registro: escopo 'casa' ligado aparece", "tv_acao" in nomes, str(nomes))


def _porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def com_uvicorn() -> None:
    app, mcp = montar()
    porta = _porta_livre()
    srv = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=porta, log_level="warning", lifespan="on")
    )
    tarefa = asyncio.create_task(srv.serve())
    for _ in range(200):
        if srv.started:
            break
        await asyncio.sleep(0.02)
    try:
        await bateria("uvicorn", f"http://127.0.0.1:{porta}/mcp/", lambda: None)
        aud = mcp.auditoria  # type: ignore[attr-defined]
        marca(
            "uvicorn: auditoria viu ok e recusa",
            any(not a[2] for a in aud) and any(a[2] for a in aud),
            str(aud[:4]),
        )
    finally:
        srv.should_exit = True
        await tarefa


async def main() -> int:
    warnings.simplefilter("default")
    await em_memoria()
    await com_uvicorn()
    falhas = [n for n, ok, _ in RESULTADOS if not ok]
    print(f"\n{len(RESULTADOS) - len(falhas)}/{len(RESULTADOS)} ok")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
