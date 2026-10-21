"""Servidor MCP da Ayanami (dono: Y5.1; spec §8, design §4.5; R5, R5.1–R5.4, D13a).

- :class:`VerificadorAyanami`: ``TokenVerifier`` que só aceita token de dispositivo tipo ``mcp`` não
  revogado (pelo :class:`~ayanami.api.auth.Autenticador`, cache de 5 s); ``scopes`` = escopos do
  dispositivo; ``claims["dispositivo"]`` = id (para a auditoria).
- :func:`montar` monta o ``MCPServer`` em ``/mcp`` da app FastAPI (o cliente usa ``/mcp/``) e põe
  ``mcp.session_manager.run`` em ``ctx.ciclo`` (o ``Mount`` não roda o lifespan do sub-app; S3).
- Tools só são **registradas** para escopos ligados em ``[mcp] escopos`` (padrão D13a ``ler`` +
  ``tarefas``) e checadas por chamada com :func:`exigir`. Toda chamada (tool e resource) grava
  ``auditoria(tipo='mcp', alvo=<tool>, resumo=<parâmetros curtos>, ok)``.
- ``tv_acao`` com intent ``danger`` (``tv.power_off``) → ``confirmacoes`` (Y2.2, 120 s); um vigia
  pelo relógio injetado audita ``ok=false`` se vencer sem resposta (a ação nunca roda).
- ``memoria_gravar`` → sempre ``confirma`` no PC (PC offline → erro ``pc_offline``).
- Notícias: item com ``spoiler.has`` nunca devolve ``title``/``summary`` (só ``safe_title``) e a busca
  nesses itens só casa com o ``safe_title``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Annotated, Any
from urllib.parse import urlparse

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import Field

from ayanami import confirmacoes as conf_mod
from ayanami import tarefas as tf
from ayanami.api import auditoria
from ayanami.api.auth import iso_z

log = logging.getLogger("ayanami.mcp")

ESCOPO_DAS_TOOLS: dict[str, str] = {
    "noticias_buscar": "ler", "noticias_ultimas": "ler", "tarefas_listar": "ler",
    "tarefa_ver": "ler", "estado": "ler", "tarefa_criar": "tarefas", "tarefa_cancelar": "tarefas",
    "tv_acao": "casa", "memoria_gravar": "memoria-escrever",
}
# campo principal de ``params`` que recebe o ``pedido`` da tool ``tarefa_criar``
CAMPO_DO_PEDIDO = {"pesquisa": "pedido", "resumo": "pedido", "lembrete": "texto", "monitor": "o_que"}
FATO_MAX = 500


# --------------------------------------------------------------------------- verificador


class VerificadorAyanami:
    """``TokenVerifier``: tipo ``mcp``, não revogado; ``scopes`` = escopos do dispositivo."""

    def __init__(self, autenticador: Any) -> None:
        self.auth = autenticador

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            disp = await asyncio.to_thread(self.auth.verificar, token)
        except Exception as e:  # noqa: BLE001 - banco fora → recusa (401), não 500
            log.warning("mcp_verificar_falhou (%s)", type(e).__name__)
            return None
        if disp is None or disp.tipo != "mcp" or disp.revogado is not None:
            return None
        return AccessToken(token=token, client_id=disp.nome, scopes=sorted(disp.escopos),
                           claims={"dispositivo": disp.id})


def exigir(escopo: str) -> AccessToken:
    """Token do pedido com ``escopo``; falta → ``ToolError("escopo: …")`` (vira ``is_error``)."""
    tok = get_access_token()
    if tok is None or escopo not in tok.scopes:
        raise ToolError(f"escopo: falta '{escopo}'")
    return tok


def _disp_id(tok: AccessToken | None) -> int | None:
    v = (tok.claims or {}).get("dispositivo") if tok is not None else None
    return v if isinstance(v, int) else None


# --------------------------------------------------------------------------- notícias


def _spoiler(sp: Any) -> bool:
    return isinstance(sp, dict) and bool(sp.get("has"))


_TEXTO_BUSCA = ("(CASE WHEN coalesce((i.spoiler->>'has')::boolean, false)"
                " THEN coalesce(i.spoiler->>'safe_title', '')"
                " ELSE i.title || ' ' || coalesce(i.summary, '') END)")

_SELECT_NOTICIA = """
SELECT i.uid::text, i.title, i.summary, i.franchise, i.first_seen, i.spoiler,
       coalesce((SELECT array_agg(r.url ORDER BY r.id) FROM news_item_sources s
                 JOIN news_raw r ON r.id = s.raw_id WHERE s.item_id = i.id), '{}')
FROM news_items i
"""


def _noticia(r: Any) -> dict[str, Any]:
    uid, title, summary, franquia, data, sp, fontes = r
    if _spoiler(sp):
        title = (sp.get("safe_title") or "").strip() or "[spoiler]"
        summary = None
    return {"uid": uid, "titulo": title, "resumo": summary, "franquia": franquia,
            "data": iso_z(data), "fontes": list(fontes or [])}


def buscar_noticias(db: Any, agora: Any, consulta: str, limite: int, dias: int) -> list[dict]:
    padrao = "%" + consulta.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    with db.connection() as conn:
        linhas = conn.execute(
            _SELECT_NOTICIA + f" WHERE i.first_seen >= %s AND {_TEXTO_BUSCA} ILIKE %s"
            " ORDER BY i.first_seen DESC, i.id DESC LIMIT %s",
            (agora - timedelta(days=dias), padrao, limite),
        ).fetchall()
        if not conn.autocommit:
            conn.rollback()
    return [_noticia(r) for r in linhas]


def ultimas_noticias(db: Any, limite: int) -> list[dict]:
    with db.connection() as conn:
        linhas = conn.execute(_SELECT_NOTICIA + " ORDER BY i.first_seen DESC, i.id DESC LIMIT %s",
                              (limite,)).fetchall()
        if not conn.autocommit:
            conn.rollback()
    return [_noticia(r) for r in linhas]


def noticia(db: Any, uid: str) -> dict | None:
    with db.connection() as conn:
        r = conn.execute(_SELECT_NOTICIA + " WHERE i.uid::text = %s", (uid,)).fetchone()
        if not conn.autocommit:
            conn.rollback()
    return _noticia(r) if r else None


# --------------------------------------------------------------------------- servidor


class ServidorMcp:
    """As tools e resources da §8 sobre o ``Contexto`` da app (``app.state.ctx``)."""

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        url = ctx.cfg.geral.url_base.rstrip("/")
        self.host = urlparse(url).netloc
        self.escopos = frozenset(ctx.cfg.mcp.escopos)
        self.vigias: set[asyncio.Task[Any]] = set()
        self.mcp = MCPServer(
            "ayanami",
            token_verifier=VerificadorAyanami(ctx.auth),
            auth=AuthSettings(issuer_url=url, resource_server_url=f"{url}/mcp/",
                              required_scopes=["ler"], validate_token_resource=False),
        )
        self._registrar()

    def app_asgi(self) -> Any:
        return self.mcp.streamable_http_app(
            streamable_http_path="/",
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=[self.host, "127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*"],
                allowed_origins=[f"https://{self.host}", "http://127.0.0.1", "http://127.0.0.1:*",
                                 "http://localhost:*"],
            ),
        )

    # ---------------------------------------------------------------- auditoria e chamada

    async def _auditar(self, disp_id: int | None, alvo: str, resumo: str, ok: bool) -> None:
        try:
            await asyncio.to_thread(auditoria.registrar, self.ctx.db, tipo="mcp", alvo=alvo,
                                    resumo=resumo, ok=ok, dispositivo=disp_id)
        except Exception as e:  # noqa: BLE001 - auditoria não derruba a chamada
            log.warning("auditoria_mcp_falhou (%s)", type(e).__name__)

    async def chamar(self, alvo: str, escopo: str, resumo: str,
                     corpo: Callable[[int | None], Awaitable[Any]]) -> Any:
        """Checa o escopo, roda ``corpo(dispositivo_id)`` e audita (``ok`` = sem erro)."""
        tok = get_access_token()
        disp_id = _disp_id(tok)
        try:
            exigir(escopo)
        except ToolError:
            await self._auditar(disp_id, alvo, f"{resumo} escopo".strip(), False)
            raise
        try:
            saida = await corpo(disp_id)
        except ToolError as e:
            await self._auditar(disp_id, alvo, f"{resumo} erro={str(e)[:60]}".strip(), False)
            raise
        except Exception as e:
            await self._auditar(disp_id, alvo, f"{resumo} erro={type(e).__name__}".strip(), False)
            log.exception("mcp_tool_falhou (%s)", alvo)
            raise ToolError("erro_interno") from e
        await self._auditar(disp_id, alvo, resumo, True)
        return saida

    # ---------------------------------------------------------------- tools

    def _ligada(self, tool: str) -> bool:
        return ESCOPO_DAS_TOOLS[tool] in self.escopos

    def _registrar(self) -> None:  # noqa: C901 - uma closure por tool, de propósito
        mcp, ctx, db = self.mcp, self.ctx, self.ctx.db

        @mcp.tool()
        async def noticias_buscar(
            consulta: Annotated[str, Field(min_length=1, max_length=200)],
            limite: Annotated[int, Field(ge=1, le=30)] = 10,
            dias: Annotated[int, Field(ge=1, le=365)] = 14,
        ) -> list[dict[str, Any]]:
            """Busca notícias recentes por texto (sem revelar spoiler)."""
            async def corpo(_: int | None) -> Any:
                return await asyncio.to_thread(buscar_noticias, db, ctx.relogio.agora(), consulta,
                                               limite, dias)
            return await self.chamar("noticias_buscar", "ler",
                                     f"consulta={len(consulta)}c limite={limite} dias={dias}", corpo)

        @mcp.tool()
        async def noticias_ultimas(limite: Annotated[int, Field(ge=1, le=30)] = 10) -> list[dict[str, Any]]:
            """Últimas notícias por primeira aparição (sem revelar spoiler)."""
            async def corpo(_: int | None) -> Any:
                return await asyncio.to_thread(ultimas_noticias, db, limite)
            return await self.chamar("noticias_ultimas", "ler", f"limite={limite}", corpo)

        @mcp.tool()
        async def tarefas_listar(
            estado: str | None = None, limite: Annotated[int, Field(ge=1, le=200)] = 20,
        ) -> list[dict[str, Any]]:
            """Tarefas da fila (mais recentes primeiro), opcionalmente por estado."""
            async def corpo(_: int | None) -> Any:
                if estado is not None and estado not in tf.ESTADO_DO_JOB.values():
                    raise ToolError("estado desconhecido")
                lista = await asyncio.to_thread(tf.listar_tarefas, db, estado, limite)
                return [t.para_json() for t in lista]
            return await self.chamar("tarefas_listar", "ler", f"estado={estado} limite={limite}", corpo)

        @mcp.tool()
        async def tarefa_ver(id: str) -> dict[str, Any]:
            """Uma tarefa pelo id."""
            async def corpo(_: int | None) -> Any:
                return (await self._tarefa(id)).para_json()
            return await self.chamar("tarefa_ver", "ler", f"id={id[:40]}", corpo)

        @mcp.tool()
        async def estado() -> dict[str, Any]:
            """PC/casa online, TVs, fila e último backup."""
            async def corpo(_: int | None) -> Any:
                return await self._estado()
            return await self.chamar("estado", "ler", "", corpo)

        @mcp.resource("ayanami://estado", mime_type="application/json")
        async def recurso_estado() -> dict[str, Any]:
            """Estado da Ayanami (mesmo da tool ``estado``)."""
            return await self.chamar("ayanami://estado", "ler", "", lambda _: self._estado())

        @mcp.resource("ayanami://tarefas/{id}", mime_type="application/json")
        async def recurso_tarefa(id: str) -> dict[str, Any]:
            """Uma tarefa (``TarefaOut``)."""
            async def corpo(_: int | None) -> Any:
                return (await self._tarefa(id)).para_json()
            return await self.chamar("ayanami://tarefas", "ler", f"id={id[:40]}", corpo)

        @mcp.resource("ayanami://noticias/{uid}", mime_type="text/plain")
        async def recurso_noticia(uid: str) -> str:
            """Texto de uma notícia (sem revelar spoiler)."""
            async def corpo(_: int | None) -> Any:
                n = await asyncio.to_thread(noticia, db, uid)
                if n is None:
                    raise ToolError("nao_encontrado")
                return "\n\n".join(x for x in (n["titulo"], n["resumo"] or "", "\n".join(n["fontes"])) if x)
            return await self.chamar("ayanami://noticias", "ler", f"uid={uid[:40]}", corpo)

        if self._ligada("tarefa_criar"):
            @mcp.tool()
            async def tarefa_criar(
                tipo: str, titulo: Annotated[str, Field(min_length=1, max_length=120)],
                pedido: Annotated[str, Field(min_length=1, max_length=2000)],
                chave: str | None = None, params: dict[str, Any] | None = None,
            ) -> dict[str, Any]:
                """Cria tarefa (pesquisa, resumo, lembrete, monitor); idempotente pela chave.

                ``pedido`` vai no campo principal do tipo; ``params`` leva o resto (ex.: ``quando``
                do lembrete, ``condicao`` do monitor)."""
                async def corpo(disp_id: int | None) -> Any:
                    campo = CAMPO_DO_PEDIDO.get(tipo)
                    if campo is None:
                        raise ToolError(f"tipo inválido: use {sorted(CAMPO_DO_PEDIDO)}")
                    t = tf.TarefaIn(tipo=tipo, titulo=titulo, params={**(params or {}), campo: pedido},
                                    chave=chave)
                    try:
                        tarefa, _ = await tf.criar_tarefa(db, t, disp_id, app=ctx.extras.get("fila"),
                                                          relogio=ctx.relogio)
                    except tf.TarefaInvalida as e:
                        raise ToolError(f"invalido: {e}") from e
                    return tarefa.para_json()
                return await self.chamar("tarefa_criar", "tarefas",
                                         f"tipo={tipo} pedido={len(pedido)}c chave={'s' if chave else 'n'}",
                                         corpo)

            @mcp.tool()
            async def tarefa_cancelar(id: str) -> dict[str, Any]:
                """Cancela uma tarefa na fila ou rodando."""
                async def corpo(_: int | None) -> Any:
                    try:
                        e = await tf.cancelar_tarefa(db, id, app=ctx.extras.get("fila"),
                                                     relogio=ctx.relogio)
                    except (tf.TarefaNaoEncontrada, ValueError) as err:
                        raise ToolError("nao_encontrado") from err
                    except tf.JaTerminou as err:
                        raise ToolError(f"ja_terminou ({err.estado})") from err
                    return {"estado": e}
                return await self.chamar("tarefa_cancelar", "tarefas", f"id={id[:40]}", corpo)

        if self._ligada("tv_acao"):
            @mcp.tool()
            async def tv_acao(
                intent: Annotated[str, Field(pattern=r"^tv\.[a-z_]{1,30}$")],
                tv: Annotated[str | None, Field(max_length=64)] = None,
                slots: dict[str, str] | None = None,
            ) -> dict[str, Any]:
                """Ação na TV (só ``tv.*``). Desligar pede confirmação do Pedro (120 s)."""
                async def corpo(disp_id: int | None) -> Any:
                    return await self._tv_acao(disp_id, tv, intent, slots or {})
                return await self.chamar("tv_acao", "casa",
                                         f"{intent} tv={tv or '-'} slots={','.join(sorted(slots or {}))}",
                                         corpo)

        if self._ligada("memoria_gravar"):
            @mcp.tool()
            async def memoria_gravar(
                fato: Annotated[str, Field(min_length=1, max_length=FATO_MAX)],
            ) -> dict[str, Any]:
                """Pede ao Pedro (no PC) para gravar um fato na memória; só grava se ele aceitar."""
                async def corpo(disp_id: int | None) -> Any:
                    return await self._memoria_gravar(disp_id, fato)
                return await self.chamar("memoria_gravar", "memoria-escrever", f"fato={len(fato)}c", corpo)

    # ---------------------------------------------------------------- corpos

    async def _tarefa(self, id: str) -> tf.TarefaOut:
        try:
            t = await asyncio.to_thread(tf.obter_tarefa, self.ctx.db, id)
        except Exception as e:  # uuid inválido → psycopg reclama
            raise ToolError("nao_encontrado") from e
        if t is None:
            raise ToolError("nao_encontrado")
        return t

    async def _estado(self) -> dict[str, Any]:
        from ayanami.api import saude
        from ayanami.api.casa import para_json
        from ayanami.hub import hub_de

        s = await asyncio.to_thread(saude.coletar, self.ctx)
        hub = hub_de(self.ctx)
        casa = hub.estado_casa()
        return {
            "pc_online": bool(s["online"].get("pc")) or hub.online("pc"),
            "casa_online": bool(s["online"].get("casa")) or casa.online,
            "tvs": para_json(casa.estados) if casa.estados else para_json(casa.tvs),
            "fila": s["fila"],
            "ultimo_backup": s["ultimo_backup"],
        }

    async def _tv_acao(self, disp_id: int | None, tv: str | None, intent: str,
                       slots: dict[str, str]) -> Any:
        from ayanami.api import casa
        from magi.elo.mensagens import AcaoPedido

        pedido = AcaoPedido(intent=intent, slots=tuple((str(k), str(v)) for k, v in slots.items()))
        status, saida = await casa.pedir_acao(self.ctx, None, tv, pedido, "mcp", dispositivo_id=disp_id)
        if status == 202:
            c = await asyncio.to_thread(conf_mod.obter, self.ctx.db, saida["confirma"])
            self._vigiar(c, "tv_acao", disp_id)
            return {"confirmacao": c.id, "expira_em": iso_z(c.expira)}
        if status >= 400:
            raise ToolError(f"{saida.get('erro')}: {saida.get('msg')}")
        return saida

    async def _memoria_gravar(self, disp_id: int | None, fato: str) -> Any:
        from ayanami.hub import hub_de

        hub = hub_de(self.ctx)
        if not hub.online("pc"):
            raise ToolError("pc_offline")
        svc = conf_mod.confirmacoes_de(self.ctx)
        c = await svc.criar(descricao=f"Gravar na memória: {fato[:150]}",
                            pedido={"tipo": "memoria.gravar", "origem": "mcp", "fato": fato},
                            origem=disp_id)
        self._vigiar(c, "memoria_gravar", disp_id)
        return {"confirmacao": c.id, "expira_em": iso_z(c.expira)}

    def _vigiar(self, c: Any, alvo: str, disp_id: int | None) -> None:
        """Depois do prazo, confirmação sem resposta → ``auditoria ok=false`` (R5.3)."""
        async def vigia() -> None:
            restante = (c.expira - self.ctx.relogio.agora()).total_seconds()
            await self.ctx.relogio.dormir(max(0.0, restante))
            atual = await asyncio.to_thread(conf_mod.obter, self.ctx.db, c.id)
            if atual is not None and atual.resposta is None:
                await self._auditar(disp_id, alvo, f"confirmacao {c.id} expirada", False)

        t = asyncio.ensure_future(vigia())
        self.vigias.add(t)
        t.add_done_callback(self.vigias.discard)


def montar(app: Any) -> ServidorMcp:
    """Monta ``/mcp`` na app FastAPI e liga o ``session_manager`` ao lifespan dela."""
    ctx = app.state.ctx
    srv = ServidorMcp(ctx)
    app.mount("/mcp", srv.app_asgi())
    ctx.ciclo.append(srv.mcp.session_manager.run)
    ctx.extras["mcp"] = srv
    return srv
