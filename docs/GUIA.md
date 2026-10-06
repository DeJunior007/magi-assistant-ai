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
| Notícias | "alguma novidade?", "o que saiu de novo de Frieren?", "pode dar spoiler de X", "não curti", "mais disso", "larguei X" |
| Pesquisa | qualquer coisa recente ("quando sai o próximo Zelda?"): Gemini com Google; links vão pro HUD |
| Tela (visão) | "que bicho é esse?", "o que tá escrito aqui?" (janela ativa); "...na tela" pega o monitor todo. Só quando você pede; a captura é apagada depois |
| Ajuda no jogo | "como passo do boss da lua?", "manda a solução" |
| Confirmação | "confirma"/"sim" ou "cancela"/"não" |

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

- `magi-news` roda a cada 2 h (timer systemd): Steam News dos jogos instalados, AniList da sua
  lista, Reddit (r/anime, r/Games), RSS e scraping. Agrupa a mesma notícia de várias fontes,
  classifica e prioriza.
- Entrega: **bomba** = frase + card (voz só fora de call); **alta** = só card. No máximo 2 por hora
  e 8 por dia; mais velha que 48 h é descartada.
- **Anti-spoiler**: manchete reescrita ou escondida para o que você ainda não viu/jogou.
  "pode dar spoiler de X" libera aquela obra.
- Retorno: "não curti" / "mais disso" mexem no peso da obra da última notícia; ignorar a mesma obra
  3× seguidas também baixa; "larguei X" para de priorizar.
- "Alguma novidade?" traz até 5 itens; sem nada guardado, ela pesquisa na internet.
- Fontes padrão em `magi/news/sources.toml`; acrescenta ou desliga em `[[news.sources]]` no config.

## 7. Memória, humor e ajuda no jogo

**Memória.** Ela guarda fatos duradouros (gostos, o que você está jogando, planos, "lembra
que...") no Postgres e busca até 5 parecidos a cada pergunta. "**Esquece isso**" apaga a última
memória guardada (ou a mais parecida com o que você disser). Um perfil curto de estilo (gírias,
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
| Serviços | `~/.config/systemd/user/magi-satellite.service`, `magi-core.service`, `magi-news.service` + `magi-news.timer` |
| Logs | `journalctl --user -u magi-core -u magi-satellite -u magi-news`; HUD em `~/.cache/gamerhud/hud.log` |
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
