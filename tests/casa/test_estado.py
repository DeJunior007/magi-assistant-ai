"""Estado da casa (spec §10.4 *Estado*): memória, ``casa-estado.json`` atômico, sondagem por driver,
``online=False`` depois de 2 falhas. ``DriverFalso`` e relógio falso; nada de rede nem ``sleep``."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from magi.casa import estado as est
from magi.casa.config import caminho_estado
from magi.casa.driver import Cap, Capacidades
from magi.casa.estado import EstadoCasa
from magi.casa.falso import DriverFalso, RelogioFalso
from magi.elo.mensagens import EstadoTv

AGORA = datetime(2026, 10, 12, 21, 0, tzinfo=UTC)


def _drv(script=None, tv_id="sala", nome="samsung"):
    caps = Capacidades(caps=frozenset({Cap.STATE, Cap.POWER_ON}))
    return DriverFalso(caps, script or {}, nome=nome, tv_id=tv_id, tv_nome="Sala")


def _casa(drivers, **kw):
    nomes = {i: ("Sala" if i == "sala" else i.title(), d.nome) for i, d in drivers.items()}
    return EstadoCasa(drivers, nomes, agora=lambda: AGORA, **kw)


async def test_comeca_offline_e_sondagem_liga():
    casa = _casa({"sala": _drv({"state": EstadoTv("sala", "x", "y", online=True, ligada=True)})})
    assert casa.todos() == (EstadoTv("sala", "Sala", "samsung", online=False),)
    e = await casa.sondar("sala")
    assert e.online and e.ligada and e.nome == "Sala" and e.driver == "samsung" and e.visto == AGORA


async def test_duas_falhas_marcam_offline_e_mantem_o_resto():
    on = EstadoTv("sala", "Sala", "samsung", online=True, ligada=True, app="netflix")
    off = EstadoTv("sala", "Sala", "samsung", online=False)
    casa = _casa({"sala": _drv({"state": [on, off, RuntimeError("rede"), on]})})
    await casa.sondar("sala")
    assert (await casa.sondar("sala")).online  # 1ª falha: ainda online
    e = await casa.sondar("sala")  # 2ª (exceção): offline
    assert not e.online and e.app == "netflix" and e.ligada
    assert (await casa.sondar("sala")).online  # voltou: zera as falhas


async def test_arquivo_atomico_e_recarga(tmp_path):
    on = EstadoTv("sala", "Sala", "samsung", online=True, volume=12)
    casa = _casa({"sala": _drv({"state": on})})
    await casa.sondar("sala")
    p = caminho_estado()
    dados = json.loads(p.read_text())
    assert dados["tvs"][0]["volume"] == 12 and dados["tvs"][0]["visto"].endswith("Z")
    assert [x.name for x in p.parent.iterdir()] == [p.name]  # sem temporário sobrando
    # reinício: o ola sai com o último estado, e TV que saiu do casa.toml não volta
    novo = _casa({"sala": _drv()})
    assert novo.get("sala").volume == 12 and novo.get("sala").visto == AGORA
    p.write_text(
        json.dumps({"tvs": [est.para_dict(on), est.para_dict(EstadoTv("velha", "V", "roku", True))]})
    )
    assert [e.id for e in _casa({"sala": _drv()}).todos()] == ["sala"]


async def test_arquivo_corrompido_nao_derruba(log_casa):
    p = caminho_estado()
    p.parent.mkdir(parents=True)
    p.write_text("{nao é json")
    assert _casa({"sala": _drv()}).get("sala").online is False
    assert any(x["evento"] == "estado_ilegivel" for x in log_casa.linhas())


async def test_ouvinte_so_em_mudanca_real():
    estados = [
        EstadoTv("sala", "Sala", "samsung", online=True, ligada=True),
        EstadoTv("sala", "Sala", "samsung", online=True, ligada=True),  # igual: só o visto anda
        EstadoTv("sala", "Sala", "samsung", online=True, ligada=False),
    ]
    casa = _casa({"sala": _drv({"state": estados})}, gravar_arquivo=False)
    vistos = []

    async def ouvinte(tvs):
        vistos.append(tvs[0].ligada)

    tira = casa.ouvir(ouvinte)
    for _ in range(3):
        await casa.sondar("sala")
    assert vistos == [True, False]
    tira()
    assert not await casa.atualizar(EstadoTv("fora", "F", "roku", True))


async def test_laco_por_driver_com_relogio_falso():
    rel = RelogioFalso(0.0)
    sam, atv = _drv(tv_id="sala"), _drv(tv_id="quarto", nome="androidtv")
    casa = _casa({"sala": sam, "quarto": atv}, gravar_arquivo=False)
    await casa.rodar(dormir=rel.dormir, relogio=rel, voltas=7)
    assert rel.t == 35.0  # 7 voltas, cada uma dorme 5 s
    assert len(sam.de("state")) == 2  # t=0 e t=30
    assert len(atv.de("state")) == 7  # t=0,5,…,30
    assert set(rel.dormidas) == {5.0}
