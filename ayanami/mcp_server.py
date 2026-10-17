"""Servidor MCP da Ayanami (dono: Y5.1; R5, R5.1–R5.4, D13a, spec §8, design §4.5, spike S3).

``MCPServer`` (``mcp`` 2.3) montado no próprio ``ayanami-api`` em ``/mcp`` (o cliente usa
``/mcp/`` com barra; ``/mcp`` → 307). Pontos que o spike S3 fixou:

- ``streamable_http_path="/"`` vai em ``streamable_http_app(...)``, não no construtor;
- o ``Mount`` não roda o lifespan do sub-app: :func:`montar` põe ``mcp.session_manager.run`` em
  ``ctx.ciclo`` (o lifespan do FastAPI entra nele);
- ``TransportSecuritySettings`` com o host de ``[geral] url_base`` (tailnet), o domínio público e
  ``127.0.0.1``/``localhost`` — senão ``Host`` do tailnet → 421;
- ``AuthSettings(validate_token_resource=False)``; ``required_scopes=["ler"]`` barra no HTTP (403).

Auth: :class:`VerificadorAyanami` aceita só token de tipo ``mcp`` não revogado (pelo
``Autenticador`` da app, cache de 5 s) e devolve ``AccessToken`` com ``client_id`` = id do
dispositivo e ``scopes`` = escopos do token. Cada tool chama :func:`exigir` (falta →
``ToolError("escopo: …")``, ``is_error`` no resultado) e toda chamada vai à ``auditoria``
(``tipo='mcp'``, ``alvo`` = tool, ``resumo`` sem texto livre longo).

Registro (D13a): tools e resources só entram se o escopo estiver em ``[mcp] escopos``
(``memoria_buscar`` também precisa de ``[mcp] memoria_ler``). ``tv_acao`` com intent ``danger``
(``tv.power_off``) vira ``confirmacoes`` (Y2.2): a ``acao`` só sai se o Pedro aceitar em 120 s.
``noticias_*`` nunca devolvem texto de item marcado spoiler (só a manchete segura).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any, Final
from urllib.parse import urlsplit
from uuid import UUID

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

from ayanami import confirmacoes as conf_mod
from ayanami import tarefas as tf
from ayanami.api import auditoria
from ayanami.api.auth import iso_z
from ayanami.api.casa import para_json, pedir_acao, servicos
from ayanami.hub import hub_de
from magi.elo.mensagens import AcaoPedido

log = logging.getLogger("ayanami.mcp")

DOMINIO_PUBLICO: Final = "ayanami.dekasis.com.br"
ESCOPOS: Final = ("ler", "tarefas", "casa", "memoria-escrever")
TIPOS_TAREFA: Final = ("pesquisa", "resumo")
ESTADOS_TAREFA: Final = ("na_fila", "rodando", *tf.TERMINAIS)
SPOILER_TITULO: Final = "(spoiler escondido)"
MAX_FATO: Final = 500


# --------------------------------------------------------------------------- auth


class VerificadorAyanami:
    """``TokenVerifier`` (Protocol do ``mcp``): tipo ``mcp``, não revogado; ``scopes`` = escopos."""

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            disp = await asyncio.to_thread(self.ctx.auth.verificar, token)
        except Exception as e:  # noqa: BLE001 - banco fora → recusa (401), não 500
            log.warning("mcp_verificar_falhou (%s)", type(e).__name__)
            return None
        if disp is None or disp.tipo != "mcp" or disp.revogado is not None:
            return None
        return AccessToken(token=token, client_id=str(disp.id), scopes=sorted(disp.escopos))


def _disp_id(tok: AccessToken | None) -> int | None:
    try:
        return int(tok.client_id) if tok is not None else None
    except (TypeError, ValueError):
        return None


def exigir(escopo: str, ligados: Iterable[str] | None = None) -> AccessToken:
    """Token do pedido com ``escopo`` (e o escopo ligado em ``[mcp] escopos``), ou ``ToolError``."""
    tok = get_access_token()
    if tok is None:
        raise ToolError("escopo: sem token")
    if ligados is not None and escopo not in ligados:
        raise ToolError(f"escopo: '{escopo}' desligado em [mcp] escopos")
    if escopo not in tok.scopes:
        raise ToolError(f"escopo: falta '{escopo}'")
    return tok


# --------------------------------------------------------------------------- serviço


class ServicoMcp:
    """As tools/resources em cima do ``Contexto`` da app (banco, relógio, hub, fila)."""

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self.ligados = frozenset(ctx.cfg.mcp.escopos)

    # --- auditoria + escopo -------------------------------------------------------------------

    @asynccontextmanager
    async def chamada(self, alvo: str, escopo: str, resumo: str = "") -> AsyncIterator[dict[str, Any]]:
        """Checa o escopo e audita a chamada (``ok`` falso se ela levantar ou se ``r["ok"]`` cair)."""
        disp_id = _disp_id(get_access_token())
        r: dict[str, Any] = {"ok": False, "resumo": resumo, "disp": disp_id}
        try:
            exigir(escopo, self.ligados)
            r["ok"] = True
            yield r
        except BaseException as e:
            r["ok"] = False
            if isinstance(e, ToolError):
                r["resumo"] = f"{r['resumo']} erro={str(e)[:80]}".strip()
            raise
        finally:
            await self._auditar(alvo, r["resumo"], bool(r["ok"]), disp_id)

    async def _auditar(self, alvo: str, resumo: str, ok: bool, disp_id: int | None) -> None:
        try:
            await asyncio.to_thread(auditoria.registrar, self.ctx.db, tipo="mcp", alvo=alvo,
                                    resumo=resumo or alvo, ok=ok, dispositivo=disp_id)
        except Exception as e:  # noqa: BLE001 - auditoria não derruba a tool
            log.warning("auditoria_mcp_falhou (%s)", type(e).__name__)

    # --- notícias -----------------------------------------------------------------------------

    _SQL_NOTICIAS = (
        "SELECT i.uid, i.title, i.summary, i.franchise, i.first_seen,"
        " COALESCE(i.spoiler->>'has', '') = 'true' AS tem_spoiler, i.spoiler->>'safe_title',"
        " COALESCE((SELECT array_agg(r.url ORDER BY r.id) FROM news_item_sources s"
        "           JOIN news_raw r ON r.id = s.raw_id WHERE s.item_id = i.id), '{}')"
        " FROM news_items i"
    )

    @staticmethod
    def _item(r: Any) -> dict[str, Any]:
        uid, titulo, resumo, franquia, data, spoiler, seguro, fontes = r
        if spoiler:  # nunca o texto do item marcado: só a manchete segura, sem resumo nem URL
            return {"uid": str(uid), "titulo": seguro or SPOILER_TITULO, "resumo": None,
                    "franquia": franquia, "data": iso_z(data), "fontes": [], "spoiler": True}
        return {"uid": str(uid), "titulo": titulo, "resumo": resumo, "franquia": franquia,
                "data": iso_z(data), "fontes": list(fontes or []), "spoiler": False}

    def _buscar(self, consulta: str, limite: int, dias: int) -> list[dict[str, Any]]:
        padrao = "%" + consulta.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        desde = self.ctx.relogio.agora() - timedelta(days=dias)
        sql = (
            self._SQL_NOTICIAS
            + " WHERE i.first_seen >= %(desde)s AND ("
            "  (COALESCE(i.spoiler->>'has', '') <> 'true'"
            "   AND (i.title ILIKE %(q)s OR i.summary ILIKE %(q)s OR i.franchise ILIKE %(q)s))"
            "  OR (COALESCE(i.spoiler->>'has', '') = 'true'"
            "   AND (i.spoiler->>'safe_title' ILIKE %(q)s OR i.franchise ILIKE %(q)s)))"
            " ORDER BY i.first_seen DESC, i.id DESC LIMIT %(n)s"
        )
        with self.ctx.db.connection() as conn:
            rs = conn.execute(sql, {"desde": desde, "q": padrao, "n": limite}).fetchall()
        return [self._item(r) for r in rs]

    def _ultimas(self, limite: int) -> list[dict[str, Any]]:
        with self.ctx.db.connection() as conn:
            rs = conn.execute(self._SQL_NOTICIAS + " ORDER BY i.first_seen DESC, i.id DESC LIMIT %s",
                              (limite,)).fetchall()
        return [self._item(r) for r in rs]

    def _noticia(self, uid: str) -> dict[str, Any] | None:
        try:
            u = UUID(uid)
        except ValueError:
            return None
        with self.ctx.db.connection() as conn:
            r = conn.execute(self._SQL_NOTICIAS + " WHERE i.uid = %s", (u,)).fetchone()
        return self._item(r) if r else None

    # --- estado -------------------------------------------------------------------------------

    def _fila_e_backup(self) -> tuple[dict[str, int], str | None]:
        fila: dict[str, int] = {}
        with self.ctx.db.connection() as conn:
            ultimo = conn.execute("SELECT max(enviado) FROM backups").fetchone()[0]
            existe = conn.execute("SELECT to_regclass('procrastinate_jobs')").fetchone()[0]
            if existe is not None:
                for status, n in conn.execute(
                        "SELECT status::text, count(*) FROM procrastinate_jobs GROUP BY status"):
                    fila[status] = n
        return fila, iso_z(ultimo)

    async def estado(self) -> dict[str, Any]:
        hub = hub_de(self.ctx)
        casa = hub.estado_casa()
        fila, ultimo = await asyncio.to_thread(self._fila_e_backup)
        return {"pc_online": hub.online("pc"), "casa_online": casa.online,
                "tvs": para_json(casa.estados), "fila": fila, "ultimo_backup": ultimo}

    # --- montagem -----------------------------------------------------------------------------

    def registrar(self, mcp: MCPServer) -> list[str]:
        """Registra o que os escopos ligados permitem; devolve os nomes das tools."""
        nomes: list[str] = []
        if "ler" in self.ligados:
            nomes += self._registrar_ler(mcp)
        if "tarefas" in self.ligados:
            nomes += self._registrar_tarefas(mcp)
        if "casa" in self.ligados:
            nomes += self._registrar_casa(mcp)
        if "memoria-escrever" in self.ligados:
            nomes += self._registrar_memoria(mcp)
        if "ler" in self.ligados and self.ctx.cfg.mcp.memoria_ler:
            nomes += self._registrar_memoria_ler(mcp)
        return nomes

    def _registrar_ler(self, mcp: MCPServer) -> list[str]:
        svc = self

        @mcp.tool()
        async def noticias_buscar(consulta: str, limite: int = 10, dias: int = 14) -> list[dict[str, Any]]:
            """Busca notícias recentes por texto (título, resumo, franquia). Spoiler nunca é revelado."""
            async with svc.chamada("noticias_buscar", "ler",
                                   f"consulta={len(consulta)}c limite={limite} dias={dias}"):
                if not 1 <= len(consulta.strip()) <= 200:
                    raise ToolError("consulta: 1 a 200 caracteres")
                if not 1 <= limite <= 30 or not 1 <= dias <= 365:
                    raise ToolError("limite: 1 a 30; dias: 1 a 365")
                return await asyncio.to_thread(svc._buscar, consulta.strip(), limite, dias)

        @mcp.tool()
        async def noticias_ultimas(limite: int = 10) -> list[dict[str, Any]]:
            """Últimas notícias (por first_seen). Spoiler nunca é revelado."""
            async with svc.chamada("noticias_ultimas", "ler", f"limite={limite}"):
                if not 1 <= limite <= 30:
                    raise ToolError("limite: 1 a 30")
                return await asyncio.to_thread(svc._ultimas, limite)

        @mcp.tool()
        async def tarefas_listar(estado: str | None = None, limite: int = 20) -> list[dict[str, Any]]:
            """Tarefas da Ayanami (mais recentes primeiro), opcionalmente por estado."""
            async with svc.chamada("tarefas_listar", "ler", f"estado={estado or '-'} limite={limite}"):
                if estado is not None and estado not in ESTADOS_TAREFA:
                    raise ToolError(f"estado: um de {', '.join(ESTADOS_TAREFA)}")
                if not 1 <= limite <= 50:
                    raise ToolError("limite: 1 a 50")
                ts = await asyncio.to_thread(tf.listar_tarefas, svc.ctx.db, estado, limite)
                return [t.para_json() for t in ts]

        @mcp.tool()
        async def tarefa_ver(id: str) -> dict[str, Any]:  # noqa: A002 - nome da spec §8
            """Uma tarefa pelo id."""
            async with svc.chamada("tarefa_ver", "ler", f"id={id[:40]}"):
                return (await svc._tarefa(id)).para_json()

        @mcp.tool()
        async def estado() -> dict[str, Any]:
            """PC e casa online, estado das TVs, fila e último backup."""
            async with svc.chamada("estado", "ler"):
                return await svc.estado()

        @mcp.resource("ayanami://noticias/{uid}", mime_type="application/json")
        async def noticia(uid: str) -> str:
            """Texto de uma notícia (sem spoiler revelado)."""
            async with svc.chamada("ayanami://noticias", "ler", f"uid={uid[:40]}"):
                item = await asyncio.to_thread(svc._noticia, uid)
                if item is None:
                    raise ToolError("noticia: nao_encontrada")
                return json.dumps(item, ensure_ascii=False)

        @mcp.resource("ayanami://tarefas/{id}", mime_type="application/json")
        async def tarefa(id: str) -> str:  # noqa: A002
            """Uma tarefa (TarefaOut em JSON)."""
            async with svc.chamada("ayanami://tarefas", "ler", f"id={id[:40]}"):
                return json.dumps((await svc._tarefa(id)).para_json(), ensure_ascii=False)

        @mcp.resource("ayanami://estado", mime_type="application/json")
        async def estado_res() -> str:
            """Estado da Ayanami (igual à tool ``estado``)."""
            async with svc.chamada("ayanami://estado", "ler"):
                return json.dumps(await svc.estado(), ensure_ascii=False)

        return ["noticias_buscar", "noticias_ultimas", "tarefas_listar", "tarefa_ver", "estado"]

    async def _tarefa(self, id_: str) -> tf.TarefaOut:
        try:
            u = UUID(id_)
        except ValueError as e:
            raise ToolError("id: uuid inválido") from e
        t = await asyncio.to_thread(tf.obter_tarefa, self.ctx.db, u)
        if t is None:
            raise ToolError("tarefa: nao_encontrada")
        return t

    def _registrar_tarefas(self, mcp: MCPServer) -> list[str]:
        svc = self

        @mcp.tool()
        async def tarefa_criar(tipo: str, titulo: str, pedido: str,
                               chave: str | None = None) -> dict[str, Any]:
            """Cria uma tarefa (pesquisa|resumo) na fila da Ayanami; idempotente pela chave."""
            resumo = f"tipo={tipo[:20]} pedido={len(pedido)}c chave={'s' if chave else 'n'}"
            async with svc.chamada("tarefa_criar", "tarefas", resumo) as r:
                if tipo not in TIPOS_TAREFA:
                    raise ToolError(f"tipo: um de {', '.join(TIPOS_TAREFA)}")
                t = tf.TarefaIn(tipo=tipo, titulo=titulo, params={"pedido": pedido}, chave=chave)  # type: ignore[arg-type]
                try:
                    out, criada = await tf.criar_tarefa(svc.ctx.db, t, r["disp"],
                                                        app=svc.ctx.extras.get("fila"),
                                                        relogio=svc.ctx.relogio)
                except tf.TarefaInvalida as e:
                    raise ToolError(f"{e.campo}: {e.msg}") from e
                r["resumo"] += f" id={out.id} {'nova' if criada else 'existente'}"
                return out.para_json()

        @mcp.tool()
        async def tarefa_cancelar(id: str) -> dict[str, Any]:  # noqa: A002
            """Cancela uma tarefa na fila (ou pede abort se já está rodando)."""
            async with svc.chamada("tarefa_cancelar", "tarefas", f"id={id[:40]}"):
                try:
                    u = UUID(id)
                except ValueError as e:
                    raise ToolError("id: uuid inválido") from e
                try:
                    est = await tf.cancelar_tarefa(svc.ctx.db, u, app=svc.ctx.extras.get("fila"),
                                                   relogio=svc.ctx.relogio)
                except tf.TarefaNaoEncontrada as e:
                    raise ToolError("tarefa: nao_encontrada") from e
                except tf.JaTerminou as e:
                    raise ToolError(f"tarefa: ja_terminou ({e.estado})") from e
                return {"estado": est}

        return ["tarefa_criar", "tarefa_cancelar"]

    def _registrar_casa(self, mcp: MCPServer) -> list[str]:
        svc = self

        @mcp.tool()
        async def tv_acao(intent: str, tv: str | None = None,
                          slots: dict[str, str] | None = None) -> dict[str, Any]:
            """Ação numa TV da casa (só intents ``tv.*``). Desligar pede confirmação do Pedro (120 s)."""
            async with svc.chamada("tv_acao", "casa", f"intent={intent[:40]} tv={(tv or '-')[:32]}") as r:
                if not intent.startswith("tv.") or len(intent) > 64:
                    raise ToolError("intent: só tv.*")
                pares = tuple((str(k), str(v)) for k, v in (slots or {}).items())
                pedido = AcaoPedido(intent=intent, slots=pares)
                status, corpo = await pedir_acao(svc.ctx, None, tv, pedido, "mcp", dispositivo_id=r["disp"])
                if status == 202:
                    c = await asyncio.to_thread(conf_mod.obter, svc.ctx.db, corpo["confirma"])
                    r["resumo"] += f" confirmacao={corpo['confirma']}"
                    return {"confirmacao": corpo["confirma"], "expira_em": iso_z(c.expira) if c else None}
                if status >= 400:
                    raise ToolError(f"{corpo.get('erro')}: {corpo.get('msg', '')}")
                r["ok"] = bool(corpo.get("ok", True))
                return corpo

        return ["tv_acao"]

    def _registrar_memoria(self, mcp: MCPServer) -> list[str]:
        svc = self

        @mcp.tool()
        async def memoria_gravar(fato: str) -> dict[str, Any]:
            """Propõe gravar um fato na memória da Condessa; sempre pede confirmação no PC."""
            async with svc.chamada("memoria_gravar", "memoria-escrever", f"fato={len(fato)}c") as r:
                if not 1 <= len(fato.strip()) <= MAX_FATO:
                    raise ToolError(f"fato: 1 a {MAX_FATO} caracteres")
                hub, conf = servicos(svc.ctx)
                if not hub.online("pc"):
                    raise ToolError("pc_offline")
                c = await conf.criar(descricao=f"Gravar na memória: {fato.strip()}",
                                     pedido={"tipo": "memoria.gravar", "origem": "mcp", "fato": fato.strip()},
                                     origem=r["disp"])
                r["resumo"] += f" confirmacao={c.id}"
                return {"confirmacao": c.id, "expira_em": iso_z(c.expira)}

        return ["memoria_gravar"]

    def _registrar_memoria_ler(self, mcp: MCPServer) -> list[str]:
        svc = self

        @mcp.tool()
        async def memoria_buscar(consulta: str) -> list[dict[str, Any]]:
            """Busca na memória (só leitura; depende de D6/D13)."""
            async with svc.chamada("memoria_buscar", "ler", f"consulta={len(consulta)}c"):
                raise ToolError("memoria_indisponivel: D6/D13 pendentes")

        return ["memoria_buscar"]


# --------------------------------------------------------------------------- montagem


def hosts_permitidos(url_base: str) -> tuple[list[str], list[str]]:
    """``(allowed_hosts, allowed_origins)`` da proteção contra DNS rebinding (S3)."""
    u = urlsplit(url_base)
    hosts = [h for h in dict.fromkeys([u.netloc, u.hostname or "", DOMINIO_PUBLICO]) if h]
    allowed = [*hosts, "127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*"]
    origens = [*(f"https://{h}" for h in hosts), "http://127.0.0.1", "http://127.0.0.1:*",
               "http://localhost", "http://localhost:*"]
    return allowed, origens


def criar_mcp(ctx: Any) -> tuple[MCPServer, Any]:
    """``(mcp, sub_app)`` ligados ao ``Contexto`` da app."""
    base = ctx.cfg.geral.url_base.rstrip("/")
    mcp = MCPServer(
        "ayanami",
        instructions="Ayanami: notícias, tarefas e estado da casa da Condessa.",
        token_verifier=VerificadorAyanami(ctx),
        auth=AuthSettings(issuer_url=base, resource_server_url=f"{base}/mcp/",
                          required_scopes=["ler"], validate_token_resource=False),
    )
    servico = ServicoMcp(ctx)
    mcp.ferramentas_ayanami = servico.registrar(mcp)  # type: ignore[attr-defined]
    hosts, origens = hosts_permitidos(base)
    sub = mcp.streamable_http_app(
        streamable_http_path="/",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True, allowed_hosts=hosts, allowed_origins=origens),
    )
    return mcp, sub


def montar(app: Any) -> MCPServer:
    """Monta em ``/mcp`` e põe ``session_manager.run`` no lifespan (``ctx.ciclo``)."""
    ctx = app.state.ctx
    mcp, sub = criar_mcp(ctx)
    app.mount("/mcp", sub)
    ctx.ciclo.append(mcp.session_manager.run)
    ctx.extras["mcp"] = mcp
    return mcp
