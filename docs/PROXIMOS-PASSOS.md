# Próximos passos

O MVP está implementado (ver [`README.md`](../README.md)). Nada novo vai ser implementado agora; isto
é o que fica para depois, cada item com **por quê**, **o que falta** e **como validar**. Fontes:
`specs/magi-assistant/tasks.md` (itens `[ ]`), [`docs/perf/fase1.md`](perf/fase1.md),
[`docs/spikes/S4.md`](spikes/S4.md) e os relatórios das tarefas.

## 1. Condessa: acerto abaixo da meta (tarefas 0.7 / 0.8)

- **Por quê:** o modelo atual dá 0,00 falso/h (patience 3, limiar 0,6–0,8) mas acerta **90,9%**
  (10 de 11 positivas reservadas); a meta é ≥ 95%. A perdida é fala sob música alta (nota 0,25).
  Também falta medir falsos disparos com áudio real de jogo (RNF-06: ≤ 1/h).
- **O que falta:** gravar ~10 positivas extras "com jogo/música alta" (app "Gravar voz da Condessa",
  `--section positive`) e ~1 h de jogo normal em `~/.local/share/magi/wakeword-data/condessa/eval/`
  (`pw-record`, ver [GUIA §12](GUIA.md#12-condessa-wake-word)); re-treinar.
- **Como validar:** `uv run python -m tools.wakeword.evaluate` com ≥ 95% de acerto e ≤ 0,5 falso/h
  incluindo o `eval/`; depois uma sessão real de jogo sem disparo falso e sem "não ouviu".

## 2. Pergunta ao agente acima de 3 s (RNF-05)

- **Por quê:** p90 **3,39 s** (meta 3 s; média 2,81 s). O tempo é STT (~0,7 s) + modelo (~1–1,5 s)
  + primeiro byte do TTS (~0,6–0,9 s), em série.
- **O que já foi tentado:** 1.23 (otimizações), 1.24 (fala por frase em streaming, ganho pequeno
  porque as respostas costumam ter uma frase só) e 1.25 (transcrição enquanto fala): a 1.25 foi
  testada e **não ajudou** (~70 ms com `gpt-transcribe`; o `gpt-live-transcribe` transcreve pior e
  custa 3,8×), então fica **desligada** (`streaming = false`).
- **Opções:** modelo de agente mais rápido; atacar o primeiro byte do TTS; ou rever a meta para
  3,5 s.
- **Como validar:** `uv run python -m tools.perf latency --turns 10 --phrase "quantas patas tem uma
  aranha" --gap 3` com p90 ≤ 3 s (ou a meta revista registrada em `requirements.md`).

## 3. Validações ao vivo pendentes

Implementado e testado com dublês; falta conferir no uso real:

| Item | O que conferir |
| --- | --- |
| 5.2 Mudo só para o Discord | Numa call: segurar Pause/PS+Share muta só o Discord e restaura ao soltar; derrubar o satélite no meio e ver o mudo voltar ao reiniciar. |
| U4 LED do HUD | Com o OpenRGB ligado, clicar no LED e ver unidades MAGI, rubor do mascote e trilho da espera tingindo com a cor da placa-mãe. |
| 2.5 "Coloca uma boa" | No Spotify real, com login: escolha faz sentido pelo gosto/jogo e o caminho `/artists/{id}/top-tracks` da Web API responde. |
| U5 Papel de parede | Desligar o PC (ou encerrar a sessão) com o HUD aberto e ver o Wallpaper Engine voltar no login seguinte. |
| 1.26 Reconhecimento | Depois das mudanças (fim de fala 1 s, fala mínima 240 ms, ganho automático): usar alguns dias e conferir no log `ouvi "..."` se a queixa "reconhece mal" sumiu. |

## 4. Lacunas conhecidas

| Lacuna | Por quê / o que falta | Como validar |
| --- | --- | --- |
| Conquistas da Steam na ajuda no jogo (4.5) | Não há leitura local simples (cache binário; Web API pede chave + steamid). O gancho `achievements_idle` existe, mas o núcleo não liga nenhum, então "travado" só usa pedidos repetidos e tempo. | Ligar uma fonte de conquistas e ver o degrau pular para dica direta depois de muito tempo sem conquista. |
| Tags da Steam via SteamSpy | Gênero do jogo (sugestão de música, "coloca uma boa") vem de serviço de terceiro (cache em `~/.cache/magi/steam-tags.json`); pode sair do ar ou mudar. | Trocar por fonte oficial ou aceitar o risco; teste: jogo novo recebe tags. |
| "A seguir" no Now playing | O bloco fica escondido: a fila do Spotify precisaria de um escopo novo no OAuth. | Pedir o escopo, refazer `magi-spotify-login` e ver a próxima faixa no HUD. |
| Limites da memória sem calibração | `MIN_SCORE 0,35` (busca), `FORGET_MIN_SCORE 0,45` ("esquece"), `DUPLICATE_SCORE 0,93` (duplicata) foram escolhidos sem dados reais. | Revisar com 2 semanas de memórias reais: lembranças irrelevantes ou duplicadas indicam ajuste. |
| Histórico curto some ao reiniciar | O histórico da conversa do agente fica só na memória do processo; reiniciar o `magi-core` zera o contexto recente. | Reabastecer a partir do histórico local/banco ao subir; teste: reiniciar e perguntar "e aquilo que eu falei?". |
| "Esquece isso" pode apagar memória antiga | Sem memória recente, apaga a mais parecida, que pode ser antiga. | Confirmar antes de apagar algo que não seja da conversa atual. |

## 5. Uso real de 2 semanas

| Tarefa | O que é |
| --- | --- |
| 4.6 Frases de ouro, rodada 2 | Ampliar as frases de teste com 2 semanas de turnos reais (RNF-07: ≥ 95% de acerto em comandos conhecidos). |
| 7.1 Medição final | Medir todos os RNF e registrar em `docs/perf/mvp.md`. |
| 7.2 Métricas do PRD | Conferir as métricas de sucesso do PRD depois de 2 semanas de uso. **Precisa do Pedro.** |

## 6. Operação

- **Mover o repo para `~/Documentos`:** mover a pasta, repontar o link
  (`ln -sfn <novo>/hud ~/.local/share/gamerhud`), rodar `hud/install.sh` de novo (as units do
  systemd guardam o caminho em `ExecStart`, e o atalho do menu "Gravar voz da Condessa" também) e
  reiniciar HUD e serviços (`systemctl --user restart magi-core magi-satellite`). Validar com
  `systemctl --user status` e abrindo o HUD.
- **Satélite no Raspberry Pi (futuro, R22):** o protocolo já é Wyoming + eventos `magi-*` com
  identificador de satélite; falta empacotar o `magi-satellite` para ARM e um áudio de saída no Pi.

## 7. Decisões em aberto

- **Nome da assistente:** "Magui" (nome no código, persona e HUD) ou "Condessa" (hoje só a palavra
  de ativação).
- **Voz:** hoje `gpt-4o-mini-tts` com a voz `nova`; ouvir as alternativas em `~/Music/magi-vozes/`
  e decidir. Troca a quente em `[tasks] tts.voice`.
