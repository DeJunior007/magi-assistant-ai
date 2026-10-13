"""Ferramentas ``tv_*`` do agente (ayanami-central C2.2, spec §13.4, DS14).

Traduzem argumentos em intents ``tv.*``; quem executa é o ``TvActions`` (``magi/core/actions/tv.py``)
pelo ``ActionRegistry``. Nomes de TV, app e entrada casam com o catálogo do ``ola`` da casa; sem
catálogo (casa ainda não respondeu) o nome segue cru e a casa decide. ``tv_estado`` só lê e não é
serial. A descrição lista as TVs do catálogo do momento em que o agente monta as ferramentas.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any

from magi.agent.tools.base import ActionTool, Mapped, Mapper, ToolArgsError, arg_str
from magi.common.contracts import (
    ActionRegistry,
    ActionResult,
    Expression,
    IntentId,
    Slot,
    SlotName,
    ToolSpec,
    TurnContext,
)
from magi.core.actions.tv import (
    SAY_CASA_OFF,
    SAY_TV_CONFIRM_OFF,
    SAY_TV_CONFIRM_OFF_PLAIN,
    TvActions,
    acha_nome,
    entrada_canonica,
    nomes_tv,
)
from magi.core.router import CasaCatalogo

Catalogo = Callable[[], CasaCatalogo]

_VOL_RE = re.compile(r"^[+-]?\d{1,3}$")
_TV_ARG = {"tv": {"type": "string", "description": "Nome da TV; omitido = a padrão"}}


def _descricao(base: str, cat: CasaCatalogo) -> str:
    if not cat.tvs:
        return base
    nomes = ", ".join(t.nome for t in cat.tvs)
    padrao = next((t.nome for t in cat.tvs if t.padrao), None)
    return f"{base} TVs: {nomes}" + (f" (padrão: {padrao})." if padrao else ".")


def _spec(
    name: str, base: str, props: Mapping[str, Any], required: tuple[str, ...], cat: CasaCatalogo
) -> ToolSpec:
    params: dict[str, Any] = {"type": "object", "properties": {**props, **_TV_ARG}}
    if required:
        params["required"] = list(required)
    return ToolSpec(name=name, description=_descricao(base, cat), parameters=params)


def _slot_tv(args: Mapping[str, Any], cat: CasaCatalogo) -> tuple[Slot, ...]:
    nome = arg_str(args, "tv")
    if not nome:
        return ()
    if not cat.tvs:
        return (Slot(SlotName.TV.value, nome, raw=nome, display=nome),)
    tv_id = acha_nome(nome, [n for t in cat.tvs for n in nomes_tv(t)])
    if tv_id is None:
        raise ToolArgsError("Qual TV?")
    info = next(t for t in cat.tvs if t.id == tv_id)
    return (Slot(SlotName.TV.value, info.id, raw=nome, display=info.nome),)


def map_ligar(cat: Catalogo) -> Mapper:
    return lambda args: Mapped(IntentId.TV_POWER_ON.value, _slot_tv(args, cat()))


def map_desligar(cat: Catalogo) -> Mapper:
    def m(args: Mapping[str, Any]) -> Mapped:
        slots = _slot_tv(args, cat())
        say = SAY_TV_CONFIRM_OFF.format(nome=slots[0].display) if slots else SAY_TV_CONFIRM_OFF_PLAIN
        return Mapped(IntentId.TV_POWER_OFF.value, slots, confirm_speech=say)

    return m


def map_volume(cat: Catalogo) -> Mapper:
    def m(args: Mapping[str, Any]) -> Mapped:
        valor = arg_str(args, "valor").replace(" ", "")
        if not _VOL_RE.match(valor) or (valor[0] not in "+-" and int(valor) > 100):
            raise ToolArgsError("Quanto de volume?")
        return Mapped(IntentId.TV_VOLUME.value, (Slot(SlotName.VOLUME.value, valor), *_slot_tv(args, cat())))

    return m


def map_mudo(cat: Catalogo) -> Mapper:
    def m(args: Mapping[str, Any]) -> Mapped:
        ligado = args.get("ligado")
        if not isinstance(ligado, bool):
            raise ToolArgsError("Mudo ligado ou desligado?")
        intent = IntentId.TV_MUTE if ligado else IntentId.TV_UNMUTE
        return Mapped(intent.value, _slot_tv(args, cat()))

    return m


def map_app(cat: Catalogo) -> Mapper:
    def m(args: Mapping[str, Any]) -> Mapped:
        nome, c = arg_str(args, "app"), cat()
        if not nome:
            raise ToolArgsError("Qual app?")
        if c.apps:
            app_id = acha_nome(nome, [(n, a.id) for a in c.apps for n in (a.nome, a.id, *a.apelidos)])
            if app_id is None:
                raise ToolArgsError("Não conheço esse app.")
            info = next(a for a in c.apps if a.id == app_id)
            slot = Slot(SlotName.APP.value, info.id, raw=nome, display=info.nome)
        else:
            slot = Slot(SlotName.APP.value, nome, raw=nome, display=nome)
        return Mapped(IntentId.TV_APP.value, (slot, *_slot_tv(args, c)))

    return m


def map_entrada(cat: Catalogo) -> Mapper:
    def m(args: Mapping[str, Any]) -> Mapped:
        nome, c = arg_str(args, "entrada"), cat()
        valor = entrada_canonica(nome, c) if nome else None
        if valor is None:
            raise ToolArgsError("Qual entrada?")
        return Mapped(IntentId.TV_INPUT.value, (Slot(SlotName.INPUT.value, valor, raw=nome, display=nome),
                                                 *_slot_tv(args, c)))

    return m


class _TvTool(ActionTool):
    """``ActionTool`` com a descrição remontada do catálogo a cada leitura de ``spec``."""

    def __init__(self, name: str, base: str, props: Mapping[str, Any], required: tuple[str, ...],
                 mapper: Mapper, registry: ActionRegistry, cat: Catalogo, *, danger: bool = False) -> None:
        self._parts = (name, base, props, required)
        self._cat = cat
        super().__init__(_spec(*self._parts, cat()), mapper, registry, danger=danger)

    @property  # type: ignore[override]
    def spec(self) -> ToolSpec:
        return _spec(*self._parts, self._cat())

    @spec.setter
    def spec(self, _value: ToolSpec) -> None:
        pass


class TvEstadoTool:
    """``tv_estado``: leitura do estado das TVs (não é ``ActionTool``; ``serial=False``, DS14)."""

    serial = False
    danger = False

    def __init__(self, tv: TvActions | None, cat: Catalogo) -> None:
        self.tv, self._cat = tv, cat

    @property
    def spec(self) -> ToolSpec:
        base = "Diz se as TVs estão ligadas, o app, o volume e a entrada."
        return _spec("tv_estado", base, {}, (), self._cat())

    @property
    def name(self) -> str:
        return "tv_estado"

    async def run(self, args: Mapping[str, Any], ctx: TurnContext, text: str = "") -> ActionResult:
        if self.tv is None:
            return ActionResult(ok=False, speech=SAY_CASA_OFF, expression=Expression.CONFUSED)
        no_ar, estados = await self.tv.estado()
        if not no_ar:
            return ActionResult(ok=False, speech=SAY_CASA_OFF, expression=Expression.CONFUSED)
        alvo = _slot_tv(args, self._cat()) if arg_str(args, "tv") and self._cat().tvs else ()
        if alvo:
            estados = tuple(e for e in estados if e.id == alvo[0].value)
        linhas = []
        for e in estados:
            if not e.online or e.ligada is False:
                linhas.append(f"{e.nome}: desligada")
                continue
            partes = ["ligada" if e.ligada else "estado desconhecido"]
            partes += [f"app {e.app}"] if e.app else []
            partes += [f"volume {e.volume}"] if e.volume is not None else []
            partes += ["no mudo"] if e.mudo else []
            partes += [f"entrada {e.entrada}"] if e.entrada else []
            linhas.append(f"{e.nome}: " + ", ".join(partes))
        texto = "; ".join(linhas) or "Nenhuma TV configurada na casa."
        return ActionResult(ok=True, speech="", full_text=texto)


def tv_tools(registry: ActionRegistry, tv: TvActions | None = None) -> list[Any]:
    """``tv_ligar``, ``tv_desligar`` (perigosa), ``tv_volume``, ``tv_mudo``, ``tv_app``,
    ``tv_entrada`` (``ActionTool``) e ``tv_estado`` (leitura)."""

    def cat() -> CasaCatalogo:
        return tv.catalogo if tv is not None else CasaCatalogo()

    s = {"type": "string"}
    return [
        _TvTool("tv_ligar", "Liga uma TV da casa.", {}, (), map_ligar(cat), registry, cat),
        _TvTool("tv_desligar", "Desliga uma TV da casa (pede confirmação).", {}, (),
                map_desligar(cat), registry, cat, danger=True),
        _TvTool("tv_volume", 'Volume da TV: "+3"/"-5" = teclas, "20" = absoluto (0-100).',
                {"valor": {**s, "description": '"+3", "-5" ou "20"'}}, ("valor",),
                map_volume(cat), registry, cat),
        _TvTool("tv_mudo", "Liga (true) ou tira (false) o mudo da TV.", {"ligado": {"type": "boolean"}},
                ("ligado",), map_mudo(cat), registry, cat),
        _TvTool("tv_app", "Abre um app na TV (YouTube, Netflix...).", {"app": s}, ("app",),
                map_app(cat), registry, cat),
        _TvTool("tv_entrada", 'Troca a entrada da TV ("hdmi2" ou um apelido como "console").',
                {"entrada": s}, ("entrada",), map_entrada(cat), registry, cat),
        TvEstadoTool(tv, cat),
    ]
