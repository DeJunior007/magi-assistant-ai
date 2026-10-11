"""``BookHandler`` dos intents ``book.*`` (tarefa A2.3; spec §5, requirements A1, A6–A8).

Tempo restante (``book.time``, A7.1), ambiguidade (A1.1), não começa em call (A8.4), música
pausada ao começar e retomada no fim/``book.stop`` pelo MPRIS (D4), ``magi-qwen`` ligado pelo
refino no ``book.read`` e parado no ``book.stop``/fim se foi ele que ligou (D2).

A narração em si é do ``TurnMachine``: o handler devolve ``on_confirm.args[ARG_NARRATE]`` com
``needs_confirmation=False`` (A2.2) e a ``Narrada`` (a ``Leitura`` embrulhada) avisa o fim do
livro para a música voltar e o refino parar.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from magi.audiolivro import custo
from magi.audiolivro.biblioteca import NOTA_MINIMA, SEM_TEXTO, Biblioteca, nota
from magi.audiolivro.config import ConfigAudiolivro
from magi.audiolivro.contratos import Livro, OpcoesVoz, Posicao
from magi.common.contracts import ARG_NARRATE, ActionRequest, ActionResult, Expression, IntentId

log = logging.getLogger(__name__)

SAY_IN_CALL = "Tô numa call; leio quando ela acabar."
SAY_NOT_FOUND = "Não achei esse livro na pasta."
SAY_NO_TEXT = "Esse PDF é escaneado, não tem texto pra eu ler."
SAY_WHICH = "Achei mais de um: {a} ou {b}. Qual?"
SAY_READING = "Lendo {titulo}."
SAY_NO_BOOK = "Não tem livro aberto."
SAY_NO_BOOKS = "Não tem livro nenhum na pasta."
SAY_LIST = "Tenho {n} livros: {lista}."
SAY_PAUSED = "Leitura pausada."
SAY_STOPPED = "Fechei o livro."
SAY_SPEED = "Velocidade {v}."
SAY_WHERE = "Capítulo {cap} de {titulo}."
SAY_TIME = "Esse capítulo leva uns {min} minutos; o livro todo, umas {horas} horas."

PASSO = 0.1


def _int(req: ActionRequest, padrao: int | None = None) -> int | None:
    s = req.intent.slot("amount")
    try:
        return int(float(s.value)) if s is not None and s.value else padrao
    except ValueError:
        return padrao


def _texto(req: ActionRequest, nome: str) -> str:
    s = req.intent.slot(nome)
    return (s.value or "").strip() if s is not None else ""


def _num(v: float) -> str:
    return f"{v:.1f}".replace(".", ",").removesuffix(",0")


class Narrada:
    """A ``Leitura`` que vai ao ``TurnMachine`` (``ARG_NARRATE``): delega tudo e chama
    ``ao_fim()`` quando ``partes()`` chega ao fim sem interrupção (fim do livro ou
    ``parar_apos_capitulos``)."""

    def __init__(self, leitura: Any, ao_fim: Callable[[], Any]) -> None:
        self.leitura = leitura
        self.ao_fim = ao_fim
        self.fechada = False

    @property
    def estado(self) -> str:
        """``parada`` depois do ``book.stop``: "pausa"/"para" voltam para a música (A6.1)."""
        return "parada" if self.fechada else self.leitura.estado

    def __getattr__(self, nome: str) -> Any:
        return getattr(self.leitura, nome)

    async def partes(self) -> AsyncIterator[tuple[str, OpcoesVoz]]:
        async for parte in self.leitura.partes():
            yield parte
        self.ao_fim()


class BookHandler:
    """``biblioteca``: ``Biblioteca``; ``nova_leitura()``: monta a ``Leitura`` (TTS Kokoro do livro
    + refino); ``mpris``: ``SpotifyMpris`` (ou ``None``); ``ultimo_path``: id do último livro
    aberto ("continua o livro" depois de reiniciar)."""

    intents = frozenset(
        i.value
        for i in (
            IntentId.BOOK_READ, IntentId.BOOK_RESUME, IntentId.BOOK_PAUSE, IntentId.BOOK_STOP,
            IntentId.BOOK_BACK, IntentId.BOOK_FORWARD, IntentId.BOOK_CHAPTER, IntentId.BOOK_SPEED,
            IntentId.BOOK_WHERE, IntentId.BOOK_LIST, IntentId.BOOK_TIME,
        )
    )

    def __init__(
        self,
        cfg: ConfigAudiolivro,
        biblioteca: Biblioteca,
        nova_leitura: Callable[[], Any],
        *,
        mpris: Any = None,
        ultimo_path: Path | None = None,
    ) -> None:
        self.cfg = cfg
        self.biblioteca = biblioteca
        self.nova_leitura = nova_leitura
        self.mpris = mpris
        self.ultimo_path = ultimo_path or cfg.estado_dir / "audiolivro-ultimo"
        self.leitura: Any = None
        self.narrada: Narrada | None = None
        self._pausei_musica = False
        self._tarefas: set[asyncio.Task[Any]] = set()

    # -- música (D4) e fim -------------------------------------------------------------------------

    async def _pausar_musica(self) -> None:
        if self.mpris is None or self.cfg.musica != "pausa" or self._pausei_musica:
            return
        try:
            if (await self.mpris.state()).playing:
                await self.mpris.pause()
                self._pausei_musica = True
        except Exception as e:  # noqa: BLE001 — sem Spotify: segue lendo
            log.info("audiolivro: música não pausada (%s)", e)

    async def _voltar_musica(self) -> None:
        if not self._pausei_musica or self.mpris is None:
            return
        self._pausei_musica = False
        try:
            await self.mpris.play()
        except Exception as e:  # noqa: BLE001
            log.info("audiolivro: música não voltou (%s)", e)

    async def encerrar(self) -> None:
        """Fim da leitura (``book.stop`` ou fim do livro): música volta, refino para (D2/D4)."""
        await self._voltar_musica()
        refino = getattr(self.leitura, "refino", None)
        if refino is not None:
            with contextlib.suppress(Exception):
                await refino.parar()

    def _ao_fim(self) -> None:
        t = asyncio.get_running_loop().create_task(self.encerrar())
        self._tarefas.add(t)
        t.add_done_callback(self._tarefas.discard)

    # -- livro -------------------------------------------------------------------------------------

    def _gravar_ultimo(self, livro: Livro) -> None:
        try:
            self.ultimo_path.parent.mkdir(parents=True, exist_ok=True)
            self.ultimo_path.write_text(livro.id, encoding="utf-8")
        except OSError as e:
            log.warning("audiolivro: último livro não gravado (%s)", e)

    def _ultimo(self) -> Livro | None:
        if self.leitura is not None and self.leitura.livro is not None:
            return self.leitura.livro
        try:
            lid = self.ultimo_path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return next((lv for lv in self.biblioteca.livros() if lv.id == lid), None)

    def _abrir(self, livro: Livro) -> None:
        if self.leitura is None or self.leitura.livro is None or self.leitura.livro.id != livro.id:
            if self.leitura is None:
                self.leitura = self.nova_leitura()
            self.leitura.abrir(livro)
            self.narrada = Narrada(self.leitura, self._ao_fim)
            self._gravar_ultimo(livro)

    async def _narrar(self, req: ActionRequest, speech: str = "") -> ActionResult:
        """Começa/retoma a narração ao fim da fala (``ARG_NARRATE``); em call, não (A8.4)."""
        if req.ctx.in_call:
            return ActionResult(ok=False, speech=SAY_IN_CALL)
        await self._pausar_musica()
        alvo = self.narrada
        on = ActionRequest(intent=req.intent, ctx=req.ctx, args={ARG_NARRATE: alvo})
        return ActionResult(ok=True, speech=speech, on_confirm=on, needs_confirmation=False)

    # -- run ---------------------------------------------------------------------------------------

    async def run(self, req: ActionRequest) -> ActionResult:
        iid = req.intent.id
        if iid == IntentId.BOOK_READ.value:
            return await self._read(req)
        if iid == IntentId.BOOK_LIST.value:
            return await self._list()
        if iid == IntentId.BOOK_TIME.value:
            return await self._time(req)
        if iid == IntentId.BOOK_RESUME.value:
            livro = await asyncio.to_thread(self._ultimo)
            if livro is None:
                return ActionResult(ok=False, speech=SAY_NO_BOOK, expression=Expression.CONFUSED)
            self._abrir(livro)
            return await self._narrar(req)
        if self.leitura is None or self.leitura.livro is None:
            if iid == IntentId.BOOK_WHERE.value:
                return await self._where()
            return ActionResult(ok=False, speech=SAY_NO_BOOK, expression=Expression.CONFUSED)
        if iid == IntentId.BOOK_PAUSE.value:
            self.leitura.interrompida()
            return ActionResult(ok=True, speech=SAY_PAUSED)
        if iid == IntentId.BOOK_STOP.value:
            self.leitura.interrompida()
            await self.encerrar()
            self.leitura.marcador.gravar()
            if self.narrada is not None:
                self.narrada.fechada = True
            self.leitura, self.narrada = None, None
            return ActionResult(ok=True, speech=SAY_STOPPED)
        if iid == IntentId.BOOK_WHERE.value:
            return await self._where()
        speech = ""
        if iid == IntentId.BOOK_BACK.value:
            n = _int(req, 0 if "repete" in req.text.lower() or "novo" in req.text.lower() else 1)
            self.leitura.voltar(n or 0)
        elif iid == IntentId.BOOK_FORWARD.value:
            self.leitura.pular(_int(req, 1) or 1)
        elif iid == IntentId.BOOK_CHAPTER.value:
            n = _int(req)
            if n is not None:
                self.leitura.capitulo(n=max(0, n - 1))
            else:
                self.leitura.capitulo(delta=-1 if _texto(req, "text") == "previous" else 1)
        elif iid == IntentId.BOOK_SPEED.value:
            modo = _texto(req, "text")
            atual = self.leitura.posicao.velocidade
            delta = {"slower": -PASSO, "faster": PASSO}.get(modo, 1.0 - atual)
            speech = SAY_SPEED.format(v=_num(self.leitura.velocidade(delta)))
        if not self.cfg.retomar_apos_comando:
            return ActionResult(ok=True, speech=speech or "Feito.")
        return await self._narrar(req, speech)

    async def _read(self, req: ActionRequest) -> ActionResult:
        fala = _texto(req, "query")
        achados = await asyncio.to_thread(self.biblioteca.achar, fala) if fala else []
        if not achados:
            sem_texto = [
                p for p, motivo in self.biblioteca.ignorados.items()
                if motivo == SEM_TEXTO and nota(fala, p.stem) >= NOTA_MINIMA
            ]
            speech = SAY_NO_TEXT if sem_texto else SAY_NOT_FOUND
            return ActionResult(ok=False, speech=speech, expression=Expression.CONFUSED)
        if Biblioteca.ambiguo(achados):
            a, b = achados[0][0].titulo, achados[1][0].titulo
            return ActionResult(ok=True, speech=SAY_WHICH.format(a=a, b=b))
        livro = achados[0][0]
        if req.ctx.in_call:
            return ActionResult(ok=False, speech=SAY_IN_CALL)
        self._abrir(livro)
        return await self._narrar(req, SAY_READING.format(titulo=livro.titulo))

    async def _list(self) -> ActionResult:
        livros = await asyncio.to_thread(self.biblioteca.livros)
        if not livros:
            return ActionResult(ok=True, speech=SAY_NO_BOOKS)
        titulos = sorted(lv.titulo for lv in livros)
        return ActionResult(
            ok=True,
            speech=SAY_LIST.format(n=len(titulos), lista=", ".join(titulos[:5])),
            full_text=SAY_LIST.format(n=len(titulos), lista=", ".join(titulos)),
        )

    async def _where(self) -> ActionResult:
        livro = await asyncio.to_thread(self._ultimo)
        if livro is None:
            return ActionResult(ok=False, speech=SAY_NO_BOOK, expression=Expression.CONFUSED)
        pos = self._posicao(livro)
        return ActionResult(ok=True, speech=SAY_WHERE.format(cap=pos.cap + 1, titulo=livro.titulo))

    def _posicao(self, livro: Livro) -> Posicao:
        if self.leitura is not None and self.leitura.livro is not None and self.leitura.livro.id == livro.id:
            return self.leitura.posicao
        marcador = getattr(self.leitura, "marcador", None)
        if marcador is None:
            from magi.audiolivro.marcador import Marcador

            marcador = Marcador(self.cfg)
        return marcador.posicao(livro.id) or Posicao(0, 0, 0)

    async def _time(self, req: ActionRequest) -> ActionResult:
        fala = _texto(req, "query")
        if fala:
            achados = await asyncio.to_thread(self.biblioteca.achar, fala)
            livro = achados[0][0] if achados else None
        else:
            livro = await asyncio.to_thread(self._ultimo)
        if livro is None:
            return ActionResult(ok=False, speech=SAY_NOT_FOUND if fala else SAY_NO_BOOK,
                                expression=Expression.CONFUSED)
        pos = self._posicao(livro) if not fala else Posicao(0, 0, 0)

        def _estimar() -> Any:
            return custo.estimar(livro, livro.capitulo(pos.cap), pos, self.cfg)

        est = await asyncio.to_thread(_estimar)
        return ActionResult(
            ok=True,
            speech=SAY_TIME.format(
                min=max(1, round(est.minutos_capitulo)), horas=_num(est.minutos_livro_restante / 60)
            ),
        )


def montar(config: Any, providers: Any, *, mpris: Any = None) -> BookHandler:
    """Monta o ``BookHandler`` real (``assemble``): ``Biblioteca`` da pasta, ``Leitura`` com o TTS
    Kokoro do livro (``registry.tts_livro()``) e o refino Qwen local (D2). Construir não lê a pasta
    nem liga o container."""
    from magi.audiolivro import marcas_llm
    from magi.audiolivro.config import audiolivro_config, idioma_dela, tarefa_marca, voz_dela
    from magi.audiolivro.leitor import Leitura
    from magi.audiolivro.marcador import Marcador

    cfg = audiolivro_config(config)
    marcador = Marcador(cfg)

    def nova_leitura() -> Leitura:
        tts = providers.tts_livro() if providers is not None else None
        refino = None
        tarefa = tarefa_marca(config, cfg)
        if tarefa is not None:
            refino = marcas_llm.criar(config, cfg, ModeloQwen(cfg.qwen_url, tarefa.model), _runtime(cfg))
        return Leitura(cfg, marcador, voz_dela=voz_dela(config), idioma_dela=idioma_dela(config),
                       tts=tts, refino=refino)

    return BookHandler(cfg, Biblioteca(cfg), nova_leitura, mpris=mpris)


def _runtime(cfg: ConfigAudiolivro) -> Any:
    from magi.learning.runtime import ContainerRuntime, NullRuntime

    if not cfg.qwen_container:
        return NullRuntime()
    return ContainerRuntime(cfg.qwen_container, cfg.qwen_url, start_timeout_s=float(cfg.qwen_start_timeout_s))


class ModeloQwen:
    """``complete(system, user, schema)`` no Ollama local (``/v1/chat/completions``, JSON). Sem
    rede externa nem custo (D2)."""

    def __init__(self, url: str, model: str, *, timeout_s: float = 60.0) -> None:
        self.url = url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s

    async def complete(self, system: str, user: str, schema: dict[str, Any]) -> Any:
        import json

        import httpx

        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            r = await client.post(f"{self.url}/v1/chat/completions", json=body)
            r.raise_for_status()
            return json.loads(r.json()["choices"][0]["message"]["content"])
