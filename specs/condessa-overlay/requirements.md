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
- R1.1 O overlay DEVE desenhar só o retrato (sem o fundo de hexágonos do HUD, ONDE
  `fundo = false`, padrão) num quadro de `tamanho` px (padrão 220, de 120 a 480).
- R1.2 SE a pasta do retrato não tiver a arte em partes (`portrait.is_parts`), ENTÃO o overlay
  DEVE avisar no log e sair com código 0 (não mostra o mascote vetorial).

**R2 — Cliques atravessam.** O overlay DEVE aceitar mouse só dentro da silhueta dela (região de
entrada); fora dela o clique e a roda DEVEM chegar à janela de trás.

**R3 — Gestos no rosto = reação.** QUANDO o Pedro clica, clica duas vezes, segura ou arrasta (com o
botão esquerdo) no rosto, o overlay DEVE mandar ao `Reactor` os mesmos eventos do HUD
(`on_click("face")`, `on_hover("dbl"|"long"|"arrasto"|"in"|"move"|"out")`). O clique NÃO DEVE
ligar a escuta (decisão de 2026-10-10).

**R4 — Mover e lembrar.** QUANDO o Pedro arrasta com o botão do meio (ou usa "Mover" no menu do
botão direito), o overlay DEVE pedir ao compositor o movimento interativo da janela; a posição DEVE
ser lembrada entre sessões (regra do KWin, spec §4).

**R5 — Estado da Magui.** O overlay DEVE ligar-se ao núcleo como mais um cliente do socket do HUD
(`HudBridge`) e refletir `state`, `mouth`, `mood` e `turn_tag`, como o HUD.

**R6 — Reações próprias.** O overlay DEVE rodar um `Reactor` próprio com os detectores que não
dependem dos sensores do HUD (spec §3) e gravar o registro em `reacoes-overlay.jsonl`, separado do
`reacoes.jsonl` do HUD.

**R7 — Convivência com o HUD principal.** ENQUANTO o HUD principal estiver aberto, o overlay DEVE
seguir a política de convivência da decisão D2 (padrão: continua independente).

**R8 — Login.** O overlay DEVE ter autostart no login (`~/.config/autostart/condessa-overlay.desktop`)
e um comando `condessa-overlay` que liga/desliga (como `hud/system/bin/gamerhud`), com trava de
instância única.

**R9 — Configuração.** O overlay DEVE ler `~/.config/magi/overlay.toml` (`tamanho`, `tela`,
`canto`, `margem`, `fundo`, `em_jogo`, `ligado`); arquivo ausente ou inválido → padrões do spec §2.

**R10 — Segurança da sessão.** Nenhum arquivo do overlay DEVE chamar `qdbus`/`gdbus` nem falar
com KGlobalAccel/KWin por D-Bus; a regra do KWin é escrita no `kwinrulesrc` pelo `install.sh`, antes
do `reconfigure` que ele já faz.

## Decisões em aberto (precisam do Pedro)

- **D1 — Processo.** (a) processo próprio `hud/condessa_overlay.py`, sempre ligado, independente do
  HUD; (b) janela extra dentro do `gamerhud.py` (só existe com o HUD aberto). **Padrão: (a)** — o
  HUD principal nem sempre está aberto (o `gamerhud-watch` abre ao começar um jogo) e o núcleo já
  aceita vários clientes no socket (`magi/core/hud_client.py`, `HudServer._clients`).
- **D2 — Com o HUD aberto.** (a) os dois rostos reagem cada um por si; (b) o overlay se esconde
  enquanto a trava `hud.lock` do HUD estiver ocupada; (c) espelho (o HUD publica a reação atual).
  **Padrão: (a)**; (c) fica para depois (precisa de canal novo).
- **D3 — Em jogo em tela cheia.** (a) esconde enquanto houver jogo (sinal do `gamerhud-watch` /
  processo do jogo); (b) fica por cima. **Padrão: (a)**, chave `em_jogo = "esconde"`.
- **D4 — Plataforma.** (a) Wayland nativo + regra do KWin (posição lembrada pelo KWin);
  (b) XWayland (`QT_QPA_PLATFORM=xcb`, o app move e lembra sozinho). **Padrão: (a)**; (b) fica como
  recaída por variável `MAGI_OVERLAY_XCB=1`.
- **D5 — Legenda.** O overlay mostra a fala dela em texto (balão) ou só o rosto? **Padrão: só o
  rosto** nesta versão.
- **D6 — Canto inicial.** **Padrão:** monitor principal, canto inferior direito, margem 24 px.
