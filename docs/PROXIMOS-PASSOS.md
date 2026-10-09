# Próximos passos

O MVP está implementado (ver [`README.md`](../README.md)). Nada novo vai ser implementado agora; isto
é o que fica para depois, cada item com **por quê**, **o que falta** e **como validar**. Fontes:
`specs/magi-assistant/tasks.md` (itens `[ ]`), [`docs/perf/fase1.md`](perf/fase1.md),
[`docs/spikes/S4.md`](spikes/S4.md) e os relatórios das tarefas.

## 1. Wake word "Condessa" — resolvido no uso (2026-10-07)

No teste de bancada acertava 90,9% (meta 95%), mas no uso real o Pedro não teve problema: tarefas
0.7/0.8 fechadas. Se voltar a falhar com música/jogo alto, o caminho está no
[GUIA §12](GUIA.md#12-condessa-wake-word) (gravar positivas com jogo e re-treinar).

## 2. Latência do agente — meta aceita; o foco vira a espera

p90 de 3,39 s ficou bom pela qualidade da resposta. Em vez de cortar tempo, a espera vai ficar
viva: animação de "pensando" mais expressiva, uma frase curta relacionada enquanto ela pensa e,
em pedidos complexos, resposta em lotes (ela entrega uma parte enquanto prepara a próxima).

## 3. Validações ao vivo pendentes

Implementado e testado com dublês; falta conferir no uso real:

| Item | O que conferir |
| --- | --- |
| 5.2 Mudo só para o Discord | **Prioridade baixíssima (Pedro, 2026-10-09).** Numa call: segurar Pause/PS+Share muta só o Discord e restaura ao soltar; derrubar o satélite no meio e ver o mudo voltar ao reiniciar. |
| 1.26 Reconhecimento | Depois das mudanças (fim de fala 1 s, fala mínima 240 ms, ganho automático): usar alguns dias e conferir no log `ouvi "..."` se a queixa "reconhece mal" sumiu. |

Conferidos pelo Pedro em 2026-10-09: **U4 LED do HUD**, **2.5 "Coloca uma boa"**, **U5 papel de
parede**, **clique no rosto** (ouve sem wake word) e **digitação no Konsole** (texto e setas).

## 4. Lacunas conhecidas

| Lacuna | Por quê / o que falta | Como validar |
| --- | --- | --- |
| ~~Conquistas da Steam (4.5)~~ | **Feito (2026-10-07):** `magi/core/steam_local.py` lê horas e conquistas do disco; linha no prompt, gancho `achievements_idle` ligado e ferramenta `steam_game`. | "quantas horas eu tenho no Persona?"; travado há muito sem conquista pula para a dica direta. |
| Tags da Steam via SteamSpy | Gênero do jogo (sugestão de música, "coloca uma boa") vem de serviço de terceiro (cache em `~/.cache/magi/steam-tags.json`); pode sair do ar ou mudar. | Trocar por fonte oficial ou aceitar o risco; teste: jogo novo recebe tags. |
| "A seguir" no Now playing | O bloco fica escondido: a fila do Spotify precisaria de um escopo novo no OAuth. | Pedir o escopo, refazer `magi-spotify-login` e ver a próxima faixa no HUD. |
| Limites da memória sem calibração | `MIN_SCORE 0,35` (busca), `FORGET_MIN_SCORE 0,45` ("esquece"), `DUPLICATE_SCORE 0,93` (duplicata) foram escolhidos sem dados reais. | Revisar com 2 semanas de memórias reais: lembranças irrelevantes ou duplicadas indicam ajuste. |

## 5. Uso real de 2 semanas

| Tarefa | O que é |
| --- | --- |
| 4.6 Frases de ouro, rodada 2 | Ampliar as frases de teste com 2 semanas de turnos reais (RNF-07: ≥ 95% de acerto em comandos conhecidos). |
| 7.1 Medição final | Medir todos os RNF e registrar em `docs/perf/mvp.md`. O uso sai de `magi-uso` (métricas do PRD direto do banco); com 4 dias (2026-10-07): 24,5 interações/dia, 0,2 correção a cada 20, 2 pulos em 18 escolhas, custo projetado US$ 3,04 de 5. |
| 7.2 Métricas do PRD | Conferir as métricas de sucesso do PRD depois de 2 semanas de uso. **Precisa do Pedro.** |

## 6. Operação

- **Mover o repo de lugar:** já feito uma vez (`~/projetos` → `~/Documentos`). Parar
  `magi-core`/`magi-satellite`/`magi-ayanami.timer`, mover a pasta, apagar o `.venv` (os scripts dele
  guardam o caminho antigo) e rodar `hud/install.sh --start`: ele repõe o link
  `~/.local/share/gamerhud`, as units, o atalho "Gravar voz da Condessa" e o `uv sync`. O Postgres
  não muda (projeto compose `magi`, volume `magi_magi-pgdata`).
- **Satélite no Raspberry Pi (futuro, R22):** o protocolo já é Wyoming + eventos `magi-*` com
  identificador de satélite; falta empacotar o `magi-satellite` para ARM e um áudio de saída no Pi.

## 7. Condessa no HUD (retrato 2.5D, reações e conselho)

- **Feito:** retrato 2.5D em partes a 60 fps (respiração, cabelo em pêndulo, olhar com parallax,
  boca pela voz, fundo com parallax que muda de cor pelo humor e cresce com a voz); reações só no
  rosto ao HUD, à música e aos cliques (`hud/wired/reactions.py`); personalidade e gosto decididos
  pelo **Conselho da Condessa** (`persona/`, comando `/conselho`).
- **Reações (2026-10-09):** as 110 do Conselho implementadas (SDD `specs/condessa-reacoes/`, todas
  as tarefas R0–R3 feitas); 108 ativas (49 e 68 foram substituídas). Sinais novos ligados: retrato
  clicável/hover, tag do turno (elogio/zoeira/correção/sussurro), hooks do Claude Code (instalados no
  `~/.claude/settings.json`), volume do PipeWire, notificações (D-Bus, só escuta), ventoinha,
  reinício pendente, capturas e `[datas]`. Arte nova montada (E3, B16, B17, P9–P13); os efeitos D
  ficam em código por decisão do Pedro (animação própria).
- **O que falta:**
  - **Semana de validação** (até ~16/10): `uv run python -m hud.tools.reacoes_relatorio` e o roteiro
    `docs/perf/reacoes.md` (limiares chutados: sussurro −42 dBFS, ventoinha, capturas).
  - **P13** (braços cruzados) refeito com os braços na altura do peito: hoje cai na faixa em que o
    corpo esmaece e quase some.
  - **Favoritas do Pedro** automáticas: hoje só por `[pedro] favoritas` no
    `~/.config/magi/condessa-gosto.toml`; dá para puxar do top do Spotify (o núcleo já tem o OAuth).
  - **"Condessa, sem comentário de música"** por voz: hoje só pelo arquivo (`[falas] musica = false`).
- **Como validar:** uma semana de uso olhando se as reações e falas aparecem na medida (sem
  poluir) e se a Favorita do Dia/madrugada fazem sentido; CPU do HUD ≤ 10% de um núcleo.

## 8. Autoconserto — retomado (2026-10-07)

Níveis 0 e 1 implementados (ver `docs/design/AUTOCONSERTO.md`). **Como validar:** derrubar um
serviço de propósito (`systemctl --user stop magi-ayanami` e um `kill -9` no `magi-satellite`), ouvir
a pergunta, dizer "sim", ver o diagnóstico no card; depois "prepara um conserto" num bug simples
de teste e "aplica o conserto" para ver o vigia reiniciar (e desfazer, se quebrar).

## 9. Validações ao vivo das features novas

| Item | O que conferir |
| --- | --- |
| FIFA 22 por voz | "Bora bater uma bola": abre o `fifaconfig` centralizado no monitor principal; FPS do MangoHud aparece no HUD e trava em 188. |
| Faxina do SSD | O timer diário (`magi-clean`) roda, a Magui avisa e a Condessa sorri no HUD. |
| Rádio Ayanami | Notícias em PT, "quer ouvir outra?", "conta mais dessa" com resumo local. |

## 10. Decisões em aberto

- **Nome da assistente:** "Magui" (nome no código, persona e HUD) ou "Condessa" (palavra de
  ativação e rosto do HUD).
- **Voz local (prioridade baixa, decidir depois):** trocar a síntese da OpenAI por uma local
  (sem custo, sem rede). Caminhos: clonar a `marin` a partir de `~/Music/magi-vozes/condessa-jovem`
  (F5-TTS/XTTS em PT-BR; medir latência na RX 9060 XT ou CPU) ou o Kokoro, já baixado em
  `~/.cache/magi/kokoro` (leve, voz `pf_dora`, mais robótica). Também abre a porta para a Ayanami
  ter voz própria no rádio.
- **Voz:** decidida — `gpt-4o-mini-tts` com a voz `marin` e instruções de voz jovem
  (`~/.config/magi/config.toml`). Alternativas locais ficaram em `~/Music/magi-vozes/`.

## 11. Nova UI do painel e Konsole (2026-10-08)

Feito: painel redesenhado pelo mockup (`docs/design/nova-ui/`), Konsole interativo do Claude Code
no HUD (troca de lugar com o CAM 01 ao expandir), dados novos (clock, swap, disco, IP/DNS, git).
Regra do KWin "MAGI Gamer" sem `acceptfocus` forçado (backup `~/.config/kwinrulesrc.bak-acceptfocus`).
`settings.json` do HUD com `konsole_cwd = /home/pedrojr` (memória do Claude Code e `/resume`).

Próximos passos, em ordem:
1. ~~**Konsole persistente com tmux**~~ — feito: o `claude` roda em `tmux -L magi` (sessão
   `magi-claude`, config `hud/tmux-magi.conf`, sem barra/prefixo, `escape-time 0`); fechar o HUD
   só desconecta, e ao abrir o HUD reconecta sozinho. `konsole_tmux: false` no `settings.json`
   volta ao pty direto. Encerrar de vez: `tmux -L magi kill-session -t magi-claude` (ou sair do
   claude). Mudou o `.conf`? `tmux -L magi kill-server`.
2. ~~Konsole: TOKENS na barra de status; linhas cortadas no card recolhido~~ — feito: TOKENS =
   contexto do último turno (entrada + cache) lido do transcript via `~/.claude/sessions/<pid>.json`
   (`TokenMeter`); o card encolhe a fonte (até 7 px do mockup) para caber a largura da sessão.
3. Testes manuais: ~~digitação no Konsole (texto, setas)~~ conferida em 2026-10-09; falta ver o foco
   voltar ao recolher, o HUD não roubar o foco do jogo sem clique e a digitação na tela learning.
4. Learning Mode onda 6: LM3.4 (balão com resultado real), LM4.2, LM4.3 (observações na tela),
   LM1.8 (tema da sessão) — `specs/learning-mode/tasks.md`. Learning ligado na config, ações no
   gpt-5.4-mini, observações no Qwen local (`magi-qwen`, só CPU, só durante a aula).
5. ~~Pendências antigas~~ — feito (2026-10-09): tokens `glpat` tirados dos remotes, do
   `~/.gitconfig`, do `~/.git-credentials` e do `glab` (os acessos já estavam revogados);
   `scratch/` no `.gitignore`; `LearningConfig.enabled` já tinha padrão True. O comando
   `magi learning` de terminal foi descartado pelo Pedro.
6. ~~`git push` da `main`~~ — feito (2026-10-09).

## 12. Voz e serviços (2026-10-09)

- **Clique no rosto faz ela ouvir:** o `push_to_talk` do HUD agora ativa sem wake word e pede uma
  escuta ao satélite (`magi-listen`, `reason="tap"`), que termina pelo VAD.
- **Keyring trancado na subida:** a fala que chega sem STT faz o núcleo reler as chaves e remontar
  voz e agente (`Core.revive`, no máximo a cada 30 s). Antes, só reiniciando o `magi-core`.
- **`docker down-all`** (função no `~/.bashrc`) não derruba mais o projeto compose `magi`: ele tinha
  apagado o `magi-pg` (memórias, volume intacto) e o `magi-qwen`; os dois foram recriados.
- **Microfone em zero:** se o log do satélite disser "silêncio digital (só zeros)", é o mudo físico
  do headset (ELITE 08), não o software.

Próximos passos, do mais rápido ao mais trabalhoso:
1. Foco do Konsole (seção 11, item 3) e o reconhecimento de voz no uso (seção 3).
2. Refazer o P13 (seção 7).
3. Espera mais viva (seção 2): animação de "pensando", frase curta e resposta em lotes.
4. Learning Mode onda 6 (LM3.4, LM4.2, LM4.3, LM1.8), em agentes por tarefa como as reações.
5. Depois de uso: semana de validação das reações (~16/10) e calibração da memória (seção 4).
