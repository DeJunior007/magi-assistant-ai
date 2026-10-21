"""Y1.3c: "como está o servidor?" a partir do ``servidor.json`` do vigia (tmp, sem rede)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from ayanami import servidor
from ayanami.api import servidor as rota
from ayanami.api.auth import ESCOPO_DE_ROTA
from ayanami.mcp_server import ESCOPO_DAS_TOOLS
from ayanami.nuvem import NUVEM_PODE
from ayanami.nuvem_tools import NuvemFerramentasDeps, ferramentas

AGORA = datetime(2026, 10, 21, 21, 0, tzinfo=UTC)
GIB = 1024**3


def _disco(_p: Path) -> Any:
    return SimpleNamespace(total=200 * GIB, free=120 * GIB)


def _resumo_vigia(ts: datetime = AGORA, **extra: Any) -> dict:
    """No formato de ``vigia.checar_servidor`` (Y1.3b)."""
    base = {
        "ts": ts.isoformat(),
        "cpu": {"minecraft": {"nucleos": "0-5", "uso": 42.4}, "ayanami": {"nucleos": "6-7", "uso": 7.9}},
        "load": [1.5, 1.2, 1.0],
        "ram": {"total_gib": 15.6, "disponivel_gib": 3.1},
        "swap": {"total_gib": 8.0, "usado_gib": 0.25},
        "minecraft": {"status": "running", "restart_count": 0, "rcon": "ok", "jogadores": 2,
                      "max_jogadores": 20, "nomes": ["Steve", "Alex"], "spark": True, "tps": 19.8},
        "alertas": [],
    }
    base.update(extra)
    return base


def _gravar(tmp_path: Path, conteudo: Any) -> Path:
    p = tmp_path / "servidor.json"
    p.write_text(conteudo if isinstance(conteudo, str) else json.dumps(conteudo), encoding="utf-8")
    return p


def test_caminho_env_e_recaida_dados() -> None:
    assert servidor.caminho_padrao({"AYANAMI_SERVIDOR_JSON": "/x/s.json"}) == Path("/x/s.json")
    assert servidor.caminho_padrao({"AYANAMI_DADOS": "/opt/ayanami/dados"}) == Path(
        "/opt/ayanami/dados/servidor.json")
    assert servidor.caminho_padrao({}) == Path("/dados/servidor.json")


def test_ok_resumo_completo(tmp_path: Path) -> None:
    d = servidor.ler(_gravar(tmp_path, _resumo_vigia(AGORA - timedelta(seconds=40))),
                     agora=AGORA, medir_disco=_disco)
    assert d["estado"] == "ok" and d["idade_s"] == 40
    assert d["cpu"]["minecraft"]["uso"] == 42.4 and d["disco"] == {"total_gib": 200.0, "livre_gib": 120.0}
    json.dumps(d)  # pronto para JSON
    r = d["resumo"]
    assert r.startswith("Servidor tranquilo.")
    assert "Minecraft 42%" in r and "eu 8%" in r
    assert "RAM 3,1 de 15,6 GiB livres" in r and "swap 0,2 GiB" in r and "disco 120 GiB livres" in r
    assert "Minecraft no ar, 2 jogando (Steve, Alex), TPS 19,8." in r


def test_alertas_e_minecraft_ausente(tmp_path: Path) -> None:
    p = _gravar(tmp_path, _resumo_vigia(minecraft="ausente", alertas=["ram", "swap"]))
    d = servidor.ler(p, agora=AGORA, medir_disco=_disco)
    assert d["minecraft"] == "ausente"
    assert "Minecraft não está instalado aqui." in d["resumo"]
    assert "De olho em: ram, swap." in d["resumo"] and "tranquilo" not in d["resumo"]


def test_minecraft_parado_e_rcon_fora(tmp_path: Path) -> None:
    mc = {"status": "exited", "restart_count": 3}
    d = servidor.ler(_gravar(tmp_path, _resumo_vigia(minecraft=mc)), agora=AGORA, medir_disco=_disco)
    assert "Minecraft parado (exited)." in d["resumo"]
    mc = {"status": "running", "restart_count": 0, "rcon": "erro (recusado)", "jogadores": None, "tps": None}
    d = servidor.ler(_gravar(tmp_path, _resumo_vigia(minecraft=mc)), agora=AGORA, medir_disco=_disco)
    assert "Minecraft no ar, RCON sem resposta." in d["resumo"]


def test_velho_apos_tres_minutos(tmp_path: Path) -> None:
    p = _gravar(tmp_path, _resumo_vigia(AGORA - timedelta(minutes=12)))
    d = servidor.ler(p, agora=AGORA, medir_disco=_disco)
    assert d["estado"] == "velho" and d["resumo"].startswith("Leitura velha, de 12 min atrás")
    assert "tranquilo" not in d["resumo"]
    p = _gravar(tmp_path, _resumo_vigia(AGORA - timedelta(minutes=3)))
    assert servidor.ler(p, agora=AGORA, medir_disco=_disco)["estado"] == "ok"


def test_ausente(tmp_path: Path) -> None:
    d = servidor.ler(tmp_path / "servidor.json", agora=AGORA, medir_disco=_disco)
    assert d["estado"] == "ausente" and d["resumo"] == servidor.SAY_AUSENTE


@pytest.mark.parametrize("conteudo", ["{nao é json", "[]", json.dumps({"ts": "ontem"}),
                                      json.dumps({"cpu": None})])
def test_corrompido(tmp_path: Path, conteudo: str) -> None:
    d = servidor.ler(_gravar(tmp_path, conteudo), agora=AGORA, medir_disco=_disco)
    assert d["estado"] == "corrompido" and d["resumo"] == servidor.SAY_CORROMPIDO


def test_campos_tortos_sao_descartados(tmp_path: Path) -> None:
    bruto = _resumo_vigia(cpu="x", ram={"total_gib": "16"}, swap=None, load="1 2 3", alertas="ram")
    def sem_disco(_p: Path) -> Any:
        raise OSError("sem disco")

    d = servidor.ler(_gravar(tmp_path, bruto), agora=AGORA, medir_disco=sem_disco)
    assert d["estado"] == "ok" and d["cpu"] is None and d["ram"] is None and d["load"] is None
    assert d["alertas"] == [] and d["disco"] is None
    assert d["resumo"].startswith("Servidor tranquilo. Minecraft no ar")


# --------------------------------------------------------------------------- rota / MCP / nuvem


def test_escopos_registrados() -> None:
    assert ESCOPO_DE_ROTA[("GET", "/v1/servidor")].escopos == ("conversa", "ler")
    assert ESCOPO_DAS_TOOLS["servidor"] == "ler"
    assert "servidor" in NUVEM_PODE


async def test_rota_get_servidor(tmp_path: Path) -> None:
    app = FastAPI()
    app.include_router(rota.router)
    caminho = _gravar(tmp_path, _resumo_vigia(AGORA - timedelta(minutes=5)))
    app.state.ctx = SimpleNamespace(relogio=SimpleNamespace(agora=lambda: AGORA),
                                    extras={"servidor_json": caminho})
    app.dependency_overrides[rota.EXIGE] = lambda: object()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as cli:
        r = await cli.get("/v1/servidor")
        assert r.status_code == 200 and r.json()["estado"] == "velho"
        caminho.unlink()
        assert (await cli.get("/v1/servidor")).json()["estado"] == "ausente"


async def test_tool_nuvem_servidor() -> None:
    dados = {"estado": "ok", "resumo": "Servidor tranquilo."}
    deps = NuvemFerramentasDeps(tarefas=None, noticias=None, servidor=lambda: dados)  # type: ignore[arg-type]
    [t] = [f for f in ferramentas(deps) if f.name == "servidor"]
    res = await t.run({}, None)  # type: ignore[arg-type]
    assert res.ok and res.speech == "Servidor tranquilo."
    deps.servidor = lambda: {"estado": "ausente", "resumo": servidor.SAY_AUSENTE}
    res = await t.run({}, None)  # type: ignore[arg-type]
    assert not res.ok and res.speech == servidor.SAY_AUSENTE
