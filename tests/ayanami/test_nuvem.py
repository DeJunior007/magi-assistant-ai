"""Modo nuvem (Y6.3): CA-Y21 (parte modo nuvem), CA-Y20 (frase em cache com casa offline) e a
troca para Kokoro na 2ª falha em 5 min. Sem rede, sem LLM, sem banco: hub, budget, turnos,
tarefas e agente falsos."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from ayanami.hub import EstadoCasa, NoOffline
from ayanami.nuvem import LINHA_NUVEM, NUVEM_PODE, TIPO_CONFIRMA, NuvemDeps, atender, carregar_frases
from ayanami.nuvem_tools import PortaTarefas
from ayanami.voz_nuvem import Disjuntor, EscutaNuvem, FalaNuvem, VozIndisponivel
from magi.common.contracts import ActionResult, BudgetExceeded, ProviderTask
from magi.elo.mensagens import Acao, AcaoOk, AcaoResultado, Envelope, Tipo, TvInfo

FRASES = carregar_frases()
SALA = TvInfo(id="sala", nome="TV da sala", driver="samsung", apelidos=("sala",), padrao=True)


class Relogio:
    def __init__(self) -> None:
        self.t = 1000.0

    def monotonico(self) -> float:
        return self.t

    def agora(self) -> datetime:
        return datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


class HubFalso:
    def __init__(self, casa: bool = True, pc: bool = False) -> None:
        self.on = {"casa": casa, "pc": pc}
        self.enviados: list[Envelope] = []

    def online(self, tipo: str) -> bool:
        return self.on.get(tipo, False)

    def estado_casa(self) -> EstadoCasa:
        return EstadoCasa(online=self.on["casa"], visto=None, tvs=(SALA,), estados=(), apps=())

    async def enviar_e_esperar(self, env: Envelope, prazo: float) -> Envelope:
        if not self.on["casa"]:
            raise NoOffline("casa")
        self.enviados.append(env)
        return Envelope(t=Tipo.ACAO_OK, corpo=AcaoOk(AcaoResultado(ok=True, dados={"tv": "sala"})),
                        de="casa", para="ayanami", resp=env.id)


class BudgetFalso:
    def __init__(self, bloqueado: bool = False) -> None:
        self.bloqueado = bloqueado
        self.pedidos: list[ProviderTask] = []

    async def ensure_allowed(self, task: ProviderTask) -> None:
        self.pedidos.append(task)
        if self.bloqueado:
            raise BudgetExceeded("teto")

    async def gasto(self) -> Any:
        return self


@dataclass
class TurnosFalsos:
    linhas: list[tuple[str, str, str, tuple[str, ...]]] = field(default_factory=list)

    async def ultimos(self, dispositivo: str, n: int) -> list[tuple[str, str]]:
        return [(u, r) for d, u, r, _ in self.linhas if d == dispositivo][-n:]

    async def gravar(self, dispositivo: str, usuario: str, resposta: str, ferramentas: Any) -> None:
        self.linhas.append((dispositivo, usuario, resposta, tuple(ferramentas)))

    async def id_de(self, dispositivo: str) -> int | None:
        return 7


class ConfirmacoesFalsas:
    def __init__(self) -> None:
        self.executores: dict[str, Any] = {}
        self.criadas: list[dict[str, Any]] = []

    def ao_confirmar(self, tipo: str, fn: Any) -> None:
        self.executores[tipo] = fn

    async def criar(self, **kw: Any) -> Any:
        self.criadas.append(kw)
        return kw


class AgenteFalso:
    def __init__(self, tools: Any, persona: str, historico: Any, chama: str | None = None) -> None:
        self.tools, self.persona, self.historico, self.chama = list(tools), persona, list(historico), chama

    async def answer(self, text: str, ctx: Any) -> ActionResult:
        if self.chama:
            tool = next(t for t in self.tools if t.name == self.chama)
            return await tool.run({}, ctx, text)
        return ActionResult(ok=True, speech="Oi da nuvem.")


def _deps(*, casa: bool = True, bloqueado: bool = False, chama: str | None = None,
          noticias: list[dict[str, Any]] | None = None) -> tuple[NuvemDeps, dict[str, Any]]:
    criados: list[Any] = []
    agentes: list[AgenteFalso] = []

    async def criar(t: Any, origem: Any) -> Any:
        criados.append((t, origem))
        return type("T", (), {"titulo": t.titulo})(), True

    async def listar(estado: Any, n: int) -> list[Any]:
        return []

    async def cancelar(tid: str) -> str:
        return "cancelada"

    async def consultar(topic: str, days: int) -> list[dict[str, Any]]:
        return list(noticias or [])

    def fabrica(tools: Any, persona: str, historico: Any) -> AgenteFalso:
        a = AgenteFalso(tools, persona, historico, chama)
        agentes.append(a)
        return a

    hub = HubFalso(casa=casa)
    deps = NuvemDeps(hub=hub, budget=BudgetFalso(bloqueado), turnos=TurnosFalsos(),
                     tarefas=PortaTarefas(criar, listar, cancelar), noticias=consultar,
                     confirmacoes=ConfirmacoesFalsas(), fabrica_agente=fabrica,
                     persona=lambda: "PERSONA", relogio=Relogio(), contexto_turnos=3)
    return deps, {"hub": hub, "agentes": agentes, "criados": criados}


# --------------------------------------------------------------------------- CA-Y21


async def test_bloqueado_liga_tv_sem_llm() -> None:
    deps, x = _deps(bloqueado=True)
    fim = await atender("liga a TV da sala", "celular", deps, turno="T1")
    assert fim.ok and fim.turno == "T1"
    assert not x["agentes"]  # sem LLM
    [env] = x["hub"].enviados
    assert env.t is Tipo.ACAO and env.de == "ayanami" and env.para == "casa"
    assert isinstance(env.corpo, Acao) and env.corpo.origem == "nuvem"
    assert env.corpo.pedido.intent == "tv.power_on"
    assert deps.turnos.linhas[-1][3] == ("tv.power_on",)  # type: ignore[attr-defined]


async def test_bloqueado_pesquisa_da_sem_verba() -> None:
    deps, x = _deps(bloqueado=True)
    fim = await atender("pesquisa o preço do Switch 2", "celular", deps)
    assert fim.fala == FRASES["sem_verba"]
    assert not x["agentes"] and not x["hub"].enviados
    assert deps.budget.pedidos == [ProviderTask.AGENT]


async def test_agente_so_recebe_nuvem_pode_e_linha_da_nuvem() -> None:
    deps, x = _deps()
    deps.turnos.linhas.append(("celular", "oi", "olá", ()))  # type: ignore[attr-defined]
    fim = await atender("me conta uma piada", "celular", deps)
    assert fim.fala == "Oi da nuvem."
    [a] = x["agentes"]
    nomes = [t.name for t in a.tools]
    assert set(nomes) <= set(NUVEM_PODE) and "tv_estado" not in nomes
    assert set(nomes) == set(NUVEM_PODE)
    assert a.persona.startswith("PERSONA") and LINHA_NUVEM in a.persona
    assert [m.content for m in a.historico] == ["oi", "olá"]
    assert deps.turnos.linhas[-1][:3] == ("celular", "me conta uma piada", "Oi da nuvem.")  # type: ignore[attr-defined]


async def test_pedido_de_pc_responde_so_no_pc() -> None:
    deps, x = _deps()
    fim = await atender("abre o hud", "celular", deps)
    assert fim.fala == FRASES["pc_offline_pedido"] and not x["agentes"]


async def test_tv_com_casa_offline_frase_fixa() -> None:
    deps, x = _deps(casa=False, chama="tv_ligar")
    fim = await atender("deixa a televisão acesa por favor", "celular", deps)
    assert fim.fala == FRASES["casa_offline"] and not fim.ok
    assert deps.turnos.linhas[-1][3] == ("tv_ligar",)  # type: ignore[attr-defined]


async def test_tv_desligar_vira_confirma() -> None:
    deps, x = _deps(bloqueado=True)
    fim = await atender("desliga a TV da sala", "celular", deps)
    assert fim.ok and "Confirma" in fim.fala and not x["hub"].enviados
    [c] = deps.confirmacoes.criadas
    assert c["pedido"]["tipo"] == TIPO_CONFIRMA and c["origem"] == 7 and c["perguntar"] is False
    res = await deps.confirmacoes.executores[TIPO_CONFIRMA](type("C", (), {"pedido": c["pedido"]})())
    assert res.ok
    [env] = x["hub"].enviados
    assert env.corpo.pedido.intent == "tv.power_off" and env.corpo.pedido.confirmed


async def test_ferramenta_de_tarefa_usa_origem_do_dispositivo() -> None:
    deps, x = _deps(chama="tarefa_criar")
    fim = await atender("anota aí", "celular", deps)
    assert fim.ok
    [(t, origem)] = x["criados"]
    assert t.tipo == "pesquisa" and origem == 7


async def test_erro_vira_erro_generico() -> None:
    deps, _ = _deps()

    def explode(*_a: Any) -> Any:
        raise RuntimeError("x")

    deps.fabrica_agente = explode
    fim = await atender("me conta uma piada", "celular", deps)
    assert fim.erro == "interno" and fim.fala == FRASES["erro_generico"] and not fim.ok


# --------------------------------------------------------------------------- voz


class FalaFalsa:
    formato = "opus"

    def __init__(self, falhas: int = 0) -> None:
        self.falhas, self.chamadas = falhas, 0

    async def sintetizar(self, texto: str) -> bytes:
        self.chamadas += 1
        if self.falhas:
            self.falhas -= 1
            raise ConnectionError("openai fora")
        return f"op:{texto}".encode()


class KokoroFalso:
    formato = "pcm16"

    def __init__(self) -> None:
        self.chamadas = 0

    async def sintetizar(self, texto: str) -> bytes:
        self.chamadas += 1
        return b"pcm"


async def test_frase_em_cache_com_casa_offline() -> None:
    oa, ko = FalaFalsa(), KokoroFalso()
    voz = FalaNuvem(oa, ko, Relogio())
    assert await voz.aquecer(FRASES[k] for k in ("casa_offline", "sem_verba")) == 2
    deps, _ = _deps(casa=False, bloqueado=True)
    fim = await atender("liga a TV da sala", "celular", deps)
    audio = await voz.sintetizar(fim.fala)
    assert audio.origem == "cache" and oa.chamadas == 2 and ko.chamadas == 0


async def test_kokoro_na_segunda_falha_em_5_min() -> None:
    rel = Relogio()
    oa, ko = FalaFalsa(falhas=2), KokoroFalso()
    voz = FalaNuvem(oa, ko, rel)
    assert (await voz.sintetizar("a")).origem == "kokoro"  # 1ª falha: reserva só nesta fala
    assert not voz.disjuntor.aberto
    rel.t += 120
    assert (await voz.sintetizar("b")).origem == "kokoro"  # 2ª em 5 min: abre
    assert voz.disjuntor.aberto
    rel.t += 60
    assert (await voz.sintetizar("c")).origem == "kokoro" and oa.chamadas == 2
    rel.t += 300  # janela passou: volta à OpenAI
    assert (await voz.sintetizar("d")).origem == "openai"


async def test_falhas_espacadas_nao_trocam() -> None:
    rel = Relogio()
    d = Disjuntor(rel)
    d.falhou()
    rel.t += 301
    d.falhou()
    assert not d.aberto


async def test_teto_usa_kokoro_e_sem_reserva_levanta() -> None:
    oa, ko = FalaFalsa(), KokoroFalso()
    voz = FalaNuvem(oa, ko, Relogio(), budget=BudgetFalso(bloqueado=True))
    assert (await voz.sintetizar("x")).origem == "kokoro" and oa.chamadas == 0
    with pytest.raises(VozIndisponivel):
        await FalaNuvem(FalaFalsa(falhas=1), None, Relogio()).sintetizar("y")


async def test_stt_cai_para_reserva() -> None:
    class Oa:
        async def transcrever(self, audio: bytes, mime: str) -> str:
            raise TimeoutError

    class Local:
        async def transcrever(self, audio: bytes, mime: str) -> str:
            return "liga a tv"

    stt = EscutaNuvem(Oa(), Local(), Relogio())
    assert await stt.transcrever(b"x", "audio/webm") == "liga a tv"
