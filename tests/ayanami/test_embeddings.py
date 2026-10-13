"""Y3.6: embeddings locais em lote (spec §5.6) — prefixos e5, lotes de 64, 384 dimensões, e o job
só registrado com ``[embeddings] ligado`` (CA-Y13: 17 → 18). Embedder falso (nada baixado); o teste
com o modelo real pula por padrão (``AYANAMI_EMB_REAL=1``)."""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence

import pytest
from procrastinate import testing

from ayanami import fila
from ayanami.config import de_dict
from ayanami.deps import Deps
from ayanami.workers import embeddings as emb

BASE = {"geral": {"url_base": "https://ayanami.exemplo.ts.net"}}
DESLIGADO = de_dict(BASE)
LIGADO = de_dict(BASE | {"embeddings": {"ligado": True}})


class Falso:
    def __init__(self, dim: int = emb.DIM) -> None:
        self.dim = dim
        self.lotes: list[list[str]] = []

    def embutir(self, textos: Sequence[str]) -> list[list[float]]:
        self.lotes.append(list(textos))
        return [[float(len(t))] * self.dim for t in textos]


def test_desligado_nao_registra_o_job_e_ligado_registra():
    desl = fila.montar(DESLIGADO, testing.InMemoryConnector(), periodicas=False)
    lig = fila.montar(LIGADO, testing.InMemoryConnector(), periodicas=False)
    nossas = {d.nome for d in fila.TAREFAS}
    assert sorted(n for n in desl.tasks if n in nossas) == sorted(nossas - {"embeddings.lote"})
    assert len([n for n in desl.tasks if n in nossas]) == 17
    assert len([n for n in lig.tasks if n in nossas]) == 18
    t = lig.tasks["embeddings.lote"]
    assert (t.queue, t.lock) == ("lenta", "emb")


def test_prefixos_e_lotes_de_64():
    falso = Falso()
    textos = [f"t{i}" for i in range(130)]
    vs = emb.embutir(falso, textos)
    assert [len(lote) for lote in falso.lotes] == [64, 64, 2]
    assert falso.lotes[0][0] == "passage: t0"
    assert len(vs) == 130 and all(len(v) == 384 for v in vs)
    emb.embutir(falso, ["quanto custa?"], "query")
    assert falso.lotes[-1] == ["query: quanto custa?"]
    with pytest.raises(ValueError):
        emb.com_prefixo(["x"], "outro")  # type: ignore[arg-type]


def test_dimensao_errada_e_erro():
    with pytest.raises(ValueError):
        emb.embutir(Falso(dim=768), ["x"])


async def test_job_lote_com_falso_e_recusa_desligado(tmp_path):
    falso = Falso()
    deps = Deps(db=None, cfg=LIGADO, dados=tmp_path, extras={"embedder": falso})  # type: ignore[arg-type]
    r = await emb.lote(deps, None, textos=["a", "bb"])  # type: ignore[arg-type]
    assert r["texto"] == "2 vetores" and r["dados"]["dim"] == 384
    assert [v[0] for v in r["dados"]["vetores"]] == [len("passage: a"), len("passage: bb")]
    with pytest.raises(RuntimeError):
        await emb.lote(Deps(db=None, cfg=DESLIGADO, extras={"embedder": falso}), None,  # type: ignore[arg-type]
                       textos=["a"])


def test_fastembed_nao_e_importado_ate_o_uso():
    e = emb.FastEmbedLocal()
    assert e.modelo == "intfloat/multilingual-e5-small" and e._m is None
    assert "fastembed" not in sys.modules


@pytest.mark.skipif(not os.environ.get("AYANAMI_EMB_REAL"), reason="modelo real: AYANAMI_EMB_REAL=1")
def test_fastembed_real_opcional():  # pragma: no cover
    vs = emb.embutir(emb.FastEmbedLocal(), ["olá"], "query")
    assert len(vs[0]) == 384
