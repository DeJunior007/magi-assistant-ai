"""Y3.5: ``ayanami-voz`` (spec §5.4) com motor falso; Kokoro real só com ``AYANAMI_KOKORO_REAL=1``."""

from __future__ import annotations

import asyncio
import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from ayanami.config import Voz
from ayanami.deps import Deps
from ayanami.relogio import RelogioFalso
from ayanami.voz import servidor
from ayanami.voz.motor import Gerenciador, para_pcm16
from ayanami.workers import voz as wvoz

PCM = b"\x01\x00\x02\x00"


class MotorFalso:
    taxa = 24000

    def __init__(self) -> None:
        self.pedidos: list[tuple[str, str, float]] = []

    async def falar(self, texto, voz, velocidade):
        self.pedidos.append((texto, voz, velocidade))
        for _ in range(3):
            yield PCM


def _ger(rel=None, **kw):
    motor = MotorFalso()
    cargas: list[int] = []

    def carregar():
        cargas.append(1)
        return motor

    ger = Gerenciador(carregar, relogio=rel or RelogioFalso(), **kw)
    return ger, motor, cargas


def _cliente(ger):
    app = servidor.criar_app(ger, vigiar=False)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://voz")


async def test_falar_carrega_preguicoso_e_faz_streaming():
    ger, motor, cargas = _ger()
    async with _cliente(ger) as c:
        assert (await c.get("/saude")).json() == {"carregado": False}
        assert cargas == []
        r = await c.post("/falar", json={"texto": "Olá, Pedro.", "velocidade": 1.1})
        assert r.status_code == 200
        assert r.headers["X-Taxa"] == "24000"
        assert r.content == PCM * 3
        assert (await c.get("/saude")).json() == {"carregado": True}
        r2 = await c.post("/falar", json={"texto": "De novo.", "voz": "pf_dora"})
        assert r2.status_code == 200
    assert cargas == [1]  # uma carga só
    assert motor.pedidos == [("Olá, Pedro.", "pf_dora", 1.1), ("De novo.", "pf_dora", 1.0)]
    assert ger._em_uso == 0


@pytest.mark.parametrize(("corpo", "status"), [
    ({"texto": "a" * 600}, 200),
    ({"texto": "a" * 601}, 413),
    ({"texto": ""}, 422),
    ({"texto": "   "}, 422),
    ({}, 422),
    ({"texto": "oi", "velocidade": 0.8}, 200),
    ({"texto": "oi", "velocidade": 1.3}, 200),
    ({"texto": "oi", "velocidade": 0.79}, 422),
    ({"texto": "oi", "velocidade": 1.31}, 422),
    ({"texto": "oi", "velocidade": "1"}, 422),
    ({"texto": "oi", "voz": "../x"}, 422),
    ({"texto": "oi", "extra": 1}, 422),
    (["oi"], 422),
])
async def test_faixas(corpo, status):
    ger, _, _ = _ger()
    async with _cliente(ger) as c:
        assert (await c.post("/falar", json=corpo)).status_code == status


async def test_corpo_grande_e_json_invalido():
    ger, _, cargas = _ger()
    async with _cliente(ger) as c:
        r = await c.post("/falar", content=b"{" + b" " * (17 * 1024) + b"}",
                         headers={"content-type": "application/json"})
        assert r.status_code == 413
        assert (await c.post("/falar", content=b"{nao")).status_code == 422
    assert cargas == []  # entrada inválida nunca carrega o modelo


async def test_503_quando_carga_passa_do_prazo():
    liberar = threading.Event()
    motor = MotorFalso()
    cargas: list[int] = []

    def carregar():
        cargas.append(1)
        liberar.wait(5)
        return motor

    ger = Gerenciador(carregar, relogio=RelogioFalso(), prazo_carga_s=0.02)
    async with _cliente(ger) as c:
        r = await c.post("/falar", json={"texto": "oi"})
        assert r.status_code == 503 and r.headers["Retry-After"] == "5"
        assert (await c.get("/saude")).json() == {"carregado": False}
        liberar.set()
        ger.prazo_carga_s = 5
        r = await c.post("/falar", json={"texto": "oi"})
        assert r.status_code == 200 and r.content == PCM * 3
    assert cargas == [1]  # a carga em andamento foi reaproveitada


async def test_falha_na_carga_da_503_e_tenta_de_novo():
    tentativas: list[int] = []

    def carregar():
        tentativas.append(1)
        if len(tentativas) == 1:
            raise OSError("sem modelo")
        return MotorFalso()

    ger = Gerenciador(carregar, relogio=RelogioFalso())
    async with _cliente(ger) as c:
        assert (await c.post("/falar", json={"texto": "oi"})).status_code == 503
        assert (await c.post("/falar", json={"texto": "oi"})).status_code == 200
    assert len(tentativas) == 2


async def test_descarrega_apos_600_s_ocioso():
    rel = RelogioFalso()
    ger, _, cargas = _ger(rel, descarregar_apos_s=Voz().descarregar_apos_s)
    assert ger.descarregar_apos_s == 600
    async with _cliente(ger) as c:
        assert (await c.post("/falar", json={"texto": "oi"})).status_code == 200
    rel.avancar(599)
    assert not ger.verificar() and ger.carregado
    rel.avancar(1)
    assert ger.verificar() and not ger.carregado
    async with _cliente(ger) as c:
        assert (await c.post("/falar", json={"texto": "oi"})).status_code == 200
    assert cargas == [1, 1] and ger.carregado


async def test_nao_descarrega_em_uso_e_vigia_usa_relogio():
    rel = RelogioFalso()
    ger, _, _ = _ger(rel, intervalo_s=30)
    await ger.obter()
    rel.avancar(10_000)
    assert not ger.verificar() and ger.carregado  # fala em andamento
    ger.liberar()
    rel.avancar(600)
    tarefa = asyncio.create_task(ger.vigiar())
    for _ in range(5):
        await asyncio.sleep(0)
    tarefa.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tarefa
    assert not ger.carregado
    assert rel.dormidas and rel.dormidas[0] == 30


def test_para_pcm16_corta_e_converte():
    assert para_pcm16([0.0, 1.0, -1.0, 2.0]) == b"\x00\x00\xff\x7f\x01\x80\xff\x7f"


def test_montar_nao_carrega_nem_importa_kokoro(tmp_path):
    app = servidor.montar(Voz(), tmp_path)
    assert app.state.ger.carregado is False
    assert servidor.ler_voz(tmp_path / "nao-existe.toml") == Voz()
    assert servidor.dir_modelos({"AYANAMI_MODELOS": "/m"}) == Path("/m/kokoro")
    assert "kokoro_onnx" not in sys.modules


# --- voz.cache_frases ---------------------------------------------------------------------

def _deps(tmp_path, frases_yaml: str, sintetizados: list, gravados: list, falhar=()):
    arq = tmp_path / "frases.yaml"
    arq.write_text(frases_yaml, encoding="utf-8")

    async def sintetizar(texto, voz):
        sintetizados.append((texto, voz))
        if texto in falhar:
            raise RuntimeError("503")
        return PCM, 24000

    async def ffmpeg(pcm, taxa, destino):
        gravados.append((pcm, taxa, destino.name))
        destino.write_bytes(b"OggS" + pcm)

    cfg = SimpleNamespace(voz=Voz())
    return Deps(db=None, cfg=cfg, relogio=RelogioFalso(), dados=tmp_path / "dados",
                extras={"voz_frases": arq, "voz_sintetizar": sintetizar, "voz_ffmpeg": ffmpeg})


async def test_cache_nao_regenera_sha1_existente(tmp_path):
    sint: list = []
    grav: list = []
    deps = _deps(tmp_path, "casa_offline: A casa está fora do ar.\npc_caiu: O PC caiu.\n", sint, grav)
    pasta = tmp_path / "dados" / "modelos" / "cache-voz"
    pasta.mkdir(parents=True)
    (pasta / f"{wvoz.chave('O PC caiu.')}.ogg").write_bytes(b"velho")

    r = await wvoz.cache_frases(deps, SimpleNamespace(), timestamp=0)
    k = wvoz.chave("A casa está fora do ar.")
    assert sint == [("A casa está fora do ar.", "pf_dora")]
    assert grav == [(PCM, 24000, f".{k}.ogg.tmp")]
    assert r["dados"] == {"geradas": [k], "existentes": [wvoz.chave("O PC caiu.")]}
    assert (pasta / f"{k}.ogg").read_bytes() == b"OggS" + PCM
    assert (pasta / f"{wvoz.chave('O PC caiu.')}.ogg").read_bytes() == b"velho"
    assert sorted(p.name for p in pasta.iterdir()) == sorted([f"{k}.ogg", f"{wvoz.chave('O PC caiu.')}.ogg"])

    sint.clear()
    r = await wvoz.cache_frases(deps, SimpleNamespace(), timestamp=0)
    assert sint == [] and r["dados"]["geradas"] == []


async def test_cache_falha_parcial_e_lista(tmp_path):
    sint: list = []
    grav: list = []
    deps = _deps(tmp_path, "- Um.\n- Dois.\n- Um.\n", sint, grav, falhar=("Um.",))
    with pytest.raises(RuntimeError, match="1 frase"):
        await wvoz.cache_frases(deps, SimpleNamespace(), timestamp=0)
    pasta = tmp_path / "dados" / "modelos" / "cache-voz"
    assert [p.name for p in pasta.iterdir()] == [f"{wvoz.chave('Dois.')}.ogg"]  # sem .tmp
    assert [t for t, _ in sint] == ["Um.", "Dois."]  # duplicata ignorada


async def test_cache_sem_arquivo_de_frases(tmp_path):
    deps = _deps(tmp_path, "", [], [])
    deps.extras["voz_frases"] = tmp_path / "nao-existe.yaml"
    r = await wvoz.cache_frases(deps, SimpleNamespace(), timestamp=0)
    assert r["dados"] == {"geradas": [], "existentes": []}


def test_frases_invalidas(tmp_path):
    arq = tmp_path / "f.yaml"
    arq.write_text("a: 3\n", encoding="utf-8")
    with pytest.raises(ValueError):
        wvoz.ler_frases(arq)


def test_nenhum_teste_importou_kokoro():
    assert "kokoro_onnx" not in sys.modules


KOKORO = Path.home() / ".cache" / "magi" / "kokoro"


@pytest.mark.skipif(os.environ.get("AYANAMI_KOKORO_REAL") != "1",
                    reason="Kokoro real só com AYANAMI_KOKORO_REAL=1 (modelo em ~/.cache/magi/kokoro)")
async def test_kokoro_real_opcional():  # pragma: no cover
    modelo = next((m for m in ("kokoro-v1.0.int8.onnx", "kokoro-v1.0.onnx") if (KOKORO / m).exists()), None)
    if modelo is None:
        pytest.skip("sem modelo Kokoro")
    app = servidor.montar(Voz(modelo=modelo), KOKORO)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://voz") as c:
        r = await c.post("/falar", json={"texto": "Bom dia, Pedro."}, timeout=120)
    assert r.status_code == 200 and r.headers["X-Taxa"] == "24000" and len(r.content) > 24000
