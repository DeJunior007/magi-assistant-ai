"""Spike S1 — bancada dos modelos pesados da Ayanami (tarefa Y0.7 de ``specs/ayanami-central``).

Mede, sem rede, os três modelos da fila ``lenta``/``ayanami-voz`` (spec §5.4–§5.6, §17 linha S1):

  kokoro    Kokoro int8 ``pf_dora`` ``lang="pt-br"``: RTF por frase em 10 frases pt-BR (p50/p90/total)
  whisper   faster-whisper ``small`` int8 ``cpu_threads=4`` ``language="pt"``: RTF e RAM de pico
            num áudio de 5 min (fala pt-BR sintetizada pelo Kokoro, ou ``--audio``)
  embed     fastembed ``intfloat/multilingual-e5-small`` (384 dim): vazão em lotes de 64
  all       tudo acima (padrão)

Cada etapa roda num processo filho próprio (``spawn``), então a RAM de pico (``ru_maxrss``) é só
dela. No fim imprime uma tabela Markdown pronta para ``docs/perf/ayanami-s1.md``.

Modelos: lidos de ``--dir`` (padrão ``~/.cache/magi/ayanami-s1``) **sem rede**. Só com
``--modelos <dir>`` o script baixa o que faltar, e só para dentro de ``<dir>``:

  <dir>/kokoro/kokoro-v1.0.int8.onnx + voices-v1.0.bin   (release model-files-v1.0 do kokoro-onnx)
  <dir>/faster-whisper-small/                             (Systran/faster-whisper-small)
  <dir>/fastembed/                                        (cache do fastembed, e5-small)

Faltou modelo (e sem ``--modelos``): a etapa sai como "falta", as outras rodam, e o código de
saída é 2. ``--kokoro-onnx``/``--kokoro-voices`` apontam outro arquivo (ex.: o fp32 do PC em
``~/.cache/magi/kokoro``) — a tabela diz qual foi usado.

Uso:  uv run --extra ayanami-ml python spikes/ayanami_s1_bancada.py all [--modelos DIR] [--curto]
"""

from __future__ import annotations

import argparse
import multiprocessing as mp
import os
import platform
import resource
import statistics
import sys
import tempfile
import time
import urllib.request
import wave
from pathlib import Path
from typing import Any

FRASES = [
    "Bom dia, Pedro. Hoje o céu está limpo e a máxima deve chegar a vinte e oito graus.",
    "Terminei de transcrever o áudio da reunião; o texto já está na sua caixa de tarefas.",
    "A televisão da sala está desligada. Quer que eu ligue e abra o YouTube?",
    "Encontrei três notícias novas sobre o lançamento que você acompanha.",
    "O backup da madrugada terminou sem erros e levou quatro minutos.",
    "Não consegui falar com a OpenAI agora, então vou responder só por texto.",
    "Lembrete: a consulta no dentista é amanhã às dez e meia da manhã.",
    "A fila lenta está com duas tarefas esperando e nenhuma em andamento.",
    "Você pediu para eu avisar quando o preço baixasse; baixou doze por cento.",
    "Até mais tarde. Se precisar de mim, é só chamar pelo celular.",
]
KOKORO_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
KOKORO_ONNX, KOKORO_VOICES = "kokoro-v1.0.int8.onnx", "voices-v1.0.bin"
WHISPER_DIR = "faster-whisper-small"
E5 = "intfloat/multilingual-e5-small"
E5_DIM = 384
TAXA_KOKORO = 24000


class FaltaModelo(Exception):
    """Modelo ausente em disco e download não autorizado (sem ``--modelos``)."""


def _pico_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # Linux: KiB


def _pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    if len(xs) == 1:
        return xs[0]
    return statistics.quantiles(xs, n=100, method="inclusive")[int(p) - 1]


def _baixar(url: str, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(destino.suffix + ".parcial")
    print(f"  baixando {url} → {destino}", file=sys.stderr)
    urllib.request.urlretrieve(url, tmp)  # noqa: S310 (URL fixa do release)
    tmp.rename(destino)


# --- Kokoro ------------------------------------------------------------------------------------


def _kokoro_arquivos(a: dict[str, Any]) -> tuple[Path, Path]:
    base = Path(a["dir"]) / "kokoro"
    onnx = Path(a["kokoro_onnx"]).expanduser() if a["kokoro_onnx"] else base / KOKORO_ONNX
    voices = Path(a["kokoro_voices"]).expanduser() if a["kokoro_voices"] else base / KOKORO_VOICES
    for arq, nome in ((onnx, KOKORO_ONNX), (voices, KOKORO_VOICES)):
        if not arq.exists():
            if not a["baixar"] or arq.parent != base:
                raise FaltaModelo(f"kokoro: falta {arq}")
            _baixar(KOKORO_URL + nome, arq)
    return onnx, voices


def etapa_kokoro(a: dict[str, Any]) -> dict[str, Any]:
    import numpy as np
    import onnxruntime as rt
    from kokoro_onnx import Kokoro

    onnx, voices = _kokoro_arquivos(a)
    t0 = time.perf_counter()
    opts = rt.SessionOptions()
    opts.intra_op_num_threads = a["threads_voz"]
    opts.inter_op_num_threads = 1
    sess = rt.InferenceSession(str(onnx), sess_options=opts, providers=["CPUExecutionProvider"])
    modelo = Kokoro.from_session(sess, str(voices))
    modelo.create("Olá.", voice="pf_dora", speed=1.0, lang="pt-br")  # aquecimento
    carga = time.perf_counter() - t0

    rtfs, durs, gerado = [], [], []
    frases = FRASES[:3] if a["curto"] else FRASES
    for frase in frases:
        t = time.perf_counter()
        audio, taxa = modelo.create(frase, voice="pf_dora", speed=1.0, lang="pt-br")
        gasto = time.perf_counter() - t
        dur = len(audio) / taxa
        rtfs.append(gasto / dur)
        durs.append(dur)
        gerado.append(np.asarray(audio, dtype=np.float32))
    pcm = np.concatenate([np.concatenate([g, np.zeros(taxa // 2, np.float32)]) for g in gerado])
    _grava_wav(Path(a["tmp"]) / "frases.wav", pcm, taxa)
    return {
        "modelo": onnx.name,
        "threads": a["threads_voz"],
        "carga_s": carga,
        "n": len(rtfs),
        "audio_s": sum(durs),
        "rtf_p50": _pct(rtfs, 50),
        "rtf_p90": _pct(rtfs, 90),
        "rtf_total": sum(r * d for r, d in zip(rtfs, durs, strict=True)) / sum(durs),
        "ram_mb": _pico_mb(),
    }


def _grava_wav(caminho: Path, pcm: Any, taxa: int) -> None:
    import numpy as np

    s16 = (np.clip(pcm, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(str(caminho), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes(s16.tobytes())


def _audio_longo(a: dict[str, Any]) -> tuple[Path, float]:
    """Repete a fala do Kokoro até ``--minutos``; ou usa ``--audio``."""
    import numpy as np

    if a["audio"]:
        caminho = Path(a["audio"]).expanduser()
        with wave.open(str(caminho)) as w:
            return caminho, w.getnframes() / w.getframerate()
    fonte = Path(a["tmp"]) / "frases.wav"
    if not fonte.exists():
        raise FaltaModelo("whisper: sem áudio (rode com kokoro ou passe --audio)")
    with wave.open(str(fonte)) as w:
        taxa = w.getframerate()
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    alvo = int(a["minutos"] * 60 * taxa)
    longo = np.tile(pcm, alvo // len(pcm) + 1)[:alvo]
    caminho = Path(a["tmp"]) / "longo.wav"
    with wave.open(str(caminho), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes(longo.tobytes())
    return caminho, alvo / taxa


# --- faster-whisper ----------------------------------------------------------------------------


def etapa_whisper(a: dict[str, Any]) -> dict[str, Any]:
    from faster_whisper import WhisperModel, download_model

    pasta = Path(a["dir"]) / WHISPER_DIR
    if not (pasta / "model.bin").exists():
        if not a["baixar"]:
            raise FaltaModelo(f"whisper: falta {pasta}/model.bin")
        download_model("small", output_dir=str(pasta))
    audio, dur = _audio_longo(a)
    t0 = time.perf_counter()
    modelo = WhisperModel(str(pasta), device="cpu", compute_type="int8", cpu_threads=4,
                          local_files_only=True)
    carga = time.perf_counter() - t0
    t = time.perf_counter()
    segs, _info = modelo.transcribe(str(audio), language="pt")
    texto = " ".join(s.text.strip() for s in segs)  # o gerador é preguiçoso: consome aqui
    gasto = time.perf_counter() - t
    return {
        "modelo": "small int8",
        "threads": 4,
        "carga_s": carga,
        "audio_s": dur,
        "gasto_s": gasto,
        "rtf": gasto / dur,
        "ram_mb": _pico_mb(),
        "amostra": texto[:90],
    }


# --- fastembed ---------------------------------------------------------------------------------


def etapa_embed(a: dict[str, Any]) -> dict[str, Any]:
    from fastembed import TextEmbedding
    from fastembed.common.model_description import ModelSource, PoolingType

    # O fastembed 0.9.0 não traz o e5-small na lista (só o e5-large): registra como modelo próprio.
    if not any(m["model"] == E5 for m in TextEmbedding.list_supported_models()):
        TextEmbedding.add_custom_model(model=E5, pooling=PoolingType.MEAN, normalization=True,
                                       sources=ModelSource(hf=E5), dim=E5_DIM,
                                       model_file="onnx/model.onnx")
    cache = Path(a["dir"]) / "fastembed"
    if not a["baixar"]:
        os.environ["HF_HUB_OFFLINE"] = "1"
        if not cache.exists():
            raise FaltaModelo(f"embed: falta {cache}")
    t0 = time.perf_counter()
    try:
        modelo = TextEmbedding(E5, cache_dir=str(cache), threads=a["threads_embed"],
                               local_files_only=not a["baixar"])
    except Exception as exc:  # fastembed embrulha o "não achei" em erros variados
        if a["baixar"]:
            raise
        raise FaltaModelo(f"embed: {E5} não está em {cache} ({type(exc).__name__})") from exc
    carga = time.perf_counter() - t0
    lotes = 4 if a["curto"] else 16
    textos = [f"passage: {FRASES[i % len(FRASES)]} (item {i})" for i in range(64 * lotes)]
    list(modelo.embed(textos[:64], batch_size=64))  # aquecimento
    t = time.perf_counter()
    vetores = list(modelo.embed(textos, batch_size=64))
    gasto = time.perf_counter() - t
    dim = len(vetores[0])
    return {
        "modelo": "e5-small",
        "threads": a["threads_embed"],
        "carga_s": carga,
        "textos": len(textos),
        "dim": dim,
        "vazao": len(textos) / gasto,
        "ms_lote": gasto / lotes * 1000,
        "ram_mb": _pico_mb(),
    }


ETAPAS = {"kokoro": etapa_kokoro, "whisper": etapa_whisper, "embed": etapa_embed}


def _filho(nome: str, a: dict[str, Any], fila: Any) -> None:
    try:
        fila.put(("ok", ETAPAS[nome](a)))
    except FaltaModelo as exc:
        fila.put(("falta", str(exc)))
    except Exception as exc:  # noqa: BLE001 — a bancada relata e segue
        fila.put(("erro", f"{type(exc).__name__}: {exc}"))


def rodar(nome: str, a: dict[str, Any]) -> tuple[str, Any]:
    ctx = mp.get_context("spawn")
    fila = ctx.Queue()
    p = ctx.Process(target=_filho, args=(nome, a, fila))
    p.start()
    p.join()
    return fila.get() if not fila.empty() else ("erro", f"processo saiu com {p.exitcode}")


def tabela(res: dict[str, tuple[str, Any]], a: dict[str, Any]) -> str:
    linhas = ["| Modelo | Threads | Carga | Medida | Resultado | Meta | RAM pico |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for nome, (st, r) in res.items():
        if st != "ok":
            linhas.append(f"| {nome} | — | — | — | **{st}**: {r} | — | — |")
            continue
        if nome == "kokoro":
            med = f"RTF em {r['n']} frases ({r['audio_s']:.0f} s de fala)"
            val = f"p50 {r['rtf_p50']:.3f} · p90 {r['rtf_p90']:.3f} · total {r['rtf_total']:.3f}"
            meta = "RTF ≤ 0,5"
        elif nome == "whisper":
            med = f"RTF em {r['audio_s'] / 60:.1f} min ({r['gasto_s']:.0f} s)"
            val, meta = f"{r['rtf']:.3f}", "RTF ≤ 0,4; RAM ≤ 2 GB"
        else:
            med = f"vazão, {r['textos']} textos em lotes de 64, dim {r['dim']}"
            val, meta = f"{r['vazao']:.0f} textos/s · {r['ms_lote']:.0f} ms/lote", "—"
        modelo = r["modelo"]
        linhas.append(f"| {nome} (`{modelo}`) | {r['threads']} | {r['carga_s']:.1f} s | {med} "
                      f"| {val} | {meta} | {r['ram_mb']:.0f} MB |")
    return "\n".join(linhas)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("etapa", nargs="?", default="all", choices=[*ETAPAS, "all"])
    ap.add_argument("--dir", default="~/.cache/magi/ayanami-s1", help="onde ler os modelos")
    ap.add_argument("--modelos", help="baixa o que faltar para este diretório (e lê dele)")
    ap.add_argument("--kokoro-onnx", help="outro .onnx do Kokoro (ex.: o fp32 do PC)")
    ap.add_argument("--kokoro-voices", help="outro voices-v1.0.bin")
    ap.add_argument("--audio", help="WAV para o whisper em vez da fala sintetizada")
    ap.add_argument("--minutos", type=float, default=5.0, help="duração do áudio do whisper")
    ap.add_argument("--threads-voz", type=int, default=2, help="cpus do ayanami-voz (design §4.4)")
    ap.add_argument("--threads-embed", type=int, default=4, help="cpus do worker-lento")
    ap.add_argument("--curto", action="store_true", help="3 frases, 1 min de áudio, 4 lotes")
    ns = ap.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="ayanami-s1-") as tmp:
        a = {
            "dir": str(Path(ns.modelos or ns.dir).expanduser()),
            "baixar": bool(ns.modelos),
            "kokoro_onnx": ns.kokoro_onnx,
            "kokoro_voices": ns.kokoro_voices,
            "audio": ns.audio,
            "minutos": 1.0 if ns.curto and ns.minutos == 5.0 else ns.minutos,
            "threads_voz": ns.threads_voz,
            "threads_embed": ns.threads_embed,
            "curto": ns.curto,
            "tmp": tmp,
        }
        nomes = list(ETAPAS) if ns.etapa == "all" else [ns.etapa]
        if "whisper" in nomes and "kokoro" not in nomes and not ns.audio:
            nomes.insert(0, "kokoro")  # o whisper precisa da fala sintetizada
        res: dict[str, tuple[str, Any]] = {}
        for nome in nomes:
            print(f"[{nome}] rodando…", file=sys.stderr, flush=True)
            res[nome] = rodar(nome, a)
            print(f"[{nome}] {res[nome][0]}", file=sys.stderr, flush=True)

    cpu = platform.processor() or platform.machine()
    try:
        cpu = next(ln.split(":", 1)[1].strip() for ln in Path("/proc/cpuinfo").read_text().splitlines()
                   if ln.startswith("model name"))
    except (OSError, StopIteration):
        pass
    print(f"\nMáquina: {cpu}, {os.cpu_count()} threads lógicas; Python {platform.python_version()}")
    print(tabela(res, a))
    if res.get("whisper", ("",))[0] == "ok":
        print(f"\nAmostra do whisper: “{res['whisper'][1]['amostra']}…”")
    return 2 if any(st == "falta" for st, _ in res.values()) else (
        1 if any(st == "erro" for st, _ in res.values()) else 0)


if __name__ == "__main__":
    sys.exit(main())
