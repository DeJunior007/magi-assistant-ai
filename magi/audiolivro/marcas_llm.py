"""Refino da marcação pelo Qwen local (tarefa A1.3; D2; spec §2, requirements A3.1).

Por capítulo, manda os parágrafos numerados e os trechos das regras; o Qwen devolve só JSON de
``Marca`` (nunca texto); valida e mescla. Roda em segundo plano à frente da leitura e nunca a
bloqueia; liga o ``magi-qwen`` pelo ``ContainerRuntime`` (``magi/learning/runtime.py``) quando
preciso. Cache por livro/capítulo em ``cache_dir/<id>/marcas-<cap>.json``. Qwen fora do ar,
timeout ou JSON inválido → ``None`` (vale a regra). Sem custo; nunca LLM pago.

- ``par`` da ``Marca`` é a posição do parágrafo na lista de trechos do capítulo; ``i`` é o índice
  do trecho dentro dele.
- O refino nunca muda ``texto`` (A9) nem transforma trecho em/de ``TITULO`` (o título vem do
  formato do livro, não do modelo).
- ``criar`` devolve ``None`` quando ``tarefa_marca`` recusa (``marcacao = "regras"`` ou provedor
  não local, A7.2): o chamador fica só com as regras e o modelo nunca é chamado.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from magi.audiolivro.config import ConfigAudiolivro, tarefa_marca
from magi.audiolivro.contratos import (
    GENEROS,
    IDADES,
    Capitulo,
    Emocao,
    Livro,
    Marca,
    Tipo,
    Trecho,
)

log = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent / "prompts" / "marcas.md"
VERSAO_CACHE = 1
TIMEOUT_PADRAO_S = 60.0
MAX_FALANTE = 60

_TIPOS = tuple(t.value for t in Tipo)
_EMOCOES = tuple(e.value for e in Emocao)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "marcas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "par": {"type": "integer"},
                    "i": {"type": "integer"},
                    "tipo": {"type": "string", "enum": list(_TIPOS)},
                    "emocao": {"type": "string", "enum": list(_EMOCOES)},
                    "falante": {"type": ["string", "null"]},
                    "genero": {"type": ["string", "null"], "enum": [*GENEROS, None]},
                    "idade": {"type": ["string", "null"], "enum": [*IDADES, None]},
                },
                "required": ["par", "i", "tipo", "emocao"],
            },
        }
    },
    "required": ["marcas"],
}


def _inteiro(v: Any) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _opcional(v: Any, escolhas: tuple[str, ...]) -> tuple[bool, str | None]:
    """(válido, valor) para campo opcional com enum."""
    if v is None or v == "":
        return True, None
    return (True, v) if isinstance(v, str) and v in escolhas else (False, None)


def _marca(item: Any, trechos: list[list[Trecho]]) -> Marca | None:
    if not isinstance(item, dict):
        return None
    par, i = _inteiro(item.get("par")), _inteiro(item.get("i"))
    if par is None or i is None or not (0 <= par < len(trechos)) or not (0 <= i < len(trechos[par])):
        return None
    tipo, emocao = item.get("tipo"), item.get("emocao")
    if tipo not in _TIPOS or emocao not in _EMOCOES:
        return None
    ok_g, genero = _opcional(item.get("genero"), GENEROS)
    ok_i, idade = _opcional(item.get("idade"), IDADES)
    if not (ok_g and ok_i):
        return None
    falante = item.get("falante")
    if falante is not None and not isinstance(falante, str):
        return None
    falante = (falante or "").strip()[:MAX_FALANTE] or None
    return Marca(
        par=par,
        i=i,
        tipo=Tipo(tipo),
        emocao=Emocao(emocao),
        falante=falante,
        genero=genero,  # type: ignore[arg-type]
        idade=idade,  # type: ignore[arg-type]
    )


def validar(dados: Any, trechos: list[list[Trecho]]) -> list[Marca]:
    """Marcas válidas do JSON (índices existentes, enums válidos); o resto é descartado."""
    if isinstance(dados, dict):
        dados = dados.get("marcas")
    if not isinstance(dados, list):
        return []
    marcas = []
    for item in dados:
        m = _marca(item, trechos)
        if m is None:
            log.debug("audiolivro: marca descartada: %r", item)
        else:
            marcas.append(m)
    return marcas


def mesclar(trechos: list[list[Trecho]], marcas: list[Marca]) -> list[list[Trecho]]:
    """Aplica as marcas nos trechos das regras sem mudar nenhum ``texto`` (A9)."""
    out = [list(p) for p in trechos]
    for m in marcas:
        if not (0 <= m.par < len(out) and 0 <= m.i < len(out[m.par])):
            continue
        t = out[m.par][m.i]
        tipo = t.tipo if Tipo.TITULO in (t.tipo, m.tipo) else m.tipo
        out[m.par][m.i] = replace(
            t,
            tipo=tipo,
            emocao=m.emocao,
            falante=m.falante if m.falante is not None else t.falante,
            genero=m.genero if m.genero is not None else t.genero,
            idade=m.idade if m.idade is not None else t.idade,
        )
    return out


def _entrada(trechos: list[list[Trecho]]) -> str:
    paragrafos = [
        {
            "par": n,
            "trechos": [
                {
                    "i": i,
                    "texto": t.texto,
                    "tipo": t.tipo.value,
                    "emocao": t.emocao.value,
                    "falante": t.falante,
                    "genero": t.genero,
                    "idade": t.idade,
                }
                for i, t in enumerate(p)
            ],
        }
        for n, p in enumerate(trechos)
    ]
    return json.dumps({"paragrafos": paragrafos}, ensure_ascii=False)


def _de_json(dados: Any) -> list[list[Trecho]] | None:
    try:
        return [
            [
                Trecho(
                    texto=t["texto"],
                    tipo=Tipo(t["tipo"]),
                    emocao=Emocao(t["emocao"]),
                    falante=t.get("falante"),
                    genero=t.get("genero"),
                    idade=t.get("idade"),
                    par=int(t.get("par", 0)),
                    frase=int(t.get("frase", 0)),
                )
                for t in p
            ]
            for p in dados
        ]
    except (TypeError, KeyError, ValueError):
        return None


def criar(config: Any, cfg: ConfigAudiolivro, modelo: Any, runtime: Any) -> RefinoQwen | None:
    """O refino, ou ``None`` (só regras) quando ``tarefa_marca`` recusa (D2/A7.2)."""
    tarefa = tarefa_marca(config, cfg)
    if tarefa is None:
        return None
    timeout = tarefa.options.get("timeout_s", TIMEOUT_PADRAO_S)
    return RefinoQwen(cfg, modelo, runtime, timeout_s=float(timeout))


class RefinoQwen:
    """``modelo``: ``LearningModel`` (``complete(system, user, schema)``); ``runtime``: o
    ``ContainerRuntime``/``NullRuntime`` do ``magi-qwen``. Os dois injetados (testes: falsos)."""

    def __init__(
        self,
        cfg: ConfigAudiolivro,
        modelo: Any,
        runtime: Any,
        *,
        timeout_s: float = TIMEOUT_PADRAO_S,
    ) -> None:
        self.cfg = cfg
        self.modelo = modelo
        self.runtime = runtime
        self.timeout_s = timeout_s
        self._ligou = False
        self._lock = asyncio.Lock()
        self._tarefas: dict[tuple[str, int], asyncio.Task[Any]] = {}
        self._prompt: str | None = None

    # -- cache ----------------------------------------------------------------------------------

    def _cache(self, livro: Livro, cap: int) -> Path:
        return self.cfg.cache_dir / livro.id / f"marcas-{cap}.json"

    def pronto(self, livro: Livro, cap: int) -> list[list[Trecho]] | None:
        """Trechos refinados do capítulo se o cache já existe; ``None`` = use as regras."""
        try:
            dados = json.loads(self._cache(livro, cap).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(dados, dict) or dados.get("versao") != VERSAO_CACHE:
            return None
        return _de_json(dados.get("trechos"))

    def _gravar(self, livro: Livro, cap: int, trechos: list[list[Trecho]]) -> None:
        caminho = self._cache(livro, cap)
        try:
            caminho.parent.mkdir(parents=True, exist_ok=True)
            tmp = caminho.with_suffix(".tmp")
            dados = {"versao": VERSAO_CACHE, "trechos": [[asdict(t) for t in p] for p in trechos]}
            tmp.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, caminho)
        except OSError as e:
            log.warning("audiolivro: cache das marcas não gravado (%s)", e)

    # -- modelo ---------------------------------------------------------------------------------

    def _system(self) -> str:
        if self._prompt is None:
            self._prompt = PROMPT_PATH.read_text(encoding="utf-8")
        return self._prompt

    async def _qwen_de_pe(self) -> bool:
        async with self._lock:
            if self.runtime.ready.is_set():
                return True
            try:
                ok = bool(await self.runtime.start())
            except Exception as e:  # noqa: BLE001 — container fora: só regras
                log.warning("audiolivro: magi-qwen não subiu (%s); só regras", e)
                return False
            if ok:
                self._ligou = True
            else:
                log.warning("audiolivro: magi-qwen não subiu; só regras")
            return ok

    async def refinar(
        self, livro: Livro, capitulo: Capitulo, trechos: list[list[Trecho]]
    ) -> list[list[Trecho]] | None:
        """Refina e grava no cache; ``None`` quando o Qwen não respondeu direito."""
        feito = self.pronto(livro, capitulo.n)
        if feito is not None:
            return feito
        if not trechos or not await self._qwen_de_pe():
            return None
        try:
            resposta = await asyncio.wait_for(
                self.modelo.complete(self._system(), _entrada(trechos), SCHEMA), self.timeout_s
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — timeout, JSON inválido, Qwen fora: vale a regra
            log.warning("audiolivro: refino do cap. %d falhou (%s); só regras", capitulo.n, e)
            return None
        dados = resposta[0] if isinstance(resposta, tuple) else resposta
        if isinstance(dados, str):
            try:
                dados = json.loads(dados)
            except ValueError:
                dados = None
        if not isinstance(dados, dict) or not isinstance(dados.get("marcas"), list):
            log.warning("audiolivro: refino do cap. %d fora do formato; só regras", capitulo.n)
            return None
        refinado = mesclar(trechos, validar(dados, trechos))
        self._gravar(livro, capitulo.n, refinado)
        return refinado

    def adiantar(
        self, livro: Livro, capitulo: Capitulo, trechos: list[list[Trecho]]
    ) -> asyncio.Task[Any] | None:
        """Agenda ``refinar`` em segundo plano (capítulo atual + próximo; nunca bloqueia a
        leitura). Já no cache ou já em andamento = nada novo."""
        chave = (livro.id, capitulo.n)
        atual = self._tarefas.get(chave)
        if atual is not None and not atual.done():
            return atual
        if self._cache(livro, capitulo.n).exists():
            return None
        tarefa = asyncio.create_task(
            self.refinar(livro, capitulo, trechos), name=f"audiolivro-marcas-{capitulo.n}"
        )
        self._tarefas[chave] = tarefa

        def _solta(t: asyncio.Task[Any]) -> None:
            if self._tarefas.get(chave) is t:
                del self._tarefas[chave]

        tarefa.add_done_callback(_solta)
        return tarefa

    async def parar(self) -> None:
        """Para o container se foi o refino que o ligou."""
        tarefas = list(self._tarefas.values())
        self._tarefas.clear()
        for t in tarefas:
            t.cancel()
        for t in tarefas:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        if self._ligou:
            self._ligou = False
            await self.runtime.stop()
