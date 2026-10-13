"""Y2.2: ``POST /v1/casa/acao`` e ``GET /v1/casa/estado`` (CA-Y10 parte casa, spec §2.2, §13.2).

A casa é um canal falso registrado direto no hub (sem rede); o relógio é manual (``dormir`` só
volta quando o teste avança o tempo)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest

from ayanami.api import casa as casa_mod
from ayanami.hub import hub_de
from magi.elo.mensagens import (
    AcaoOk,
    AcaoPedido,
    AcaoResultado,
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
    responder,
)

pytestmark = pytest.mark.pg


class RelogioManual:
    def __init__(self) -> None:
        self._agora = datetime(2026, 10, 12, 21, 0, tzinfo=UTC)
        self._mono = 1000.0
        self.esperas: list[tuple[float, asyncio.Future[None]]] = []

    def agora(self) -> datetime:
        return self._agora

    def monotonico(self) -> float:
        return self._mono

    async def dormir(self, s: float) -> None:
        item = (self._mono + max(0.0, s), asyncio.get_running_loop().create_future())
        self.esperas.append(item)
        try:
            await item[1]
        finally:
            self.esperas.remove(item)

    def avancar(self, s: float) -> None:
        self._mono += s
        self._agora += timedelta(seconds=s)
        for fim, fut in list(self.esperas):
            if fim <= self._mono + 1e-9 and not fut.done():
                fut.set_result(None)


async def ate(cond, limite: float = 3.0) -> None:
    for _ in range(int(limite / 0.005)):
        if cond():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condição não chegou")


@pytest.fixture
def relogio() -> RelogioManual:
    return RelogioManual()


TVS = (TvInfo(id="sala", nome="Sala", driver="samsung", padrao=True),
       TvInfo(id="quarto", nome="Quarto", driver="roku"))
APPS = (AppInfo(id="netflix", nome="Netflix"),)
OK = AcaoResultado(ok=True)


class CasaFalsa:
    """Canal do hub: responde ``acao`` com ``resultado`` (ou não responde)."""

    def __init__(self, hub, resultado: AcaoResultado | None) -> None:
        self.hub = hub
        self.resultado = resultado
        self.no = None
        self.acoes: list[Envelope] = []
        self.fechado: int | None = None

    async def enviar(self, texto: str) -> None:
        env = decode(texto)
        if env.t is Tipo.ACAO:
            self.acoes.append(env)
            if self.resultado is not None:
                r = responder(env, Tipo.ACAO_OK, AcaoOk(self.resultado), "casa-sala")
                asyncio.get_running_loop().create_task(self.hub.receber(self.no, encode(r)))

    async def fechar(self, codigo: int) -> None:
        self.fechado = codigo


@pytest.fixture
def montar(fazer_app, db, novo_token, cliente):
    async def fazer(resultado: AcaoResultado | None = OK, *, com_casa: bool = True):
        app = fazer_app(db)
        ctx = app.state.ctx
        hub = hub_de(ctx)
        cel = novo_token("celular-pedro", "celular")
        casa = None
        if com_casa:
            disp = ctx.auth.verificar(novo_token("casa-sala", "casa"))
            casa = CasaFalsa(hub, resultado)
            casa.no = await hub.registrar(disp, casa)
            ola = Envelope(t=Tipo.OLA, corpo=Ola(tipo=TipoDispositivo.CASA, versao="0.1", tvs=TVS, apps=APPS),
                           de="casa-sala", para="ayanami")
            respostas, _ = await hub.receber(casa.no, encode(ola))
            assert decode(respostas[0]).t is Tipo.ACK
        return app, cliente(app, cel), casa, hub

    return fazer


def _corpo(intent: str, tv: str | None = "Sala", **slots: str) -> dict:
    return {"tv": tv, "pedido": {"intent": intent, "slots": [[k, v] for k, v in slots.items()]}}


async def test_casa_offline_503(montar):
    _, c, _, _ = await montar(com_casa=False)
    async with c:
        r = await c.post("/v1/casa/acao", json=_corpo("tv.power_on"))
    assert r.status_code == 503
    assert r.json() == {"erro": "casa_offline", "msg": "A casa está fora do ar."}


async def test_casa_sem_batida_ha_30s_e_offline(montar, relogio):
    _, c, casa, _ = await montar()
    relogio.avancar(31)
    async with c:
        r = await c.post("/v1/casa/acao", json=_corpo("tv.mute"))
    assert r.status_code == 503 and casa.acoes == []


async def test_casa_que_nao_responde_504_em_8s(montar, relogio, db):
    _, c, casa, _ = await montar(resultado=None)
    async with c:
        t = asyncio.ensure_future(c.post("/v1/casa/acao", json=_corpo("tv.mute")))
        await ate(lambda: casa.acoes and relogio.esperas)
        relogio.avancar(7.9)
        await asyncio.sleep(0.02)
        assert not t.done()
        relogio.avancar(0.1)
        r = await t
    assert r.status_code == 504
    assert r.json()["erro"] == "tempo_esgotado"
    assert len(casa.acoes) == 1  # 8 s < 10 s: sem reenvio
    with db.connection() as conn:
        linhas = conn.execute("SELECT tipo, alvo, ok FROM auditoria WHERE tipo = 'casa'").fetchall()
    assert ("casa", "tv.mute", False) in linhas


@pytest.mark.parametrize(("intent", "slots", "prazo"), [
    ("tv.power_on", {}, 10000), ("tv.volume", {"volume": "30"}, 10000),
    ("tv.volume", {"volume": "+3"}, 8000), ("tv.mute", {}, 8000),
])
async def test_prazo_ms(montar, intent, slots, prazo):
    _, c, casa, _ = await montar()
    async with c:
        r = await c.post("/v1/casa/acao", json=_corpo(intent, **slots))
    assert r.status_code == 200
    acao = casa.acoes[0].corpo
    assert acao.prazo_ms == prazo and acao.origem == "pwa"
    assert ("tv", "Sala") in acao.pedido.slots


@pytest.mark.parametrize(("intent", "slots", "res", "fala"), [
    ("tv.power_on", {}, AcaoResultado(ok=True), "Pronto, TV ligada."),
    ("tv.volume", {"volume": "+3"}, AcaoResultado(ok=True), "Ok."),
    ("tv.app", {"app": "netflix"}, AcaoResultado(ok=True), "Abrindo Netflix na TV."),
    ("tv.mute", {}, AcaoResultado(ok=False, motivo="offline", dados={"tv": "sala"}),
     "A Sala está desligada."),
    ("tv.power_on", {}, AcaoResultado(ok=False, motivo="rede_desligada", dados={"tv": "quarto"}),
     "Não consegui ligar a Quarto; ative o Início rápido da TV."),
    ("tv.mute", {}, AcaoResultado(ok=False, motivo="tv_ambigua", dados={"candidatos": ["sala", "quarto"]}),
     "Mais de uma TV: Sala ou Quarto?"),
    ("tv.mute", {}, AcaoResultado(ok=False, motivo="inventado"), "A TV recusou o comando."),
])
async def test_fala_pela_tabela(montar, intent, slots, res, fala):
    _, c, _, _ = await montar(res)
    async with c:
        r = await c.post("/v1/casa/acao", json=_corpo(intent, **slots))
    assert r.status_code == 200
    assert r.json()["fala"] == fala
    assert r.json()["ok"] is res.ok


async def test_frase_ausente_do_yaml_cai_na_generica(montar, tmp_path, monkeypatch):
    yaml = tmp_path / "phrases.yaml"
    yaml.write_text("fixed:\n  - \"TV desligada.\"\nlazy: []\ntemplates: []\n", encoding="utf-8")
    monkeypatch.setattr(casa_mod, "CAMINHO_FRASES", yaml)
    assert casa_mod.frase("ok:tv.power_off", ok=True) == "TV desligada."
    _, c, _, _ = await montar(AcaoResultado(ok=True))
    async with c:
        r = await c.post("/v1/casa/acao", json=_corpo("tv.power_on"))
        r2 = await c.post("/v1/casa/acao", json=_corpo("tv.power_on", tv=None))
    assert r.json()["fala"] == casa_mod.FALA_OK_GENERICA
    assert r2.status_code == 200


async def test_estado_do_ultimo_ola_e_estado(montar):
    _, c, casa, hub = await montar()
    est = Estado(tvs=(EstadoTv(id="sala", nome="Sala", driver="samsung", online=True, ligada=True,
                               volume=12),))
    await hub.receber(casa.no, encode(Envelope(t=Tipo.ESTADO, corpo=est, de="casa-sala", para="ayanami")))
    async with c:
        r = await c.get("/v1/casa/estado")
    d = r.json()
    assert r.status_code == 200 and d["online"] is True and d["visto"].endswith("Z")
    assert [t["nome"] for t in d["tvs"]] == ["Sala", "Quarto"]
    assert d["estados"][0]["volume"] == 12 and d["apps"][0]["id"] == "netflix"


async def test_mcp_perigosa_vira_confirmacao_e_roda_no_sim(montar, novo_token, cliente):
    app, c, casa, _ = await montar(AcaoResultado(ok=True))
    ctx = app.state.ctx
    status, corpo = await casa_mod.pedir_acao(ctx, None, "Sala", AcaoPedido(intent="tv.power_off"), "mcp")
    assert status == 202 and set(corpo) == {"confirma"}
    assert casa.acoes == []
    async with c:
        r = await c.post(f"/v1/confirma/{corpo['confirma']}", json={"resposta": True})
        r2 = await c.post(f"/v1/confirma/{corpo['confirma']}", json={"resposta": True})
    assert r.status_code == 200, r.text
    assert r.json()["resultado"]["fala"] == "TV desligada."
    assert len(casa.acoes) == 1 and casa.acoes[0].corpo.pedido.confirmed is True
    assert r2.status_code == 409


async def test_acao_ok_atrasado_so_vai_a_auditoria(montar, relogio, db):
    _, c, casa, hub = await montar(resultado=None)
    async with c:
        t = asyncio.ensure_future(c.post("/v1/casa/acao", json=_corpo("tv.mute")))
        await ate(lambda: casa.acoes and relogio.esperas)
        relogio.avancar(8)
        assert (await t).status_code == 504
    atrasado = responder(casa.acoes[0], Tipo.ACAO_OK, AcaoOk(AcaoResultado(ok=True)), "casa-sala")
    respostas, fechar = await hub.receber(casa.no, encode(atrasado))
    assert respostas == [] and fechar is None
    with db.connection() as conn:
        resumos = [r[0] for r in conn.execute("SELECT resumo FROM auditoria").fetchall()]
    assert any("atrasado" in r for r in resumos)
    assert all("ayn_" not in json.dumps(r) for r in resumos)
