"""``Executor``: de intent a driver, com emulação honesta (spec §10.6, §10.7, §11.5, §13.3; dono:
C1.1b).

``Executor.rodar(req)``:

1. resolve a TV (§13.3, [DS13]): slot ``tv`` → ``padrao`` do ``casa.toml`` → única TV → (comando ≠
   ligar) única TV ``ligada=True`` → ``TV_AMBIGUA`` com os ids candidatos em ``detalhe`` (separados
   por vírgula); nome que não existe → ``TV_DESCONHECIDA``;
2. ``tv.power_off`` sem ``confirmed`` → ``PRECISA_CONFIRMAR`` (driver não é chamado);
3. traduz o intent para o método do ``TvDriver`` (tabela ``INTENTS``);
4. cap ausente → emulação (só se a cap estiver em ``capacidades.emula``) ou ``NAO_SUPORTADO``;
5. cada chamada ao driver tem o prazo da §11.5 (``PRAZOS``); estourou → ``TEMPO_ESGOTADO``, a
   conexão é descartada (``fechar``) e reaberta (``conectar``) na chamada seguinte;
6. loga uma linha ``acao`` (``tv, driver, acao, ok, motivo, ms, origem``).

O ``Executor`` nunca devolve ``ok=True`` quando o driver devolveu ``ok=False``, e ligar só é ``ok``
com ``ligada=True`` confirmado (sonda a cada 500 ms por até 8 s; o Roku confirma sozinho, C1.3).

Estado: ``estados`` (``tv_id → EstadoTv``) é o cache vivo, que a C1.1c pode compartilhar; o
``Executor`` o atualiza a cada ``state()`` que faz. Relógio e ``dormir`` são injetados.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable, Hashable, Mapping, MutableMapping
from dataclasses import dataclass, replace
from typing import Any

from magi.casa import log
from magi.casa.config import CasaConfig, normaliza
from magi.casa.driver import (
    ENTRADAS_CANONICAS,
    Cap,
    EstadoTv,
    Key,
    Motivo,
    ResTv,
    TvConfig,
    TvDriver,
)
from magi.casa.fila import FilaTv, Vez
from magi.common.contracts import ActionRequest

# Intents da §13.1 e os do controle remoto (PWA/MCP; args: ``step``, ``key``, ``texto``).
TV_POWER_ON = "tv.power_on"
TV_POWER_OFF = "tv.power_off"
TV_VOLUME = "tv.volume"
TV_MUTE = "tv.mute"
TV_UNMUTE = "tv.unmute"
TV_APP = "tv.app"
TV_INPUT = "tv.input"
TV_CHANNEL = "tv.channel"  # args step=±n
TV_KEY = "tv.key"  # args key=<Key>
TV_TEXT = "tv.text"  # args texto=<str>
TV_STATE = "tv.state"

#: intent → método do ``TvDriver`` (CA-Y30).
INTENTS: Mapping[str, str] = {
    TV_POWER_ON: "power",
    TV_POWER_OFF: "power",
    TV_VOLUME: "volume",
    TV_MUTE: "mute",
    TV_UNMUTE: "mute",
    TV_APP: "app",
    TV_INPUT: "input",
    TV_CHANNEL: "channel",
    TV_KEY: "key",
    TV_TEXT: "text",
    TV_STATE: "state",
}

TECLA_S = 0.08  # 80 ms entre teclas emuladas
SONDA_S = 0.5  # sondagem do ligar
LIGAR_S = 8.0
MAX_TECLAS_COM_ESTADO = 60
MAX_TECLAS_SEM_ESTADO = 100  # [DS10]
MAX_N_SEM_ESTADO = 50
MAX_CORRECAO = 3
PASSO_MAX = 30
DRIVERS_WOL = frozenset({"samsung", "roku"})
ACIMA = "acima do que dá para emular"


@dataclass(frozen=True)
class Prazos:
    """Prazos da §11.5, em segundos."""

    conectar: float
    simples: float
    ligar: float
    sondagem: float
    emulacao: float


PRAZOS: Mapping[str, Prazos] = {
    "samsung": Prazos(conectar=3.0, simples=2.0, ligar=8.0, sondagem=1.5, emulacao=8.0),
    "roku": Prazos(conectar=1.5, simples=1.5, ligar=8.0, sondagem=1.5, emulacao=8.0),  # HTTP
    "androidtv": Prazos(conectar=4.0, simples=2.0, ligar=8.0, sondagem=2.0, emulacao=4.8),  # push
}
PRAZO_PADRAO = Prazos(conectar=3.0, simples=2.0, ligar=8.0, sondagem=1.5, emulacao=8.0)


class _Esgotou(Exception):
    def __init__(self, res: ResTv) -> None:
        self.res = res


def candidatos(res: ResTv) -> tuple[str, ...]:
    """Ids candidatos de um ``TV_AMBIGUA`` (vêm em ``detalhe``, separados por vírgula)."""
    if res.motivo is not Motivo.TV_AMBIGUA or not res.detalhe:
        return ()
    return tuple(x for x in res.detalhe.split(",") if x)


class Executor:
    def __init__(
        self,
        cfg: CasaConfig,
        drivers: Mapping[str, TvDriver],
        *,
        estados: MutableMapping[str, EstadoTv] | None = None,
        fila: FilaTv | None = None,
        relogio: Callable[[], float] | None = None,
        dormir: Callable[[float], Awaitable[None]] | None = None,
        prazos: Mapping[str, Prazos] | None = None,
    ) -> None:
        self.cfg = cfg
        self.drivers = drivers
        self.estados: MutableMapping[str, EstadoTv] = estados if estados is not None else {}
        self.relogio = relogio or time.monotonic
        self.dormir = dormir or asyncio.sleep
        self.fila = fila or FilaTv(relogio=self.relogio)
        self.prazos = dict(PRAZOS if prazos is None else prazos)
        self._descartados: set[str] = set()

    # --- escolha da TV (§13.3) --------------------------------------------------------------
    def escolher_tv(self, req: ActionRequest) -> TvConfig | ResTv:
        tvs = self.cfg.tvs
        slot = req.intent.slot("tv")
        if slot is not None and (slot.value or slot.raw):
            alvo = normaliza(slot.value or slot.raw)
            for tv in tvs:
                nomes = (tv.id, tv.nome, *tv.apelidos)
                if any(normaliza(n) == alvo for n in nomes):
                    return tv
            return ResTv(False, Motivo.TV_DESCONHECIDA, slot.value or slot.raw)
        if not tvs:
            return ResTv(False, Motivo.TV_DESCONHECIDA, "nenhuma TV configurada")
        if self.cfg.padrao and (tv := self.cfg.tv(self.cfg.padrao)) is not None:
            return tv
        if len(tvs) == 1:
            return tvs[0]
        ligadas = [t for t in tvs if (e := self.estados.get(t.id)) is not None and e.ligada is True]
        if req.intent.id != TV_POWER_ON and len(ligadas) == 1:
            return ligadas[0]
        cands = ligadas if len(ligadas) > 1 and req.intent.id != TV_POWER_ON else list(tvs)
        return ResTv(False, Motivo.TV_AMBIGUA, ",".join(t.id for t in cands))

    # --- entrada -----------------------------------------------------------------------------
    async def rodar(self, req: ActionRequest, *, origem: str = "local") -> ResTv:
        t0 = self.relogio()
        intent = req.intent.id
        tv: TvConfig | None = None
        drv: TvDriver | None = None
        res: ResTv
        if intent not in INTENTS:
            res = ResTv(False, Motivo.NAO_SUPORTADO, f"intent {intent}")
        else:
            escolha = self.escolher_tv(req)
            if isinstance(escolha, ResTv):
                res = escolha
            else:
                tv = escolha
                drv = self.drivers.get(tv.id)
                if drv is None:
                    res = ResTv(False, Motivo.ERRO_DRIVER, f"{tv.id}: sem driver")
                elif intent == TV_POWER_OFF and not req.confirmed:
                    res = ResTv(False, Motivo.PRECISA_CONFIRMAR, "tv.power_off")
                else:
                    tv_ok, drv_ok = tv, drv

                    async def vez_de(vez: Vez) -> ResTv:
                        return await self._executar(tv_ok, drv_ok, req, vez)

                    res = await self.fila.rodar(tv.id, vez_de, repeticao=_repeticao(req))
        log.evento(
            "acao",
            tv=tv.id if tv else None,
            driver=drv.nome if drv else None,
            acao=intent,
            ok=res.ok,
            motivo=res.motivo.value if res.motivo else None,
            ms=round((self.relogio() - t0) * 1000),
            origem=origem,
            emulado=res.emulado,
        )
        return res

    async def _executar(self, tv: TvConfig, drv: TvDriver, req: ActionRequest, vez: Vez) -> ResTv:
        try:
            return await self._despachar(tv, drv, req, vez)
        except _Esgotou as e:
            return e.res

    async def _despachar(self, tv: TvConfig, drv: TvDriver, req: ActionRequest, vez: Vez) -> ResTv:
        intent = req.intent.id
        caps = drv.capacidades
        args = req.args
        p = self._prazo(drv)
        if intent in (TV_POWER_ON, TV_POWER_OFF):
            return await self._power(tv, drv, intent == TV_POWER_ON, vez)
        if intent == TV_VOLUME:
            return await self._volume(tv, drv, req, vez)
        if intent in (TV_MUTE, TV_UNMUTE):
            return await self._mute(tv, drv, intent == TV_MUTE)
        if intent == TV_STATE:
            st = await self._estado(tv, drv)
            if st is None:
                return ResTv(False, Motivo.OFFLINE, "sem estado")
            return ResTv(True, estado=st)
        if intent == TV_INPUT:
            if Cap.INPUT not in caps.caps:  # não emula: o menu de fonte varia por modelo
                return ResTv(False, Motivo.NAO_SUPORTADO, "sem input")
            nome = _slot(req, "input")
            canon = _entrada(tv, nome)
            if canon is None:
                return ResTv(False, Motivo.ENTRADA_DESCONHECIDA, nome)
            return await self._chamar(tv, drv, p.simples, lambda: drv.input(canon))
        if intent == TV_APP:
            if Cap.APP not in caps.caps:
                return ResTv(False, Motivo.NAO_SUPORTADO, "sem app")
            app_id = _slot(req, "app")
            return await self._chamar(tv, drv, p.simples, lambda: drv.app(app_id))
        if intent == TV_CHANNEL:
            if Cap.CHANNEL not in caps.caps:
                return ResTv(False, Motivo.NAO_SUPORTADO, "sem channel")
            step = int(args.get("step", 1))
            return await self._chamar(tv, drv, p.simples, lambda: drv.channel(step))
        if intent == TV_KEY:
            if Cap.KEY not in caps.caps:
                return ResTv(False, Motivo.NAO_SUPORTADO, "sem key")
            try:
                key = Key(str(args.get("key", "")))
            except ValueError:
                return ResTv(False, Motivo.NAO_SUPORTADO, f"tecla {args.get('key')!r}")
            return await self._chamar(tv, drv, p.simples, lambda: drv.key(key))
        if intent == TV_TEXT:
            if Cap.TEXT not in caps.caps:
                return ResTv(False, Motivo.NAO_SUPORTADO, "sem text")
            texto = str(args.get("texto", req.text))
            return await self._chamar(tv, drv, p.simples, lambda: drv.text(texto))
        return ResTv(False, Motivo.NAO_SUPORTADO, intent)  # pragma: no cover

    # --- chamadas com prazo (§11.5) --------------------------------------------------------
    def _prazo(self, drv: TvDriver) -> Prazos:
        return self.prazos.get(drv.nome, PRAZO_PADRAO)

    async def _com_prazo(
        self, tv: TvConfig, drv: TvDriver, limite: float, fn: Callable[[], Awaitable[Any]]
    ) -> Any:
        """Chama o driver com prazo; estouro (pelo ``wait_for`` ou pelo relógio injetado) levanta
        ``_Esgotou`` depois de descartar a conexão; exceção do driver → ``ERRO_DRIVER``."""
        if tv.id in self._descartados and fn.__name__ != "_conectar":
            self._descartados.discard(tv.id)
            r = await self._com_prazo(tv, drv, self._prazo(drv).conectar, _conectar(drv))
            if not r.ok:
                self._descartados.add(tv.id)
                raise _Esgotou(r)
        t0 = self.relogio()
        try:
            r = await asyncio.wait_for(fn(), limite)
        except TimeoutError:
            r = None
            esgotou = True
        except Exception as e:  # o contrato diz que o driver não levanta; se levantar, vira motivo
            log.evento("driver_erro", 40, exc=True, tv=tv.id, driver=drv.nome)
            raise _Esgotou(ResTv(False, Motivo.ERRO_DRIVER, type(e).__name__)) from None
        else:
            esgotou = self.relogio() - t0 > limite
        if esgotou:
            await self._descartar(tv, drv)
            raise _Esgotou(ResTv(False, Motivo.TEMPO_ESGOTADO, f"{drv.nome}: > {limite:g} s"))
        return r

    async def _chamar(
        self, tv: TvConfig, drv: TvDriver, limite: float, fn: Callable[[], Awaitable[ResTv]]
    ) -> ResTv:
        r = await self._com_prazo(tv, drv, limite, fn)
        if r.estado is not None:
            self.estados[tv.id] = r.estado
        return r

    async def _descartar(self, tv: TvConfig, drv: TvDriver) -> None:
        self._descartados.add(tv.id)
        with contextlib.suppress(Exception):
            await asyncio.wait_for(drv.fechar(), self._prazo(drv).simples)
        log.evento("conexao_descartada", tv=tv.id, driver=drv.nome)

    async def _estado(self, tv: TvConfig, drv: TvDriver) -> EstadoTv | None:
        """Relê o estado (prazo de sondagem); falha → último conhecido (ou ``None``)."""
        try:
            st = await self._com_prazo(tv, drv, self._prazo(drv).sondagem, drv.state)
        except _Esgotou:
            return None
        if isinstance(st, EstadoTv):
            self.estados[tv.id] = st
            return st
        return None

    # --- ligar/desligar (§10.7, R6.5) ------------------------------------------------------
    async def _power(self, tv: TvConfig, drv: TvDriver, on: bool, vez: Vez) -> ResTv:
        cap = Cap.POWER_ON if on else Cap.POWER_OFF
        caps = drv.capacidades
        t0 = self.relogio()
        antes = self.estados.get(tv.id)
        online_antes = bool(antes and antes.online)
        if cap in caps.caps:
            r = await self._chamar(tv, drv, self._prazo(drv).ligar, lambda: drv.power(on))
            if not r.ok or not on:
                return r
            if drv.nome == "roku" or (r.estado is not None and r.estado.ligada is True):
                return r  # o Roku relê o device-info e confirma sozinho (C1.3)
            return await self._confirmar_ligada(tv, drv, t0, online_antes, emulado=r.emulado)
        if cap in caps.emula and Cap.KEY in caps.caps:
            st = await self._estado(tv, drv)
            if st is None or st.ligada is None:
                return ResTv(False, Motivo.NAO_SUPORTADO, "estado desconhecido")
            if st.ligada is on:
                return ResTv(True, detalhe="já estava", emulado=True, estado=st)
            r = await self._chamar(tv, drv, self._prazo(drv).simples, lambda: drv.key(Key.POWER))
            if not r.ok:
                return replace(r, emulado=True)
            if not on:
                return ResTv(True, emulado=True)
            return await self._confirmar_ligada(tv, drv, t0, st.online, emulado=True)
        return ResTv(False, Motivo.NAO_SUPORTADO, f"sem {cap.value}")

    async def _confirmar_ligada(
        self, tv: TvConfig, drv: TvDriver, t0: float, online_antes: bool, *, emulado: bool
    ) -> ResTv:
        respondeu = online_antes
        while self.relogio() + SONDA_S <= t0 + LIGAR_S + 1e-9:
            await self.dormir(SONDA_S)
            st = await self._estado(tv, drv)
            if st is None:
                continue
            respondeu = respondeu or st.online
            if st.ligada is True:
                return ResTv(True, emulado=emulado, estado=st)
        if not respondeu:
            if not tv.mac and drv.nome in DRIVERS_WOL:
                return ResTv(False, Motivo.SEM_MAC, "sem MAC no casa.toml", emulado=emulado)
            return ResTv(False, Motivo.REDE_DESLIGADA, "sem resposta de rede", emulado=emulado)
        return ResTv(False, Motivo.STANDBY_PROFUNDO, f"não ligou em {LIGAR_S:g} s", emulado=emulado)

    # --- volume (§10.7) -------------------------------------------------------------------
    async def _volume(self, tv: TvConfig, drv: TvDriver, req: ActionRequest, vez: Vez) -> ResTv:
        valor = _slot(req, "volume").strip()
        caps = drv.capacidades
        p = self._prazo(drv)
        if not valor:
            return ResTv(False, Motivo.NAO_SUPORTADO, "volume sem valor")
        try:
            n = int(valor)
        except ValueError:
            return ResTv(False, Motivo.NAO_SUPORTADO, f"volume {valor!r}")
        if valor[0] in "+-":
            k = max(1, min(PASSO_MAX, abs(n))) * (1 if n >= 0 else -1)
            if Cap.VOL_STEP in caps.caps:
                return await self._chamar(tv, drv, p.simples, lambda: drv.volume(step=k))
            if Cap.VOL_STEP in caps.emula and Cap.KEY in caps.caps:
                return await self._teclas(tv, drv, k, vez, self.relogio())
            return ResTv(False, Motivo.NAO_SUPORTADO, "sem vol_step")
        n = max(0, min(100, n))
        if Cap.VOL_SET in caps.caps:
            return await self._chamar(tv, drv, p.simples, lambda: drv.volume(set_to=n))
        if Cap.VOL_SET not in caps.emula or not (caps.caps & {Cap.VOL_STEP, Cap.KEY}):
            return ResTv(False, Motivo.NAO_SUPORTADO, "sem vol_set")
        return await self._emular_vol_set(tv, drv, n, vez)

    def _passos(self, drv: TvDriver, delta: int) -> int:
        """Delta na escala 0–100 → teclas (1 tecla = 100/``vol_max``; C1.4)."""
        vmax = drv.capacidades.vol_max or 100
        return round(abs(delta) * vmax / 100)

    async def _emular_vol_set(self, tv: TvConfig, drv: TvDriver, n: int, vez: Vez) -> ResTv:
        t0 = self.relogio()
        st = await self._estado(tv, drv) if Cap.STATE in drv.capacidades.caps else None
        st = st or self.estados.get(tv.id)
        atual = st.volume if st is not None else None
        if atual is not None:
            passos = self._passos(drv, n - atual)
            if passos > MAX_TECLAS_COM_ESTADO:
                return ResTv(False, Motivo.NAO_SUPORTADO, ACIMA)
            sinal = 1 if n >= atual else -1
            r = await self._teclas(tv, drv, sinal * passos, vez, t0)
            if not r.ok:
                return r
            le = Cap.STATE in drv.capacidades.caps
            st2 = await self._estado(tv, drv) if le else None
            if st2 is not None and st2.volume is not None and st2.volume != n:
                corr = self._passos(drv, n - st2.volume)
                if 0 < corr <= MAX_CORRECAO:
                    sinal = 1 if n > st2.volume else -1
                    r = await self._teclas(tv, drv, corr * sinal, vez, None, primeira=False)
                    if not r.ok:
                        return r
                    st2 = await self._estado(tv, drv)
            return ResTv(True, emulado=True, estado=st2)
        zerar = tv.zerar_passos
        subir = self._passos(drv, n)
        if subir > MAX_N_SEM_ESTADO or zerar + subir > MAX_TECLAS_SEM_ESTADO:
            return ResTv(False, Motivo.NAO_SUPORTADO, ACIMA)
        r = await self._teclas(tv, drv, -zerar, vez, t0)
        if r.ok:
            r = await self._teclas(tv, drv, subir, vez, t0, primeira=False)
        if not r.ok:
            return r
        return ResTv(True, emulado=True, detalhe=f"zerou {zerar} e subiu {subir}")

    async def _teclas(
        self, tv: TvConfig, drv: TvDriver, passos: int, vez: Vez, t0: float | None, *, primeira: bool = True
    ) -> ResTv:
        """``|passos|`` teclas de volume a 80 ms; aborta se outra ``acao`` da TV chegar; ``t0`` conta
        o prazo de emulação da §11.5 (``None`` = correção, fora do prazo)."""
        p = self._prazo(drv)
        usa_step = Cap.VOL_STEP in drv.capacidades.caps
        sinal = 1 if passos >= 0 else -1
        for i in range(abs(passos)):
            if i > 0 or not primeira:
                await self.dormir(TECLA_S)
            if vez.abortada:
                return ResTv(False, Motivo.OCUPADA, "interrompida por outra ação", emulado=True)
            if t0 is not None and self.relogio() - t0 > p.emulacao + 1e-9:
                await self._descartar(tv, drv)
                return ResTv(False, Motivo.TEMPO_ESGOTADO, f"emulação > {p.emulacao:g} s", emulado=True)
            if usa_step:
                r = await self._chamar(tv, drv, p.simples, lambda: drv.volume(step=sinal))
            else:
                k = Key.VOL_UP if sinal > 0 else Key.VOL_DOWN
                r = await self._chamar(tv, drv, p.simples, lambda k=k: drv.key(k))
            if not r.ok:
                return replace(r, emulado=True)
        return ResTv(True, emulado=True)

    # --- mudo (§10.7) ----------------------------------------------------------------------
    async def _mute(self, tv: TvConfig, drv: TvDriver, on: bool) -> ResTv:
        caps = drv.capacidades
        p = self._prazo(drv)
        if Cap.MUTE in caps.caps:
            alternar: Callable[[], Awaitable[ResTv]] = lambda: drv.mute(None)  # noqa: E731
        elif Cap.MUTE in caps.emula and Cap.KEY in caps.caps:
            alternar = lambda: drv.key(Key.MUTE)  # noqa: E731
        else:
            return ResTv(False, Motivo.NAO_SUPORTADO, "sem mute")
        st = await self._estado(tv, drv) if Cap.STATE in caps.caps else self.estados.get(tv.id)
        mudo = st.mudo if st is not None else None
        if mudo is on:
            return ResTv(True, detalhe="já estava", estado=st)
        if mudo is not None and Cap.MUTE in caps.caps:  # conhecido e diferente: pede explícito
            r = await self._chamar(tv, drv, p.simples, lambda: drv.mute(on))
            if r.ok or r.motivo is not Motivo.NAO_SUPORTADO:
                return r
        r = await self._chamar(tv, drv, p.simples, alternar)
        if not r.ok:
            return replace(r, emulado=True)
        if mudo is None:
            return ResTv(True, emulado=True, detalhe="alternado")
        return ResTv(True, emulado=True)


# --- utilidades -----------------------------------------------------------------------------
def _slot(req: ActionRequest, nome: str) -> str:
    s = req.intent.slot(nome)
    if s is not None and s.value:
        return s.value
    v = req.args.get(nome)
    return "" if v is None else str(v)


def _entrada(tv: TvConfig, nome: str) -> str | None:
    alvo = normaliza(nome).replace(" ", "")
    if alvo in ENTRADAS_CANONICAS:
        return alvo
    for apelido, canon in tv.entradas.items():
        if normaliza(apelido) == normaliza(nome):
            return canon
    return None


def _repeticao(req: ActionRequest) -> Hashable | None:
    """Assinatura de comando repetível (segurar a tecla no PWA): tecla, passo de volume, canal."""
    i = req.intent.id
    if i == TV_KEY:
        return (i, str(req.args.get("key", "")))
    if i == TV_CHANNEL:
        return (i, str(req.args.get("step", 1)))
    if i == TV_VOLUME:
        v = _slot(req, "volume").strip()
        if v[:1] in ("+", "-"):
            return (i, v)
    return None


def _conectar(drv: TvDriver) -> Callable[[], Awaitable[ResTv]]:
    async def _conectar() -> ResTv:
        return await drv.conectar()

    return _conectar
