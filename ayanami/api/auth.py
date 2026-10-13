"""Tokens, escopos e autenticação da API (dono: Y2.1; spec §2.1–§2.2, design §10.3).

- Token ``ayn_<tipo>_<43 base64url>`` (32 bytes de ``secrets.token_bytes``). No banco vai só o
  ``sha256`` hex e o prefixo ``ayn_<tipo>_<4 primeiros>`` (para listar).
- :class:`Autenticador`: verifica o Bearer com cache em memória de **5 s**; :meth:`revogar` grava
  ``revogado``, limpa o cache e chama os ganchos ``ao_revogar`` (o hub da Y2.2 fecha WS/SSE).
- :func:`exigir`: dependência FastAPI de uma rota (escopo e/ou tipo); aplica também o limite de
  60 req/min por dispositivo (:mod:`ayanami.api.limites`).
- :data:`ESCOPO_DE_ROTA`: todas as linhas da tabela §2.2 (menos ``/app/*`` e ``/mcp``, que têm
  regra própria). Os testes percorrem a tabela.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import re
import secrets
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import Depends, Request

from ayanami.db import Db, transacao

log = logging.getLogger("ayanami.api.auth")

TIPOS = ("pc", "casa", "celular", "mcp")
TOKEN_RE = re.compile(r"^ayn_(pc|casa|celular|mcp)_[A-Za-z0-9_-]{43}$")
NOME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
TTL_CACHE_S = 5.0

ESCOPOS_PADRAO: dict[str, tuple[str, ...]] = {
    "pc": ("conversa", "casa", "tarefas", "feed", "backup", "noticias", "custos"),
    "casa": ("casa-executar",),
    "celular": ("conversa", "casa", "tarefas", "feed"),
    "mcp": ("ler", "tarefas"),  # o real vem de [mcp] escopos (cfg)
}

QUALQUER = "qualquer"  # rota autenticada sem escopo (ex.: DELETE /v1/dispositivo)
NENHUM = None  # rota sem token


@dataclass(frozen=True)
class Exigencia:
    """Escopos aceitos (basta um) e/ou tipos aceitos; ``QUALQUER`` = só token válido."""

    escopos: tuple[str, ...] = ()
    tipos: tuple[str, ...] = ()


def _e(*escopos: str) -> Exigencia:
    return Exigencia(escopos=escopos)


def _t(*tipos: str) -> Exigencia:
    return Exigencia(tipos=tipos)


# (método, caminho) -> exigência; None = sem token (spec §2.2).
ESCOPO_DE_ROTA: dict[tuple[str, str], Exigencia | None] = {
    ("GET", "/saude"): NENHUM,
    ("GET", "/ws"): _t("pc", "casa"),
    ("GET", "/v1/longpoll"): _t("pc", "casa"),
    ("POST", "/v1/longpoll"): _t("pc", "casa"),
    ("POST", "/v1/pareamento"): _t("pc"),
    ("POST", "/v1/pareamento/trocar"): NENHUM,
    ("DELETE", "/v1/dispositivo"): Exigencia(),
    ("PUT", "/v1/dispositivo/preferencias"): _e("conversa"),
    ("POST", "/v1/turno"): _e("conversa"),
    ("GET", "/v1/turno/{id}"): _e("conversa"),
    ("GET", "/v1/turno/{id}/audio"): _e("conversa"),
    ("GET", "/v1/eventos"): _e("conversa"),
    ("POST", "/v1/confirma/{pedido}"): _e("conversa"),
    ("POST", "/v1/casa/acao"): _e("casa"),
    ("GET", "/v1/casa/estado"): _e("casa", "ler"),
    ("GET", "/v1/feed"): _e("feed"),
    ("GET", "/v1/tarefas"): _e("tarefas"),
    ("POST", "/v1/tarefas"): _e("tarefas"),
    ("GET", "/v1/tarefas/{id}"): _e("tarefas"),
    ("DELETE", "/v1/tarefas/{id}"): _e("tarefas"),
    ("GET", "/v1/fila"): _e("tarefas"),
    ("POST", "/v1/push/assinar"): _e("conversa"),
    ("DELETE", "/v1/push/assinar"): _e("conversa"),
    ("GET", "/v1/noticias"): _e("noticias"),
    ("PUT", "/v1/noticias/preferencias"): _e("noticias"),
    ("GET", "/v1/custos"): _e("custos"),
    ("PUT", "/v1/backup/pc"): _e("backup"),
}


class ErroApi(Exception):
    """Erro da API no formato ``{"erro": codigo, "msg": frase}`` (spec §2)."""

    def __init__(self, status: int, codigo: str, msg: str, headers: dict[str, str] | None = None) -> None:
        super().__init__(f"{status} {codigo}")
        self.status = status
        self.codigo = codigo
        self.msg = msg
        self.headers = headers or {}


# --------------------------------------------------------------------------- tokens


def gerar_token(tipo: str) -> str:
    if tipo not in TIPOS:
        raise ValueError(f"tipo inválido: {tipo!r}")
    corpo = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    return f"ayn_{tipo}_{corpo}"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def prefixo_token(token: str) -> str:
    _, tipo, corpo = token.split("_", 2)
    return f"ayn_{tipo}_{corpo[:4]}"


def iso_z(ts: datetime | None) -> str | None:
    """ISO-8601 em UTC com ``Z`` (spec §2)."""
    if ts is None:
        return None
    return ts.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def nome_valido(nome: str) -> bool:
    return bool(NOME_RE.match(nome)) and nome != "ayanami"


@dataclass(frozen=True)
class Dispositivo:
    id: int
    nome: str
    tipo: str
    escopos: frozenset[str]
    prefixo: str = ""
    criado: datetime | None = None
    ultimo_uso: datetime | None = None
    revogado: datetime | None = None


_COLUNAS = "id, nome, tipo, escopos, prefixo, criado, ultimo_uso, revogado"


def _linha(r: Any) -> Dispositivo:
    return Dispositivo(r[0], r[1], r[2], frozenset(r[3]), r[4], r[5], r[6], r[7])


class NomeEmUso(ValueError):
    pass


def criar_dispositivo(
    conn: Any, nome: str, tipo: str, escopos: Iterable[str] | None = None
) -> tuple[str, Dispositivo]:
    """Cria o dispositivo e devolve ``(token, dispositivo)``; o token só existe aqui."""
    if tipo not in TIPOS:
        raise ValueError(f"tipo inválido: {tipo!r}")
    if not nome_valido(nome):
        raise ValueError(f"nome inválido: {nome!r} (a-z, 0-9, '-', até 32; não 'ayanami')")
    lista = list(ESCOPOS_PADRAO[tipo] if escopos is None else escopos)
    token = gerar_token(tipo)
    if conn.execute("SELECT 1 FROM dispositivos WHERE nome = %s", (nome,)).fetchone():
        raise NomeEmUso(nome)
    r = conn.execute(
        f"INSERT INTO dispositivos (nome, tipo, escopos, hash, prefixo) VALUES (%s, %s, %s, %s, %s)"
        f" RETURNING {_COLUNAS}",
        (nome, tipo, lista, hash_token(token), prefixo_token(token)),
    ).fetchone()
    return token, _linha(r)


def listar_dispositivos(conn: Any) -> list[Dispositivo]:
    return [_linha(r) for r in conn.execute(f"SELECT {_COLUNAS} FROM dispositivos ORDER BY id").fetchall()]


def marcar_revogado(conn: Any, chave: int | str, quando: datetime) -> Dispositivo | None:
    """Revoga por id ou nome (idempotente: mantém o primeiro ``revogado``)."""
    campo = "id" if isinstance(chave, int) else "nome"
    r = conn.execute(
        f"UPDATE dispositivos SET revogado = coalesce(revogado, %s) WHERE {campo} = %s RETURNING {_COLUNAS}",
        (quando, chave),
    ).fetchone()
    return _linha(r) if r else None


# --------------------------------------------------------------------------- verificação


@dataclass
class Autenticador:
    db: Db
    relogio: Any
    ttl_s: float = TTL_CACHE_S
    ao_revogar: list[Callable[[Dispositivo], Any]] = field(default_factory=list)
    _cache: dict[str, tuple[float, Dispositivo | None]] = field(default_factory=dict, repr=False)
    _trava: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def verificar(self, token: str) -> Dispositivo | None:
        """Dispositivo ativo do token, ou ``None`` (formato errado, desconhecido ou revogado)."""
        if not TOKEN_RE.match(token):
            return None
        h = hash_token(token)
        agora = self.relogio.monotonico()
        with self._trava:
            item = self._cache.get(h)
        if item is not None and agora - item[0] < self.ttl_s:
            return item[1]
        with transacao(self.db) as conn:
            r = conn.execute(
                f"UPDATE dispositivos SET ultimo_uso = %s WHERE hash = %s AND revogado IS NULL"
                f" RETURNING {_COLUNAS}",
                (self.relogio.agora(), h),
            ).fetchone()
        disp = _linha(r) if r else None
        with self._trava:
            self._cache[h] = (agora, disp)
        return disp

    def revogar(self, chave: int | str) -> Dispositivo | None:
        with transacao(self.db) as conn:
            disp = marcar_revogado(conn, chave, self.relogio.agora())
        if disp is None:
            return None
        self.esquecer(disp.id)
        for gancho in list(self.ao_revogar):
            try:
                gancho(disp)
            except Exception:  # um gancho quebrado não impede a revogação
                log.exception("gancho ao_revogar falhou (dispositivo %s)", disp.id)
        return disp

    def esquecer(self, dispositivo_id: int) -> None:
        with self._trava:
            for h, (_, d) in list(self._cache.items()):
                if d is not None and d.id == dispositivo_id:
                    del self._cache[h]


def token_do_cabecalho(request: Request) -> str | None:
    valor = request.headers.get("authorization", "")
    tipo, _, token = valor.partition(" ")
    if tipo.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def autenticar(request: Request) -> Dispositivo:
    ctx = request.app.state.ctx
    token = token_do_cabecalho(request)
    disp = ctx.auth.verificar(token) if token else None
    if disp is None:
        raise ErroApi(401, "nao_autorizado", "token ausente, inválido ou revogado",
                      {"WWW-Authenticate": "Bearer"})
    request.state.dispositivo = disp
    return disp


def checar(disp: Dispositivo, exig: Exigencia) -> None:
    if exig.tipos and disp.tipo not in exig.tipos:
        raise ErroApi(403, "tipo_proibido", "este tipo de dispositivo não usa esta rota")
    if exig.escopos and not (disp.escopos & set(exig.escopos)):
        raise ErroApi(403, "escopo_faltando", "o token não tem o escopo desta rota")


def exigir(*escopos: str, tipos: Iterable[str] = ()) -> Callable[[Request], Dispositivo]:
    """Dependência: token válido + (algum dos ``escopos``) + (tipo em ``tipos``) + limite 60/min."""
    exig = Exigencia(escopos=tuple(escopos), tipos=tuple(tipos))

    def dependencia(request: Request) -> Dispositivo:
        disp = autenticar(request)
        checar(disp, exig)
        request.app.state.ctx.limites.por_dispositivo(request, disp)
        return disp

    return dependencia


def exigir_rota(metodo: str, caminho: str) -> Callable[[Request], Dispositivo]:
    """:func:`exigir` com a exigência da linha ``(metodo, caminho)`` de :data:`ESCOPO_DE_ROTA`."""
    exig = ESCOPO_DE_ROTA[(metodo, caminho)]
    if exig is None:
        raise ValueError(f"{metodo} {caminho} não exige token")
    return exigir(*exig.escopos, tipos=exig.tipos)


def rota_stub(router: Any, metodo: str, caminho: str, dono: str) -> None:
    """Registra em ``router`` uma rota que só autentica (pela linha de :data:`ESCOPO_DE_ROTA`) e
    responde ``501 nao_implementado`` — o dono troca pela rota real."""
    dep = exigir_rota(metodo, caminho)

    def nao_implementado() -> None:
        raise ErroApi(501, "nao_implementado", f"rota ainda não implementada (dono: {dono})")

    nao_implementado.__name__ = f"stub_{metodo.lower()}_{caminho.strip('/').replace('/', '_')}"
    router.add_api_route(caminho, nao_implementado, methods=[metodo], status_code=501,
                        dependencies=[Depends(dep)])
