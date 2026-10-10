# Reações da Condessa: validação de uma semana (R3.2)

Roteiro para o Pedro. Critérios de sucesso 3 e 4 do `specs/condessa-reacoes/requirements.md`:
CPU do HUD ≤ 10% de um núcleo e uma semana de uso real sem o rosto "poluído" (≤ 8 ativas por
hora no registro). O que estiver poluindo volta ao Conselho (`/conselho`).

## 0. Semana da vida (V0.9, specs/condessa-vida)

O replay do dia 2026-10-09 (`tests/hud/test_vida_simulacao.py`) passou nas 7 metas do acordo §8
(Conselho 2026-10-10). Agora vale a semana real. O HUD só pega o código novo quando for reaberto.

**Religado no seu gosto** (`~/.config/magi/condessa-gosto.toml`): `[reacoes] desligadas = []`.
`fone_repouso`, `ajeitando_fone` e `cabeca_ritmo` voltaram, porque o fone agora segue a música
e essas passivas só saem com música. Se voltar o "põe e tira o fone no silêncio", desligue de
novo e anote aqui.

**Mudou no `[vida]`** (persona + `VIDA_PADRAO`): `piso_vida_min` 6 → 5,5 (o piso, com o sorteio a
cada 10 s, fica abaixo dos 6 min) e `pedro_sumido` −0,05/15 min → −0,10/10 min (com a meia-vida de
8 min, o −0,05 sumia e ela nunca saía de Contente). A escada do Tédio agora conta o tempo sem
música: o encarando sai aos 15 min sem música, e o "ei, tô aqui" só depois dele, aos 30 min.

**O que conferir na semana:**
- Quando você volta (almoço, jogo longo, cochilo dela), ela faz uma cena de volta, e não só uma olhada.
- Com você no PC, fora de jogo e de conversa, ela nunca fica parada mais de ~6 min.
- Nenhum suspiro, franja ou beicinho sem motivo (Claude te esperando, erro, PC quente, "ei"
  ignorado). Se aparecer, anote a hora para achar no registro.
- Depois de 1 h ou mais fora, ela volta **Neutra** (rosto B1 C1) e sobe de novo quando você
  aparece. Emburrada deve ser rara e curta.
- Jogo longo sem música: no replay, a hora das 14h às vezes ficou **sem nenhuma expressão
  positiva**, porque o grupo Jogando só tem positiva com música (`cabeca_ritmo`). Veja se isso
  incomoda; se incomodar, o assunto volta ao Conselho.
- Silêncio sem nada rodando: encarando por volta dos 15 min, "ei, tô aqui" depois dos 30 min, e
  beicinho só se você ignorar o "ei" por 10 s.
- Nenhuma rajada (3 expressões em 30 s), principalmente na volta com música e jogo juntos.

**Como ler o relatório novo** (`uv run python -m hud.tools.reacoes_relatorio --dias 7`): o bloco
`Vida (por hora)` traz uma linha por tipo, com média por hora e pico.
- `cena + gesto + ativa` ≈ expressões/h. A meta é 12–20/h; o replay deu ~14.
- `atencao` são olhadas dirigidas e não contam como expressão. `repouso` é a troca do rosto
  parado, não uma reação.
- `descartada_sem_causa` é uma negativa que o governador barrou por falta de culpado. Alguns
  casos são normais; muitos indicam um grupo de passivas pedindo negativa demais.
- `Momentos:` mostra a fração das linhas em cada momento. Jogando e Curtindo devem dominar nos
  seus dias, e Tédio alto quer dizer muito silêncio.
- `Faixas:` deve mostrar pelo menos 3 faixas na semana, Emburrada abaixo de 15 % e Radiante acima
  de 0. Se Emburrada passar de 15 %, avise: a Kurisu pediu para a "birra fresca" voltar à mesa.

### Resultado da semana da vida (preencher)

```
(colar a saída do relatório e as horas estranhas aqui)
```

## 1. Antes de começar

- Reabrir o HUD depois de qualquer build da arte (`catalogo.ATIVAS` olha a pasta do retrato só
  na importação).
- Conferir que o registro está sendo gravado: `tail -f ~/.local/state/magi/reacoes.jsonl`
  (cada linha: `t`, `hora`, `chave`, `n`, `variante`, `motivo`, `furou_cota`; gira em 5 MB para
  `reacoes.jsonl.1`, que o relatório também lê).
- Anotar a data de início: ____

## 2. Relatório depois de 7 dias

```sh
uv run python -m hud.tools.reacoes_relatorio --dias 7
# outro arquivo: uv run python -m hud.tools.reacoes_relatorio caminho/reacoes.jsonl --dias 7
```

Mostra: ativas e passivas por hora (média sobre todas as horas cobertas, e pico), ativas "na
cota" (sem `SISTEMA`/`VITORIA`/`VOLTA`), horas acima de 8 na cota, furos de cota por classe,
top 10 e as reações de `ATIVAS` nunca tocadas. Arquivo ausente ou vazio sai com código 0 e aviso.

Atenção: as 19 reações antigas tocam pelo `fire` direto e **não** são gravadas nem contam no teto
(ver calibragens). O relatório só mostra o que passou pelo governador.

### Resultado (preencher)

```
(colar a saída do relatório aqui)
```

## 3. CPU do HUD (≤ 10% de um núcleo)

Com o HUD aberto há ≥ 10 min, num uso típico (música tocando, Claude rodando, um jogo por um
tempo):

```sh
PID=$(pgrep -f gamerhud | head -1)
pidstat -u -p "$PID" 60 10        # 10 amostras de 1 min (pacote sysstat); %CPU é de um núcleo
# sem pidstat: top -b -d 60 -n 10 -p "$PID" | grep "$PID"
```

Referência sem tocar na sessão ao vivo (HUD offscreen, timers reais, R23.8):

```sh
QT_QPA_PLATFORM=offscreen uv run python hud/tools/wired_hud.py bench 120
QT_QPA_PLATFORM=offscreen uv run python hud/tools/wired_hud.py bench 120 awake
```

Medir o HUD ao vivo em três cenários: parado (Magui dormindo), música + Claude, jogo aberto. Passa se a média
de cada cenário ficar ≤ 10%.

### Resultado (preencher)

| Cenário | Média %CPU | Pico %CPU | Passa? |
| --- | --- | --- | --- |
| Parado | | | |
| Música + Claude | | | |
| Jogo aberto | | | |

## 4. Calibragens pendentes (das *Sobras* do `tasks.md`)

Conferir cada item durante a semana; anotar o que mudar.

- [ ] **Sussurro (88, R2.F):** `energy_db < −42 dBFS` escolhido sem medida do satélite. Falar
  baixo de propósito algumas vezes e ver se a 88 sai (e se não sai com voz normal).
- [ ] **Ventoinha (43, R2.G):** rpm ≥ média de 5 min × 1,3 e ≥ 300 rpm (rearma < × 1,15).
  Ver se sai com carga real e não com oscilação à toa.
- [ ] **Capturas (51, R2.G):** arquivo novo com ≤ 120 s na pasta de Imagens (`xdg-user-dir
  PICTURES`). Tirar um print e conferir; ver se a pasta do Spectacle é essa.
- [ ] **Reinício pendente (50, R2.G):** no Nobara o `dnf` é o dnf5; se `dnf needs-restarting -r`
  não existir, a 50 nunca sai. Rodar o comando à mão e ver o código de saída.
- [ ] **I4 (`vergonha`) engolido pelo `fps_drop`:** o `fps_drop` antigo toca no mesmo tick pelo
  `fire`, com prio ≥ a da sequência, e pode engolir a I4. Se ela nunca aparecer no relatório com
  quedas de FPS reais, pular o `fire` antigo quando houver a variante.
- [ ] **19 antigas fora do teto de 8/h:** tocam pelo `fire`, sem registro e sem contar na cota.
  Se o rosto parecer poluído com o relatório abaixo de 8/h, a culpa provavelmente é delas.
- [ ] **Teste instável:** `tests/hud/test_wired_portrait.py::test_partes_ouvindo_acorda_e_fica_atenta`
  falhou ~1 em 5 rodadas (R1.1, R1.6). Investigar fora da semana.
- [ ] **Arte nova (R3.1):** posição e escala dos `extra/D*.png` e `extra/P*.png` (quadro de 1024)
  conferidas com a arte real; I20 só entra em `ATIVAS` com `extra/P13.png` (reabrir o HUD).
- [x] **Hooks do Claude Code (54/55, R2.C):** instalados em 2026-10-09 (`PostToolUseFailure`,
  `Notification`, `Stop`); conferido ao vivo. Na semana, ver se 54/55 aparecem no relatório.

### Ajustes feitos (preencher)

| Item | Valor antigo | Valor novo | Por quê |
| --- | --- | --- | --- |
| | | | |

## 5. Nota do Pedro (preencher)

- Rosto poluído? ____
- Reações que cansaram (levar ao `/conselho` ou `[reacoes] desligadas`): ____
- Reações que faltaram aparecer: ____
