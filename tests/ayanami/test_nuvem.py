"""Y6.3: modo nuvem (CA-Y21 parte nuvem, CA-Y20 parte frase em cache, troca para o Kokoro).

Agente, hub, confirmações, TTS e STT falsos; relógio falso. Nenhuma chamada paga, nenhuma rede.
O ``pedir_acao`` é o real (Y2.2) sobre um hub falso: o ``acao`` que sairia pela WS da casa fica em
``hub.enviados``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from ayanami import nuvem
from ayanami.hub import EstadoCasa
from ayanami.nuvem import NUVEM_PODE, NuvemDeps, PgTurnos, atender, carregar_frases
from ayanami.nuvem_tools import ServicosNuvem, TvActionsNuvem
from ayanami.relogio import RelogioFalso
from ayanami.tarefas import TarefaOut
from ayanami.voz_nuvem import SttNuvem, VozNuvem
from ayanami.workers.voz import chave, ler_frases
from magi.common.contracts import ActionResult, BudgetExceeded, ProviderTask, TurnContext, Usage
from magi.elo.mensagens import AcaoOk, AcaoResultado, Envelope, EstadoTv, Tipo, TvInfo

AGORA = datetime(2026, 10, 13, 15, 0, tzinfo=UTC)
SALA = TvInfo(id="sala", nome="TV da sala", driver="samsung", apelidos=("sala",), padrao=True)
QUARTO = TvInfo(id="quarto", nome="TV do quarto", driver="roku")
FRASES = carregar_frases()
SEM_BANCO = object()  # NewsQuery falsa: a ferramenta existe, nunca roda


# --------------------------------------------------------------------------- falsos


class HubFalso:
    _ligado_auth = True

    def __init__(self, online: bool = True) -> None:
        self.casa = EstadoCasa(online=online, visto=None, tvs=(SALA, QUARTO),
                               estados=(EstadoTv(id="sala", nome="TV da sala", driver="samsung",
                                                 online=True, ligada=False),), apps=())
        self.enviados: list[Envelope] = []

    def estado_casa(self) -> EstadoCasa:
        return self.casa

    def online(self, tipo: str) -> bool:
        return False

    async def enviar_e_esperar(self, env: Envelope, prazo: float) -> Envelope:
        self.enviados.append(env)
        return Envelope(t=Tipo.ACAO_OK, corpo=AcaoOk(AcaoResultado(ok=True, dados={"tv": "sala"})),
                        de="casa", para="ayanami", resp=env.id)


class ConfFalsa:
    def __init__(self) -> None:
        self.executores: dict[str, Any] = {}
        self.criadas: list[dict[str, Any]] = []

    def ao_confirmar(self, tipo: str, fn: Any) -> None:
        self.executores[tipo] = fn

    async def criar(self, *, descricao: str, pedido: Mapping[str, Any], origem: int | None = None,
                    perguntar: bool = True) -> Any:
        self.criadas.append({"descricao": descricao, "pedido": dict(pedido), "origem": origem})
        return SimpleNamespace(id="01JCONFIRMA")


class BudgetFalso:
    def __init__(self, bloqueado: bool = False) -> None:
        self.bloqueado = bloqueado
        self.usos: list[Usage] = []

    async def ensure_allowed(self, task: ProviderTask) -> None:
        if self.bloqueado and task is ProviderTask.AGENT:
            raise BudgetExceeded("teto")

    async def gasto(self) -> Any:
        return SimpleNamespace(bloqueado=self.bloqueado)

    async def record(self, usage: Usage) -> None:
        self.usos.append(usage)


class TurnosMem:
    def __init__(self, antigos: Sequence[tuple[str, str]] = ()) -> None:
        self.linhas: list[tuple[int | None, str, str, list[str]]] = [(7, u, r, []) for u, r in antigos]

    async def recentes(self, dispositivo: int | None, n: int) -> list[tuple[str, str]]:
        return [(u, r) for d, u, r, _ in self.linhas if d == dispositivo][-n:] if n > 0 else []

    async def gravar(self, dispositivo: int | None, usuario: str, resposta: str,
                     ferramentas: Sequence[str]) -> None:
        self.linhas.append((dispositivo, usuario, resposta, list(ferramentas)))


class AgenteFalso:
    """Chama as ferramentas do roteiro e responde ``resposta`` (ou o pendente de confirmação)."""

    def __init__(self, roteiro: Sequence[tuple[str, dict]] = (), resposta: str = "Feito.") -> None:
        self.roteiro, self.resposta = roteiro, resposta
        self.montagens: list[dict[str, Any]] = []

    def fazer(self, persona: str, tools: Sequence[Any], historico: Sequence[tuple[str, str]]) -> Any:
        self.montagens.append({"persona": persona, "tools": list(tools), "historico": list(historico)})
        por_nome = {t.name: t for t in tools}

        async def answer(text: str, ctx: TurnContext) -> ActionResult:
            for nome, args in self.roteiro:
                r = await por_nome[nome].run(args, ctx, text)
                if r.needs_confirmation:
                    return r
            return ActionResult(ok=True, speech=self.resposta)

        return SimpleNamespace(answer=answer)


def _tarefa(titulo: str, estado: str = "na_fila") -> TarefaOut:
    return TarefaOut(id="00000000-0000-0000-0000-000000000001", tipo="pesquisa", titulo=titulo,  # type: ignore[arg-type]
                     estado=estado, progresso=None, frase=None, origem=7, criada=AGORA,  # type: ignore[arg-type]
                     atualizada=AGORA, resultado=None, erro=None)


@pytest.fixture
def montar() -> Callable[..., SimpleNamespace]:
    def fazer(*, casa_online: bool = True, bloqueado: bool = False, antigos: Sequence[tuple[str, str]] = (),
              roteiro: Sequence[tuple[str, dict]] = (), noticias: Any = SEM_BANCO) -> SimpleNamespace:
        hub, conf = HubFalso(casa_online), ConfFalsa()
        relogio = RelogioFalso(AGORA)
        ctx = SimpleNamespace(extras={"hub": hub, "confirmacoes": conf},
                              auth=SimpleNamespace(ao_revogar=[]), db=None, relogio=relogio)
        criadas: list[Any] = []

        async def criar(t: Any) -> tuple[Any, bool]:
            criadas.append(t)
            return _tarefa(t.titulo), True

        async def listar() -> list[Any]:
            return [_tarefa("preço do PS5")]

        async def cancelar(_tid: str) -> str:
            return "cancelada"

        async def estado() -> dict[str, Any]:
            return {"pc_online": False, "casa_online": casa_online}

        serv = ServicosNuvem(criar, listar, cancelar, estado, noticias=noticias)
        agente = AgenteFalso(roteiro)
        turnos = TurnosMem(antigos)
        deps = NuvemDeps(relogio=relogio, budget=BudgetFalso(bloqueado), turnos=turnos,
                         tv=lambda d: TvActionsNuvem.do_ctx(ctx, d, FRASES), servicos=lambda d: serv,
                         fazer_agente=agente.fazer, persona="Você é a Condessa (teste).", frases=FRASES)
        return SimpleNamespace(deps=deps, hub=hub, conf=conf, agente=agente, turnos=turnos, criadas=criadas)

    return fazer


# --------------------------------------------------------------------------- frases


def test_frases_yaml_tem_as_cinco_e_o_cache_le():
    for k in ("casa_offline", "pc_offline_pedido", "sem_verba", "erro_generico", "pc_caiu"):
        assert FRASES[k].strip()
    assert sorted(ler_frases(nuvem.CAMINHO_FRASES)) == sorted(set(FRASES.values()))


# --------------------------------------------------------------------------- CA-Y21 (parte nuvem)


async def test_bloqueado_liga_tv_gera_acao_sem_llm(montar):
    m = montar(bloqueado=True)
    fim = await atender("liga a TV da sala", "7", m.deps, turno="t1")
    assert m.agente.montagens == []  # nenhum LLM
    assert len(m.hub.enviados) == 1
    env = m.hub.enviados[0]
    assert env.t is Tipo.ACAO and env.corpo.origem == "nuvem"
    assert env.corpo.pedido.intent == "tv.power_on" and ("tv", "sala") in env.corpo.pedido.slots
    assert fim.turno == "t1" and fim.ok and fim.fala
    assert m.turnos.linhas[-1][:2] == (7, "liga a TV da sala")
    assert m.turnos.linhas[-1][3] == ["intent:tv.power_on"]


async def test_bloqueado_pesquisa_da_sem_verba(montar):
    m = montar(bloqueado=True)
    fim = await atender("pesquisa X", "7", m.deps)
    assert fim.fala == FRASES["sem_verba"] and not fim.ok and fim.erro == "sem_verba"
    assert m.agente.montagens == [] and m.hub.enviados == []


async def test_bloqueado_desliga_tv_vira_confirma_sem_llm(montar):
    m = montar(bloqueado=True)
    fim = await atender("desliga a TV da sala", "7", m.deps)
    assert m.hub.enviados == [] and m.agente.montagens == []
    (c,) = m.conf.criadas
    assert c["pedido"]["tipo"] == "casa.acao" and c["pedido"]["origem"] == "nuvem" and c["origem"] == 7
    assert c["pedido"]["pedido"]["intent"] == "tv.power_off" and not c["pedido"]["pedido"]["confirmed"]
    assert "casa.acao" in m.conf.executores  # o "sim" no PWA roda o pedir_acao confirmado
    assert fim.fala == c["descricao"] == "Desligar a TV da sala? Confirma?"


async def test_agente_so_recebe_ferramentas_de_nuvem_pode(montar):
    m = montar()
    await atender("me conta uma novidade", "7", m.deps)
    (mont,) = m.agente.montagens
    nomes = {t.name for t in mont["tools"]}
    assert nomes <= set(NUVEM_PODE)
    assert nomes == set(NUVEM_PODE)  # com casa e notícias todas existem
    assert "tv_estado" not in nomes
    assert nuvem.LINHA_NUVEM in mont["persona"] and mont["persona"].startswith("Você é a Condessa")


async def test_sem_casa_nem_noticias_as_ferramentas_somem(montar):
    m = montar(noticias=None)
    m.deps.tv = lambda d: None
    await atender("oi", "7", m.deps)
    nomes = {t.name for t in m.agente.montagens[0]["tools"]}
    assert not any(n.startswith("tv_") for n in nomes) and "news_query" not in nomes
    assert nomes <= set(NUVEM_PODE)


async def test_tv_desligar_pelo_agente_vira_confirma(montar):
    m = montar(roteiro=[("tv_desligar", {"tv": "sala"})])
    fim = await atender("apaga aquela tela lá", "7", m.deps)
    assert m.hub.enviados == []
    (c,) = m.conf.criadas
    assert c["pedido"]["pedido"]["intent"] == "tv.power_off"
    assert fim.fala.startswith("Desligar a") and fim.ok
    assert m.turnos.linhas[-1][3] == ["tv_desligar"]


async def test_tv_volume_pelo_agente_manda_acao(montar):
    m = montar(roteiro=[("tv_volume", {"valor": "+3", "tv": "quarto"})])
    fim = await atender("sobe um pouco o som da tela do quarto", "7", m.deps)
    (env,) = m.hub.enviados
    assert env.corpo.pedido.intent == "tv.volume" and ("tv", "quarto") in env.corpo.pedido.slots
    assert fim.ok and fim.fala == "Feito."


async def test_tarefa_criada_pelo_agente(montar):
    m = montar(roteiro=[("tarefa_criar", {"pedido": "preço do PS5 no Brasil"}),
                        ("lembrete_criar", {"texto": "regar", "quando": "2026-10-14T09:00:00-03:00"})])
    await atender("pesquisa o preço do PS5 e me lembra de regar amanhã", "7", m.deps)
    assert [t.tipo for t in m.criadas] == ["pesquisa", "lembrete"]
    assert m.criadas[0].params == {"pedido": "preço do PS5 no Brasil"}


@pytest.mark.parametrize("texto", ["abre o HUD", "abre o Hades", "aumenta o volume"])
async def test_pedido_do_pc_responde_so_no_pc(montar, texto):
    m = montar()
    fim = await atender(texto, "7", m.deps)
    assert fim.fala == FRASES["pc_offline_pedido"]
    assert m.agente.montagens == [] and m.hub.enviados == []


async def test_contexto_dos_ultimos_turnos_e_gravacao(montar):
    antigos = [(f"pergunta {i}", f"resposta {i}") for i in range(25)]
    m = montar(antigos=antigos)
    m.deps.contexto_turnos = 20
    fim = await atender("e agora?", "7", m.deps)
    hist = m.agente.montagens[0]["historico"]
    assert hist == antigos[-20:]
    assert m.turnos.linhas[-1] == (7, "e agora?", fim.texto, [])


async def test_erro_do_agente_vira_erro_generico(montar):
    m = montar()

    def quebra(*_a: Any) -> Any:
        raise RuntimeError("boom")

    m.deps.fazer_agente = quebra
    fim = await atender("oi", "7", m.deps)
    assert fim.fala == FRASES["erro_generico"] and fim.erro == "erro" and not fim.ok
    assert m.turnos.linhas[-1][2] == FRASES["erro_generico"]


# --------------------------------------------------------------------------- CA-Y20 (frase em cache)


class TtsFalso:
    def __init__(self, nome: str, falha: bool = False) -> None:
        self.nome, self.falha, self.textos = nome, falha, []

    async def sintetizar(self, texto: str) -> bytes:
        self.textos.append(texto)
        if self.falha:
            raise ConnectionError("fora")
        return f"{self.nome}:{texto}".encode()


def _voz(tmp_path, relogio, *, openai_falha=False, budget=None) -> tuple[VozNuvem, TtsFalso, TtsFalso]:
    o, k = TtsFalso("openai", openai_falha), TtsFalso("kokoro")
    v = VozNuvem(o, k, relogio, cache_frases=tmp_path / "cache-voz", cache=tmp_path / "cache-tts",
                 budget=budget)
    return v, o, k


async def test_casa_offline_frase_em_cache_sem_tts(montar, tmp_path):
    m = montar(casa_online=False)
    fim = await atender("liga a TV da sala", "7", m.deps)
    assert fim.fala == FRASES["casa_offline"] and not fim.ok
    assert m.hub.enviados == []
    relogio = RelogioFalso(AGORA)
    v, o, k = _voz(tmp_path, relogio)
    (tmp_path / "cache-voz").mkdir()
    (tmp_path / "cache-voz" / f"{chave(fim.fala)}.ogg").write_bytes(b"OggS-casa")
    assert await v.falar(fim.fala) == b"OggS-casa"
    assert o.textos == [] and k.textos == [] and v.ultimo_motor == "cache"


async def test_casa_offline_pelo_agente_frase_casa_offline(montar):
    m = montar(casa_online=False, roteiro=[("tv_ligar", {"tv": "sala"})])
    await atender("bom dia, pode cuidar daquilo?", "7", m.deps)
    assert m.hub.enviados == [] and m.turnos.linhas[-1][3] == ["tv_ligar"]
    tool = next(t for t in m.agente.montagens[0]["tools"] if t.name == "tv_ligar")
    r = await tool.run({"tv": "sala"}, TurnContext(satellite="celular", source="ptt", started_at=AGORA))  # type: ignore[arg-type]
    assert r.speech == FRASES["casa_offline"] and not r.ok


# --------------------------------------------------------------------------- TTS: OpenAI → Kokoro


async def test_kokoro_na_segunda_falha_em_5_min(tmp_path):
    relogio = RelogioFalso(AGORA)
    v, o, k = _voz(tmp_path, relogio, openai_falha=True)
    assert await v.falar("um") == b"kokoro:um"  # 1ª falha: cai no Kokoro só desta vez
    assert not v.em_kokoro() and len(o.textos) == 1
    relogio.avancar(120)
    assert await v.falar("dois") == b"kokoro:dois"  # 2ª falha em 5 min → troca
    assert v.em_kokoro() and len(o.textos) == 2
    relogio.avancar(60)
    await v.falar("tres")
    assert len(o.textos) == 2 and v.ultimo_motor == "kokoro"  # nem tenta a OpenAI
    relogio.avancar(241)
    o.falha = False
    assert await v.falar("quatro") == b"openai:quatro"  # passou a janela: volta à OpenAI


async def test_falhas_espacadas_nao_trocam(tmp_path):
    relogio = RelogioFalso(AGORA)
    v, o, _k = _voz(tmp_path, relogio, openai_falha=True)
    await v.falar("um")
    relogio.avancar(301)
    await v.falar("dois")
    assert not v.em_kokoro()


async def test_openai_ok_cacheia_e_registra_custo(tmp_path):
    relogio, b = RelogioFalso(AGORA), BudgetFalso()
    v, o, k = _voz(tmp_path, relogio, budget=b)
    assert await v.falar("olá") == "openai:olá".encode()
    assert await v.falar("olá") == "openai:olá".encode()
    assert o.textos == ["olá"] and k.textos == []
    assert (tmp_path / "cache-tts" / f"{chave('olá')}.ogg").exists()
    assert [(u.task, u.input_units) for u in b.usos] == [(ProviderTask.TTS, 3.0)]


async def test_teto_batido_usa_kokoro(tmp_path):
    relogio = RelogioFalso(AGORA)
    v, o, k = _voz(tmp_path, relogio, budget=BudgetFalso(bloqueado=True))
    assert await v.falar("oi") == b"kokoro:oi"
    assert o.textos == []


async def test_stt_registra_segundos():
    class SttFalso:
        async def transcrever(self, audio: bytes, mime: str) -> tuple[str, float]:
            return "liga a TV", 2.5

    b = BudgetFalso()
    s = SttNuvem(SttFalso(), modelo="gpt-transcribe", budget=b)
    assert await s.transcrever(b"x", "audio/webm") == "liga a TV"
    assert [(u.task, u.model, u.input_units) for u in b.usos] == [(ProviderTask.STT, "gpt-transcribe", 2.5)]


# --------------------------------------------------------------------------- nuvem_turnos no banco


class _Db:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    @contextmanager
    def connection(self) -> Iterator[Any]:
        import psycopg

        with psycopg.connect(self.dsn) as conn:
            yield conn


@pytest.mark.pg
async def test_pg_turnos_grava_e_le_por_dispositivo(pg_nova_base):
    import psycopg

    from ayanami.migrar import migrar

    dsn = pg_nova_base("ayanami_nuvem")
    with psycopg.connect(dsn) as conn:
        migrar(conn)
    relogio = RelogioFalso(AGORA)
    t = PgTurnos(_Db(dsn), relogio)
    for i in range(3):
        await t.gravar(None, f"u{i}", f"r{i}", ["tv_ligar"] if i == 1 else [])
        relogio.avancar(1)
    assert await t.recentes(None, 2) == [("u1", "r1"), ("u2", "r2")]
    assert await t.recentes(None, 0) == []
