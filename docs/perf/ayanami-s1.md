# Spike S1 — bancada dos modelos pesados da Ayanami

Tarefas Y0.7 (script + linha de base do PC) e Y0.8 (node 2) de `specs/ayanami-central/tasks.md`.
Script: `spikes/ayanami_s1_bancada.py` (cada etapa num processo filho; RAM de pico = `ru_maxrss`
do filho). Metas da spec §17, linha S1: Kokoro RTF ≤ 0,5 (§5.4); faster-whisper `small` int8
RTF ≤ 0,4 e RAM ≤ 2 GB (§5.5); vazão do e5-small (§5.6).

```sh
# sem rede: lê de ~/.cache/magi/ayanami-s1 (ou --dir); falta modelo → etapa "falta", exit 2
uv run --extra ayanami-ml python spikes/ayanami_s1_bancada.py all
# baixa o que faltar (só para dentro de DIR) e mede
uv run --extra ayanami-ml python spikes/ayanami_s1_bancada.py all --modelos DIR
```

## PC

Rodado em 2026-10-21 no PC do Pedro (Intel i5-11400F, 6 núcleos / 12 threads, 31 GB), Python
3.12.14, `kokoro-onnx` 0.6.1, `onnxruntime` 1.30.0, `faster-whisper` 1.2.1, `fastembed` 0.9.0.
**Sem rede** (regra da tarefa): só havia em disco o Kokoro **fp32** do PC
(`~/.cache/magi/kokoro/kokoro-v1.0.onnx`); o int8, o `faster-whisper-small` e o e5-small não
estavam baixados, então essas etapas saíram "falta" (exit 2, nada baixado).

```sh
uv run --extra ayanami-ml python spikes/ayanami_s1_bancada.py all \
  --kokoro-onnx ~/.cache/magi/kokoro/kokoro-v1.0.onnx --kokoro-voices ~/.cache/magi/kokoro/voices-v1.0.bin
```

| Modelo | Threads | Carga | Medida | Resultado | Meta | RAM pico |
| --- | --- | --- | --- | --- | --- | --- |
| kokoro (`kokoro-v1.0.onnx`, fp32) | 2 | 0.9 s | RTF em 10 frases (43 s de fala) | p50 0.404 · p90 0.425 · total 0.408 | RTF ≤ 0,5 | 576 MB |
| kokoro (`kokoro-v1.0.onnx`, fp32) | 4 | 0.7 s | RTF em 10 frases (43 s de fala) | p50 0.279 · p90 0.293 · total 0.281 | RTF ≤ 0,5 | 577 MB |
| whisper (`small` int8) | 4 | — | RTF em 5 min | **não medido** (modelo ausente, sem rede) | RTF ≤ 0,4; RAM ≤ 2 GB | — |
| embed (`e5-small`) | 4 | — | vazão, lotes de 64 | **não medido** (modelo ausente, sem rede) | — | — |

Leitura:

- Kokoro fp32 com 2 threads (o `cpus: 2` do `ayanami-voz`, design §4.4) fica **dentro** da meta
  (0,41 < 0,5) no PC, mas com pouca folga; o node 2 (vCPU de nuvem, sem turbo) tende a ser mais
  lento. O int8 deve ser mais rápido que o fp32 — confirmar na rodada com `--modelos`.
- RAM do Kokoro fp32 ≈ 580 MB, cabe no `1536m` do `ayanami-voz`.
- **fastembed 0.9.0 não traz `intfloat/multilingual-e5-small`** na lista de modelos (só o
  `multilingual-e5-large`). O script registra o modelo com `TextEmbedding.add_custom_model`
  (`pooling=MEAN`, `normalization=True`, `onnx/model.onnx` do repositório `intfloat/…` no HF) —
  não verificado sem rede; o worker de embeddings (§5.6) vai precisar do mesmo registro.
- Pendente para completar esta seção: `… all --modelos ~/.cache/magi/ayanami-s1` com rede
  (≈ 1 GB: Kokoro int8 + whisper small + e5-small).

## node 2

*(Y0.8, Pedro.)*
