# Spike S6 — turno remoto (parte local)

Tarefa Y0.6 de `specs/ayanami-central/tasks.md`. Rodado no PC (Nobara, `ffmpeg` 8.1.2 com
`libopus`), sem Ayanami e sem rede: `uv run python spikes/ayanami_s6_turno.py all --rodadas 20`.
O p90 do caminho 4G (voz ≤ 4 s, critério 2) fica para a F.x.

## Tempos locais (20 rodadas, 2026-10-12)

| medida | n | p50 ms | p90 ms | máx ms |
| --- | --- | --- | --- | --- |
| webm/opus 15 s (46 KiB) → PCM 16 kHz | 20 | 117 | 119 | 121 |
| PCM 24 kHz → ogg/opus 32k: 1º byte de áudio | 20 | 97 | 100 | 104 |
| PCM 24 kHz → ogg/opus 32k: total (96 KiB) | 20 | 147 | 149 | 155 |
| turno áudio: AUDIO_FIM → gancho | 20 | 1 | 2 | 6 |
| turno áudio: AUDIO_FIM → 1º AUDIO_OUT | 20 | 1 | 2 | 6 |
| turno texto: fim → gancho | 20 | 0 | 0 | 0 |
| turno texto: fim → 1º AUDIO_OUT | 20 | 0 | 0 | 0 |

- **Entrada**: `ffmpeg -i pipe:0 -f s16le -ac 1 -ar 16000 pipe:1` lê webm (Matroska) de pipe sem
  problema; 15 s em ~120 ms, muito abaixo do prazo de 2 s da §6.2. Áudio de teste = tom + ruído em
  opus 24 kbit/s 48 kHz (como o `MediaRecorder`); voz real não muda o custo de decodificação.
- **Saída**: `-c:a libopus -b:a 32k -application voip -frame_duration 20 -flush_packets 1
  -page_duration 20000 -f ogg` em streaming; sem `-page_duration` o muxer ogg segura páginas de
  até 1 s. O 1º byte de áudio sai ~100 ms após o 1º quadro (quase tudo é a partida do `ffmpeg`);
  a Y2.x pode manter um processo aberto por turno desde o `Turno` para tirar isso do caminho.
- **Turno**: com STT/TTS falsos instantâneos, o custo do `TurnMachine` + quadros do elo é ≤ 6 ms;
  o tempo real é STT + agente + TTS do PC, como no headset.

## Gancho `on_turn_done` [DS6] — para a Y6.2

- **Linha exata**: `magi/core/turn.py`, `TurnMachine._deliver`, logo após
  `result = tr_result(compose(result))` (linha **1132** no commit `f55593e`), antes de
  `needs_confirmation`/cards/legenda/`speaker.say`. Chamar ali
  `await deps.on_turn_done(self._ctx, result)` quando `self._ctx` e o gancho existirem (erro do
  gancho: log e segue). O resultado já está composto (fala curta, legenda, cards) e traduzido.
- Todos os caminhos de resposta passam por `_deliver` (turno normal, confirmação, oferta,
  "Cancelado.", resposta à confirmação anterior); `announce`/`narrate` **não** passam (avisos
  proativos e audiolivro), então não geram `TurnoFim` — correto para o celular.
- Com fala antecipada (`early`, 1.24) o áudio pode começar **antes** do gancho; o `TurnoFim` ainda
  sai antes do fim da fala. O protótipo confirma o gancho antes do `speaker.say` no caminho normal.
- A spec §6.3 não muda de ponto; só ganhou esses detalhes.

## Registro do satélite `celular` — para a Y6.2

- Hoje o único jeito de criar um `TurnMachine` é `CoreService._serve` (TCP Wyoming):
  `magi/core/service.py` linhas **167–179** (`machine = TurnMachine(...)` …
  `self._machines[hello.satellite] = machine`). **Precisa** de um método público novo no
  `CoreService` (ex.: `anexar(link, *, pipeline=None, hud=None, followup_ms=None) -> TurnMachine`)
  que faça o mesmo sem socket, fechando o anterior do mesmo id. O protótipo `anexar()` do script
  mexe em `_machines` direto.
- **PTT**: `WakeEvent(PTT, "celular")` → `AudioStart(16000, 2, 1)` → `AudioChunk` por quadro
  `AUDIO_IN` de 80 ms → `AudioEnd(reason=PTT_RELEASE, tone=None)` no `AUDIO_FIM`. `tone=None` não
  conta como silêncio; áudio vazio conta.
- **Texto**: não há entrada de texto no `TurnMachine` nem no HUD. Sem mexer no `turn.py`, o
  protótipo usa um `TurnPipeline` próprio do celular (mesmas `deps`) cujo `transcribe` devolve o
  texto pronto (`Transcript.raw`), e manda o mesmo PTT com um quadro mudo de 80 ms. Funciona e
  passa por router/agente/gancho/fala como um turno de voz.
- **`playback-done`**: o celular não o manda; o `RemoteLink.play` precisa injetar
  `PlaybackDone("celular")` no `TurnMachine` ao terminar, senão o turno fica em `speaking`.
- `followup_ms=None` no celular (não há escuta aberta pela WS); `ListenRequest` é ignorado,
  `StopPlayback` → `AUDIO_FIM`. HUD do celular: `NullHud()` no protótipo (o turno do celular não
  mexe no rosto do PC); a Y6.2 decide se espelha.
- Confirmação (`needs_confirmation`): o `TurnMachine` fica em `confirming`; o "sim"/"não" do
  celular chega num novo `Turno`, cujo `WakeEvent` guarda a pergunta como pendente recente
  (`_keep_stale`) e o `_think` a responde — mesmo caminho do headset, sem código novo.
