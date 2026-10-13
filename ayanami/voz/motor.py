"""Motor de TTS e carga preguiçosa (dono: Y3.5; spec §5.4).

O servidor só conhece o protocolo :class:`Motor` (PCM s16le mono, em pedaços). O motor real
(:class:`MotorKokoro`) importa ``kokoro_onnx`` só no construtor, que roda dentro de
:meth:`Gerenciador.obter` na 1ª fala; os testes passam um carregador falso.

:class:`Gerenciador`:

- ``obter()`` carrega o motor (em thread) na 1ª chamada; a carga é uma só mesmo com pedidos
  simultâneos. Se ela passar de ``prazo_carga_s`` (20 s), levanta :class:`Carregando` (o servidor
  responde ``503``) e a carga continua em segundo plano para o próximo pedido.
- Cada fala marca uso (``obter`` → ``liberar``); ``verificar()`` descarrega quando nada está em
  uso e o último uso foi há ≥ ``descarregar_apos_s`` (relógio monotônico injetado).
- ``vigiar()`` roda ``verificar()`` a cada ``intervalo_s`` com ``relogio.dormir``.
"""

from __future__ import annotations

import asyncio
import gc
import logging
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ayanami.relogio import Relogio, RelogioReal

log = logging.getLogger(__name__)

TAXA = 24000
LANG = "pt-br"
VOICES_ARQUIVO = "voices-v1.0.bin"


@runtime_checkable
class Motor(Protocol):
    taxa: int

    def falar(self, texto: str, voz: str, velocidade: float) -> AsyncIterator[bytes]:
        """PCM s16le mono em ``taxa`` Hz, em pedaços, na ordem."""
        ...


class Carregando(Exception):
    """O modelo ainda está carregando depois do prazo (``503``)."""


def para_pcm16(amostras: Any) -> bytes:
    """``float32`` em [-1, 1] → PCM s16le (corta fora da faixa)."""
    import numpy as np

    a = np.clip(np.asarray(amostras, dtype=np.float32), -1.0, 1.0)
    return (a * 32767.0).astype("<i2").tobytes()


class MotorKokoro:
    """Kokoro (``kokoro-onnx`` 0.6.1) em CPU, ``lang="pt-br"``."""

    def __init__(self, modelo: Path, voices: Path) -> None:
        from kokoro_onnx import Kokoro  # só aqui: nenhum teste importa kokoro_onnx

        self._k = Kokoro(str(modelo), str(voices))
        self.taxa = TAXA

    async def falar(self, texto: str, voz: str, velocidade: float) -> AsyncIterator[bytes]:
        async for amostras, taxa in self._k.create_stream(texto, voz, speed=velocidade, lang=LANG):
            if taxa != self.taxa:
                raise RuntimeError(f"kokoro: taxa {taxa}, esperava {self.taxa}")
            yield para_pcm16(amostras)


def carregador_kokoro(dir_modelos: Path, modelo: str) -> Callable[[], Motor]:
    """Carregador do motor real: ``<dir_modelos>/<modelo>`` + ``voices-v1.0.bin`` ao lado."""

    def carregar() -> Motor:
        return MotorKokoro(dir_modelos / modelo, dir_modelos / VOICES_ARQUIVO)

    return carregar


class Gerenciador:
    def __init__(
        self,
        carregar: Callable[[], Motor],
        *,
        relogio: Relogio | None = None,
        descarregar_apos_s: float = 600,
        prazo_carga_s: float = 20,
        intervalo_s: float = 30,
    ) -> None:
        self._carregar = carregar
        self._relogio = relogio or RelogioReal()
        self.descarregar_apos_s = descarregar_apos_s
        self.prazo_carga_s = prazo_carga_s
        self.intervalo_s = intervalo_s
        self._motor: Motor | None = None
        self._carga: asyncio.Task[Motor] | None = None
        self._em_uso = 0
        self._ultimo_uso = self._relogio.monotonico()
        self.cargas = 0

    @property
    def carregado(self) -> bool:
        return self._motor is not None

    async def _carregar_em_thread(self) -> Motor:
        self.cargas += 1
        log.info("voz: carregando o modelo")
        return await asyncio.to_thread(self._carregar)

    async def obter(self) -> Motor:
        """Motor pronto e marcado em uso; quem chama deve chamar :meth:`liberar` depois."""
        if self._motor is None:
            if self._carga is None:
                self._carga = asyncio.create_task(self._carregar_em_thread())
                self._carga.add_done_callback(self._fim_carga)
            try:
                await asyncio.wait_for(asyncio.shield(self._carga), self.prazo_carga_s)
            except TimeoutError:
                raise Carregando(f"voz: modelo carregando há mais de {self.prazo_carga_s:g} s") from None
        motor = self._motor
        if motor is None:  # a carga falhou: o erro já foi levantado pelo wait_for
            raise Carregando("voz: modelo indisponível")
        self._em_uso += 1
        self._ultimo_uso = self._relogio.monotonico()
        return motor

    def _fim_carga(self, tarefa: asyncio.Task[Motor]) -> None:
        self._carga = None
        if tarefa.cancelled():
            return
        erro = tarefa.exception()
        if erro is not None:
            log.error("voz: falha ao carregar o modelo: %s", erro)
            return
        self._motor = tarefa.result()
        self._ultimo_uso = self._relogio.monotonico()
        log.info("voz: modelo carregado")

    def liberar(self) -> None:
        self._em_uso = max(0, self._em_uso - 1)
        self._ultimo_uso = self._relogio.monotonico()

    def verificar(self) -> bool:
        """Descarrega se ocioso há ≥ ``descarregar_apos_s``; devolve ``True`` se descarregou."""
        if self._motor is None or self._em_uso > 0:
            return False
        if self._relogio.monotonico() - self._ultimo_uso < self.descarregar_apos_s:
            return False
        self.descarregar()
        return True

    def descarregar(self) -> None:
        motor, self._motor = self._motor, None
        fechar = getattr(motor, "fechar", None)
        if callable(fechar):
            fechar()
        del motor
        gc.collect()
        log.info("voz: modelo descarregado (ocioso)")

    async def vigiar(self) -> None:
        while True:
            await self._relogio.dormir(self.intervalo_s)
            self.verificar()
