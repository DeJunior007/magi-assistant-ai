"""Web Push no servidor (dono: P2.1; spec §15, design §6, R9, D12a).

- Chaves: :func:`gerar_chaves` (VAPID P-256 via ``py-vapid``) e ``ayanami push chaves`` (:func:`cli`),
  que imprime as linhas do ``.env`` (``VAPID_PUBLIC_KEY``/``VAPID_PRIVATE_KEY``/``VAPID_SUB``).
- Payload: :func:`montar_payload` (``titulo`` ≤ 40, ``resumo`` ≤ 120, ``tag``, ``url``) e
  :func:`serializar` (≤ 3 KB). ``tipo`` a partir do ``EventoTipo`` (:data:`TIPO_DE_EVENTO`);
  Urgency/TTL da tabela §15 (:data:`POLITICAS`).
- Decisão por dispositivo (:func:`decidir`, pura): preferência ``push``; ``push_com_pc=false`` com o
  PC online pula tudo menos ``confirma``; silêncio (``[push] silencio_padrao`` ou preferência
  ``silencio``, no fuso ``[geral] fuso``) deixa passar só ``confirma``/``lembrete``, descarta
  ``noticia`` e acumula o resto; ``[push] noticias_dia``; ``[push] max_hora`` por hora (relógio local)
  e dispositivo — o excedente acumula até a hora seguinte (``confirma``/``lembrete`` não esperam).
- Acumulados saem como **um** push "N avisos" (tag ``resumo-manha``) num ``push.enviar`` agendado
  para o fim do silêncio/da hora (:func:`processar` → ``_liberar``).
- Envio: ``webpush`` em ``asyncio.to_thread`` (injetável), timeout 10 s; 404/410 apaga a assinatura,
  413 corta o ``resumo`` e reenvia uma vez, 429/5xx/erro de rede reagenda ``push.enviar`` só para
  aquela assinatura (5 s, 30 s, 2 min, nunca antes do ``Retry-After``; desiste se passar do TTL).

Livro-caixa: a ``auditoria`` (tipo ``push``, ``alvo = "evento:<seq>"``, ``resumo`` = ação + tipo +
status, **sem texto**) guarda a decisão por dispositivo; dela saem a idempotência, o limite por hora
e a lista de acumulados (``acumulado`` sem ``agrupado`` correspondente).

Injeção (``deps.extras``): ``webpush`` (função com a assinatura do ``pywebpush.webpush``),
``segredos`` (padrão :func:`ayanami.config.ler_segredos`), ``fila`` (app do ``procrastinate``; padrão
``contexto.app``), ``pc_online`` (``() -> bool``; padrão ``dispositivos.visto`` recente).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, TextIO
from zoneinfo import ZoneInfo

from magi.elo.mensagens import Evento, EventoTipo

log = logging.getLogger(__name__)

MAX_TITULO = 40
MAX_RESUMO = 120
LIMITE_PAYLOAD = 3 * 1024
TIMEOUT_S = 10
ESPERAS_S = (5, 30, 120)  # 3 repetições em 429/5xx (§15)
TAG_AGRUPADO = "resumo-manha"
URL_FEED = "/app/#/feed"
SUB_EXEMPLO = "mailto:voce@exemplo.com"

TIPO_DE_EVENTO: Mapping[str, str] = {
    EventoTipo.CONFIRMACAO: "confirma",
    EventoTipo.LEMBRETE: "lembrete",
    EventoTipo.TAREFA_PRONTA: "tarefa",
    EventoTipo.TAREFA_FALHOU: "tarefa",
    EventoTipo.MONITOR: "monitor",
    EventoTipo.NOTICIA_BOMBA: "noticia",
    EventoTipo.BACKUP_FALHOU: "operacao",
}


@dataclass(frozen=True)
class Politica:
    urgencia: str
    ttl: int
    silencio: str  # "passa" | "acumula" | "descarta"


POLITICAS: Mapping[str, Politica] = {
    "confirma": Politica("high", 120, "passa"),
    "lembrete": Politica("high", 3600, "passa"),
    "tarefa": Politica("normal", 24 * 3600, "acumula"),
    "monitor": Politica("normal", 12 * 3600, "acumula"),
    "noticia": Politica("low", 6 * 3600, "descarta"),
    "operacao": Politica("normal", 24 * 3600, "acumula"),
}
POLITICA_AGRUPADO = Politica("normal", 12 * 3600, "acumula")
SEM_ESPERA_DE_LIMITE = frozenset({"confirma", "lembrete"})

_ID_OK = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_HORARIO = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})\s*$")


def tipo_push(tipo: EventoTipo | str) -> str | None:
    """``tipo`` do push para o ``EventoTipo`` (``dispositivo`` e desconhecidos → ``None``)."""
    return TIPO_DE_EVENTO.get(str(tipo))


def cortar(texto: str, n: int) -> str:
    texto = " ".join((texto or "").split())
    return texto if len(texto) <= n else texto[: n - 1].rstrip() + "…"


def _iso_z(ts: datetime) -> str:
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _url_e_tag(tipo: str, seq: int, ref: str | None) -> tuple[str, str]:
    tipo_ref, _, valor = (ref or "").partition(":")
    ok = bool(_ID_OK.match(valor))
    if ok and tipo_ref == "tarefa":
        return f"/app/#/tarefas/{valor}", f"tarefa-{valor}"
    if ok and tipo_ref == "confirma":
        return f"/app/#/confirma/{valor}", f"confirma-{valor}"
    if ok and tipo_ref == "noticia":
        return URL_FEED, f"noticia-{valor}"
    return URL_FEED, f"{tipo}-{seq}"


def montar_payload(evento: Evento, criado: datetime) -> dict[str, Any]:
    """Payload da §15 a partir do ``Evento`` (títulos cortados; só o que o evento já traz)."""
    tipo = tipo_push(evento.tipo) or "operacao"
    url, tag = _url_e_tag(tipo, evento.seq, evento.ref)
    return {"v": 1, "tipo": tipo, "id": str(evento.seq), "titulo": cortar(evento.titulo, MAX_TITULO),
            "resumo": cortar(evento.resumo, MAX_RESUMO), "url": url, "tag": tag, "ts": _iso_z(criado)}


def payload_agrupado(n: int, agora: datetime, seq: int) -> dict[str, Any]:
    return {"v": 1, "tipo": "agrupado", "id": str(seq), "titulo": f"{n} avisos",
            "resumo": "Abra a Ayanami para ver.", "url": URL_FEED, "tag": TAG_AGRUPADO,
            "ts": _iso_z(agora)}


def serializar(payload: Mapping[str, Any], limite: int = LIMITE_PAYLOAD) -> str:
    """JSON compacto ≤ ``limite`` bytes (corta ``resumo`` e depois ``titulo`` se precisar)."""
    p = dict(payload)
    dados = json.dumps(p, ensure_ascii=False, separators=(",", ":"))
    for campo in ("resumo", "titulo"):
        while len(dados.encode()) > limite and p.get(campo):
            p[campo] = str(p[campo])[: max(0, len(p[campo]) // 2 - 1)]
            dados = json.dumps(p, ensure_ascii=False, separators=(",", ":"))
    if len(dados.encode()) > limite:
        raise ValueError("payload de push grande demais")
    return dados


def topic(tag: str) -> str:
    """Cabeçalho ``Topic`` (RFC 8030: ≤ 32 caracteres do alfabeto base64url)."""
    limpo = re.sub(r"[^A-Za-z0-9_-]", "", tag)
    return limpo if 0 < len(limpo) <= 32 else hashlib.sha256(tag.encode()).hexdigest()[:32]


# --------------------------------------------------------------------------- silêncio e limite

Janela = tuple[time, time]


def ler_janela(texto: str | None) -> Janela | None:
    """``"23:00-07:30"`` → ``(23:00, 07:30)``; vazio → ``None`` (sem silêncio); inválido → ValueError."""
    if not texto or not texto.strip():
        return None
    m = _HORARIO.match(texto)
    if not m:
        raise ValueError(f"horário de silêncio inválido: {texto!r}")
    h1, m1, h2, m2 = (int(x) for x in m.groups())
    return time(h1, m1), time(h2, m2)


def janela_do(padrao: str, preferencias: Mapping[str, Any]) -> Janela | None:
    """Preferência ``silencio`` do celular (``""`` desliga) ou ``[push] silencio_padrao``."""
    if "silencio" in preferencias and isinstance(preferencias["silencio"], str):
        try:
            return ler_janela(preferencias["silencio"])
        except ValueError:
            log.warning("push_silencio_invalido; usa o padrão")
    return ler_janela(padrao)


def em_silencio(agora: datetime, janela: Janela | None, fuso: ZoneInfo) -> bool:
    if janela is None:
        return False
    ini, fim = janela
    t = agora.astimezone(fuso).time()
    return ini <= t < fim if ini <= fim else (t >= ini or t < fim)


def fim_do_silencio(agora: datetime, janela: Janela, fuso: ZoneInfo) -> datetime:
    local = agora.astimezone(fuso)
    fim = datetime.combine(local.date(), janela[1], tzinfo=fuso)
    if fim <= local:
        fim = datetime.combine(local.date() + timedelta(days=1), janela[1], tzinfo=fuso)
    return fim.astimezone(UTC)


def inicio_da_hora(agora: datetime, fuso: ZoneInfo) -> datetime:
    return agora.astimezone(fuso).replace(minute=0, second=0, microsecond=0).astimezone(UTC)


def inicio_do_dia(agora: datetime, fuso: ZoneInfo) -> datetime:
    return agora.astimezone(fuso).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


@dataclass(frozen=True)
class Decisao:
    acao: str  # "enviar" | "acumular" | "descartar" | "pular"
    motivo: str = ""
    liberar_em: datetime | None = None


def decidir(tipo: str, preferencias: Mapping[str, Any], *, agora: datetime, fuso: ZoneInfo,
            silencio_padrao: str, max_hora: int, noticias_dia: int, pc_online: bool,
            enviados_hora: int, noticias_hoje: int) -> Decisao:
    """O que fazer com um push de ``tipo`` para um celular (spec §15, DS18, R9.2)."""
    if preferencias.get("push") is False:
        return Decisao("pular", "push_desligado")
    if preferencias.get("push_com_pc") is False and pc_online and tipo != "confirma":
        return Decisao("pular", "pc_online")
    pol = POLITICAS[tipo]
    janela = janela_do(silencio_padrao, preferencias)
    if pol.silencio != "passa" and janela is not None and em_silencio(agora, janela, fuso):
        if pol.silencio == "descarta":
            return Decisao("descartar", "silencio")
        return Decisao("acumular", "silencio", fim_do_silencio(agora, janela, fuso))
    if tipo == "noticia" and noticias_hoje >= noticias_dia:
        return Decisao("descartar", "noticias_dia")
    if tipo not in SEM_ESPERA_DE_LIMITE and enviados_hora >= max_hora:
        return Decisao("acumular", "max_hora", inicio_da_hora(agora, fuso) + timedelta(hours=1))
    return Decisao("enviar")


# --------------------------------------------------------------------------- envio de um push


def retry_after(valor: str | None, agora: datetime) -> float | None:
    """``Retry-After`` em segundos (número ou data HTTP); ausente/ilegível → ``None``."""
    if not valor:
        return None
    valor = valor.strip()
    if valor.isdigit():
        return float(valor)
    try:
        quando = parsedate_to_datetime(valor)
    except (TypeError, ValueError):
        return None
    if quando.tzinfo is None:
        quando = quando.replace(tzinfo=UTC)
    return max(0.0, (quando - agora).total_seconds())


@dataclass(frozen=True)
class Resultado:
    status: int  # 0 = sem resposta (timeout/rede)
    retry_after: float | None = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def expirada(self) -> bool:
        return self.status in (404, 410)

    @property
    def repetir(self) -> bool:
        return self.status == 0 or self.status == 429 or self.status >= 500


@dataclass(frozen=True)
class Assinatura:
    id: int
    endpoint: str
    p256dh: str
    auth: str

    def info(self) -> dict[str, Any]:
        return {"endpoint": self.endpoint, "keys": {"p256dh": self.p256dh, "auth": self.auth}}


@dataclass(frozen=True)
class Vapid:
    privada: str
    sub: str


def _webpush_padrao() -> Callable[..., Any]:
    from pywebpush import webpush

    return webpush


async def enviar_um(webpush: Callable[..., Any], ass: Assinatura, dados: str, vapid: Vapid, *,
                    urgencia: str, ttl: int, tag: str, agora: datetime) -> Resultado:
    """Um ``webpush`` em thread; devolve status e ``Retry-After`` (nunca levanta)."""
    from pywebpush import WebPushException

    def chamar() -> Any:
        return webpush(subscription_info=ass.info(), data=dados, vapid_private_key=vapid.privada,
                       vapid_claims={"sub": vapid.sub}, ttl=ttl, timeout=TIMEOUT_S,
                       headers={"Urgency": urgencia, "Topic": topic(tag)})

    try:
        resp = await asyncio.to_thread(chamar)
    except WebPushException as e:
        resp = e.response
        if resp is None:
            return Resultado(0)
    except Exception as e:  # noqa: BLE001 - rede/timeout viram "repetir"
        log.warning("push_sem_resposta (%s)", type(e).__name__)
        return Resultado(0)
    status = int(getattr(resp, "status_code", 201) or 0)
    cab = getattr(resp, "headers", None) or {}
    return Resultado(status, retry_after(cab.get("Retry-After"), agora))


# --------------------------------------------------------------------------- banco


@dataclass
class Destino:
    id: int
    preferencias: dict[str, Any]
    assinaturas: list[Assinatura] = field(default_factory=list)


def _ler_evento(db: Any, evento_id: int) -> tuple[Evento, datetime, tuple[str, ...]] | None:
    with db.connection() as conn:
        r = conn.execute("SELECT id, tipo, titulo, resumo, ref, para, criado FROM eventos WHERE id = %s",
                         (evento_id,)).fetchone()
    if r is None:
        return None
    try:
        tipo = EventoTipo(r[1])
    except ValueError:
        return None
    return Evento(seq=r[0], tipo=tipo, titulo=r[2], resumo=r[3] or "", ref=r[4]), r[6], tuple(r[5] or ())


def _destinos(db: Any) -> list[Destino]:
    with db.connection() as conn:
        linhas = conn.execute(
            "SELECT d.id, d.preferencias, s.id, s.endpoint, s.p256dh, s.auth FROM dispositivos d"
            " JOIN push_assinaturas s ON s.dispositivo = d.id"
            " WHERE d.tipo = 'celular' AND d.revogado IS NULL ORDER BY d.id, s.id").fetchall()
    por_id: dict[int, Destino] = {}
    for did, prefs, sid, endpoint, p256dh, auth in linhas:
        d = por_id.setdefault(did, Destino(did, dict(prefs or {})))
        d.assinaturas.append(Assinatura(sid, endpoint, p256dh, auth))
    return list(por_id.values())


def _destino_da_assinatura(db: Any, assinatura: int) -> Destino | None:
    for d in _destinos(db):
        so = [a for a in d.assinaturas if a.id == assinatura]
        if so:
            return Destino(d.id, d.preferencias, so)
    return None


def _pc_online_db(db: Any, agora: datetime, offline_s: int) -> bool:
    with db.connection() as conn:
        r = conn.execute("SELECT EXISTS (SELECT 1 FROM dispositivos WHERE tipo = 'pc' AND revogado IS NULL"
                         " AND visto > %s)", (agora - timedelta(seconds=offline_s),)).fetchone()
    return bool(r and r[0])


def _acoes(db: Any, disp: int, alvo: str) -> set[str]:
    with db.connection() as conn:
        linhas = conn.execute("SELECT split_part(resumo, ' ', 1) FROM auditoria WHERE tipo = 'push'"
                              " AND dispositivo = %s AND alvo = %s", (disp, alvo)).fetchall()
    return {r[0] for r in linhas}


def _contar_enviados(db: Any, disp: int, desde: datetime, tipo: str | None = None) -> int:
    filtro = "enviado %" if tipo is None else f"enviado tipo={tipo} %"
    with db.connection() as conn:
        r = conn.execute("SELECT count(*) FROM auditoria WHERE tipo = 'push' AND dispositivo = %s"
                         " AND ts >= %s AND resumo LIKE %s", (disp, desde, filtro)).fetchone()
    return int(r[0])


def _pendentes(db: Any, disp: int, desde: datetime) -> list[int]:
    with db.connection() as conn:
        linhas = conn.execute(
            "SELECT DISTINCT a.alvo FROM auditoria a WHERE a.tipo = 'push' AND a.dispositivo = %(d)s"
            " AND a.ts >= %(desde)s AND a.resumo LIKE 'acumulado %%' AND NOT EXISTS ("
            "  SELECT 1 FROM auditoria b WHERE b.tipo = 'push' AND b.dispositivo = %(d)s"
            "  AND b.alvo = a.alvo AND b.resumo LIKE 'agrupado %%')",
            {"d": disp, "desde": desde}).fetchall()
    return sorted(int(r[0].split(":", 1)[1]) for r in linhas if r[0] and r[0].startswith("evento:"))


def _auditar(db: Any, disp: int, alvo: str, resumo: str, ok: bool, quando: datetime) -> None:
    with db.connection() as conn:
        conn.execute("INSERT INTO auditoria (ts, dispositivo, tipo, alvo, resumo, ok)"
                     " VALUES (%s, %s, 'push', %s, %s, %s)", (quando, disp, alvo, resumo[:300], ok))


def _apagar_assinatura(db: Any, sid: int) -> None:
    with db.connection() as conn:
        conn.execute("DELETE FROM push_assinaturas WHERE id = %s", (sid,))


def _contar_falha(db: Any, sid: int, ok: bool) -> None:
    with db.connection() as conn:
        if ok:
            conn.execute("UPDATE push_assinaturas SET falhas = 0 WHERE id = %s AND falhas <> 0", (sid,))
        else:
            conn.execute("UPDATE push_assinaturas SET falhas = LEAST(falhas + 1, 32000) WHERE id = %s",
                         (sid,))


def _marcar_processado(db: Any, evento_id: int, agora: datetime) -> None:
    with db.connection() as conn:
        conn.execute("UPDATE eventos SET push_enviado = %s WHERE id = %s AND push_enviado IS NULL",
                     (agora, evento_id))


# --------------------------------------------------------------------------- orquestração (job)


def _vapid(deps: Any) -> Vapid | None:
    s = deps.extras.get("segredos")
    if s is None:
        from ayanami.config import ler_segredos

        s = deps.extras["segredos"] = ler_segredos(deps.cfg)
    privada, sub = s.get("VAPID_PRIVATE_KEY"), s.get("VAPID_SUB")
    return Vapid(privada, sub) if privada and sub else None


async def _db(funcao: Callable[..., Any], *args: Any) -> Any:
    return await asyncio.to_thread(funcao, *args)


async def agendar(app: Any, evento_id: int, quando: datetime | None = None, **kwargs: Any) -> Any:
    """Defere ``push.enviar`` (``quando`` = ``schedule_at``). Para quem cria eventos com ``celular``."""
    from ayanami import fila

    extra = {"schedule_at": quando} if quando is not None else {}
    return await app.configure_task("push.enviar", **fila.defer_opcoes("push.enviar", **extra)) \
        .defer_async(evento_id=evento_id, **kwargs)


def _algum_2xx(status: str) -> bool:
    return any(x.startswith("2") for x in status.split(","))


class Envio:
    """Um ``push.enviar`` em andamento (relógio, fila, ``webpush`` e chaves injetados)."""

    def __init__(self, deps: Any, fila_app: Any) -> None:
        self.deps = deps
        self.db = deps.db
        self.cfg = deps.cfg
        self.fila = fila_app
        self.agora: datetime = deps.relogio.agora()
        self.fuso = ZoneInfo(deps.cfg.geral.fuso)
        self.webpush = deps.extras.get("webpush") or _webpush_padrao()
        self.contagem: dict[str, int] = {}

    def _conta(self, chave: str, n: int = 1) -> None:
        self.contagem[chave] = self.contagem.get(chave, 0) + n

    async def pc_online(self) -> bool:
        f = self.deps.extras.get("pc_online")
        if callable(f):
            return bool(f())
        return await _db(_pc_online_db, self.db, self.agora, self.cfg.rede.offline_apos_s)

    async def processar(self, evento_id: int) -> dict[str, Any]:
        lido = await _db(_ler_evento, self.db, evento_id)
        if lido is None or "celular" not in lido[2]:
            return self._saida()
        evento, criado, _ = lido
        tipo = tipo_push(evento.tipo)
        if tipo is None:
            await _db(_marcar_processado, self.db, evento_id, self.agora)
            return self._saida()
        vapid = _vapid(self.deps)
        if vapid is None:
            log.warning("push_sem_vapid (faltam VAPID_PRIVATE_KEY/VAPID_SUB)")
            return self._saida(erro="sem_vapid")
        alvo = f"evento:{evento_id}"
        pc_on = await self.pc_online()
        for dest in await _db(_destinos, self.db):
            acoes = await _db(_acoes, self.db, dest.id, alvo)
            if "acumulado" in acoes and "agrupado" not in acoes:
                await self._liberar(dest, vapid, pc_on, evento_id)
                continue
            if acoes:
                continue  # já decidido (repetição do job)
            await self._decidir_e_agir(dest, vapid, pc_on, evento, criado, tipo, alvo)
        await _db(_marcar_processado, self.db, evento_id, self.agora)
        return self._saida()

    async def _decidir_e_agir(self, dest: Destino, vapid: Vapid, pc_on: bool, evento: Evento,
                              criado: datetime, tipo: str, alvo: str) -> None:
        hora = await _db(_contar_enviados, self.db, dest.id, inicio_da_hora(self.agora, self.fuso))
        noticias = 0
        if tipo == "noticia":
            noticias = await _db(_contar_enviados, self.db, dest.id, inicio_do_dia(self.agora, self.fuso),
                                 "noticia")
        p = self.cfg.push
        dec = decidir(tipo, dest.preferencias, agora=self.agora, fuso=self.fuso,
                      silencio_padrao=p.silencio_padrao, max_hora=p.max_hora, noticias_dia=p.noticias_dia,
                      pc_online=pc_on, enviados_hora=hora, noticias_hoje=noticias)
        if dec.acao == "enviar":
            pol = POLITICAS[tipo]
            st = await self._enviar_destino(dest, vapid, montar_payload(evento, criado), pol, evento.seq)
            await _db(_auditar, self.db, dest.id, alvo, f"enviado tipo={tipo} status={st}",
                      _algum_2xx(st), self.agora)
            return
        resumo = f"{self._palavra(dec.acao)} tipo={tipo} motivo={dec.motivo}"
        await _db(_auditar, self.db, dest.id, alvo, resumo, True, self.agora)
        self._conta(dec.acao)
        if dec.acao == "acumular" and dec.liberar_em is not None and self.fila is not None:
            await agendar(self.fila, evento.seq, dec.liberar_em)

    @staticmethod
    def _palavra(acao: str) -> str:
        return {"acumular": "acumulado", "descartar": "descartado", "pular": "pulado"}[acao]

    async def _liberar(self, dest: Destino, vapid: Vapid, pc_on: bool, evento_id: int) -> None:
        """Manda os acumulados do celular como **um** push, se o silêncio e o limite deixarem."""
        p = self.cfg.push
        janela = janela_do(p.silencio_padrao, dest.preferencias)
        if janela is not None and em_silencio(self.agora, janela, self.fuso):
            if self.fila is not None:
                await agendar(self.fila, evento_id, fim_do_silencio(self.agora, janela, self.fuso))
            return
        hora = await _db(_contar_enviados, self.db, dest.id, inicio_da_hora(self.agora, self.fuso))
        if hora >= p.max_hora:
            if self.fila is not None:
                proxima = inicio_da_hora(self.agora, self.fuso) + timedelta(hours=1)
                await agendar(self.fila, evento_id, proxima)
            return
        ids = await _db(_pendentes, self.db, dest.id, self.agora - timedelta(days=2))
        if not ids:
            return
        pular = dest.preferencias.get("push") is False or (
            dest.preferencias.get("push_com_pc") is False and pc_on)
        n = len(ids)
        if pular:
            st = "pulado"
        else:
            if n == 1 and (lido := await _db(_ler_evento, self.db, ids[0])) is not None:
                payload = montar_payload(lido[0], lido[1])
                pol = POLITICAS.get(payload["tipo"], POLITICA_AGRUPADO)
            else:
                payload, pol = payload_agrupado(n, self.agora, ids[-1]), POLITICA_AGRUPADO
            st = await self._enviar_destino(dest, vapid, payload, pol, ids[-1])
            await _db(_auditar, self.db, dest.id, f"grupo:{ids[-1]}",
                      f"enviado tipo=agrupado n={n} status={st}", _algum_2xx(st), self.agora)
        for i in ids:
            await _db(_auditar, self.db, dest.id, f"evento:{i}", f"agrupado n={n} status={st}", True,
                      self.agora)

    async def _enviar_destino(self, dest: Destino, vapid: Vapid, payload: Mapping[str, Any], pol: Politica,
                              seq: int) -> str:
        """Envia a todas as assinaturas do celular; devolve os status (``"201"``, ``"410,201"``…)."""
        status: list[str] = []
        for ass in dest.assinaturas:
            r = await self._enviar_assinatura(dest.id, ass, vapid, payload, pol, seq, tentativa=0)
            status.append(str(r.status))
        return ",".join(status) or "sem_assinatura"

    async def _enviar_assinatura(self, disp: int, ass: Assinatura, vapid: Vapid, payload: Mapping[str, Any],
                                 pol: Politica, seq: int, *, tentativa: int) -> Resultado:
        tag = str(payload.get("tag") or TAG_AGRUPADO)
        dados = serializar(payload)
        r = await enviar_um(self.webpush, ass, dados, vapid, urgencia=pol.urgencia, ttl=pol.ttl, tag=tag,
                            agora=self.agora)
        if r.status == 413 and payload.get("resumo"):
            payload = {**payload, "resumo": ""}
            r = await enviar_um(self.webpush, ass, serializar(payload), vapid, urgencia=pol.urgencia,
                                ttl=pol.ttl, tag=tag, agora=self.agora)
        alvo = f"evento:{seq}"
        tipo = payload.get("tipo")
        if r.ok:
            self._conta("enviados")
            await _db(_contar_falha, self.db, ass.id, True)
        elif r.expirada:
            self._conta("expiradas")
            await _db(_apagar_assinatura, self.db, ass.id)
            await _db(_auditar, self.db, disp, alvo, f"expirada tipo={tipo} status={r.status}", False,
                      self.agora)
        elif r.repetir and tentativa < len(ESPERAS_S) and self.fila is not None:
            espera = max(float(ESPERAS_S[tentativa]), r.retry_after or 0.0)
            if espera > pol.ttl:
                await self._falhou(disp, ass, alvo, tipo, r)
            else:
                self._conta("repetir")
                await agendar(self.fila, seq, self.agora + timedelta(seconds=espera), assinatura=ass.id,
                              tentativa=tentativa + 1, payload=dict(payload), urgencia=pol.urgencia,
                              ttl=pol.ttl)
                await _db(_auditar, self.db, disp, alvo,
                          f"repetir tipo={tipo} status={r.status} em={int(espera)}s", False, self.agora)
        else:
            await self._falhou(disp, ass, alvo, tipo, r)
        return r

    async def _falhou(self, disp: int, ass: Assinatura, alvo: str, tipo: Any, r: Resultado) -> None:
        self._conta("falhas")
        await _db(_contar_falha, self.db, ass.id, False)
        await _db(_auditar, self.db, disp, alvo, f"falhou tipo={tipo} status={r.status}", False, self.agora)

    async def repetir(self, evento_id: int, assinatura: int, tentativa: int, payload: Mapping[str, Any],
                      urgencia: str, ttl: int) -> dict[str, Any]:
        """Repetição agendada de um envio que voltou 429/5xx (só aquela assinatura)."""
        vapid = _vapid(self.deps)
        if vapid is None:
            return self._saida(erro="sem_vapid")
        dest = await _db(_destino_da_assinatura, self.db, assinatura)
        if dest is None or not dest.assinaturas:
            return self._saida()
        pol = Politica(urgencia, ttl, "acumula")
        res = await self._enviar_assinatura(dest.id, dest.assinaturas[0], vapid, payload, pol, evento_id,
                                            tentativa=tentativa)
        if res.ok:
            await _db(_auditar, self.db, dest.id, f"evento:{evento_id}",
                      f"repetido tipo={payload.get('tipo')} status={res.status}", True, self.agora)
        return self._saida()

    def _saida(self, erro: str | None = None) -> dict[str, Any]:
        dados: dict[str, Any] = dict(self.contagem)
        if erro:
            dados["erro"] = erro
        n = dados.get("enviados", 0)
        return {"texto": f"{n} push(es) enviado(s)", "dados": dados}


async def processar(deps: Any, fila_app: Any, evento_id: int, *, assinatura: int | None = None,
                    tentativa: int = 0, payload: Mapping[str, Any] | None = None,
                    urgencia: str | None = None, ttl: int | None = None) -> dict[str, Any]:
    """Corpo de ``push.enviar`` (o job em :mod:`ayanami.workers.push` só chama isto)."""
    envio = Envio(deps, fila_app)
    if assinatura is not None and payload is not None:
        return await envio.repetir(evento_id, assinatura, tentativa, payload, urgencia or "normal",
                                   int(ttl or 3600))
    return await envio.processar(evento_id)


# --------------------------------------------------------------------------- chaves e CLI


def gerar_chaves() -> dict[str, str]:
    """Par VAPID P-256 novo: pública = ponto não comprimido em base64url (``applicationServerKey``),
    privada = 32 bytes crus em base64url (formato que o ``pywebpush`` aceita como string)."""
    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid as PyVapid
    from py_vapid import b64urlencode

    v = PyVapid()
    v.generate_keys()
    privada = v.private_key.private_numbers().private_value.to_bytes(32, "big")
    publica = v.public_key.public_bytes(serialization.Encoding.X962,
                                        serialization.PublicFormat.UncompressedPoint)
    return {"VAPID_PUBLIC_KEY": b64urlencode(publica), "VAPID_PRIVATE_KEY": b64urlencode(privada)}


def linhas_env(chaves: Mapping[str, str], sub: str = SUB_EXEMPLO) -> list[str]:
    return [f"VAPID_PUBLIC_KEY={chaves['VAPID_PUBLIC_KEY']}",
            f"VAPID_PRIVATE_KEY={chaves['VAPID_PRIVATE_KEY']}", f"VAPID_SUB={sub}"]


def cli(args: Sequence[str], *, saida: TextIO | None = None, erro: TextIO | None = None) -> int:
    """``ayanami push chaves [--sub mailto:…]``: imprime as linhas do ``.env`` (não grava nada)."""
    saida = saida or sys.stdout
    erro = erro or sys.stderr
    parser = argparse.ArgumentParser(prog="ayanami push", description="Web Push (spec §15)")
    subs = parser.add_subparsers(dest="cmd", required=True)
    p = subs.add_parser("chaves", help="gera um par VAPID e imprime as linhas do .env")
    p.add_argument("--sub", default=SUB_EXEMPLO, help="contato VAPID (mailto:…)")
    a = parser.parse_args(list(args))
    if a.cmd == "chaves":
        if not a.sub.startswith(("mailto:", "https://")):
            print("--sub precisa começar com mailto: ou https://", file=erro)
            return 2
        for linha in linhas_env(gerar_chaves(), a.sub):
            print(linha, file=saida)
        print("# cole em /opt/ayanami/.env (0600). Trocar as chaves invalida as assinaturas; "
              "o PWA reassina ao abrir.", file=erro)
        return 0
    return 2  # pragma: no cover
