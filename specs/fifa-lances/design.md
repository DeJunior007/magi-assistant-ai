# Design — Lances do FIFA 22

Implementa [requirements.md](requirements.md). Seções citadas por `§`.

## 1. Onde mora hoje

```
núcleo: GameWatcher (core/game_context.py, /proc a cada N s) ─GameEvent opened/closed─▶ assinantes
        (ex.: MusicSuggester.on_game, assemble.py:960); FIFA = [[game.custom]] process "FIFA22.exe"
        ProactiveSink (fala só com satélite livre; call → legenda) · hud_client ─▶ HUD
HUD:    FpsSource (MangoHud CSV) + steam_game ─▶ Snapshot.gaming/fps ─▶ Reactor (1 Hz) ─▶ det_* ─▶ Disparo
        núcleo→HUD: magi/common/events.py (decode_hud) ─▶ hud/hud_bridge.py (_MIN_DECODERS, sinais Qt)
        ─▶ gamerhud.on_bridge_* ─▶ WiredUI.set_* ─▶ Snapshot (modelo: turn_tag da R2.B das reações)
vida (em andamento, specs/condessa-vida): Disparo(causa) ─▶ diretor.Diretor ─▶ Cena; estado.Humor;
        momento JOGANDO; episodio.py (FPS/calor)
```

## 2. Visão nova

```
GameWatcher(FIFA22.exe opened) ─▶ lances.Servico (núcleo, asyncio)
        └─ subprocesso `magi-lances olhar` ──stdout JSONL──▶ Servico
              portal ScreenCast (dbus-next, restore_token) ─fd─▶ gst-launch pipewiresrc ─GRAY8 1 fps─▶
              recorte ─▶ ocr (placar/relógio) ─▶ confirma 2 quadros ─▶ partida.Maquina ─▶ Lance
Servico ─┬─ LanceMsg ─▶ HUD (bridge ─▶ WiredUI.set_lance ─▶ Snapshot.lance ─▶ det_lances ─▶ Disparo(causa)
         │                                                     ─▶ diretor da vida ─▶ cena + Evento de humor)
         ├─ CardMsg "PSG 2 × 1 BAR · 67'" ─▶ HUD
         ├─ ProactiveSink(Priority.VOICE) ─▶ fala curta (≤ 4/partida)
         └─ lances.jsonl
```
- **Subprocesso** isola GStreamer, OCR e a sessão do portal: se travar ou estourar memória, o núcleo
  só perde os lances (reinicia no máximo 3×/partida). Morre com o pai (`PR_SET_PDEATHSIG`, como o
  `Notificacoes` do HUD).
- **A máquina da partida roda no subprocesso** (pura, testável sem tela); o núcleo só decide voz,
  card e repasse. O HUD só decide rosto.

## 3. Captura no Wayland/KDE (escolha)

| Caminho | Prompt | Custo a 1 Hz | Veredito |
| --- | --- | --- | --- |
| **Portal ScreenCast + `restore_token` (`persist_mode=2`) + PipeWire → `gst-launch pipewiresrc fd=N path=<nó>`** | só na 1ª vez | fluxo contínuo; recorte e conversão no GStreamer; ~1–3% de um núcleo (medir) | **escolhido** |
| `spectacle -b -n -o <png>` por quadro | nunca (app autorizado do KDE) | sobe um app Qt + PNG da tela inteira por segundo (~30–50% de um núcleo) | só na **calibração** (1 captura) |
| Interface `org.kde.KWin.ScreenShot2` por D-Bus | nunca (com `.desktop` autorizado) | baixo | **proibido**: D-Bus direto no KWin (regra do projeto) |
| Portal `Screenshot` | pede (ou silencioso só com permissão do app) a cada chamada | PNG inteiro por chamada | descartado |
| `ffmpeg -f kmsgrab` | não | baixo | exige `CAP_SYS_ADMIN`; descartado |
| gamescope | não | — | muda como o jogo roda; descartado |

Detalhes do escolhido:
- `dbus-next` (já dependência) fala com `org.freedesktop.portal.Desktop` (não é o KWin):
  `CreateSession` → `SelectSources(types=MONITOR, multiple=false, cursor_mode=HIDDEN,
  persist_mode=2, restore_token=<salvo>)` → `Start` (devolve `streams[0].node_id` e o
  `restore_token` novo — **sempre** regravar) → `OpenPipeWireRemote` (fd).
- O fd vai ao `gst-launch-1.0` por `pass_fds`; pipeline (spec §2) pede `max-framerate` baixo,
  recorta **antes** de converter e entrega `GRAY8` cru no stdout, quadro de tamanho fixo.
- Token em `~/.local/state/magi/lances-portal.json` (0600). Recusa/expiração → F2.1.
- Risco: o screencast pode impedir o *direct scanout* do jogo em tela cheia e custar FPS → o spike
  F1.1 mede com o MangoHud (critério 3); se passar de 3%, cair para `intervalo_s = 2`.

## 4. Pacote novo `magi/lances/`

| Módulo | Papel | Dono |
| --- | --- | --- |
| `contratos.py` | `Leitura`, `Partida`, `Fase`, `TipoLance`, `Lance`, `Recorte` | F0.1 |
| `config.py` | `[fifa]` (spec §7) | F0.1 |
| `portal.py` | sessão ScreenCast com token (dbus-next), sem lógica de imagem | F1.1 |
| `captura.py` | sobe o `gst-launch`, lê quadros `GRAY8` de tamanho fixo, para limpo | F1.1 |
| `calibrar.py` | `magi-lances calibrar` (spectacle, recortes padrão, grava `lances-recorte.json`) | F1.2 |
| `ocr.py` | pré-processo (numpy), motor (D2), `ler(quadro) -> Leitura | None`, pula OCR se a região não mudou | F1.3 |
| `partida.py` | `Maquina.alimentar(leitura, agora) -> list[Lance]` (spec §4), pura | F1.4 |
| `__main__.py` | `magi-lances olhar` (loop: captura → ocr → máquina → JSONL) e `calibrar` | F1.5 |
| `servico.py` | núcleo: liga/desliga pelo `GameWatcher`, lê o JSONL, voz/card/HUD/registro | F1.5 |
| `times.toml` | sigla → nome falado ("BAR" → "Barcelona"); siglas fora da tabela são faladas letra a letra | F1.5 |
| `narrador.py` | caminho 2 (só depois do spike F3.1) | F3.2 |

HUD (fora do pacote): `magi/common/events.py` (`LanceMsg`), `hud/hud_bridge.py` (decoder + sinal
`lance`), `hud/gamerhud.py` (`on_bridge_lance`), `hud/wired/integration.py`/`main_screen.py`
(`Snapshot.lance`), `hud/wired/reacoes/det_lances.py` (novo detector registrado em `DETECTORES`) e
os roteiros de cena no `catalogo.py`/`diretor.py` da vida.

## 5. Encaixe na vida da Condessa

- Momento: lances só existem com jogo aberto → momento **Jogando** (vida spec §1; entra na hora).
- `det_lances` emite `Disparo(chave="lance", variante=<tipo>, causa=f"lance:{partida}:{n}")`; o
  diretor mapeia variante → tipo de cena (spec §5) e aplica fila/interrupção da vida: gol e fim são
  prioridade 2 (fila), virada/goleada/vitória são vitória (furam a cota de cenas, F7.1); um lance
  durante cena de episódio de FPS/calor espera (F7.2).
- Cada lance também vira `Evento` de humor (spec §5, números em `[vida.lances]` do gosto).
- Repouso durante a partida: o da vida (B1 C10 / B6 C8 com episódio); depois de gol a favor, a faixa
  de humor sobe e o repouso muda sozinho — o lance não precisa de repouso próprio.
- Gols em rajada (3 em 1 min) = uma cena com ramo `goleada` (regra "uma causa, uma cena" da vida:
  a causa é `lance:<partida>:gol` dentro de `mesma_causa_s`).

## 6. Caminhos 2 e 3

- **(2) Narrador:** `pw-dump` acha o nó de saída do processo do jogo (`application.process.binary`
  do Wine/Proton) → `pw-record --target <serial> --rate 16000 --channels 1 -` (só leitura do fluxo
  do jogo, não do microfone) → STT local com gramática fechada de palavras-chave (Vosk pequeno) ou
  `faster-whisper tiny` em janelas de 3 s. Dá o que o placar não dá (entrada forte, cartão, trave),
  com risco de CPU em jogo e de falso positivo. Fica atrás do spike F3.1 (D5, D6).
- **(3) Memória do processo — descartado.** Ler a memória do `FIFA22.exe` dentro do Wine exige
  `ptrace` (ou `process_vm_readv`) num processo de outro prefixo, offsets que mudam a cada patch e
  a cada partida (ASLR), e no modo online/FUT o anti-cheat da EA pode tratar como trapaça (risco de
  banimento da conta). Fragilidade + risco > ganho. Não entra em tarefa.

## 7. Riscos

| Risco | Mitigação |
| --- | --- |
| FPS cai com o screencast | spike mede (critério 3); 2 s de intervalo; recorte no GStreamer |
| OCR erra dígito (gol fantasma) | 2 quadros iguais; placar só sobe; queda de 1 = anulado; gol exige +1 num lado só |
| Replay mostra placar antigo/sem placar | sem placar = sem evento; ao voltar compara com o último confirmado |
| Layout do placar muda (modo, resolução, HUD do jogo desligado) | calibração com recortes por resolução; sem leitura por 5 min com relógio ausente → legenda "não tô vendo o placar" 1×/partida |
| Diálogo do portal toda vez | `restore_token` regravado a cada `Start`; F2.1 só pede de novo por comando |
| Vida ainda não ligada | F2.1 depende de V0.1 e F2.2 de V0.8/V0.10; antes disso o núcleo já fala, manda card e grava lances |
| Sessão KDE cair | nada de `qdbus`/`gdbus`/KWin; só o portal (o caminho oficial para apps) |
