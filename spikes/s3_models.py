"""Spike S3 — modelos da OpenAI e do Gemini (tarefa 0.6).

Mede latência (mediana/p90 em N repetições), custo estimado e qualidade de:

  stt      transcrição PT-BR (fala real, frase "enrolada", nomes de jogos com/sem dica)
  tts      TTS feminina: tempo até o primeiro byte (streaming) e UMA amostra por voz em
           ~/Music/magi-vozes/<modelo>-<voz>.wav
  agent    modelos de chat com tool calling (cultura pop + chamada de ferramenta)
  gemini   classificação de notícias em JSON, embeddings 768d (Gemini) e 1536d (OpenAI)
  search   pesquisa com Google Search grounding (Gemini) e web_search (OpenAI)
  all      tudo acima

Usa os adaptadores do projeto (``Registry`` com config temporária); chaves ``openai-1`` e
``gemini-1`` vêm do keyring. Para no teto de gasto da OpenAI (``--cap``, padrão US$ 0,30).

Uso:  uv run python spikes/s3_models.py all --reps 4 --out /tmp/s3.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
import wave
from pathlib import Path
from typing import Any

from magi.common.config import parse_config
from magi.common.contracts import (
    BudgetStatus,
    ChatMessage,
    PcmFormat,
    ProviderTask,
    ToolSpec,
    Usage,
)
from magi.providers.registry import Registry

ROOT = Path(__file__).resolve().parents[1]
FALA = ROOT / "tests/satellite/data/fala_ptbr.wav"
VOZES = Path.home() / "Music/magi-vozes"
TTS_FMT = PcmFormat(rate=24_000, width=2, channels=1)

# Preços oficiais (developers.openai.com/api/docs/pricing, acessado em 2026-10-02).
STT_USD_MIN = {
    "whisper-1": 0.006,
    "gpt-4o-transcribe": 0.006,
    "gpt-transcribe": 0.0045,
    "gpt-4o-mini-transcribe": 0.003,
}
CHAT_USD_M = {  # (entrada, saída) por 1M tokens
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-5.4-nano": (0.20, 1.25),
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5.6-luna": (0.20, 1.20),
}
TTS_USD_CHAR = {"tts-1": 15e-6, "tts-1-hd": 30e-6}
MINI_TTS_TEXT_USD_M = 0.60  # gpt-4o-mini-tts: texto de entrada por 1M tokens
MINI_TTS_USD_MIN = 0.015  # gpt-4o-mini-tts: estimativa oficial por minuto de áudio
EMB_USD_M = {"text-embedding-3-small": 0.02}

STT_MODELS = ["whisper-1", "gpt-4o-mini-transcribe", "gpt-transcribe", "gpt-4o-transcribe"]
TTS_VOICES = {
    "gpt-4o-mini-tts": ["alloy", "coral", "marin", "nova", "sage", "shimmer"],
    "tts-1-hd": ["alloy", "coral", "nova", "sage", "shimmer"],
    "tts-1": ["alloy", "coral", "nova", "sage", "shimmer"],
}
TTS_INSTRUCTIONS = (
    "Fale em português do Brasil com sotaque brasileiro natural. Voz feminina jovem, animada e "
    "brincalhona, como uma amiga gamer conversando no Discord."
)
PERSONA = (
    "Opa! Abrindo Dead Cells. Bora que hoje a gente zera esse boss. "
    "Ih, morreu de novo pro primeiro chefe? Relaxa, eu não conto pra ninguém... só pro chat inteiro."
)
TTFB_TEXT = "Opa! Abrindo Dead Cells."
AGENT_MODELS = ["gpt-4.1-mini", "gpt-5.4-nano", "gpt-5.4-mini", "gpt-5.6-luna"]
# Bug do adaptador: OpenAIBackend.chat não repassa `reasoning_effort`; o gpt-5.6-luna recusa tools
# sem reasoning_effort="none" no /v1/chat/completions. Contorno: chamada direta pelo SDK.
DIRECT_REASONING_NONE = {"gpt-5.6-luna"}
GEMINI_NEWS = ["gemini-3.5-flash-lite", "gemini-flash-lite-latest", "gemini-3.8-flash"]
GEMINI_EMB = ["gemini-embedding-001", "gemini-embedding-2"]
# Google Search grounding: "Not available" na cota gratuita dos Gemini 3.x (429 com limite 0);
# o gemini-2.5-flash ainda tem grounding gratuito.
GEMINI_SEARCH = ["gemini-2.5-flash"]
OPENAI_SEARCH = ["gpt-5.4-mini"]
WEB_SEARCH_USD_CALL = 0.01  # US$ 10 / 1k chamadas da ferramenta web_search
SEARCH_Q = "Qual a data de lançamento mais recente anunciada para GTA 6?"

# Áudios de teste: (id, texto para o TTS gerar, velocidade, dica de vocabulário)
GAMES_HINT = "Hollow Knight: Silksong, Baldur's Gate 3, Elden Ring Nightreign, Dead Cells, Hades II, Magui"
STT_CASES = [
    (
        "enrolada",
        "Ô Magui, cê num tá vendo que eu tô morrendo aqui, pô? Abre aí o negócio do mapa, rapidão!",
        1.35,
        "",
    ),
    (
        "jogos",
        "Magui, abre o Hollow Knight Silksong e depois procura dica de Baldur's Gate 3 e de Elden Ring "
        "Nightreign.",
        1.0,
        "",
    ),
    ("jogos+dica", None, 1.0, GAMES_HINT),
]


class SpendCapError(RuntimeError):
    pass


class SpikeBudget:
    """Budget falso: só registra o uso (o custo real é estimado pelo spike)."""

    def __init__(self) -> None:
        self.usages: list[Usage] = []

    async def ensure_allowed(self, task: ProviderTask) -> None:
        return None

    async def record(self, usage: Usage) -> None:
        self.usages.append(usage)

    async def status(self) -> BudgetStatus:
        return BudgetStatus(0.0, 5.0)


class Spike:
    def __init__(self, reps: int, cap: float) -> None:
        self.reps = reps
        self.cap = cap
        self.openai_usd = 0.0
        self.results: dict[str, list[dict[str, Any]]] = {}
        self.bugs: list[str] = []

    # -- infraestrutura -------------------------------------------------------------------

    def registry(self, task: str, provider: str, model: str, **opts: Any) -> Registry:
        data = {
            "providers": {
                "openai": {"keys": ["openai-1"], "timeout_s": 60.0},
                "gemini": {"keys": ["gemini-1"], "free_tier": True},
            },
            "tasks": {task: {"provider": provider, "model": model, **opts}},
        }
        return Registry(parse_config(data), SpikeBudget())

    def spend(self, usd: float) -> None:
        self.openai_usd += usd
        if self.openai_usd > self.cap:
            raise SpendCapError(f"teto do spike estourado: US$ {self.openai_usd:.4f}")

    def check(self, est: float) -> None:
        if self.openai_usd + est > self.cap:
            raise SpendCapError(f"próxima chamada passaria do teto (gasto US$ {self.openai_usd:.4f})")

    def add(self, section: str, row: dict[str, Any]) -> None:
        self.results.setdefault(section, []).append(row)
        lat = row.get("lat_s") or []
        stats = f"med {stats_ms(lat)}" if lat else ""
        print(f"[{section}] {row.get('model')} {row.get('case', '')} {stats} {row.get('note', '')}"[:300])

    # -- STT ------------------------------------------------------------------------------

    async def make_stt_audio(self) -> dict[str, tuple[bytes, PcmFormat, str, str]]:
        """Gera as falas de teste com tts-1/nova (barato) e lê a fala real do repositório."""
        audios: dict[str, tuple[bytes, PcmFormat, str, str]] = {}
        with wave.open(str(FALA)) as w:
            audios["fala_real"] = (
                w.readframes(w.getnframes()),
                PcmFormat(w.getframerate(), w.getsampwidth(), w.getnchannels()),
                "",
                "(desconhecido)",
            )
        last_pcm = b""
        for cid, text, speed, hint in STT_CASES:
            if text is None:
                audios[cid] = (last_pcm, TTS_FMT, hint, audios["jogos"][3])
                continue
            self.check(len(text) * 15e-6)
            tts = self.registry("tts", "openai", "tts-1", voice="nova", speed=speed).tts()
            pcm = b"".join([c async for c in tts.synthesize(text, personal=False)])
            self.spend(len(text) * 15e-6)
            audios[cid] = (pcm, TTS_FMT, hint, text)
            last_pcm = pcm
        return audios

    async def stt(self) -> None:
        audios = await self.make_stt_audio()
        for model in STT_MODELS:
            stt = self.registry("stt", "openai", model).stt()
            for cid, (pcm, fmt, hint, ref) in audios.items():
                secs = len(pcm) / (fmt.rate * fmt.width * fmt.channels)
                cost = secs / 60 * STT_USD_MIN[model]
                lats, texts = [], []
                for _ in range(self.reps):
                    self.check(cost)
                    t0 = time.perf_counter()
                    tr = await stt.transcribe(pcm, fmt, hint=hint, language="pt", personal=False)
                    lats.append(time.perf_counter() - t0)
                    self.spend(cost)
                    texts.append(tr.heard)
                self.add(
                    "stt",
                    {
                        "model": model,
                        "case": cid,
                        "audio_s": round(secs, 2),
                        "lat_s": lats,
                        "usd": cost,
                        "ref": ref,
                        "texts": sorted(set(texts)),
                    },
                )

    # -- TTS ------------------------------------------------------------------------------

    def tts_cost(self, model: str, text: str, secs: float) -> float:
        if model in TTS_USD_CHAR:
            return len(text) * TTS_USD_CHAR[model]
        return len(text) / 4 * MINI_TTS_TEXT_USD_M / 1e6 + secs / 60 * MINI_TTS_USD_MIN

    def tts_opts(self, model: str, voice: str) -> dict[str, Any]:
        opts: dict[str, Any] = {"voice": voice}
        if model == "gpt-4o-mini-tts":
            opts["instructions"] = TTS_INSTRUCTIONS
        return opts

    async def tts(self) -> None:
        VOZES.mkdir(parents=True, exist_ok=True)
        for model, voices in TTS_VOICES.items():
            # Tempo até o primeiro byte, com a 1ª voz da lista.
            tts = self.registry("tts", "openai", model, **self.tts_opts(model, voices[1])).tts()
            ttfb, total = [], []
            secs = 0.0
            for _ in range(self.reps):
                self.check(self.tts_cost(model, TTFB_TEXT, 3.0))
                t0 = time.perf_counter()
                first = None
                n = 0
                async for chunk in tts.synthesize(TTFB_TEXT, personal=False):
                    first = first or time.perf_counter() - t0
                    n += len(chunk)
                total.append(time.perf_counter() - t0)
                ttfb.append(first or 0.0)
                secs = n / (TTS_FMT.rate * TTS_FMT.width)
                self.spend(self.tts_cost(model, TTFB_TEXT, secs))
            self.add(
                "tts_ttfb",
                {
                    "model": model,
                    "voice": voices[1],
                    "lat_s": ttfb,
                    "total_s": total,
                    "audio_s": round(secs, 2),
                    "usd": self.tts_cost(model, TTFB_TEXT, secs),
                },
            )
            # Uma amostra por voz com a frase de persona.
            for voice in voices:
                tts = self.registry("tts", "openai", model, **self.tts_opts(model, voice)).tts()
                self.check(self.tts_cost(model, PERSONA, 12.0))
                pcm = b"".join([c async for c in tts.synthesize(PERSONA, personal=False)])
                secs = len(pcm) / (TTS_FMT.rate * TTS_FMT.width)
                self.spend(self.tts_cost(model, PERSONA, secs))
                path = VOZES / f"{model}-{voice}.wav"
                with wave.open(str(path), "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(TTS_FMT.rate)
                    w.writeframes(pcm)
                self.add(
                    "tts_sample",
                    {
                        "model": model,
                        "voice": voice,
                        "file": str(path),
                        "audio_s": round(secs, 2),
                        "usd": self.tts_cost(model, PERSONA, secs),
                    },
                )

    # -- agente ---------------------------------------------------------------------------

    async def agent(self) -> None:
        system = ChatMessage(
            "system",
            "Você é a Magui, assistente gamer brasileira, bem-humorada. "
            "Responda em PT-BR, curto (até 2 frases), para ser falado em voz alta.",
        )
        tools = [
            ToolSpec(
                "open_game",
                "Abre um jogo instalado na Steam pelo nome.",
                {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
            )
        ]
        prompts = {
            "cultura_pop": "Quem criou Metal Gear Solid e qual o jogo mais recente dele?",
            "ferramenta": "Abre o Dead Cells pra mim.",
        }
        for model in AGENT_MODELS:
            chat = self.registry("agent", "openai", model).chat()
            pin, pout = CHAT_USD_M[model]
            for case, prompt in prompts.items():
                lats, outs, costs = [], [], []
                for _ in range(self.reps):
                    self.check(0.002)
                    t0 = time.perf_counter()
                    try:
                        msgs = [system, ChatMessage("user", prompt)]
                        if model in DIRECT_REASONING_NONE:
                            reply = await _direct_chat(model, msgs, tools)
                        else:
                            reply = await chat.chat(msgs, tools=tools, personal=False)
                    except Exception as e:  # noqa: BLE001 — o spike anota e segue
                        self.add("agent", {"model": model, "case": case, "note": f"ERRO {e!r}"[:300]})
                        break
                    lats.append(time.perf_counter() - t0)
                    u = reply.usage
                    cost = (u.input_units * pin + u.output_units * pout) / 1e6 if u else 0.0
                    self.spend(cost)
                    costs.append(cost)
                    calls = [f"{c.name}({dict(c.arguments)})" for c in reply.tool_calls]
                    outs.append(reply.text or " ".join(calls))
                if lats:
                    self.add(
                        "agent",
                        {
                            "model": model,
                            "case": case,
                            "lat_s": lats,
                            "usd": statistics.mean(costs),
                            "texts": outs[:2],
                        },
                    )

    # -- Gemini (cota gratuita) + embeddings OpenAI -----------------------------------------

    async def gemini(self) -> None:
        news_sys = ChatMessage(
            "system",
            'Classifique a notícia. Responda só JSON: {"categoria": '
            '"lancamento|atualizacao|promocao|esports|industria|outro", '
            '"relevancia": 0-1, "jogos": [nomes]}',
        )
        news = ChatMessage(
            "user",
            "Team Cherry anuncia DLC gratuita de Hollow Knight: Silksong com nova área "
            "e chefe, chegando em novembro para PC e consoles.",
        )
        for model in GEMINI_NEWS:
            await self._gemini_loop(
                "news",
                model,
                lambda r, m=model: r.chat(ProviderTask.NEWS).chat(
                    [news_sys, news], json_mode=True, personal=False
                ),
                lambda rep: _json_note(rep.text),
            )
        for model in GEMINI_EMB:
            await self._gemini_loop(
                "news",
                "gemini-3.5-flash-lite",
                lambda r: r.embeddings(ProviderTask.NEWS).embed(
                    ["Silksong ganha DLC", "Promoção de Hades II"], personal=False
                ),
                lambda vecs: f"dims={[len(v) for v in vecs]}",
                section="gemini_emb",
                label=model,
                embedding_model=model,
                dimensions=768,
            )
        # Embeddings da OpenAI para [tasks.embeddings] (memória, 1536d).
        emb = self.registry("embeddings", "openai", "text-embedding-3-small", dimensions=1536).embeddings()
        lats = []
        for _ in range(self.reps):
            t0 = time.perf_counter()
            vecs = await emb.embed(["o usuário prefere jogos de terror"], personal=False)
            lats.append(time.perf_counter() - t0)
            self.spend(10 * EMB_USD_M["text-embedding-3-small"] / 1e6)
        self.add(
            "openai_emb",
            {"model": "text-embedding-3-small", "lat_s": lats, "usd": 2e-7, "note": f"dims={len(vecs[0])}"},
        )

    async def search(self) -> None:
        for model in GEMINI_SEARCH:
            await self._gemini_loop(
                "search",
                model,
                lambda r: r.search().search(SEARCH_Q, personal=False),
                lambda res: f"fontes={len(res.sources)} {res.answer[:160]!r}",
            )
        for model in OPENAI_SEARCH:
            srch = self.registry("search", "openai", model).search()
            pin, pout = CHAT_USD_M[model]
            lats, notes, costs = [], [], []
            for _ in range(self.reps):
                self.check(0.03)
                t0 = time.perf_counter()
                res = await srch.search(SEARCH_Q, personal=False)
                lats.append(time.perf_counter() - t0)
                u = res.usage
                cost = WEB_SEARCH_USD_CALL + (
                    (u.input_units * pin + u.output_units * pout) / 1e6 if u else 0.0
                )
                self.spend(cost)
                costs.append(cost)
                notes.append(
                    f"fontes={len(res.sources)} tokens={u and (u.input_units, u.output_units)} "
                    f"{res.answer[:160]!r}"
                )
            self.add(
                "openai_search",
                {"model": model, "lat_s": lats, "usd": statistics.mean(costs), "texts": notes[:3]},
            )

    async def _gemini_loop(
        self,
        task: str,
        model: str,
        call: Any,
        note: Any,
        *,
        section: str | None = None,
        label: str | None = None,
        **opts: Any,
    ) -> None:
        section = section or f"gemini_{task}"
        reg = self.registry(task, "gemini", model, **opts)
        lats, notes = [], []
        for _ in range(self.reps):
            t0 = time.perf_counter()
            try:
                res = await call(reg)
            except Exception as e:  # noqa: BLE001
                notes.append(f"ERRO {type(e).__name__}: {e}"[:300])
                break
            lats.append(time.perf_counter() - t0)
            notes.append(note(res))
            await asyncio.sleep(2.0)  # cota gratuita: poucas chamadas por minuto
        self.add(section, {"model": label or model, "lat_s": lats, "usd": 0.0, "texts": notes[:3]})


async def _direct_chat(model: str, messages: list[ChatMessage], tools: list[ToolSpec]) -> Any:
    """Contorno do bug de reasoning_effort: reusa os conversores do adaptador e chama o SDK."""
    import openai

    from magi.common.secrets import require_secret
    from magi.providers.base import CallCtx
    from magi.providers.openai_provider import _messages, _reply, _tools

    client = openai.AsyncOpenAI(api_key=require_secret("openai-1"), max_retries=0)
    resp = await client.chat.completions.create(
        model=model, messages=_messages(messages), tools=_tools(tools), reasoning_effort="none"
    )
    return _reply(resp, CallCtx(provider="openai", task=ProviderTask.AGENT, model=model, options={}))


def _json_note(text: str) -> str:
    try:
        return "JSON ok " + json.dumps(json.loads(text), ensure_ascii=False)[:160]
    except ValueError:
        return f"JSON inválido: {text[:120]!r}"


def stats_ms(lat: list[float]) -> str:
    if not lat:
        return "-"
    s = sorted(lat)
    p90 = s[min(len(s) - 1, round(0.9 * (len(s) - 1)))]
    return f"{statistics.median(s) * 1000:.0f}/{p90 * 1000:.0f} ms"


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=["stt", "tts", "agent", "gemini", "search", "all"])
    ap.add_argument("--reps", type=int, default=4)
    ap.add_argument("--cap", type=float, default=0.30, help="teto de gasto na OpenAI (USD)")
    ap.add_argument("--out", type=Path, default=None, help="grava os resultados em JSON")
    args = ap.parse_args()
    spike = Spike(args.reps, args.cap)
    steps = ["stt", "tts", "agent", "gemini", "search"] if args.what == "all" else [args.what]
    try:
        for step in steps:
            await getattr(spike, step)()
    finally:
        print(f"Gasto estimado na OpenAI: US$ {spike.openai_usd:.4f}")
        if args.out:
            args.out.write_text(
                json.dumps({"openai_usd": spike.openai_usd, **spike.results}, ensure_ascii=False, indent=1)
            )


if __name__ == "__main__":
    asyncio.run(main())
