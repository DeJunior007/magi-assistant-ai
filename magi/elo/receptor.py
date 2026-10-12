"""Receptor do elo: idempotência por id e corte de quem manda lixo (spec §1.3).

Sem I/O: recebe o frame de texto, devolve a resposta (já codificada) e, quando for o caso, o
código para fechar a WS. Guarda os últimos ``cache`` ids com a resposta dada; o mesmo envelope
reenviado (mesmo ``id``) recebe a mesma resposta sem reexecutar o handler (``acao`` nunca roda 2×).
Frame inválido → ``erro`` com ``codigo="invalido"``; ``limite`` inválidos em ``janela_s`` → 1008.
"""

from __future__ import annotations

import inspect
import json
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final

from magi.elo.ids import valido
from magi.elo.mensagens import NOME_RE, EloError, Envelope, Erro, Tipo, decode, encode

FECHA_POLITICA: Final = 1008
CACHE_IDS: Final = 512
LIMITE_INVALIDOS: Final = 10
JANELA_INVALIDOS_S: Final = 60.0

Handler = Callable[[Envelope], "Envelope | None | Awaitable[Envelope | None]"]


@dataclass(frozen=True, slots=True)
class Saida:
    """O que fazer com o frame: ``resposta`` (texto a mandar, ou ``None``) e ``fechar`` (código WS)."""

    resposta: str | None = None
    fechar: int | None = None
    repetido: bool = False


class Receptor:
    """``nome``: quem responde (``de`` das respostas). ``relogio``: segundos monotônicos (injetado).

    ``handler(env)`` devolve a resposta (``Envelope`` ou ``None``), síncrono ou ``async``. Exceção
    no handler vira ``erro`` ``interno`` (sem texto de exceção) e também fica no cache.
    """

    def __init__(
        self,
        nome: str,
        handler: Handler,
        relogio: Callable[[], float],
        *,
        cache: int = CACHE_IDS,
        limite_invalidos: int = LIMITE_INVALIDOS,
        janela_s: float = JANELA_INVALIDOS_S,
    ) -> None:
        self.nome = nome
        self._handler = handler
        self._relogio = relogio
        self._max_cache = cache
        self._cache: OrderedDict[str, str | None] = OrderedDict()
        self._limite = limite_invalidos
        self._janela = janela_s
        self._invalidos: deque[float] = deque()

    def __contains__(self, id_: str) -> bool:
        return id_ in self._cache

    async def receber(self, raw: str | bytes) -> Saida:
        """Trata um frame de texto do elo."""
        try:
            env = decode(raw)
        except EloError as e:
            return self._invalido(raw, e)
        if env.id in self._cache:
            self._cache.move_to_end(env.id)
            return Saida(resposta=self._cache[env.id], repetido=True)
        try:
            r = self._handler(env)
            if inspect.isawaitable(r):
                r = await r
            resposta = encode(r) if r is not None else None
        except Exception:  # noqa: BLE001 - o elo não derruba a conexão por erro do handler
            resposta = encode(self._erro(env.de, env.id, "interno"))
        self._guarda(env.id, resposta)
        return Saida(resposta=resposta)

    def _guarda(self, id_: str, resposta: str | None) -> None:
        self._cache[id_] = resposta
        while len(self._cache) > self._max_cache:
            self._cache.popitem(last=False)

    def _erro(self, para: str, resp: str | None, codigo: str, msg: str = "") -> Envelope:
        return Envelope(
            t=Tipo.ERRO, corpo=Erro(codigo=codigo, msg=msg[:200]), de=self.nome, para=para, resp=resp
        )

    def _invalido(self, raw: str | bytes, e: EloError) -> Saida:
        agora = self._relogio()
        self._invalidos.append(agora)
        while self._invalidos and agora - self._invalidos[0] >= self._janela:
            self._invalidos.popleft()
        para, resp = _remetente(raw)
        resposta = encode(self._erro(para, resp, "invalido", e.codigo))
        fechar = FECHA_POLITICA if len(self._invalidos) >= self._limite else None
        return Saida(resposta=resposta, fechar=fechar)


def _remetente(raw: str | bytes) -> tuple[str, str | None]:
    """Melhor esforço para achar ``de`` e ``id`` de um frame inválido."""
    try:
        d = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return "desconhecido", None
    if not isinstance(d, dict):
        return "desconhecido", None
    de = d.get("de")
    para = de if isinstance(de, str) and NOME_RE.fullmatch(de) else "desconhecido"
    id_ = d.get("id")
    return para, id_ if valido(id_) else None
