"""A1.3: refino pelo Qwen local com modelo e ``ContainerRuntime`` falsos (nada de rede/docker)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from magi.audiolivro import marcas_llm as ml
from magi.audiolivro.config import ConfigAudiolivro
from magi.audiolivro.contratos import Capitulo, Emocao, Livro, Paragrafo, Tipo, Trecho
from magi.common.config import parse_config
from magi.learning.model import ModelInvalid, ModelTimeout


class ModeloFalso:
    def __init__(self, resposta: Any = None, erro: BaseException | None = None, trava: bool = False):
        self.resposta = resposta
        self.erro = erro
        self.trava = trava
        self.chamadas: list[tuple[str, str, dict]] = []

    async def complete(self, system: str, user: str, schema: dict) -> tuple[dict, float]:
        self.chamadas.append((system, user, schema))
        if self.trava:
            await asyncio.Event().wait()
        if self.erro is not None:
            raise self.erro
        return self.resposta, 0.0


class RuntimeFalso:
    def __init__(self, sobe: bool = True, pronto: bool = False, explode: bool = False):
        self.ready = asyncio.Event()
        if pronto:
            self.ready.set()
        self.sobe = sobe
        self.explode = explode
        self.starts = 0
        self.stops = 0

    async def start(self) -> bool:
        self.starts += 1
        if self.explode:
            raise OSError("docker ausente")
        if self.sobe:
            self.ready.set()
        return self.sobe

    async def stop(self) -> None:
        self.stops += 1
        self.ready.clear()


def _livro(tmp_path: Path) -> Livro:
    return Livro("abc123", tmp_path / "x.epub", "Duna", "Herbert", "pt-br", "epub", 3, 100)


def _cap() -> Capitulo:
    ps = (Paragrafo(0, ("— Vem — disse ela.",)), Paragrafo(1, ("Ele ficou.",)))
    return Capitulo(0, "Um", ps, 1.0)


def _trechos() -> list[list[Trecho]]:
    return [
        [
            Trecho("— Vem", Tipo.FALA, par=0),
            Trecho(" — disse ela.", Tipo.NARRACAO, genero="f", par=0),
        ],
        [Trecho("Ele ficou.", par=1)],
    ]


def _refino(tmp_path: Path, modelo: Any, runtime: Any, **kw: Any) -> ml.RefinoQwen:
    cfg = ConfigAudiolivro(cache_dir=tmp_path / "cache")
    return ml.RefinoQwen(cfg, modelo, runtime, **kw)


BOA = {
    "marcas": [
        {"par": 0, "i": 0, "tipo": "fala", "emocao": "sussurro", "falante": "Chani", "genero": "f",
         "idade": "jovem"},
        {"par": 1, "i": 0, "tipo": "narracao", "emocao": "tensa", "falante": None},
    ]
}


def _textos(ts: list[list[Trecho]]) -> list[list[str]]:
    return [[t.texto for t in p] for p in ts]


async def test_resposta_boa_mescla_e_liga_container(tmp_path: Path) -> None:
    modelo, rt = ModeloFalso(BOA), RuntimeFalso()
    r = _refino(tmp_path, modelo, rt)
    out = await r.refinar(_livro(tmp_path), _cap(), _trechos())
    assert out is not None
    assert _textos(out) == _textos(_trechos())  # A9
    fala = out[0][0]
    assert (fala.tipo, fala.emocao, fala.falante, fala.genero, fala.idade) == (
        Tipo.FALA, Emocao.SUSSURRO, "Chani", "f", "jovem")
    assert out[0][1].genero == "f"  # sem marca: fica a regra
    assert out[1][0].emocao is Emocao.TENSA
    assert rt.starts == 1 and len(modelo.chamadas) == 1
    system, user, schema = modelo.chamadas[0]
    assert "JSON" in system and '"par": 0' in user and schema is ml.SCHEMA
    await r.parar()
    assert rt.stops == 1  # foi ele que ligou


async def test_nao_para_container_que_nao_ligou(tmp_path: Path) -> None:
    rt = RuntimeFalso(pronto=True)
    r = _refino(tmp_path, ModeloFalso(BOA), rt)
    assert await r.refinar(_livro(tmp_path), _cap(), _trechos()) is not None
    await r.parar()
    assert rt.starts == 0 and rt.stops == 0


async def test_indice_invalido_descartado(tmp_path: Path) -> None:
    resp = {
        "marcas": [
            {"par": 9, "i": 0, "tipo": "fala", "emocao": "grito"},
            {"par": 0, "i": 5, "tipo": "fala", "emocao": "grito"},
            {"par": 0, "i": 0, "tipo": "cantoria", "emocao": "grito"},
            {"par": 0, "i": 0, "tipo": "fala", "emocao": "grito", "genero": "x"},
            {"par": True, "i": 0, "tipo": "fala", "emocao": "grito"},
            {"par": 1, "i": 0, "tipo": "pensamento", "emocao": "medo", "texto": "outro texto"},
        ]
    }
    out = await _refino(tmp_path, ModeloFalso(resp), RuntimeFalso()).refinar(
        _livro(tmp_path), _cap(), _trechos()
    )
    assert out is not None
    assert out[0] == _trechos()[0]  # nada válido no par 0
    assert out[1][0].tipo is Tipo.PENSAMENTO and out[1][0].texto == "Ele ficou."


@pytest.mark.parametrize(
    "modelo",
    [
        ModeloFalso(erro=ModelInvalid("não é JSON")),  # texto em vez de JSON
        ModeloFalso("Claro! Aqui estão as marcas: ..."),
        ModeloFalso({"resposta": "o capítulo fala de..."}),
        ModeloFalso(erro=ModelTimeout("timeout")),
        ModeloFalso(erro=ConnectionError("Qwen fora do ar")),
    ],
    ids=["invalid", "texto", "sem-marcas", "timeout", "fora"],
)
async def test_falhas_viram_regras(tmp_path: Path, modelo: ModeloFalso) -> None:
    r = _refino(tmp_path, modelo, RuntimeFalso())
    assert await r.refinar(_livro(tmp_path), _cap(), _trechos()) is None
    assert r.pronto(_livro(tmp_path), 0) is None  # nada no cache


async def test_timeout_proprio(tmp_path: Path) -> None:
    r = _refino(tmp_path, ModeloFalso(trava=True), RuntimeFalso(), timeout_s=0.01)
    assert await r.refinar(_livro(tmp_path), _cap(), _trechos()) is None


@pytest.mark.parametrize("rt", [RuntimeFalso(sobe=False), RuntimeFalso(explode=True)])
async def test_container_nao_sobe(tmp_path: Path, rt: RuntimeFalso) -> None:
    modelo = ModeloFalso(BOA)
    r = _refino(tmp_path, modelo, rt)
    assert await r.refinar(_livro(tmp_path), _cap(), _trechos()) is None
    assert modelo.chamadas == []
    await r.parar()
    assert rt.stops == 0


async def test_cache_reaproveitado(tmp_path: Path) -> None:
    modelo = ModeloFalso(BOA)
    r = _refino(tmp_path, modelo, RuntimeFalso())
    livro = _livro(tmp_path)
    assert r.pronto(livro, 0) is None
    primeira = await r.refinar(livro, _cap(), _trechos())
    assert (tmp_path / "cache" / "abc123" / "marcas-0.json").exists()
    outro = _refino(tmp_path, ModeloFalso(BOA), RuntimeFalso())
    assert outro.pronto(livro, 0) == primeira
    assert await outro.refinar(livro, _cap(), _trechos()) == primeira
    assert outro.modelo.chamadas == [] and outro.runtime.starts == 0  # 0 chamadas na 2ª vez


async def test_adiantar_em_segundo_plano(tmp_path: Path) -> None:
    modelo = ModeloFalso(BOA)
    r = _refino(tmp_path, modelo, RuntimeFalso())
    livro = _livro(tmp_path)
    t1 = r.adiantar(livro, _cap(), _trechos())
    assert t1 is not None and r.adiantar(livro, _cap(), _trechos()) is t1  # sem duplicar
    assert r.pronto(livro, 0) is None  # não bloqueou
    await t1
    assert r.pronto(livro, 0) is not None
    assert r.adiantar(livro, _cap(), _trechos()) is None  # já no cache
    assert len(modelo.chamadas) == 1


def test_titulo_nao_muda() -> None:
    ts = [[Trecho("Capítulo 1", Tipo.TITULO), Trecho("Oi.")]]
    marcas = ml.validar(
        {"marcas": [{"par": 0, "i": 0, "tipo": "fala", "emocao": "neutra"},
                    {"par": 0, "i": 1, "tipo": "titulo", "emocao": "alegre"}]}, ts
    )
    out = ml.mesclar(ts, marcas)
    assert out[0][0].tipo is Tipo.TITULO
    assert out[0][1].tipo is Tipo.NARRACAO and out[0][1].emocao is Emocao.ALEGRE
    assert ml.validar("texto solto", ts) == [] and ml.validar(None, ts) == []


def _config(raw: dict) -> Any:
    prov = {n: {"keys": []} for n in ("kokoro", "openai", "qwen")}
    base: dict[str, Any] = {"providers": prov, "tasks": {}}
    base.update(raw)
    return parse_config(base)


async def test_provedor_pago_zero_chamadas(tmp_path: Path) -> None:
    cfg = ConfigAudiolivro(cache_dir=tmp_path / "cache")
    modelo, rt = ModeloFalso(BOA), RuntimeFalso()
    pago = _config({"tasks": {"audiolivro_marca": {"provider": "openai", "model": "gpt-5.4-mini"}}})
    assert ml.criar(pago, cfg, modelo, rt) is None
    assert ml.criar(_config({}), ConfigAudiolivro(marcacao="regras"), modelo, rt) is None
    assert modelo.chamadas == [] and rt.starts == 0
    local = ml.criar(_config({}), cfg, modelo, rt)
    assert local is not None and local.timeout_s == 60.0
