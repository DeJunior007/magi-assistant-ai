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

## 5. Uso real de 2 semanas

| Tarefa | O que é |
| --- | --- |
| 4.6 Frases de ouro, rodada 2 | Ampliar as frases de teste com 2 semanas de turnos reais (RNF-07: ≥ 95% de acerto em comandos conhecidos). |
| 7.1 Medição final | Medir todos os RNF e registrar em `docs/perf/mvp.md`. |
| 7.2 Métricas do PRD | Conferir as métricas de sucesso do PRD depois de 2 semanas de uso. **Precisa do Pedro.** |

## 6. Operação

- **Mover o repo de lugar:** já feito uma vez (`~/projetos` → `~/Documentos`). Parar
  `magi-core`/`magi-satellite`/`magi-news.timer`, mover a pasta, apagar o `.venv` (os scripts dele
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
- **O que falta:**
  - **B15** (olhos totalmente fechados, dormindo): gerar e rodar `hud/tools/condessa_build.py`.
  - **D1–D9** (rubor, suor, zz, ?, !, notas, lágrima, veia, brilho) como arte: hoje são desenhados
    em código; com a arte, trocar pelo PNG.
  - **Favoritas do Pedro** automáticas: hoje só por `[pedro] favoritas` no
    `~/.config/magi/condessa-gosto.toml`; dá para puxar do top do Spotify (o núcleo já tem o OAuth).
  - **"Condessa, sem comentário de música"** por voz: hoje só pelo arquivo (`[falas] musica = false`).
  - Reações a mais da persona: Claude Code concluindo, PC travado/jogo caiu (emburrada leve, rara).
- **Como validar:** uma semana de uso olhando se as reações e falas aparecem na medida (sem
  poluir) e se a Favorita do Dia/madrugada fazem sentido; CPU do HUD ≤ 10% de um núcleo.

## 8. Autoconserto

- **Feito:** painel do Claude Code no HUD (tokens do dia, janela de 5 h, sessões rodando).
- **Parado:** o autoconserto (a Magui chamar o Claude Code sozinha) foi bloqueado pelo classificador
  de segurança; o código está num `git stash` ("autoconserto (bloqueado…)"). **Decisão do Pedro:**
  descartar o stash ou retomar só no nível A (diagnóstico, sem editar nada) depois de liberar a
  permissão. Proposta e limites em `docs/design/AUTOCONSERTO.md`.

## 9. Validações ao vivo das features novas

| Item | O que conferir |
| --- | --- |
| FIFA 22 por voz | "Bora bater uma bola": abre o `fifaconfig` centralizado no monitor principal; FPS do MangoHud aparece no HUD e trava em 188. |
| Faxina do SSD | O timer diário (`magi-clean`) roda, a Magui avisa e a Condessa sorri no HUD. |
| Rádio Ayanami | Notícias em PT, "quer ouvir outra?", "conta mais dessa" com resumo local. |

## 10. Decisões em aberto

- **Nome da assistente:** "Magui" (nome no código, persona e HUD) ou "Condessa" (palavra de
  ativação e rosto do HUD).
- **Voz:** decidida — `gpt-4o-mini-tts` com a voz `marin` e instruções de voz jovem
  (`~/.config/magi/config.toml`). Alternativas locais ficaram em `~/Music/magi-vozes/`.
