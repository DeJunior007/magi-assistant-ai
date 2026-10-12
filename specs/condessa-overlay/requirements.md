# Requisitos — Overlay da Condessa

Fonte: `docs/PROXIMOS-PASSOS.md` §13 ("Overlay só da Condessa") e a decisão do Pedro de 2026-10-10
(commit `4fc1759`: clique no rosto só faz reação, não liga a escuta). Este arquivo é o **PRD**.
Arquitetura em [design.md](design.md); contratos e números em [spec.md](spec.md); implementação em
[tasks.md](tasks.md). Critérios em EARS:

- **O overlay DEVE …** — sempre vale. **QUANDO** gatilho, **o overlay DEVE** … — reação a evento.
- **ENQUANTO** estado, **o overlay DEVE** … · **SE** falha, **ENTÃO** … · **ONDE** opção ligada, …

## Problema

A Condessa só aparece dentro do HUD inteiro (`hud/gamerhud.py`), em tela cheia no monitor de cima.
No monitor principal, onde o Pedro trabalha e joga, ela não existe: não dá para vê-la falar,
ouvir ou reagir sem olhar para cima. O Pedro quer uma presença pequena, sempre ali, "como uma
Siri/Alexa".

## Objetivo

Uma janela pequena, sem moldura, só com o retrato em partes (`PartsPortrait`), por cima do
desktop, ligada no login, que reflete o estado da Magui (dormindo, ouvindo, pensando, falando,
boca pela voz) e reage como no HUD, sem pegar foco nem atrapalhar cliques no que está atrás.

## Critérios de sucesso

1. Depois do login, o retrato aparece em ≤ 10 s, na posição de antes, sem mexer no foco.
2. Clique fora da silhueta dela passa para a janela de trás (teste manual em 5 pontos do quadro).
3. CPU do processo do overlay ≤ 3% de um núcleo parada e ≤ 8% falando (medida como em
   `docs/PROXIMOS-PASSOS.md` §7), com o HUD principal aberto ou fechado.
4. Núcleo fora do ar: o overlay continua aberto, dormindo, e volta a reagir sozinho quando o núcleo
   sobe (reconexão da `HudBridge`).
5. Uma semana de uso sem o Pedro fechar o overlay por incômodo (nota dele no fim da O3.2).

## Requisitos

**R1 — Janela.** O overlay DEVE ser uma janela sem moldura, de fundo transparente, sempre acima
das janelas comuns, fora do Alt+Tab, da barra de tarefas e do pager, que não aceita foco.
- R1.1 O overlay DEVE desenhar o retrato num quadro de `tamanho` px (padrão 220, de 120 a 480).
  ONDE `estilo = "card"` (padrão, O4.1): num card com moldura na cor do humor, cantos marcados,
  retrato com fundo (`fundo` forçado) e placa `CONDESSA` + estado; ONDE `estilo = "solto"`: só o
  retrato (sem o fundo de hexágonos, ONDE `fundo = false`).
- R1.2 SE a pasta do retrato não tiver a arte em partes (`portrait.is_parts`), ENTÃO o overlay
  DEVE avisar no log e sair com código 0 (não mostra o mascote vetorial).

**R2 — Cliques atravessam.** No `solto`, o overlay DEVE aceitar mouse só dentro da silhueta dela
(região de entrada); fora dela o clique e a roda DEVEM chegar à janela de trás. No `card` (O4.1) a
região de entrada é o retângulo inteiro do card.

**R3 — Gestos no rosto = reação.** QUANDO o Pedro clica, clica duas vezes, segura ou arrasta (com o
botão esquerdo) no rosto, o overlay DEVE mandar ao `Reactor` os mesmos eventos do HUD
(`on_click("face")`, `on_hover("dbl"|"long"|"arrasto"|"in"|"move"|"out")`). O clique NÃO DEVE
ligar a escuta (decisão de 2026-10-10).

**R4 — Mover e lembrar.** QUANDO o Pedro arrasta com o botão do meio, com o esquerdo no `card`
(O4.1; no card o arrasto move em vez de virar reação), ou usa "Mover" no menu do botão direito, o
overlay DEVE pedir ao compositor o movimento interativo da janela (recusado → move na mão); a
posição DEVE ser lembrada entre sessões (regra do KWin, spec §4; fora do Wayland nativo também em
`~/.local/state/magi/overlay-pos.json`, restaurada antes do canto D6).

**R5 — Estado da Magui.** O overlay DEVE ligar-se ao núcleo como mais um cliente do socket do HUD
(`HudBridge`) e refletir `state`, `mouth`, `mood` e `turn_tag`, como o HUD.

**R6 — Reações próprias.** O overlay DEVE rodar um `Reactor` próprio com os detectores que não
dependem dos sensores do HUD (spec §3) e gravar o registro em `reacoes-overlay.jsonl`, separado do
`reacoes.jsonl` do HUD.

**R7 — Convivência com o HUD principal (D2).** ENQUANTO o HUD principal estiver aberto (trava
`~/.cache/gamerhud/hud.lock` ocupada), o overlay DEVE ficar escondido; QUANDO o HUD fecha, o
overlay DEVE voltar a aparecer no mesmo lugar. Chave `com_hud = "esconde"` (padrão);
`"independente"` mantém os dois.

**R7.1 — Em jogo (D3).** ENQUANTO houver jogo aberto, o overlay DEVE ir para um monitor diferente
do monitor do jogo (`tela_jogo`; padrão: o principal). SE só houver um monitor ligado, ENTÃO o
overlay DEVE sumir enquanto o jogo estiver aberto. QUANDO o jogo fecha, o overlay DEVE voltar ao
monitor e à posição de antes. Chave `em_jogo = "oposto"` (padrão); `"esconde"` some sempre em
jogo; `"fica"` não muda nada.

**R8 — Login.** O overlay DEVE ter autostart no login (`~/.config/autostart/condessa-overlay.desktop`)
e um comando `condessa-overlay` que liga/desliga (como `hud/system/bin/gamerhud`), com trava de
instância única.

**R9 — Configuração.** O overlay DEVE ler `~/.config/magi/overlay.toml` (`tamanho`, `tela`,
`canto`, `margem`, `fundo`, `estilo`, `renderer`, `em_jogo`, `tela_jogo`, `com_hud`, `ligado`); arquivo
ausente ou inválido → padrões do spec §2. Posição inicial (D6): canto **superior direito** do
monitor principal, margem 24 px.

**R10 — Segurança da sessão.** Nenhum arquivo do overlay DEVE chamar `qdbus`/`gdbus` nem falar
com KGlobalAccel/KWin por D-Bus; a regra do KWin é escrita no `kwinrulesrc` pelo `install.sh`, antes
do `reconfigure` que ele já faz.

## Decisões do Pedro (2026-10-10, `specs/DECISOES-2026-10-10.md`)

Valem acima do texto antigo; aplicadas neste SDD na O0.1.

- **D1 — Processo.** ✔ Confirmada (padrão): processo próprio `hud/condessa_overlay.py`, sempre
  ligado, independente do HUD (o núcleo já aceita vários clientes no socket).
- **D2 — Com o HUD aberto.** ⚠ **Mudou:** o overlay **se esconde** enquanto a trava `hud.lock` do
  HUD estiver ocupada e volta quando o HUD fecha (`com_hud = "esconde"`). O espelho fica para depois.
- **D3 — Em jogo.** ⚠ **Mudou:** o overlay **vai para o monitor oposto ao do jogo**; com um
  monitor só, **some** enquanto o jogo estiver aberto e volta ao lugar de antes quando ele fecha
  (`em_jogo = "oposto"`). O monitor do jogo é `tela_jogo` (padrão: o principal, onde o Pedro joga;
  descobrir a janela do jogo exigiria D-Bus do KWin, proibido pelo R10).
- **D4 — Plataforma.** ✔ Confirmada (padrão): Wayland nativo + regra do KWin; recaída XWayland por
  `MAGI_OVERLAY_XCB=1`.
- **D5 — Legenda e moldura.** ✔ Revista pelo Pedro em 2026-10-12 (O4.1): card com moldura
  ("ela tinha que ter um quadradinho pra ela"); só o rosto, sem balão de texto, continua. O estilo
  antigo fica em `estilo = "solto"`.
- **D6 — Canto inicial.** ⚠ **Mudou:** monitor principal, canto **superior direito**
  (`canto = "sup_dir"`), margem 24 px.
