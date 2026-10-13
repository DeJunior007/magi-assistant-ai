"""TV pela ``magi-casa`` (ayanami-central C2.2, spec §10.2, §13.2–§13.4).

``TvActions`` fala com a casa pelo elo local: **uma** conexão TCP de JSON-lines (envelopes do
``magi.elo``), aberta sob demanda. Cliente → ``ola`` (``tipo="pc"``, ``token`` = ``casa.token``);
casa → ``ola`` com ``tvs``/``apps`` (vira o ``CasaCatalogo`` do roteador); ``acao`` → ``acao_ok``.

Nunca levanta nem trava: sem ``casa.token``, conexão recusada, token recusado ou elo quebrado →
"A casa está fora do ar." (RNF-A9: nada disso passa pela Ayanami); ``acao`` sem resposta no prazo
(2,5 s; 10 s para ligar e volume absoluto) → "A TV não respondeu.".

``TV_AMBIGUA`` → "Mais de uma TV: sala ou quarto?" como pergunta pendente do turno: o
``on_confirm`` leva em ``ARG_ESCOLHA`` uma função que resolve a próxima fala curta ("a da sala")
num pedido com o slot ``tv``; o ``magi.core.turn`` reenvia esse pedido.

Apelidos de entrada (``console`` → ``hdmi2``) não vêm no ``TvInfo``: saem do ``casa.toml`` local
(``[[tv]] entradas``) quando a casa é deste PC, e de itens ``"apelido=hdmiN"`` em ``TvInfo.entradas``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz

from magi.common.contracts import (
    ARG_QUIET,
    ActionRequest,
    ActionResult,
    Expression,
    IntentId,
    Slot,
    SlotName,
)
from magi.core.router import CASA_SCORE, CasaCatalogo, normalize_text
from magi.elo.converte import pedido_de_request
from magi.elo.mensagens import (
    MAX_TEXTO_BYTES,
    Acao,
    AcaoOk,
    AcaoResultado,
    EloError,
    Envelope,
    Erro,
    Estado,
    EstadoTv,
    Ola,
    Tipo,
    TipoDispositivo,
    TvInfo,
    decode,
    encode,
)

log = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 10760
TIMEOUT_S = 2.5
TIMEOUT_LONGO_S = 10.0
VERSAO_PC = "magi-core"
DE, PARA = "pc", "casa"

#: Pergunta "qual TV?" pendente: ``Callable[[str], ActionRequest | None]`` no ``on_confirm.args``.
ARG_ESCOLHA = "tv_escolha"

SAY_CASA_OFF = "A casa está fora do ar."
SAY_TV_NO_RESPONSE = "A TV não respondeu."
SAY_TV_REFUSED = "A TV recusou o comando."
SAY_TV_ON_FAILED = "Não consegui ligar a TV."
SAY_TV_WHICH = "Qual TV?"
SAY_TV_AMBIGUOUS = "Mais de uma TV: {nome}?"
SAY_TV_CONFIRM_OFF = "Desligar a {nome}? Confirma?"
SAY_TV_CONFIRM_OFF_PLAIN = "Desligar a TV? Confirma?"
SAY_TV_MUTE_TOGGLED = "Mudo alternado."
SAY_TV_APP_OPEN = "Abrindo {nome} na TV."

#: Resposta de sucesso por intent (volume relativo: só "Ok.", spec §13.2).
SAY_TV_OK: dict[str, str] = {
    IntentId.TV_POWER_ON: "Pronto, TV ligada.",
    IntentId.TV_POWER_OFF: "TV desligada.",
    IntentId.TV_VOLUME: "Volume da TV ajustado.",
    IntentId.TV_MUTE: "TV no mudo.",
    IntentId.TV_UNMUTE: "Som da TV de volta.",
    IntentId.TV_APP: "Abrindo na TV.",
    IntentId.TV_INPUT: "Entrada trocada.",
}
SAY_TV_STEP = "Ok."

#: ``motivo`` (``Motivo`` da casa, §10.5) → frase da §13.2; ``{nome}`` = nome da TV.
SAY_TV_MOTIVO: dict[str, str] = {
    "nao_suportado": "Essa TV não faz isso.",
    "entrada_desconhecida": "Essa TV não faz isso.",
    "offline": "A {nome} está desligada.",
    "tempo_esgotado": "A TV não respondeu.",
    "sem_mac": "Não consegui ligar a {nome}; ela precisa do Ligar com celular ativo.",
    "standby_profundo": "Não consegui ligar a {nome}; ela está em espera profunda.",
    "acesso_negado": "A {nome} está bloqueando o controle; ative o Acesso à rede.",
    "nao_pareado": "Essa TV ainda não foi pareada.",
    "app_desconhecido": "Não conheço esse app nessa TV.",
    "tv_desconhecida": "Qual TV?",
    "ocupada": "A TV recusou o comando.",
    "erro_driver": "A TV recusou o comando.",
    "nao_autorizado": "A casa está fora do ar.",
}
#: ``rede_desligada`` ao ligar: a dica depende do driver (Roku: Início rápido).
SAY_TV_REDE: dict[str, str] = {
    "roku": "Não consegui ligar a {nome}; ative o Início rápido da TV.",
    "": "Não consegui ligar a {nome}; ela precisa do Ligar com celular ativo.",
}

_LONGOS = frozenset({IntentId.TV_POWER_ON.value})
_HDMI_RE = re.compile(r"^hdmi[1-4]$")


def token_padrao() -> Path:
    """``~/.config/magi/casa.token`` (lido na hora, para os testes trocarem o HOME)."""
    return Path("~/.config/magi/casa.token").expanduser()


def casa_toml_padrao() -> Path:
    return Path("~/.config/magi/casa.toml").expanduser()


def _chave(texto: str) -> str:
    return " ".join(normalize_text(texto))


def acha_nome(texto: str, nomes: Sequence[tuple[str, str]], score: float = CASA_SCORE) -> str | None:
    """``valor`` cujo nome (``(nome, valor)``) melhor casa com algum trecho de ``texto`` (≥ ``score``)."""
    words = normalize_text(texto)
    tabela = [(k, v) for n, v in nomes if (k := _chave(n))]
    best: tuple[float, str] | None = None
    for i in range(len(words)):
        for n in range(1, min(4, len(words) - i) + 1):
            gram = " ".join(words[i : i + n])
            for key, valor in tabela:
                sc = fuzz.ratio(gram, key)
                if sc >= score and (best is None or sc > best[0]):
                    best = (sc, valor)
    return best[1] if best else None


def nomes_tv(tv: TvInfo) -> list[tuple[str, str]]:
    return [(n, tv.id) for n in (tv.nome, tv.id, *tv.apelidos)]


def falado(tv: TvInfo) -> str:
    """Forma curta para a pergunta ("sala"): primeiro apelido, senão o nome."""
    return tv.apelidos[0] if tv.apelidos else tv.nome


def entradas_do_toml(caminho: Path) -> dict[str, str]:
    """``apelido → hdmiN`` dos ``[[tv]] entradas`` do ``casa.toml``; arquivo ausente/ruim → ``{}``."""
    try:
        dados = tomllib.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return {}
    out: dict[str, str] = {}
    for tv in dados.get("tv") or ():
        ent = tv.get("entradas") if isinstance(tv, Mapping) else None
        if isinstance(ent, Mapping):
            out.update({str(k): str(v) for k, v in ent.items() if isinstance(v, str)})
    return out


def entradas_do_ola(tvs: Sequence[TvInfo]) -> dict[str, str]:
    """Itens ``"apelido=hdmiN"`` em ``TvInfo.entradas`` (as canônicas ficam de fora)."""
    out: dict[str, str] = {}
    for tv in tvs:
        for e in tv.entradas:
            nome, sep, valor = e.partition("=")
            if sep and nome.strip() and valor.strip():
                out[nome.strip()] = valor.strip()
    return out


def _escalares(args: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in args.items() if isinstance(v, str | int | float | bool) and k != ARG_QUIET}


def _absoluto(req: ActionRequest) -> bool:
    s = req.intent.slot(SlotName.VOLUME)
    return s is not None and s.value.strip().isdigit()


class _Caiu(Exception):
    """A conexão com a casa fechou com pedido em voo."""


class TvActions:
    """``tv.*`` via ``magi-casa`` (spec §13.4), no molde do ``RgbActions``.

    ``ao_catalogo(cat)``: chamado a cada ``ola`` da casa (o ``assemble`` troca ``LocalRouter.casa``).
    ``token_file``/``casa_toml``: ``None`` = caminhos padrão, lidos na hora.
    """

    intents = frozenset({
        IntentId.TV_POWER_ON, IntentId.TV_POWER_OFF, IntentId.TV_VOLUME, IntentId.TV_MUTE,
        IntentId.TV_UNMUTE, IntentId.TV_APP, IntentId.TV_INPUT,
    })

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        token_file: Path | None = None,
        *,
        timeout_s: float = TIMEOUT_S,
        timeout_longo_s: float = TIMEOUT_LONGO_S,
        ao_catalogo: Callable[[CasaCatalogo], None] | None = None,
        casa_toml: Path | None = None,
    ) -> None:
        self.host, self.port = host, port
        self.token_file, self.casa_toml = token_file, casa_toml
        self.timeout_s, self.timeout_longo_s = timeout_s, timeout_longo_s
        self.ao_catalogo = ao_catalogo
        self.catalogo = CasaCatalogo()
        self.estados: tuple[EstadoTv, ...] = ()
        self._w: asyncio.StreamWriter | None = None
        self._leitor: asyncio.Task[None] | None = None
        self._lock: asyncio.Lock | None = None
        self._pend: dict[str, asyncio.Future[Envelope]] = {}
        self._esperando_estado: list[asyncio.Future[tuple[EstadoTv, ...]]] = []

    # -- conexão -------------------------------------------------------------------------------
    def _vivo(self) -> bool:
        return (self._w is not None and not self._w.is_closing()
                and self._leitor is not None and not self._leitor.done())

    def _token(self) -> str | None:
        try:
            tok = (self.token_file or token_padrao()).read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return tok or None

    async def _conectar(self) -> bool:
        """Abre o elo (``ola`` ida e volta) se preciso. ``False`` = casa fora do ar."""
        if self._vivo():
            return True
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            if self._vivo():
                return True
            token = self._token()
            if token is None:
                log.info("casa: sem casa.token; a magi-casa não rodou neste PC")
                return False
            w: asyncio.StreamWriter | None = None
            try:
                r, w = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self.port, limit=MAX_TEXTO_BYTES + 2), self.timeout_s
                )
                ola = Ola(tipo=TipoDispositivo.PC, versao=VERSAO_PC, caps=("acao", "estado"), token=token)
                await self._mandar(w, Envelope(t=Tipo.OLA, corpo=ola, de=DE, para=PARA))
                env = decode(await asyncio.wait_for(r.readline(), self.timeout_s))
            except (OSError, TimeoutError, EloError, ValueError) as e:
                log.info("casa fora do ar (%s:%s): %s", self.host, self.port, type(e).__name__)
                await self._fecha(w)
                return False
            if env.t is not Tipo.OLA or not isinstance(env.corpo, Ola):
                codigo = env.corpo.codigo if isinstance(env.corpo, Erro) else env.t.value
                log.warning("casa recusou o ola: %s", codigo)
                await self._fecha(w)
                return False
            self._aplica_ola(env.corpo)
            self._w = w
            self._leitor = asyncio.create_task(self._ler(r, w), name="casa-elo")
            return True

    @staticmethod
    async def _mandar(w: asyncio.StreamWriter, env: Envelope) -> None:
        w.write((encode(env) + "\n").encode())
        await w.drain()

    @staticmethod
    async def _fecha(w: asyncio.StreamWriter | None) -> None:
        if w is None:
            return
        with contextlib.suppress(Exception):
            w.close()
            await asyncio.wait_for(w.wait_closed(), 0.5)

    async def _ler(self, r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        try:
            while line := await r.readline():
                try:
                    env = decode(line)
                except EloError as e:
                    log.warning("casa: envelope inválido (%s)", e)
                    continue
                self._recebe(env)
        except (OSError, ValueError, asyncio.IncompleteReadError):
            log.info("casa: elo caiu")
        finally:
            for fut in self._pend.values():
                if not fut.done():
                    fut.set_exception(_Caiu())
            self._pend.clear()
            await self._fecha(w)

    def _recebe(self, env: Envelope) -> None:
        if env.t is Tipo.OLA and isinstance(env.corpo, Ola):
            self._aplica_ola(env.corpo)
        elif env.t is Tipo.ESTADO and isinstance(env.corpo, Estado):
            self.estados = env.corpo.tvs
            esperando, self._esperando_estado = self._esperando_estado, []
            for fut in esperando:
                if not fut.done():
                    fut.set_result(env.corpo.tvs)
        if env.resp is not None and (fut := self._pend.pop(env.resp, None)) is not None and not fut.done():
            fut.set_result(env)

    def _aplica_ola(self, ola: Ola) -> None:
        entradas: dict[str, str] = {}
        if self.host in ("127.0.0.1", "localhost", "::1"):  # casa deste PC: casa.toml ao lado
            entradas.update(entradas_do_toml(self.casa_toml or casa_toml_padrao()))
        entradas.update(entradas_do_ola(ola.tvs))
        self.catalogo = CasaCatalogo(tvs=ola.tvs, apps=ola.apps, entradas=entradas)
        if self.ao_catalogo is not None:
            try:
                self.ao_catalogo(self.catalogo)
            except Exception:
                log.exception("casa: falha ao trocar o catálogo do roteador")

    async def aquecer(self) -> None:
        """Tenta o elo uma vez (catálogo pronto para o roteador). Nunca levanta."""
        try:
            await self._conectar()
        except Exception:
            log.exception("casa: aquecimento falhou")

    async def aclose(self) -> None:
        if self._leitor is not None:
            self._leitor.cancel()
            with contextlib.suppress(BaseException):
                await self._leitor
        await self._fecha(self._w)
        self._w = self._leitor = None

    # -- pedidos -------------------------------------------------------------------------------
    async def _pedir(self, env: Envelope, timeout: float) -> Envelope | None:
        """Manda ``env`` e espera a resposta (``resp``). ``None`` = estourou o prazo."""
        assert self._w is not None
        fut: asyncio.Future[Envelope] = asyncio.get_running_loop().create_future()
        self._pend[env.id] = fut
        try:
            await self._mandar(self._w, env)
            return await asyncio.wait_for(fut, timeout)
        except TimeoutError:
            return None
        finally:
            self._pend.pop(env.id, None)

    async def run(self, req: ActionRequest) -> ActionResult:
        try:
            return await self._run(req)
        except Exception:  # nunca derruba o turno: a casa é opcional
            log.exception("casa: %s falhou", req.intent.id)
            return ActionResult(ok=False, speech=SAY_CASA_OFF, expression=Expression.CONFUSED)

    async def _run(self, req: ActionRequest) -> ActionResult:
        if req.intent.id == IntentId.TV_POWER_OFF and not req.confirmed:
            return self._confirma(req)
        longo = req.intent.id in _LONGOS or (req.intent.id == IntentId.TV_VOLUME and _absoluto(req))
        timeout = self.timeout_longo_s if longo else self.timeout_s
        pedido = pedido_de_request(replace(req, args=_escalares(req.args)))
        prazo = max(500, min(30_000, round(timeout * 1000)))
        for tentativa in range(2):  # 2ª vez: elo velho (casa fechou por ócio) — reabre uma vez
            if not await self._conectar():
                return ActionResult(ok=False, speech=SAY_CASA_OFF, expression=Expression.CONFUSED)
            env = Envelope(t=Tipo.ACAO, corpo=Acao(pedido=pedido, origem="voz-pc", prazo_ms=prazo),
                           de=DE, para=PARA)
            try:
                resp = await self._pedir(env, timeout)
            except (_Caiu, OSError):
                await self._fecha(self._w)
                if tentativa == 0:
                    continue
                return ActionResult(ok=False, speech=SAY_CASA_OFF, expression=Expression.CONFUSED)
            if resp is None:
                return ActionResult(ok=False, speech=SAY_TV_NO_RESPONSE, expression=Expression.CONFUSED)
            if isinstance(resp.corpo, AcaoOk):
                return self.traduz(req, resp.corpo.resultado)
            if isinstance(resp.corpo, Erro) and resp.corpo.codigo == "nao_autorizado":
                log.warning("casa: token recusado")
                return ActionResult(ok=False, speech=SAY_CASA_OFF, expression=Expression.CONFUSED)
            return ActionResult(ok=False, speech=SAY_TV_REFUSED, expression=Expression.CONFUSED)
        return ActionResult(ok=False, speech=SAY_CASA_OFF, expression=Expression.CONFUSED)

    async def estado(self) -> tuple[bool, tuple[EstadoTv, ...]]:
        """Pede o estado das TVs: ``(casa no ar, estados)``; sem resposta fica o último empurrado."""
        try:
            if not await self._conectar() or self._w is None:
                return False, ()
            fut: asyncio.Future[tuple[EstadoTv, ...]] = asyncio.get_running_loop().create_future()
            self._esperando_estado.append(fut)
            await self._mandar(self._w, Envelope(t=Tipo.ESTADO, corpo=Estado(), de=DE, para=PARA))
            try:
                return True, await asyncio.wait_for(fut, self.timeout_s)
            except (TimeoutError, _Caiu):
                return True, self.estados
        except Exception:
            log.exception("casa: estado falhou")
            return False, ()

    # -- respostas -----------------------------------------------------------------------------
    def tv(self, tv_id: str | None) -> TvInfo | None:
        return next((t for t in self.catalogo.tvs if t.id == tv_id), None)

    def _nome_tv(self, req: ActionRequest, res: AcaoResultado | None = None) -> str:
        tv_id = str(res.dados.get("tv") or "") if res is not None else ""
        slot = req.intent.slot(SlotName.TV)
        info = self.tv(tv_id or (slot.value if slot else None))
        if info is not None:
            return info.nome
        if slot is not None:
            return slot.display or slot.value
        return "TV"

    def _confirma(self, req: ActionRequest) -> ActionResult:
        nome = self._nome_tv(req)
        say = SAY_TV_CONFIRM_OFF_PLAIN if nome == "TV" else SAY_TV_CONFIRM_OFF.format(nome=nome)
        return ActionResult(ok=True, speech=say, needs_confirmation=True, dangerous=True,
                            on_confirm=replace(req, confirmed=True), expression=Expression.ALERT)

    def traduz(self, req: ActionRequest, res: AcaoResultado) -> ActionResult:
        """``AcaoResultado`` da casa → ``ActionResult`` com a frase da §13.2."""
        intent = str(req.intent.id)
        if res.ok:
            if intent == IntentId.TV_VOLUME and not _absoluto(req):
                say = SAY_TV_STEP
            elif intent in (IntentId.TV_MUTE, IntentId.TV_UNMUTE) and res.dados.get("emulado"):
                say = SAY_TV_MUTE_TOGGLED
            elif intent == IntentId.TV_APP and (app := req.intent.slot(SlotName.APP)) is not None:
                apps = self.catalogo.apps
                nome = app.display or next((a.nome for a in apps if a.id == app.value), app.value)
                say = SAY_TV_APP_OPEN.format(nome=nome)
            else:
                say = SAY_TV_OK.get(intent, SAY_TV_STEP)
            return ActionResult(ok=True, speech=say)
        motivo = res.motivo or ""
        if motivo == "tv_ambigua":
            return self._pergunta(req, res)
        if motivo == "precisa_confirmar" or res.precisa_confirmar:
            return self._confirma(req)
        nome = self._nome_tv(req, res)
        if motivo == "rede_desligada":
            info = self.tv(str(res.dados.get("tv") or "")) or self.tv(
                s.value if (s := req.intent.slot(SlotName.TV)) else None)
            tpl = SAY_TV_REDE.get(info.driver if info else "", SAY_TV_REDE[""])
        elif motivo in SAY_TV_MOTIVO:
            tpl = SAY_TV_MOTIVO[motivo]
        else:
            tpl = SAY_TV_ON_FAILED if intent == IntentId.TV_POWER_ON else SAY_TV_REFUSED
        if intent == IntentId.TV_POWER_ON and motivo == "offline":
            tpl = SAY_TV_ON_FAILED
        return ActionResult(ok=False, speech=tpl.format(nome=nome), expression=Expression.CONFUSED)

    def _pergunta(self, req: ActionRequest, res: AcaoResultado) -> ActionResult:
        """``TV_AMBIGUA`` → "Mais de uma TV: sala ou quarto?" + escolha na próxima fala (DS13)."""
        ids = res.dados.get("candidatos")
        tvs = [t for t in self.catalogo.tvs if not isinstance(ids, list | tuple) or t.id in ids]
        if len(tvs) < 2:
            return ActionResult(ok=False, speech=SAY_TV_WHICH, expression=Expression.CONFUSED)
        nomes = [falado(t) for t in tvs]
        juntos = ", ".join(nomes[:-1]) + " ou " + nomes[-1]

        def escolha(texto: str) -> ActionRequest | None:
            return self.escolher(req, texto, tvs)

        args = {**req.args, ARG_ESCOLHA: escolha, ARG_QUIET: True}
        return ActionResult(ok=True, speech=SAY_TV_AMBIGUOUS.format(nome=juntos), needs_confirmation=True,
                            on_confirm=replace(req, args=args), expression=Expression.CONFUSED)

    @staticmethod
    def escolher(req: ActionRequest, texto: str, tvs: Sequence[TvInfo]) -> ActionRequest | None:
        """Resposta curta ("a da sala") → ``req`` com o slot ``tv``; não casou → ``None``."""
        tv_id = acha_nome(texto, [n for t in tvs for n in nomes_tv(t)])
        if tv_id is None:
            return None
        info = next(t for t in tvs if t.id == tv_id)
        slot = Slot(SlotName.TV.value, info.id, raw=texto, display=info.nome)
        slots = tuple(s for s in req.intent.slots if s.name != SlotName.TV) + (slot,)
        args = {k: v for k, v in req.args.items() if k not in (ARG_ESCOLHA, ARG_QUIET)}
        return replace(req, intent=replace(req.intent, slots=slots), args=args)


def tv_actions_de(registry: Any) -> TvActions | None:
    """O ``TvActions`` registrado (para as ferramentas ``tv_*``), se houver."""
    por_intent = getattr(registry, "_by_intent", None)
    h = por_intent.get(IntentId.TV_POWER_ON.value) if isinstance(por_intent, Mapping) else None
    return h if isinstance(h, TvActions) else None


def entrada_canonica(texto: str, catalogo: CasaCatalogo) -> str | None:
    """"hdmi 2"/"HDMI2"/"2"/apelido → ``hdmiN`` (ou ``tv``/``av``); ``None`` se não reconhece."""
    k = "".join(normalize_text(texto))
    if _HDMI_RE.match(k):
        return k
    if k.isdigit() and 1 <= int(k) <= 4:
        return f"hdmi{k}"
    if k in ("tv", "av"):
        return k
    return acha_nome(texto, list(catalogo.entradas.items()))
