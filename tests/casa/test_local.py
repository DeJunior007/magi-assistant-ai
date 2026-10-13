"""API local da casa (spec §10.2, CA-Y37, CA-Y38) e ``servir``: cliente TCP em ``127.0.0.1:0``,
``DriverFalso`` e executor falso (a C1.1b roda em paralelo; aqui só a interface ``rodar``)."""

from __future__ import annotations

import asyncio
import os
import stat

import pytest

from magi.casa import local
from magi.casa.config import caminho_token_local, dir_pareamento
from magi.casa.driver import Cap, Capacidades, Motivo, ResTv
from magi.casa.estado import EstadoCasa
from magi.casa.falso import DriverFalso
from magi.casa.local import ApiLocal, garantir_token
from magi.casa.servir import servir_async
from magi.common.contracts import ActionRequest
from magi.elo.mensagens import (
    Acao,
    AcaoPedido,
    AppInfo,
    Envelope,
    Estado,
    EstadoTv,
    Ola,
    Tipo,
    TipoDispositivo,
    TvInfo,
    decode,
    encode,
)

TOKEN = "token-de-teste-falso"


class ExecutorFalso:
    def __init__(self, res: ResTv | None = None, erro: Exception | None = None, espera: float = 0):
        self.pedidos: list[ActionRequest] = []
        self.res = res or ResTv(True, estado=EstadoTv("sala", "Sala", "falso", True, ligada=True))
        self.erro = erro
        self.espera = espera

    async def rodar(self, req: ActionRequest) -> ResTv:
        self.pedidos.append(req)
        if self.espera:
            await asyncio.Event().wait()  # preso até a casa cancelar
        if self.erro:
            raise self.erro
        return self.res


def _ola(token=TOKEN):
    return Envelope(
        t=Tipo.OLA, corpo=Ola(tipo=TipoDispositivo.PC, versao="t", token=token), de="pc", para="casa"
    )


def _acao(intent="tv.power_on", prazo_ms=8000):
    pedido = AcaoPedido(intent=intent, slots=(("tv", "sala"),))
    return Envelope(
        t=Tipo.ACAO, corpo=Acao(pedido=pedido, origem="voz-pc", prazo_ms=prazo_ms), de="pc", para="casa"
    )


class Cliente:
    def __init__(self, r: asyncio.StreamReader, w: asyncio.StreamWriter):
        self.r, self.w = r, w

    async def manda(self, env: Envelope | bytes) -> None:
        self.w.write(env if isinstance(env, bytes) else encode(env).encode() + b"\n")
        await self.w.drain()

    async def recebe(self) -> Envelope | None:
        linha = await asyncio.wait_for(self.r.readline(), 2)
        return decode(linha) if linha else None

    async def recebe_tipo(self, t: Tipo) -> Envelope:
        """Pula os ``estado`` empurrados sem pedido até achar ``t``."""
        while (r := await self.recebe()) is not None:
            if r.t == t:
                return r
        raise AssertionError(f"fechou antes de {t}")

    def fecha(self):
        self.w.close()


@pytest.fixture
async def api():
    drv = DriverFalso(Capacidades(caps=frozenset({Cap.STATE, Cap.POWER_ON})), tv_id="sala", tv_nome="Sala")
    estado = EstadoCasa({"sala": drv}, {"sala": ("Sala", "falso")}, gravar_arquivo=False)
    tvs = (TvInfo(id="sala", nome="Sala", driver="falso", caps=("power_on", "state"), padrao=True),)
    apps = (AppInfo(id="netflix", nome="Netflix"),)
    ex = ExecutorFalso()
    a = ApiLocal(TOKEN, ex, estado, lambda: (tvs, apps), versao="t")
    host, porta = await a.iniciar("127.0.0.1", 0)
    a.porta, a.drv, a.ex = porta, drv, ex
    yield a
    await a.fechar()


async def _conecta(a, autenticar=True) -> Cliente:
    c = Cliente(*await asyncio.open_connection("127.0.0.1", a.porta))
    if autenticar:
        await c.manda(_ola())
        r = await c.recebe()
        assert r.t == Tipo.OLA
    return c


# --- CA-Y37 ------------------------------------------------------------------------------------
async def test_token_errado_erro_e_fecha(api):
    c = await _conecta(api, autenticar=False)
    env = _ola("errado")
    await c.manda(env)
    r = await c.recebe()
    assert r.t == Tipo.ERRO and r.corpo.codigo == "nao_autorizado" and r.resp == env.id
    assert await c.recebe() is None  # fechada


async def test_primeira_linha_sem_ola_e_recusada(api):
    c = await _conecta(api, autenticar=False)
    await c.manda(_acao())
    r = await c.recebe()
    assert r.corpo.codigo == "nao_autorizado" and await c.recebe() is None
    assert api.ex.pedidos == []


async def test_ola_certo_lista_tvs_caps_e_apps(api):
    c = await _conecta(api, autenticar=False)
    env = _ola()
    await c.manda(env)
    r = await c.recebe()
    assert r.t == Tipo.OLA and r.resp == env.id and r.de == "casa"
    assert r.corpo.tipo == TipoDispositivo.CASA and r.corpo.token is None
    assert [t.id for t in r.corpo.tvs] == ["sala"] and r.corpo.tvs[0].caps == ("power_on", "state")
    assert [a.id for a in r.corpo.apps] == ["netflix"]
    c.fecha()


async def test_acao_vira_acao_ok_com_resp(api):
    c = await _conecta(api)
    env = _acao()
    await c.manda(env)
    r = await c.recebe_tipo(Tipo.ACAO_OK)
    assert r.resp == env.id
    res = r.corpo.resultado
    assert res.ok and res.fala == "" and res.dados["tv"] == "sala" and res.dados["emulado"] is False
    assert res.dados["estado"]["ligada"] is True
    req = api.ex.pedidos[0]
    assert req.intent.id == "tv.power_on" and dict((s.name, s.value) for s in req.intent.slots) == {
        "tv": "sala"
    }
    # mesmo envelope reenviado: mesma resposta, sem rodar 2×
    await c.manda(env)
    r2 = await c.recebe_tipo(Tipo.ACAO_OK)
    assert r2.resp == env.id and len(api.ex.pedidos) == 1
    c.fecha()


async def test_acao_falha_e_prazo(api, monkeypatch):
    monkeypatch.setattr(local, "prazo_s", lambda acao: 0.01)
    c = await _conecta(api)
    api.ex.res = ResTv(False, Motivo.PRECISA_CONFIRMAR, "x" * 500)
    await c.manda(_acao("tv.power_off"))
    res = (await c.recebe()).corpo.resultado
    assert not res.ok and res.motivo == "precisa_confirmar" and res.precisa_confirmar
    assert res.dados["tv"] == "sala" and len(res.dados["detalhe"]) == 200
    api.ex.erro = RuntimeError("segredo-nao-vaza")
    await c.manda(_acao())
    res = (await c.recebe()).corpo.resultado
    assert res.motivo == "erro_driver" and "segredo" not in res.dados["detalhe"]
    api.ex.erro, api.ex.espera = None, 1
    await c.manda(_acao(prazo_ms=500))  # executor preso: a casa responde tempo_esgotado no prazo
    res = (await c.recebe()).corpo.resultado
    assert res.motivo == "tempo_esgotado"
    c.fecha()


# --- CA-Y38 ------------------------------------------------------------------------------------
async def test_estado_pedido_e_empurrado(api):
    c = await _conecta(api)
    env = Envelope(t=Tipo.ESTADO, corpo=Estado(), de="pc", para="casa")
    await c.manda(env)
    r = await c.recebe()
    assert r.t == Tipo.ESTADO and r.resp == env.id
    assert r.corpo.tvs == (EstadoTv("sala", "Sala", "falso", online=False),)
    # mudança no driver falso → estado empurrado sem pedido
    api.drv.script["state"] = EstadoTv("sala", "Sala", "falso", online=True, app="netflix")
    await api.estado.sondar("sala")
    r = await c.recebe()
    assert r.t == Tipo.ESTADO and r.resp is None and r.corpo.tvs[0].app == "netflix"
    # resultado de acao com estado também atualiza e empurra
    await c.manda(_acao())
    tipos = {(await c.recebe()).t, (await c.recebe()).t}
    assert tipos == {Tipo.ESTADO, Tipo.ACAO_OK}
    c.fecha()


# --- robustez ----------------------------------------------------------------------------------
async def test_linha_invalida_responde_e_segue(api):
    c = await _conecta(api)
    await c.manda(b'{"v":1,"t":"acao"}\n')
    r = await c.recebe()
    assert r.t == Tipo.ERRO and r.corpo.codigo == "invalido"
    await c.manda(Envelope(t=Tipo.ESTADO, corpo=Estado(), de="pc", para="casa"))
    assert (await c.recebe()).t == Tipo.ESTADO
    c.fecha()


async def test_linha_acima_de_64k_fecha(api):
    c = await _conecta(api)
    await c.manda(b"x" * (local.MAX_LINHA + 10) + b"\n")
    assert await c.recebe() is None


async def test_ociosa_fecha():
    estado = EstadoCasa({}, {}, gravar_arquivo=False)
    a = ApiLocal(TOKEN, ExecutorFalso(), estado, lambda: ((), ()), ocioso_s=0.02)
    _, a.porta = await a.iniciar("127.0.0.1", 0)
    c = await _conecta(a)
    assert await c.recebe() is None
    await a.fechar()


async def test_nunca_escuta_em_todas_as_interfaces():
    a = ApiLocal(TOKEN, ExecutorFalso(), EstadoCasa({}, {}, gravar_arquivo=False), lambda: ((), ()))
    for host in ("0.0.0.0", "::", ""):
        with pytest.raises(ValueError):
            await a.iniciar(host, 0)


# --- token ---------------------------------------------------------------------------------------
def test_token_criado_0600_e_reaproveitado():
    t = garantir_token()
    p = caminho_token_local()
    assert stat.S_IMODE(p.stat().st_mode) == 0o600 and len(t) >= 40
    assert garantir_token() == t


# --- servir --------------------------------------------------------------------------------------
async def test_servir_sem_casa_toml_ola_vazio():
    parar = asyncio.Event()
    pronto: asyncio.Future = asyncio.get_running_loop().create_future()
    t = asyncio.create_task(servir_async(porta=0, parar=parar, pronto=lambda h, p: pronto.set_result(p)))
    porta = await asyncio.wait_for(pronto, 2)
    c = Cliente(*await asyncio.open_connection("127.0.0.1", porta))
    await c.manda(_ola(caminho_token_local().read_text().strip()))
    r = await c.recebe()
    assert r.t == Tipo.OLA and r.corpo.tvs == () and len(r.corpo.apps) > 0
    c.fecha()
    parar.set()
    assert await asyncio.wait_for(t, 2) == 0


async def test_servir_recusa_pareamento_aberto(log_casa):
    d = dir_pareamento()
    d.mkdir(parents=True)
    f = d / "sala.atv.key"
    f.write_text("chave-falsa")
    os.chmod(f, 0o644)
    assert await servir_async(porta=0, parar=asyncio.Event()) == 1
    linhas = [x for x in log_casa.linhas() if x["evento"] == "permissao_aberta"]
    assert linhas and "chave-falsa" not in log_casa.texto
