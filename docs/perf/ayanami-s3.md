# Spike S3 — MCP `mcp` 2.3 (parte local)

Tarefa Y0.5 de `specs/ayanami-central/tasks.md`. Rodado no PC (2026-10-12), só em `127.0.0.1`, sem
banco (verificador com tabela falsa de tokens `tok-…`):
`uv run --with 'mcp==2.3.*' python spikes/ayanami_s3_mcp.py` → **28/28 ok** (o `uv.lock` já fixa
`mcp==2.3.0`; o `--with` não muda nada). O cliente é o da própria lib (`mcp.Client` +
`streamable_http_client` sobre `httpx2`), contra o ASGI em memória (`httpx2.ASGITransport`) e
contra `uvicorn` em porta efêmera. A parte "pelo tailnet" (`claude mcp add`, `mcp-remote` no
Desktop) fica na Y1.6.

**Veredito: montagem no próprio `ayanami-api` confirmada.** A alternativa da §17 ("processo/porta
própria") não é necessária.

## O que foi confirmado

| item | resultado |
| --- | --- |
| `app.mount("/mcp", mcp.streamable_http_app(streamable_http_path="/"))` num FastAPI | funciona; rotas vizinhas (`/saude`) intactas |
| `TokenVerifier` próprio (Protocol, só `verify_token`) | tipo `pc`, revogado ou desconhecido → `None` → **401** `invalid_token` |
| `AuthSettings(required_scopes=["ler"])` | token `mcp` sem `ler` → **403** `insufficient_scope` antes do MCP |
| `get_access_token()` dentro da tool | devolve o `AccessToken` do pedido (`client_id`, `scopes`) |
| `exigir("tarefas")` com `ToolError` | `call_tool` volta `is_error=True`, texto `Error executing tool tarefa_criar: escopo: falta 'tarefas'` (a sessão segue viva) |
| escopo desligado não registrado | `list_tools` só mostra o que foi registrado (`tv_acao` só com `casa`) |
| cliente em `…/mcp` (sem barra) | Starlette responde **307 → `…/mcp/`**; o cliente MCP segue (mesma origem) |
| `Host` do tailnet | aceito só se estiver em `transport_security.allowed_hosts`; `Host` estranho → **421** |

## Diferenças para o bloco da spec §8 (já corrigido lá)

1. **`streamable_http_path` é argumento de `streamable_http_app(...)`**, não do construtor
   `MCPServer(...)` (o construtor nem aceita).
2. **Lifespan:** o `Mount` do FastAPI não roda o lifespan do sub-app Starlette do MCP. Sem
   `async with mcp.session_manager.run()` no lifespan do FastAPI, todo pedido estoura
   `RuntimeError: Task group is not initialized. Make sure to use run().` (`session_manager` só
   existe depois de chamar `streamable_http_app()`).
3. **`AuthSettings(validate_token_resource=False)`**: com `resource_server_url` e sem esse campo a
   2.3 emite `MCPDeprecationWarning` (na 3.0 o padrão vira `True` e exigiria
   `AccessToken.resource`). Nosso verificador já checa tipo/revogação; deixamos `False`.
4. **Proteção contra DNS rebinding:** `streamable_http_app(host="127.0.0.1")` (padrão) liga a
   proteção só com `127.0.0.1:*`/`localhost:*` — pedido com `Host: ayanami.<tailnet>.ts.net`
   (o que o `tailscale serve` repassa) toma **421**. Passar
   `transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=True,
   allowed_hosts=[<host do tailnet>, "127.0.0.1:*", "localhost:*"], allowed_origins=[…])`.
   Atenção: `"127.0.0.1:*"` não casa `Host: 127.0.0.1` sem porta (precisa listar os dois).
5. **URL com barra:** o MCP responde em `/mcp/`; `/mcp` leva 307. Atrás do `tailscale serve`
   (TLS termina fora), o `Location` sai `http://…` se o uvicorn não confiar nos cabeçalhos do
   proxy, e o cliente MCP **recusa** redirect https→http. Portanto: registrar o cliente em
   **`https://ayanami.<tailnet>.ts.net/mcp/`** (com barra) e `resource_server_url` idem; ou rodar o
   uvicorn com `--proxy-headers --forwarded-allow-ips=127.0.0.1`. A Y1.6 confere ao vivo.
6. **Metadado RFC 9728** (`/.well-known/oauth-protected-resource/mcp`) fica dentro do Mount
   (`/mcp/.well-known/…`), não na raiz. Irrelevante para o nosso uso (token fixo no cabeçalho, sem
   OAuth/descoberta); se algum cliente exigir descoberta, a Y5.1 expõe a rota na raiz do FastAPI.

## Notas para a Y5.1

- `exigir()` deve levantar `ToolError("escopo: …")` (vira `is_error` no resultado, não erro de
  protocolo) e gravar `auditoria ok=false` antes de relançar.
- `required_scopes=["ler"]` já barra no HTTP token sem `ler`; a checagem por tool continua
  necessária para `tarefas`/`casa`/`memoria-escrever`.
- O cliente 2.3 em modo `auto` tenta `discover` e cai para `initialize` (legado) sem problema
  com o servidor 2.3; nenhum ajuste foi preciso.
