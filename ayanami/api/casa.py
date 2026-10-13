"""Ação e estado da casa (dono: Y2.2; spec §2.2, §6.1, §13.2; R5.3, R6.6).

- ``POST /v1/casa/acao`` ``{"tv": "TV da sala"|null, "pedido": AcaoPedido}``: manda ``acao`` à casa
  pelo hub e espera o ``acao_ok`` até ``prazo_ms`` (8 s; 10 s em ``tv.power_on`` e volume
  absoluto). Casa sem conexão viva → ``503 casa_offline``; sem resposta no prazo → ``504
  tempo_esgotado`` (o ``acao_ok`` atrasado só vai à auditoria, no hub). Resposta ``200``
  ``AcaoResultado`` com ``fala`` preenchida pela tabela da §13.2. Pedido perigoso (``danger`` no
  ``intents.yaml``) vindo do MCP sem ``confirmed`` → ``202 {"confirma": ulid}`` e a ação só roda na
  resposta ``true`` (:mod:`ayanami.confirmacoes`). :func:`pedir_acao` é a chamada interna (Y5.1).
- ``GET /v1/casa/estado``: ``{"online","visto","tvs","estados","apps"}`` do último ``ola``/``estado``.

``fala``: a tabela :data:`FALAS` usa as frases da §13.2; cada uma só é usada se existir no
``magi/core/phrases.yaml`` (quem preenche é a C2.1) — chave que falta lá cai numa frase genérica.
"""

from __future__ import annotations

import asyncio
import dataclasses
import functools
import logging
from collections.abc import Mapping
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Final

import yaml
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ayanami.api import auditoria
from ayanami.api.auth import Dispositivo, ErroApi, exigir_rota
from ayanami.confirmacoes import Confirmacao, confirmacoes_de
from ayanami.hub import NoOffline, hub_de
from magi.elo.mensagens import Acao, AcaoOk, AcaoPedido, AcaoResultado, Envelope, Tipo, formata_ts

log = logging.getLogger("ayanami.api.casa")

router = APIRouter()

_MAGI_CORE = Path(__file__).resolve().parents[2] / "magi" / "core"
CAMINHO_FRASES: Path = _MAGI_CORE / "phrases.yaml"
CAMINHO_INTENTS: Path = _MAGI_CORE / "intents.yaml"

PRAZO_MS: Final = 8000
PRAZO_LONGO_MS: Final = 10000
PERIGOSAS_PADRAO: Final = frozenset({"tv.power_off"})

FALA_OK_GENERICA: Final = "Ok."
FALA_FALHA_GENERICA: Final = "Deu ruim aqui, não consegui."

#: Tabela da §13.2: chave → frase (``{nome}`` = TV, app ou entrada). Espelha os ``SAY_TV_*`` do PC.
FALAS: Final[Mapping[str, str]] = {
    "ok:tv.power_on": "Pronto, TV ligada.",
    "ok:tv.power_off": "TV desligada.",
    "ok:tv.volume": "Volume da TV ajustado.",
    "ok:tv.volume_passo": "Ok.",
    "ok:tv.mute": "TV no mudo.",
    "ok:tv.unmute": "Som da TV de volta.",
    "ok:tv.mute_alternado": "Mudo alternado.",
    "ok:tv.app": "Abrindo {nome} na TV.",
    "ok:tv.app_sem_nome": "Abrindo na TV.",
    "ok:tv.input": "Entrada trocada.",
    "casa_offline": "A casa está fora do ar.",
    "tempo_esgotado": "A TV não respondeu.",
    "precisa_confirmar": "Desligar a {nome}? Confirma?",
    "tv_ambigua": "Mais de uma TV: {nome}?",
    "falha:tv.power_on": "Não consegui ligar a TV.",
    "falha": "A TV recusou o comando.",
    "motivo:nao_suportado": "Essa TV não faz isso.",
    "motivo:entrada_desconhecida": "Essa TV não faz isso.",
    "motivo:offline": "A {nome} está desligada.",
    "motivo:tempo_esgotado": "A TV não respondeu.",
    "motivo:sem_mac": "Não consegui ligar a {nome}; ela precisa do Ligar com celular ativo.",
    "motivo:rede_desligada": "Não consegui ligar a {nome}; ela precisa do Ligar com celular ativo.",
    "motivo:rede_desligada:roku": "Não consegui ligar a {nome}; ative o Início rápido da TV.",
    "motivo:standby_profundo": "Não consegui ligar a {nome}; ela está em espera profunda.",
    "motivo:acesso_negado": "A {nome} está bloqueando o controle; ative o Acesso à rede.",
    "motivo:nao_pareado": "Essa TV ainda não foi pareada.",
    "motivo:app_desconhecido": "Não conheço esse app nessa TV.",
    "motivo:tv_desconhecida": "Qual TV?",
    "motivo:ocupada": "A TV recusou o comando.",
    "motivo:erro_driver": "A TV recusou o comando.",
}


@functools.lru_cache(maxsize=4)
def _frases_do_yaml(caminho: Path) -> frozenset[str]:
    try:
        dados = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as e:
        log.warning("frases_ausentes (%s): falas genéricas", type(e).__name__)
        return frozenset()
    return frozenset(
        str(f) for secao in ("fixed", "lazy", "templates") for f in (dados.get(secao) or ()) if f
    )


def frase(chave: str, nome: str = "", *, ok: bool = False) -> str:
    """Frase da tabela se ela estiver no ``phrases.yaml``; senão a genérica."""
    modelo = FALAS.get(chave)
    if modelo is None or modelo not in _frases_do_yaml(CAMINHO_FRASES):
        return FALA_OK_GENERICA if ok else FALA_FALHA_GENERICA
    return modelo.format(nome=nome or "TV")


@functools.lru_cache(maxsize=4)
def _perigosas(caminho: Path) -> frozenset[str]:
    try:
        dados = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return PERIGOSAS_PADRAO
    itens = dados.get("intents", []) or []
    ids = {str(i.get("id")) for i in itens if isinstance(i, dict) and i.get("danger")}
    return frozenset(ids) or PERIGOSAS_PADRAO


def perigosa(intent: str) -> bool:
    return intent in _perigosas(CAMINHO_INTENTS)


def _slot(p: AcaoPedido, nome: str) -> str | None:
    return next((v for k, v in p.slots if k == nome), None)


def _absoluto(p: AcaoPedido) -> bool:
    v = _slot(p, "volume")
    return v is not None and v.strip().isdigit()


def prazo_ms(p: AcaoPedido) -> int:
    if p.intent == "tv.power_on" or (p.intent == "tv.volume" and _absoluto(p)):
        return PRAZO_LONGO_MS
    return PRAZO_MS


def _nome_tv(tv_id: str | None, tvs: tuple[Any, ...], padrao: str | None) -> str:
    for t in tvs:
        if tv_id in (t.id, t.nome):
            return t.nome
    return padrao or ""


def _nome_app(app: str, apps: tuple[Any, ...]) -> str:
    return next((a.nome for a in apps if app in (a.id, a.nome)), app)


def preencher_fala(
    p: AcaoPedido, r: AcaoResultado, tvs: tuple[Any, ...], tv: str | None, apps: tuple[Any, ...] = ()
) -> AcaoResultado:
    """``fala`` pela §13.2 (``dados["tv"]``/``tv`` dão o ``{nome}``)."""
    dados = r.dados or {}
    nome = _nome_tv(str(dados.get("tv") or "") or None, tvs, tv)
    motivo = r.motivo or ""
    if motivo == "tv_ambigua":
        ids = dados.get("candidatos") or [t.id for t in tvs]
        nomes = [_nome_tv(str(i), tvs, str(i)) for i in ids] if isinstance(ids, list | tuple) else []
        fala = frase("tv_ambigua", " ou ".join(n for n in nomes if n) or "TV")
    elif r.precisa_confirmar or motivo == "precisa_confirmar":
        fala = frase("precisa_confirmar", nome)
    elif r.ok:
        chave = f"ok:{p.intent}"
        alvo = nome
        if p.intent == "tv.volume" and not _absoluto(p):
            chave = "ok:tv.volume_passo"
        elif p.intent in ("tv.mute", "tv.unmute") and dados.get("emulado"):
            chave = "ok:tv.mute_alternado"
        elif p.intent == "tv.app":
            app = _slot(p, "app")
            alvo = _nome_app(app, apps) if app else ""
            chave = "ok:tv.app" if app else "ok:tv.app_sem_nome"
        fala = frase(chave, alvo, ok=True)
    else:
        driver = next((t.driver for t in tvs if nome and t.nome == nome), "")
        chave = f"motivo:{motivo}:{driver}" if f"motivo:{motivo}:{driver}" in FALAS else f"motivo:{motivo}"
        if p.intent == "tv.power_on" and motivo in ("offline", ""):
            chave = "falha:tv.power_on"
        elif chave not in FALAS:
            chave = "falha"
        fala = frase(chave, nome)
    return dataclasses.replace(r, fala=fala)


def para_json(v: Any) -> Any:
    if dataclasses.is_dataclass(v) and not isinstance(v, type):
        return {f.name: para_json(getattr(v, f.name)) for f in dataclasses.fields(v)}
    if isinstance(v, Enum):
        return v.value
    if isinstance(v, datetime):
        return formata_ts(v)
    if isinstance(v, tuple | list):
        return [para_json(x) for x in v]
    if isinstance(v, Mapping):
        return {str(k): para_json(x) for k, x in v.items()}
    return v


# --------------------------------------------------------------------------- serviço


def servicos(ctx: Any) -> tuple[Any, Any]:
    """``(hub, confirmacoes)`` da app, com o executor ``"casa.acao"`` registrado."""
    hub = hub_de(ctx)
    conf = confirmacoes_de(ctx)
    if "casa.acao" not in conf.executores:
        async def executar(c: Confirmacao) -> Any:
            d = c.pedido
            p = dataclasses.replace(_pedido_de_dict(d.get("pedido") or {}), confirmed=True)
            _, corpo = await pedir_acao(ctx, None, d.get("tv"), p, str(d.get("origem") or "mcp"),
                                        dispositivo_id=c.origem)
            return corpo

        conf.ao_confirmar("casa.acao", executar)
    return hub, conf


def _pedido_de_dict(d: Mapping[str, Any]) -> AcaoPedido:
    return AcaoPedido(
        intent=str(d.get("intent", "")),
        slots=tuple((str(k), str(v)) for k, v in d.get("slots") or ()),
        texto=str(d.get("texto") or ""),
        confirmed=bool(d.get("confirmed", False)),
        args=dict(d.get("args") or {}),
    )


async def pedir_acao(
    ctx: Any, disp: Dispositivo | None, tv: str | None, pedido: AcaoPedido, origem: str,
    *, dispositivo_id: int | None = None,
) -> tuple[int, dict]:
    """Chamada interna (rota, MCP da Y5.1, confirmação): devolve ``(status, corpo_json)``."""
    hub, conf = servicos(ctx)
    disp_id = disp.id if disp is not None else dispositivo_id
    if tv and _slot(pedido, "tv") is None:
        pedido = dataclasses.replace(pedido, slots=(*pedido.slots, ("tv", tv)))
    casa = hub.estado_casa()
    if origem == "mcp" and perigosa(pedido.intent) and not pedido.confirmed:
        nome = _nome_tv(tv, casa.tvs, tv)
        c = await conf.criar(
            descricao=frase("precisa_confirmar", nome),
            pedido={"tipo": "casa.acao", "origem": origem, "tv": tv, "pedido": para_json(pedido)},
            origem=disp_id,
        )
        await _auditar(ctx, disp_id, pedido, f"confirmacao {c.id}", True)
        return 202, {"confirma": c.id}
    prazo = prazo_ms(pedido)
    env = Envelope(t=Tipo.ACAO, corpo=Acao(pedido=pedido, origem=origem, prazo_ms=prazo),
                   de="ayanami", para="casa")
    if not casa.online:
        await _auditar(ctx, disp_id, pedido, "casa_offline", False)
        return 503, {"erro": "casa_offline", "msg": frase("casa_offline")}
    try:
        r = await hub.enviar_e_esperar(env, prazo / 1000)
    except NoOffline:
        await _auditar(ctx, disp_id, pedido, "casa_offline", False)
        return 503, {"erro": "casa_offline", "msg": frase("casa_offline")}
    except TimeoutError:
        await _auditar(ctx, disp_id, pedido, f"tempo_esgotado acao={env.id}", False)
        return 504, {"erro": "tempo_esgotado", "msg": frase("tempo_esgotado")}
    if not isinstance(r.corpo, AcaoOk):
        await _auditar(ctx, disp_id, pedido, f"resposta {r.t.value}", False)
        return 502, {"erro": "resposta_invalida", "msg": frase("falha")}
    res = preencher_fala(pedido, r.corpo.resultado, casa.tvs, tv, casa.apps)
    await _auditar(ctx, disp_id, pedido, f"motivo={res.motivo or '-'}", res.ok)
    return 200, para_json(res)


async def _auditar(ctx: Any, disp_id: int | None, p: AcaoPedido, resumo: str, ok: bool) -> None:
    try:
        await asyncio.to_thread(auditoria.registrar, ctx.db, tipo="casa", alvo=p.intent,
                                resumo=f"{p.intent} {resumo}", ok=ok, dispositivo=disp_id)
    except Exception as e:  # noqa: BLE001 - auditoria não derruba a ação
        log.warning("auditoria_casa_falhou (%s)", type(e).__name__)


# --------------------------------------------------------------------------- rotas


class PedidoIn(BaseModel):
    intent: str = Field(min_length=1, max_length=64)
    slots: list[tuple[str, str]] = Field(default_factory=list, max_length=16)
    texto: str = Field("", max_length=4000)
    confirmed: bool = False
    args: dict[str, str | int | float | bool] = Field(default_factory=dict)


class AcaoIn(BaseModel):
    tv: str | None = Field(None, max_length=64)
    pedido: PedidoIn


_ORIGEM = {"pc": "voz-pc", "celular": "pwa", "mcp": "mcp"}


@router.post("/v1/casa/acao")
async def casa_acao(
    corpo: AcaoIn, request: Request,
    disp: Annotated[Dispositivo, Depends(exigir_rota("POST", "/v1/casa/acao"))],
) -> JSONResponse:
    p = corpo.pedido
    pedido = AcaoPedido(intent=p.intent, slots=tuple(p.slots), texto=p.texto, confirmed=p.confirmed,
                        args=dict(p.args))
    status, saida = await pedir_acao(request.app.state.ctx, disp, corpo.tv, pedido,
                                     _ORIGEM.get(disp.tipo, "pwa"))
    if status >= 400:
        raise ErroApi(status, saida["erro"], saida["msg"])
    return JSONResponse(saida, status_code=status)


@router.get("/v1/casa/estado")
async def casa_estado(
    request: Request, _disp: Annotated[Dispositivo, Depends(exigir_rota("GET", "/v1/casa/estado"))]
) -> dict:
    hub = hub_de(request.app.state.ctx)
    e = hub.estado_casa()
    return {"online": e.online, "visto": formata_ts(e.visto) if e.visto else None,
            "tvs": para_json(e.tvs), "estados": para_json(e.estados), "apps": para_json(e.apps)}
