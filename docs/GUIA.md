# Guia da Magui e do MAGI Gamer

Guia de uso direto ao ponto. Instalação no [`README.md`](../README.md); o que falta em
[`PROXIMOS-PASSOS.md`](PROXIMOS-PASSOS.md).

**Índice**

1. [Como chamar a Magui](#1-como-chamar-a-magui)
2. [Conversa contínua e dispensa](#2-conversa-contínua-e-dispensa)
3. [O que ela sabe fazer](#3-o-que-ela-sabe-fazer)
4. [HUD](#4-hud)
5. [Música](#5-música)
6. [Notícias e spoiler](#6-notícias-e-spoiler)
7. [Memória, humor e ajuda no jogo](#7-memória-humor-e-ajuda-no-jogo)
8. [Alertas, call no Discord e gasto](#8-alertas-call-no-discord-e-gasto)
9. [Onde fica cada coisa no PC](#9-onde-fica-cada-coisa-no-pc)
10. [Config](#10-config)
11. [Logs e diagnóstico](#11-logs-e-diagnóstico)
12. [Condessa (wake word)](#12-condessa-wake-word)
13. [Problemas comuns](#13-problemas-comuns)
14. [Custos e desempenho](#14-custos-e-desempenho)
15. [Casa, Ayanami e celular](#15-casa-ayanami-e-celular)

---

## 1. Como chamar a Magui

| Jeito | Como |
| --- | --- |
| Voz | **"Condessa"**, sozinha ou com "hey", "oi" ou "oh" na frente. Depois do bip, fala o pedido. |
| Teclado | Segura **Pause**, fala, solta (atalho global do KDE; trocar em `[satellite] ptt_key`). |
| DualSense | Segura **PS + Share** juntos, fala, solta. |
| HUD | Clica no **mascote** (push-to-talk). |

- Pode falar tudo junto: "Condessa, abre o Hades". O satélite manda ~0,4 s de áudio de antes da
  ativação, e espera até 5 s pela fala depois do "Condessa".
- A fala termina com 1 s de silêncio (`end_silence_ms`); máximo de 15 s por gravação.
- Em **call no Discord** a palavra "Condessa" fica desligada: só o atalho (Pause/PS+Share) funciona.

## 2. Conversa contínua e dispensa

Depois que ela responde, fica **3 s ouvindo sem precisar do "Condessa"** e sem bip (rosto
"ouvindo" no HUD). Falou nesse tempo, é um turno normal que reabre a janela. Silêncio: ela dorme
calada.

Para dispensar na hora, fala só: "valeu", "obrigado(a)", "brigado", "só isso", "pode ir",
"dispensa", "tchau", "nada não", "esquece", "falou" (com ou sem "Magui"/"Condessa" junto). Ela
sorri e dorme sem falar nada.

Desligar ou mudar o tempo: `[conversation] followup = false` / `followup_s = 3.0`. Em call no
Discord não tem janela.

## 3. O que ela sabe fazer

Comandos simples caem no **roteador local** (`magi/core/intents.yaml`): rápidos e de graça. O
resto vai para o **agente** (gpt-5.4-mini) com ferramentas. Pergunta "**o que você sabe fazer?**"
que ela mesma lista.

| Área | Exemplos |
| --- | --- |
| Jogos | "abre o Hades", "bora jogar Elden Ring", "fecha o jogo", "mata o jogo" (pede confirmação) |
| HUD | "abre o hud", "esconde o hud", "alterna a tela", "tela de ociosidade", "painel completo", "mostra a gpu", "como tá a memória", "fecha os detalhes", "liga o rgb sync" |
| Volume do sistema | "aumenta o volume", "volume em 30", "muta", "tira do mudo" |
| RGB | "muda o rgb pra vermelho", "brilho em 50" |
| Sistema | "desliga o pc", "reinicia o computador" (pede confirmação) |
| Spotify | "abre o spotify", "toca", "pausa", "próxima", "anterior", "volume da música em 40", "toca Linkin Park", "coloca uma boa", "essa é boa", "nunca mais toca isso" |
| Correção | "não, eu falei X" (refaz o turno e aprende a correção) |
| Memória | "lembra que eu tô jogando Elden Ring", "esquece isso" |
| Humor | "pega leve", "pode pegar pesado" |
| Gasto | "aumenta o teto pra 8 dólares" |
| Notícias | "alguma novidade?", "conta mais dessa", "o que saiu de novo de Frieren?", "pode dar spoiler de X", "não curti", "mais disso", "larguei X" |
| Pesquisa | qualquer coisa recente ("quando sai o próximo Zelda?"): Gemini com Google; links vão pro HUD |
| Tela (visão) | "que bicho é esse?", "o que tá escrito aqui?" (janela ativa); "...na tela" pega o monitor todo. Só quando você pede; a captura é apagada depois |
| Ajuda no jogo | "como passo do boss da lua?", "manda a solução" |
| Confirmação | "confirma"/"sim" ou "cancela"/"não"; vale até 20 s depois mesmo se você apertar o atalho no meio da pergunta. Pedido meio entendido vai direto para a IA, sem "você quis dizer"; só desligar/reiniciar/fechar jogo perguntam |

Ferramentas do agente (`magi/agent/tools/`): `open_game`, `close_game`, `hud`, `volume`, `rgb`,
`spotify_play`, `spotify_control`, `spotify_pick`, `search`, `news_query`, `screenshot`,
`remember`, `forget`, `game_help`.

Respostas faladas têm até 2 frases; a resposta completa e os links aparecem como legenda/card no HUD.

## 4. HUD

- Abre sozinho quando um jogo começa (vigia `gamerhud-watch.py`) e fecha quando termina. Manual:
  menu "MAGI Gamer" ou `gamerhud`.
- **Win+M** (Meta+M): alterna Painel completo ↔ Tela de espera, com cortina.
- Cliques no Painel completo:
  - **LED** (消灯 OFF / 点灯 ON): liga/desliga o RGB Sync. Ligado, o HUD tinge com a cor atual do
    OpenRGB; sem OpenRGB volta ao visual off e avisa no rodapé.
  - **Now playing**: anterior / tocar-pausar / próxima (Spotify por MPRIS).
  - **Cards CPU / GPU / RAM**: consumo por processo; clique de novo fecha.
  - **Mascote**: push-to-talk.
- Mascote = rosto da Magui (expressão, boca falando, legenda) e termômetro de humor (0–4) ao lado.
  Rodapé: jogo detectado/fechado, troca de faixa, Magui ativada, alertas.
- **Tema**: `~/.config/gamerhud/settings.json` → `"ui": "wired"` (padrão) ou `"eva"` (painel NERV
  antigo). Vale na hora. Outras chaves: `rgb_sync`, `view` (`full`|`idle`), `transition`,
  `wallpaper` (`still`|`pause`|`off`), `auto_open`, `auto_close`.
- Enquanto aberto, troca as cenas do Wallpaper Engine por um print (libera ~580 MB de VRAM) e
  devolve ao fechar.

## 5. Música

- Precisa do Spotify (flatpak) e, para buscar por nome, do login: `uv run magi-spotify-login`.
  Controles simples (tocar, pausar, próxima) vão por MPRIS e funcionam sem login; se o app estiver
  fechado ela abre e espera até 15 s.
- **"Coloca uma boa"**: escolhe pelo seu gosto (mais ouvidas e recentes importadas do Spotify) +
  contexto (horário, gênero do jogo aberto, o que você pediu).
- **Sinais de gosto**: "essa é boa" (sobe), "nunca mais toca isso" (corta), pular antes de 30 s
  (desce), ouvir inteira (sobe).
- **Sugestão ao abrir jogo**: pelas tags da Steam; em jogo casual no máximo 1× por sessão. Desliga
  com `[music] suggest = false`.
- Quando ela fala, o Spotify e o jogo abaixam de volume (ducking) e voltam depois.

## 6. Notícias e spoiler

- A **Ayanami** (`magi-ayanami`, o agente de notícias, no Gemini) roda a cada 2 h (timer systemd): Steam News dos jogos instalados, AniList da sua
  lista, Reddit (r/anime, r/Games), RSS e scraping. Agrupa a mesma notícia de várias fontes,
  classifica e prioriza.
- Entrega: **bomba** = frase + card (voz só fora de call); **alta** = só card. No máximo 2 por hora
  e 8 por dia; mais velha que 48 h é descartada.
- **Anti-spoiler**: manchete reescrita ou escondida para o que você ainda não viu/jogou.
  "pode dar spoiler de X" libera aquela obra.
- Retorno: "não curti" / "mais disso" mexem no peso da obra da última notícia; ignorar a mesma obra
  3× seguidas também baixa; "larguei X" para de priorizar.
- "Alguma novidade?" é um **modo rádio**: ela conta uma notícia por vez, em português (as fontes
  são em inglês; quem traduz e resume é o modelo da tarefa `news`), e pergunta "Quer ouvir
  outra?". "Sim" conta a próxima, "não" encerra ("Beleza, depois tem mais.") e o silêncio
  encerra calado. "Mais disso"/"não curti" valem para a notícia que acabou de tocar. Sem o
  modelo, ela fala a manchete original.
- "**Conta mais dessa**" ("fala mais sobre essa", "aprofunda", "mais detalhes"), na hora do "Quer
  ouvir outra?" ou depois: ela abre as páginas de até 5 fontes da notícia (ou usa o texto do feed
  quando a página bloqueia), o Python faz um resumo extrativo (`magi/news/digest.py`) e só esse
  resumo curto vai à IA, que conta em 5-7 frases. Depois pergunta de novo se quer outra.
  Notícia escondida por spoiler não é aprofundada.
- "O que saiu de novo de X?" (pela IA) traz até 5 itens; sem nada guardado, ela pesquisa na
  internet.
- Fontes padrão em `magi/news/sources.toml`; acrescenta ou desliga em `[[news.sources]]` no config.

## 7. Memória, humor e ajuda no jogo

**Memória.** Ela guarda fatos duradouros (gostos, o que você está jogando, planos, "lembra
que...") no Postgres e busca até 5 parecidos a cada pergunta. "**Esquece isso**" apaga a última
memória guardada (ou a mais parecida com o que você disser): se ela for desta conversa (até
30 min), some na hora; se for antiga, ela lê em voz alta e pergunta "Apago?". Um perfil curto de estilo (gírias,
formalidade, tamanho de resposta) é atualizado 1× por dia.

**Humor.** Nota 0–4 suavizada a partir do tom de voz (gritando, desanimado), palavras (palavrão
desce, risada/elogio sobe), "para de zoar", repetição e horário. Muda o quanto ela zoa.
"**Pega leve**" baixa, "**pode pegar pesado**" sobe. Aparece como termômetro ao lado do mascote.

**Ajuda no jogo, em degraus.** Pergunta sobre o jogo aberto vira: **pista → dica direta →
solução**. Pedir de novo o mesmo trecho ("o chefe da lua" = "boss da lua") sobe um degrau.
"**Manda a solução**" / "fala logo" pula direto. Se você está travado (pediu de novo na mesma
sessão ou faz tempo no mesmo trecho) já começa na dica direta. Pedido com mais de 2 h fora da
sessão recomeça na pista. Ela nunca tira print sozinha.

## 8. Alertas, call no Discord e gasto

**Alertas** (`[alerts]`): CPU ≥ 90 °C, GPU ≥ 95 °C (junção), bateria do controle ≤ 15%, gasto em
80% e 100% do teto. Fala curta + card; em call, só card. O mesmo alerta não repete antes de 15 min
e só volta depois de esfriar (82/85 °C) ou carregar.

**SSD e faxina.** Ela avisa quando o SSD passa de 85% e de novo, mais firme, em 95% (`disk_*` em
`[alerts]`). Todo dia às 04:30 (ou ao ligar o PC, se estava desligado) o `magi-clean.timer` faz uma
faxina no Docker: cache de build com mais de 7 dias e imagens órfãs; com o disco acima de 90%,
todo o cache de build. **Nunca apaga volumes** (bancos e arquivos dos projetos) nem imagens com
nome. Se liberou 0,5 GB ou mais, ela conta quanto. Rodar na mão: `systemctl --user start
magi-clean`; resultado em `~/.local/share/magi/cleanup_state.json` e no `journalctl --user -u
magi-clean`.

**Call no Discord.** O satélite vê a captura do Discord a cada 2 s. Em call: "Condessa" desligada,
sem conversa contínua, e o atalho **muta só o Discord** enquanto você fala com ela (restaura ao
soltar, e se algo cair restaura ao reiniciar).

**Gasto.** Teto mensal em `[budget] monthly_usd` (5 dólares no exemplo). Avisa em 80%; em 100%
bloqueia as chamadas pagas até virar o mês. "Aumenta o teto pra 8 dólares" ajusta por voz (fica em
`~/.local/share/magi/budget_state.json`; editar `monthly_usd` depois descarta o ajuste). Gemini na
cota gratuita custa 0 e por isso nunca recebe dado pessoal (memória, voz, humor, capturas).

## 9. Onde fica cada coisa no PC

| O quê | Onde |
| --- | --- |
| Código | `~/Documentos/magi-assistant-ai/` |
| Código do HUD em uso | `~/.local/share/gamerhud` → link para `hud/` do repo |
| Config da Magui | `~/.config/magi/config.toml` (ou `$MAGI_CONFIG`) |
| Config do HUD | `~/.config/gamerhud/settings.json` |
| Dados da Magui | `~/.local/share/magi/` (`mood.json`, `taste-import.json`, `artist-genres.json`, `budget_state.json`) |
| Modelos do wake word | `~/.local/share/magi/models/wakeword/` (`condessa.onnx`, `condessa.onnx.bak`, `hey_jarvis`, `melspectrogram`, `embedding_model`, `silero_vad`) |
| Gravações da Condessa | `~/.local/share/magi/wakeword-data/condessa/` (`positive/`, `negative/`, `noise/`, `synthetic/`, `eval/`) |
| Dados de treino baixados | `~/.local/share/magi/wakeword-train/` (~1,4 GB) |
| Cache da Magui | `~/.cache/magi/` (`tts/` frases prontas, `steam-tags.json`, `perf/`) |
| Áudio de diagnóstico | `~/.cache/magi/utterances/` (50 últimas falas, só com `[debug] save_audio = true`) |
| Cache do HUD | `~/.cache/gamerhud/` (`covers/`, `fps/`, `stills/` prints do papel de parede, `hud.log`, travas) |
| Coisas de sessão | `$XDG_RUNTIME_DIR/magi/` = `/run/user/1000/magi/` (`hud.sock`, estado do ducking e do mudo do Discord) |
| Banco | Postgres + pgvector no Docker: container `magi-pg`, `127.0.0.1:54329`, volume `magi-pgdata` |
| Chaves | KWallet (Secret Service), serviço **`magi-assistant`**: `openai-1`, `gemini-1`…, `spotify-client-id`, `spotify-token`, `reddit-client-id`, `reddit-client-secret`. Ver com `uv run magi-keys list` |
| Serviços | `~/.config/systemd/user/magi-satellite.service`, `magi-core.service`, `magi-ayanami.service` + `magi-ayanami.timer` (Ayanami) |
| Logs | `journalctl --user -u magi-core -u magi-satellite -u magi-ayanami`; HUD em `~/.cache/gamerhud/hud.log` |
| App de gravação | menu: "Gravar voz da Condessa" |

## 10. Config

Arquivo: `~/.config/magi/config.toml` (modelo comentado em `config.example.toml`). Só **nomes**
de chave vão nele; o valor fica no KWallet (`magi-keys add <nome>`). Salvou, o núcleo relê sozinho;
config inválido é ignorado (fica o anterior, erro no log e card no HUD).

| Seção | Chaves principais | Recarrega a quente? |
| --- | --- | --- |
| `[providers.openai]`, `[providers.gemini]` | `keys` (nomes), `free_tier` | sim |
| `[tasks]` | `stt`, `tts` (`voice`, `instructions`), `agent`, `vision`, `embeddings`, `search`, `search_fallback`, `news` — cada uma com `provider`, `model`, `timeout_s`… | sim (voz nova vale na próxima fala) |
| `[user]` | `name` | sim |
| `[budget]` | `monthly_usd`, `prices` | sim |
| `[conversation]` | `followup`, `followup_s` | sim |
| `[alerts]` | `enabled`, limites de temperatura/bateria, `cooldown_s`, `cost` | sim |
| `[news.delivery]`, `[news.feedback]` | limites de entrega, pesos | sim |
| `[satellite]` wake | `wake_threshold`, `wake_patience`, `wake_cooldown_ms`, `wake_gate_dbfs` | sim (o satélite relê) |
| `[satellite]` resto | `wake_model`, `mic_target`, `ptt_key`, `ptt_keyboard`, `ptt_dualsense`, `end_silence_ms`, `min_speech_ms`, `vad_threshold`, `wake_no_speech_ms`, `preroll_ms` | não: `systemctl --user restart magi-satellite` |
| `[debug]` | `save_audio` | não: reiniciar `magi-core` |
| `[database]`, `[paths]`, `[game]` (`known_processes`), `[music]` (`suggest`), `[[news.sources]]` | | não: reiniciar `magi-core` (fontes valem na próxima coleta) |

Valores atuais da Condessa: `wake_model = "condessa"`, `wake_threshold = 0.6`, `wake_patience = 3`.

## 11. Logs e diagnóstico

```bash
systemctl --user status magi-core magi-satellite        # estão de pé?
systemctl --user restart magi-core magi-satellite       # reinicia
journalctl --user -u magi-core -u magi-satellite -f     # tudo, ao vivo

# só o que interessa para "ela não entendeu":
journalctl --user -u magi-core -u magi-satellite -f | grep -E 'ouvi "|corrigido para|rota |fim da gravação|silêncio digital'
```

O que cada linha diz:

- `fim da gravação: ... rms -35 dBFS, pico ...`: o satélite gravou; volume da fala (ruído de fundo
  fica perto de −60, fala perto de −35).
- `silêncio digital`: o áudio chegou zerado → microfone mudo ou fonte errada no PipeWire.
- `ouvi "..."`: o que o STT entendeu (e o ganho aplicado).
- `corrigido para "..."`: uma correção sua ("não, eu falei X") foi aplicada.
- `rota <tipo>:<intenção> (nota) -> "<fala>"`: foi pro roteador local ou pro agente, e o que ela respondeu.

Para ouvir o que ela recebeu: `[debug] save_audio = true` no config, `systemctl --user restart
magi-core`, e as falas aparecem em `~/.cache/magi/utterances/` (guarda só as 50 últimas). Desliga
depois.

Medir desempenho: `uv run python -m tools.perf idle --minutes 10` e `uv run python -m tools.perf
latency` (detalhes em `docs/perf/fase1.md`).

## 12. Condessa (wake word)

Detalhes completos em [`docs/spikes/S4.md`](spikes/S4.md).

1. **Gravar**: abre "**Gravar voz da Condessa**" no menu (ou
   `uv run python -m tools.wakeword.record_gui`; `--section positive|negative|noise` grava só uma
   parte). Segura **Espaço** (ou o botão) enquanto fala e solta; **A** = modo automático, **R** =
   regrava, **P** = pula, **O** = ouve a última, Esc fecha. Retoma de onde parou. Pode deixar o
   satélite ligado. Versão de terminal: `uv run python -m tools.wakeword.record`.
2. **Gravar jogo** (para medir falsos disparos): `pw-record --rate 16000 --channels 1 --format s16
   ~/.local/share/magi/wakeword-data/condessa/eval/jogo1.wav` durante ~1 h de jogo, sem dizer
   "Condessa". Ctrl+C para parar.
3. **Treinar** (~13 min, até 13 GB de RAM):
   ```bash
   uv run python -m tools.wakeword.train fetch --acav 400000   # só na primeira vez (1,4 GB)
   uv run --with onnx python -m tools.wakeword.train train     # o anterior vira condessa.onnx.bak
   ```
4. **Avaliar**: `uv run python -m tools.wakeword.evaluate` mostra acerto e falsos/h por limiar e
   `patience`, e sugere o par. Meta: ≥ 95% de acerto e ≤ 0,5 falso/h.
5. **Ajustar**: no config, `[satellite] wake_threshold` (mais alto = menos falsos, mais "não
   ouviu") e `wake_patience` (quantos blocos de 80 ms seguidos acima do limiar). Valem ao salvar.
   Trocou o `.onnx`? `systemctl --user restart magi-satellite`. Voltar pro provisório:
   `wake_model = "hey_jarvis"`.

Hoje: 0 falso/h nas 1,6 h de teste, mas 10 de 11 acertos (perde com música alta).

## 13. Problemas comuns

| Sintoma | O que fazer |
| --- | --- |
| Papel de parede ficou preso num print | `python3 ~/.local/share/gamerhud/gamerhud.py --restore`. O vigia também tenta a cada 30 s quando o HUD não está aberto. |
| Ela não entende / entende errado | Olha o log da seção 11: `ouvi "..."` mostra o que chegou. Corta no meio? Aumenta `end_silence_ms`. Voz baixa? `vad_threshold = 0.4`. Liga `save_audio` e escuta. Corrige na hora com "não, eu falei X". |
| Não acorda com "Condessa" | Log do satélite; tenta baixar `wake_threshold` um pouco ou usa Pause/PS+Share. Em call no Discord ela só responde ao atalho. |
| Acorda sozinha | Sobe `wake_threshold` (ex.: 0.7) ou `wake_patience`. |
| Spotify não toca o que pedi | Sem login a busca por nome não funciona: `uv run magi-spotify-login`. O app precisa estar instalado (flatpak); ela espera até 15 s o MPRIS. Token renovado fica no keyring (`spotify-token`). |
| DualSense não achado | O satélite procura de novo sozinho; confere no log `DualSense em /dev/input/...`. Precisa do controle conectado (USB/Bluetooth) e da ACL `uaccess` do udev (sessão local). `[satellite] ptt_dualsense = false` desliga. |
| Pause não funciona | Atalho registrado no KDE (componente `magi-satellite`, ação `push_to_talk`): confere em Configurações do Sistema → Atalhos. Troca com `ptt_key`. |
| Sem voz / serviço caído | `systemctl --user status magi-core magi-satellite`; `restart`. Eles reiniciam sozinhos se cair. |
| Erro de chave / "não peguei" | `uv run magi-keys list` mostra se as chaves do config estão no keyring. |
| Banco fora | `docker ps` deve mostrar `magi-pg`; sobe com `docker compose -f deploy/docker-compose.yml up -d`. Sem banco, memória, notícias, gosto musical e registro de gasto não funcionam; as correções valem só até reiniciar. |
| Gasto estourou | Card no HUD; "aumenta o teto pra N dólares" ou espera virar o mês. |
| "A casa está fora do ar." | A `magi-casa` não está rodando ou falta o `~/.config/magi/casa.token`: `systemctl --user status magi-casa` (a unit é copiada pelo instalador, mas não habilitada). Veja a seção 15. |
| Celular: "Sem conexão com a Ayanami — ligue o Tailscale" | O app do celular só fala com a Ayanami pelo Tailscale: ligue o Tailscale no celular e tente de novo. |

## 14. Custos e desempenho

**Custos** (preços em `config.example.toml`, medidos no spike S3):

| Item | Preço |
| --- | --- |
| Agente `gpt-5.4-mini` | US$ 0,75 / 4,50 por 1M tokens (entrada/saída); ~US$ 0,0003 por turno curto |
| Transcrição `gpt-transcribe` | US$ 0,0045 por minuto de áudio |
| Voz `gpt-4o-mini-tts` (voz `nova`) | ~US$ 20 por 1M caracteres (estimativa ≈ US$ 0,015/min); frases curtas ficam em cache |
| Embeddings `text-embedding-3-small` | US$ 0,02 por 1M tokens |
| Pesquisa | Gemini 2.5 Flash na cota gratuita; reserva paga na OpenAI ~US$ 0,017 por pesquisa |
| Notícias | Gemini na cota gratuita |
| Teto | `monthly_usd = 5.0` no exemplo |

**Desempenho** (`docs/perf/fase1.md`, medido ao vivo em 2026-10-03):

| Medida | Meta | Agora |
| --- | --- | --- |
| CPU com ela dormindo (satélite + núcleo + Postgres) | ≤ 2% de um núcleo | 1,12% |
| RAM dormindo | ≤ 300 MB | 233 MB |
| Comando conhecido, fim da fala → ação | ≤ 1,5 s p90 | 1,17 s |
| Pergunta ao agente, fim da fala → voz | ≤ 3 s p90 | 3,39 s (fora por pouco) |
| Falsos disparos da Condessa | ≤ 1 por hora | 0/h nas 1,6 h de teste (falta 1 h de jogo real) |
| HUD wired (CPU) | 10% painel / 3% espera | ~1,5% / ~0,3% |

## 15. Casa, Ayanami e celular

SDD em [`specs/ayanami-central/`](../specs/ayanami-central/). O código está no `main`, mas a
Ayanami **ainda não está no ar** (falta o Pedro provisionar o node 2 e fazer o primeiro deploy) e a
validação ao vivo (F.1) não foi feita: tempos, telas e comportamento real das TVs e do celular
estão **a confirmar no F.1**.

### O que é cada parte

| Parte | Onde roda | Para quê |
| --- | --- | --- |
| **Ayanami** | node 2 (VPS), em Docker, só no Tailscale | API central: notícias, backup, fila de jobs, MCP, modo nuvem (responde quando o PC está desligado e depois passa a conversa para a memória do PC), Web Push, e serve o PWA em `/app/` |
| **Casa** (`magi-casa`) | PC (ou um Pi, depois) | Controla as TVs pela rede de casa. A Condessa usa pelas intents `tv.*` |
| **Celular** (PWA) | Android, instalado pelo Chrome | Conversa por texto e voz, controle das TVs, confirmações e notificações |

### Casa: parear uma TV

```bash
uv run magi-casa descobrir                        # lista as TVs achadas (SSDP + mDNS)
uv run magi-casa nomear 1 sala "TV da sala"       # linha, chave ou IP do descobrir → casa.toml
uv run magi-casa nomear 2 quarto "TV do quarto" --apelido quarto --driver roku
uv run magi-casa parear sala                      # Samsung: "Permitir" na TV (60 s); Android TV: código de 6 caracteres; Roku: nada
uv run magi-casa testar sala power_off            # ações: power_on, power_off, volume, mute, app, input, key, text, state
uv run magi-casa testar sala app app=netflix
uv run magi-casa estado
systemctl --user enable --now magi-casa           # sobe a API local (magi-casa servir)
```

- O `casa.toml` fica em `~/.config/magi/`; tokens e certificados das TVs em
  `~/.local/share/magi/casa/` (`0700`). `magi-casa esquecer <tv>` apaga um pareamento.
- No `config.toml`, a seção `[casa]` é opcional (padrão: ligada, `127.0.0.1:10760`).
- Pela voz: "Condessa, liga a TV", "desliga a TV da sala", "abre a Netflix na TV". Toda frase de
  TV precisa ter "TV"/"televisão", o nome da TV ou "HDMI"; "aumenta o volume" sozinho continua
  sendo o volume do PC.
- **Samsung:** para ligar a TV pela rede, ative **"Ligar com celular"** (Power On with Mobile) nas
  configurações da TV. Sem isso ela só desliga e a Condessa avisa que não conseguiu ligar.
- **Roku:** em Configurações → Sistema → Configurações avançadas → Controle por apps móveis, deixe
  **"Acesso à rede"** em *Ativado*. Em *Limitado* (Roku OS 14.1.4+) a TV recusa os comandos.
- Comportamento com as TVs reais (Spike S2): **a confirmar no F.1**.

### Celular: instalar o PWA e parear

1. Tailscale ligado no celular (a Ayanami só existe dentro do tailnet; nada fica exposto na
   internet).
2. Peça o código de pareamento no PC:
   - pela voz: **"Condessa, pareia o celular"** — *quando a tarefa Y6.6b entrar* (mostra o código
     no HUD);
   - hoje: `uv run python -m magi.elo.parear --nome celular-pedro` imprime o código de 6 dígitos
     (vale 5 min, uso único), a URL `…/app/#/parear?c=<código>` e, se a lib `qrcode` estiver
     instalada, o QR em texto.
3. Abra a URL no Chrome do celular (ou leia o QR) e confirme. O código nunca vai para log.
4. Chrome → menu → **"Instalar app"** (vira WebAPK, com ícone próprio). O app empacotado (TWA) fica
   para depois.
5. **Push:** em Ajustes, ligue o interruptor de notificações; o Chrome pede a permissão nesse toque.
   Notificação com a tela bloqueada e instalação: **a confirmar no F.1** (Spike S4).

Se o app mostrar "sem conexão com a Ayanami — ligue o Tailscale", é o Tailscale do celular
desligado (ou a Ayanami fora do ar).

### PC ligado à Ayanami

No `config.toml`, a seção `[ayanami]` (comentada no `config.example.toml`) aponta para a URL da
Ayanami no tailnet. O token do PC fica no keyring (serviço `magi`, nome `ayanami_pc`) ou em
`~/.config/magi/ayanami.token` (`0600`), nunca no config. Com ela, `magi-news-sync.timer` puxa as
notícias a cada 15 min (a coleta local só roda se a nuvem passar 6 h sem entregar) e
`magi-backup.timer` manda o backup do PC. Sem a seção o PC funciona sozinho, como antes.

### Domínio

O nome previsto é `ayanami.dekasis.com.br`, apontando para o endereço da Ayanami **dentro do
Tailscale** (acesso continua só privado; o DNS é do Pedro). Hoje o código e os scripts usam o nome
`ayanami.<tailnet>.ts.net` do `tailscale serve`. O certificado do `tailscale serve` é do nome
`.ts.net`; usar o nome próprio pede certificado próprio. **A decidir pelo Pedro / a confirmar no
F.1.**

### Node 2 compartilhado com o Minecraft

O node 2 também roda o servidor de Minecraft (núcleos 0-5, 13 GiB). A Ayanami fica nos **núcleos
6-7** com ~6,4 GiB no total, pelo override `deploy/ayanami/compose.node2.yml`, ligado com
`COMPOSE_FILE=compose.yml:compose.node2.yml` no `.env` do node 2. Limites por serviço e comandos:
[runbook §3](ayanami/runbook.md#perfil-node-2-compartilhado-y10b).

### Vigia (alertas do node 2)

`deploy/ayanami/vigia/vigia.py` roda no host do node 2 a cada minuto (`ayanami-vigia.timer`) e manda
alerta no Telegram (1 mensagem por causa a cada 6 h) quando: a `/saude` falha 3 vezes, o disco passa
de 85%, um worker fica sem batimento por 5 min, o backup do PC ou da Ayanami passa de 36 h, um
backup falha ou o restore de teste fica vermelho; e, do servidor: CPU do Minecraft > 95%, RAM livre
< 1 GiB, swap > 6 GiB, Minecraft parado/reiniciado ou TPS < 15. Tudo vai também para
`/opt/ayanami/dados/servidor.json` (para a Condessa responder "como está o servidor?" — a rota/tool
que lê esse arquivo está em andamento, Y1.3c). O que fazer em cada alerta:
[runbook §8](ayanami/runbook.md#8-alertas-do-vigia-telegram).
