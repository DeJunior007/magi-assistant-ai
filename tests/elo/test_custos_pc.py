"""``CustosPc`` (Y6.6, spec §6.4): puxa ``/v1/custos`` paginado, insere sem duplicar (2 puxadas
seguidas), total local do mês para o ``Bate``, puxada a cada conexão nova e a cada 15 min.
Ayanami falsa por ``httpx.MockTransport``; repo falso; relógio e ``dormir`` injetados."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

import httpx
import pytest

from magi.elo import custos_pc as cp
from magi.elo.custos_pc import CustosPc, linha_valida
from magi.memory.costs_repo import TZ


def _linha(i: int, usd: float = 0.01) -> dict[str, Any]:
    return {"uid": f"00000000-0000-0000-0000-{i:012d}", "at": "2026-10-13T12:00:00Z", "provider": "openai",
            "task": "agent", "model": "gpt-x", "input_units": 10, "output_units": 5, "usd": usd}


class Repo:
    def __init__(self) -> None:
        self.linhas: dict[str, Mapping[str, Any]] = {}
        self.local = 1.25

    async def ultimo_uid(self) -> str | None:
        return list(self.linhas)[-1] if self.linhas else None

    async def inserir(self, linhas: Sequence[Mapping[str, Any]]) -> int:
        n = 0
        for ln in linhas:
            if ln["uid"] not in self.linhas:
                self.linhas[ln["uid"]] = ln
                n += 1
        return n

    async def total_local_mes(self, ano: int, mes: int) -> float:
        assert (ano, mes) == (2026, 10)
        return self.local


class Ayanami:
    """``GET /v1/custos?desde=&n=``: ordem de id; ``desde`` desconhecido recomeça do início."""

    def __init__(self, total: int) -> None:
        self.todas = [_linha(i) for i in range(total)]
        self.pedidos: list[dict[str, str]] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/v1/custos"
        assert req.headers["Authorization"] == "Bearer tok-falso"
        q = dict(req.url.params)
        self.pedidos.append(q)
        uids = [x["uid"] for x in self.todas]
        ini = uids.index(q["desde"]) + 1 if q.get("desde") in uids else 0
        n = int(q.get("n", 500))
        return httpx.Response(200, json={"linhas": self.todas[ini:ini + n]})


class Cliente:
    base_url = "http://ayanami.teste"
    _cabecalhos = {"Authorization": "Bearer tok-falso"}
    modo: str | None = None


def _custos(api: Ayanami, repo: Repo, cliente: Any = None, **kw: Any) -> CustosPc:
    http = httpx.AsyncClient(transport=httpx.MockTransport(api))
    return CustosPc(None, cliente or Cliente(), repo=repo, http=http,
                    agora=lambda: datetime(2026, 10, 13, 9, tzinfo=TZ), **kw)


async def test_duas_puxadas_nao_duplicam(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cp, "PAGINA", 50)
    api, repo = Ayanami(120), Repo()
    c = _custos(api, repo)
    assert await c.puxar() == 120
    assert [p.get("desde") for p in api.pedidos] == [None, _linha(49)["uid"], _linha(99)["uid"]]
    api.todas.append(_linha(120))
    assert await c.puxar() == 1
    assert api.pedidos[-1]["desde"] == _linha(119)["uid"]
    # outro processo (reinício): lê o último uid do banco; desde desconhecido não duplica
    c2 = _custos(api, repo)
    assert await c2.puxar() == 0
    c3 = _custos(Ayanami(121), repo)
    c3._desde_lido = True  # força recomeçar do início
    assert await c3.puxar() == 0
    assert len(repo.linhas) == 121


async def test_total_mes_e_so_o_local() -> None:
    c = _custos(Ayanami(0), Repo())
    assert c.total_mes() is None
    assert await c.atualizar_total() == 1.25
    assert c.total_mes() == 1.25


def test_linha_valida() -> None:
    assert linha_valida(_linha(1))["at"].tzinfo is not None
    assert linha_valida({**_linha(1), "usd": -1}) is None
    assert linha_valida({**_linha(1), "usd": "nan"}) is None
    assert linha_valida({**_linha(1), "at": "2026-10-13T12:00:00"}) is None
    assert linha_valida({"uid": "x"}) is None
    assert linha_valida("lixo") is None


async def test_rodar_puxa_na_conexao_nova_e_a_cada_15_min() -> None:
    api, repo = Ayanami(1), Repo()
    cli = Cliente()
    t = [0.0]
    voltas: list[float] = []

    class Fim(Exception):
        pass

    roteiro = {1: "ws", 3: None, 4: "longpoll"}  # conecta, cai, reconecta

    async def dormir(s: float) -> None:
        voltas.append(s)
        n = len(voltas)
        if n in roteiro:
            cli.modo = roteiro[n]
        t[0] += 300 if n >= 5 else 1
        if n >= 10:
            raise Fim

    c = _custos(api, repo, cliente=cli, relogio=lambda: t[0], dormir=dormir)
    with pytest.raises(Fim):
        await c.rodar()
    # início (t=0), conexão "ws" (t=1), reconexão "longpoll" (t=4) e 15 min depois (t=904); t=1804 não chega
    assert len(api.pedidos) == 4


async def test_erro_de_rede_nao_derruba() -> None:
    def falha(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("fora")

    c = CustosPc(None, Cliente(), repo=Repo(), http=httpx.AsyncClient(transport=httpx.MockTransport(falha)),
                 agora=lambda: datetime(2026, 10, 13, tzinfo=TZ))
    await c._volta()  # não levanta
    assert c.total_mes() == 1.25
