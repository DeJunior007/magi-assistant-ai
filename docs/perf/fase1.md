# Medição da fase 1 (tarefa 1.18)

Medido em 2026-10-03 nos serviços reais (`magi-satellite` e `magi-core` via `systemd --user`,
`magi-pg` em Docker). O script só lê: não reinicia nem para nada. Script: `tools/perf.py`.

## Resumo

| RNF | Meta | Medido | Veredito |
| --- | --- | --- | --- |
| RNF-01 CPU dormindo (satélite + núcleo + Postgres) | ≤ 2% de um núcleo | média **1,30%**, p90 1,10% (Magui sozinha: 0,34%) | **dentro** |
| RNF-02 RAM dormindo (satélite + núcleo + Postgres) | ≤ 300 MB | PSS **402 MB** (p90 403); pela conta do `docker stats`, 555 MB | **fora** |
| RNF-04 comando conhecido, fim da fala → ação | ≤ 1,5 s p90 | primeiro áudio: p90 **1,78 s** (média 1,43 s); só até a ação (sem o TTS): p90 ≈ 0,81 s | **fora** pelo primeiro áudio; dentro se "ação" for a ação em si |
| RNF-05 pergunta, fim da fala → início da voz | ≤ 3 s p90 | p90 **4,12 s** (média 3,22 s), só 5 turnos | **fora** (amostra pequena) |

## Metodologia

### Ociosa (RNF-01, RNF-02): `uv run python -m tools.perf idle --minutes 10`

- 120 amostras, uma a cada 5 s, durante 10 min, com a Magui dormindo (satélite ouvindo o wake word
  no microfone, sem turnos).
- CPU: diferença de `usage_usec` do `cpu.stat` do cgroup de cada serviço (`systemctl --user show
  -p ControlGroup`) e do cgroup do container (`system.slice/docker-<id>.scope`), em % de um núcleo.
- RAM dos serviços: soma de RSS e PSS (`/proc/<pid>/smaps_rollup`) dos processos do cgroup. PSS
  divide as bibliotecas compartilhadas e é o número usado no veredito.
- RAM do Postgres: os processos são de outro usuário (sem `smaps` legível). Duas contas pelo
  `memory.stat` do cgroup: a do `docker stats` (`memory.current - inactive_file`, inclui cache de
  arquivo ativo, que o kernel devolve sob pressão) e `anon + shmem` (heap + `shared_buffers`, o
  residente de fato). O veredito usa `anon + shmem`. `docker stats --no-stream` roda no início e
  no fim só para conferência (leva vários segundos por chamada, não serve para amostrar a cada 5 s).
- Foram 3 rodadas de 10 min. As duas primeiras pegaram reinícios do núcleo por merges (00:36 e
  05:09); vale a terceira (05:21–05:31, sem reinício, núcleo de pé desde 05:15:55 e já depois de
  60 turnos de latência, isto é, com os clientes de API carregados como no uso real).

| Processo | CPU média / p90 / máx | PSS média | RSS média |
| --- | --- | --- | --- |
| magi-satellite | 0,31% / 0,36% / 0,42% | 223 MB | 244 MB |
| magi-core | 0,03% / 0,04% / 0,07% | 126 MB | 142 MB |
| magi-pg | 0,96% / 0,75% / 21,8% | 53 MB (anon+shmem) | 170 MB (conta do docker) |
| **total** | **1,30% / 1,10% / 22,2%** | **402 MB** | 555 MB |

Conferência de longo prazo: o satélite gastou 56,4 s de CPU em 4 h 46 min (0,33%) e o núcleo
anterior, 4,4 s em 4 h 33 min (0,03%), segundo o systemd.

O Postgres é compartilhado com outros agentes e testes (regra 9): sua mediana foi 0,02%, e só 9 das
120 amostras passaram de 1% (picos de até 22% coincidem com uso externo). Nas rodadas anteriores a
média dele foi 1,9–2,0% pelo mesmo motivo. O RNF-01 fica dentro mesmo com esse ruído.

### Latência (RNF-04, RNF-05): `uv run python -m tools.perf latency`

- Cliente Wyoming próprio no script, conectado ao núcleo real como satélite **`perf`**. O núcleo
  mantém uma máquina de turno por id de satélite (`CoreService._machines`), então o cliente não
  disputa o turno com o satélite real (`pc`), que segue ligado. Efeito visível: o HUD mostra o
  estado/legenda desses turnos (é compartilhado).
- Cada turno: `magi-wake` (ptt), `audio-start`, chunks do áudio da frase (enviados sem esperar o
  tempo real), `audio-stop` (reason `vad`). O relógio parte do envio do `audio-stop` e para no
  primeiro `audio-chunk` da resposta (eventos anteriores, como um bip, são descartados). Depois
  manda `playback-done` e espera 1,5–3 s.
- O áudio de cada frase foi gerado uma vez pelo TTS configurado (OpenAI `gpt-4o-mini-tts`) e
  cacheado em `~/.cache/magi/perf/`.
- Não entra a cauda do VAD do satélite (700 ms de silêncio para encerrar a fala); com ela, o
  usuário percebe ~0,7 s a mais.
- Comando escolhido: **"cancela"** (intent local `confirm.no`; fora de uma confirmação não tem
  handler e responde "Ainda não sei fazer isso."). Percorre o caminho inteiro de um comando local
  (STT na nuvem → roteador local → despacho → TTS) sem efeito nenhum no PC. "Aumenta o volume" e
  afins mexeriam na sessão do usuário; `magi.help` gera fala longa (~130 caracteres por turno) e
  foi medido só como conferência.
- Pergunta ao agente: "quantas patas tem uma aranha" (sem pesquisa nem visão), 5 turnos.
- Custo estimado da medição: ~US$ 0,07 (STT ~US$ 0,01, TTS ~US$ 0,045, agente ~US$ 0,01; a parte
  do RNF-05 ficou em ~US$ 0,02, abaixo do teto de US$ 0,05).

| Frase | Turnos | Média | p90 | Máx | Falhas |
| --- | --- | --- | --- | --- | --- |
| "cancela" (comando local) | 50 | 1,43 s | **1,78 s** | 6,94 s | 0 |
| "o que você sabe fazer" (`magi.help`) | 5 | 1,43 s | 1,78 s | 1,79 s | 0 |
| "quantas patas tem uma aranha" (agente) | 5 | 3,22 s | **4,12 s** | 4,71 s | 0 |

Decomposição pelo log do núcleo (horário de chegada das respostas HTTP):

- Comando: STT ≈ 0,72 s (p90 0,81 s) + TTS até o primeiro áudio ≈ 0,71 s (p90 0,90 s). O
  roteador e a ação são desprezíveis.
- Pergunta: STT ≈ 0,3–0,7 s → embeddings da memória 0,3–1,1 s → chat (primeira resposta)
  0,8–2,3 s → TTS 0,4–0,9 s, tudo em série.

## Causas prováveis do que ficou fora

- **RNF-02 (402 MB):** o satélite sozinho ocupa 223 MB de PSS: ~158 MB são heap/anon do
  onnxruntime (sessões do openWakeWord: melspectrogram + embedding + modelo, mais o Silero VAD, com
  o arena allocator padrão) e 20 MB a própria biblioteca do onnxruntime; o scipy também é
  carregado. O núcleo tem 126 MB depois dos primeiros turnos (91 MB recém-iniciado): SDKs da OpenAI
  e do Gemini, psycopg, catálogos. O Postgres em si é pequeno (53 MB residentes). Caminhos: desligar
  o arena do onnxruntime (`enable_cpu_mem_arena=False`) e usar 1 thread por sessão, evitar importar
  scipy no satélite, importar os SDKs só quando usados. A meta de 300 MB parece apertada para
  Python + onnxruntime + Postgres; vale rever a meta ou as dependências.
- **RNF-04 (1,78 s até o primeiro áudio):** são duas idas à nuvem em série (STT ~0,7 s + TTS
  ~0,7 s). A ação em si sai em ~0,8 s (p90), dentro da meta. A fala da resposta medida não está no
  cache de frases (`phrases.yaml`); em comandos cuja resposta está no cache ("Volume ajustado.",
  "Pulando.", "Abrindo {game}." depois da primeira vez) o TTS some e o primeiro áudio fica perto de
  0,8 s. Pôr as respostas fixas do núcleo (`SAY_UNAVAILABLE`, `SAY_DID_YOU_MEAN`...) no cache
  resolveria esse caso. O máximo de 6,9 s foi um STT lento isolado na nuvem.
- **RNF-05 (4,1 s, 5 turnos):** a busca de memória por embeddings roda antes do chat, em série, e o
  primeiro turno pagou o aquecimento (4,7 s). Paralelizar a busca de memória com o início do chat
  (ou pular para perguntas factuais) e abrir o TTS na primeira frase do stream cortaria ~0,5–1 s.
  Cinco turnos é pouco para um p90; repetir com mais turnos se o gasto permitir.

## Como repetir

```
uv run python -m tools.perf idle --minutes 10 --json idle.json
uv run python -m tools.perf latency --turns 50 --phrase cancela --json cmd.json
uv run python -m tools.perf latency --turns 5 --phrase "quantas patas tem uma aranha" --gap 3
```

O núcleo e o satélite precisam estar rodando; não rode `latency` junto com `idle`.
