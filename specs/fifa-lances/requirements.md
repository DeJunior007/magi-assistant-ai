# Requisitos — Lances do FIFA 22

Fonte: `docs/PROXIMOS-PASSOS.md` §13 ("FIFA 22: reagir a lances") e o SDD em andamento
`specs/condessa-vida/` (humor, momentos, cenas; citado como **vida spec §n**, e o acordo do Conselho
`persona/conselho/atas/2026-10-09-ritmo-e-humor/acordo.md` como **acordo-vida §n**). Este arquivo é
o **PRD**. Arquitetura em [design.md](design.md); contratos, números e frases em [spec.md](spec.md);
implementação em [tasks.md](tasks.md). Critérios em EARS:

- **O sistema DEVE …** — sempre vale. **QUANDO** gatilho, **o sistema DEVE** … — reação a evento.
- **ENQUANTO** estado, **o sistema DEVE** … · **SE** falha, **ENTÃO** … · **ONDE** opção ligada, …

## Problema

O FIFA 22 roda pelo Proton (`[[game.custom]]` "FIFA 22", processo `FIFA22.exe`, aberto por voz com
"bora bater uma bola"). O HUD sabe que há jogo e o FPS (MangoHud), mas o jogo **não expõe eventos**:
a Condessa não sabe que saiu gol, quem está jogando nem o placar. No Wayland/KDE capturar a tela sem
pedir permissão a cada vez não é trivial, e nada no projeto lê a tela hoje.

## Objetivo

Durante uma partida, ela sabe o placar, os times e o tempo de jogo, reage no rosto a gol (a favor,
contra, anulado, virada, goleada) e a início/intervalo/fim, e comenta por voz poucas vezes
("PSG x Barcelona, hein?"; "golaço!"; "perdeu, né"). Caminho (1) OCR do placar primeiro; (2)
áudio do narrador só depois de um spike aprovado; (3) memória do processo descartado (design §6).

## Critérios de sucesso

1. Em 2 partidas reais, ≥ 95% dos gols viram evento `gol` com o lado certo, com atraso ≤ 3 s, e
   zero gols fantasmas (replay, VAR, menu não contam de novo).
2. Times e placar final corretos em 2 de 2 partidas.
3. Captura + OCR ≤ 5% de um núcleo em média; queda de FPS médio ≤ 3% com a captura ligada
   (medida com o MangoHud, mesma partida).
4. Nenhum pedido de permissão na tela depois da 1ª vez (portal com permissão persistente).
5. ≤ 4 falas por partida; nenhuma em call no Discord (vira legenda).
6. As reações de lance entram como cenas do momento **Jogando** (vida) e passam pelas cotas da vida.

## Requisitos

**F1 — Ligar só no FIFA.** O núcleo DEVE ligar a captura QUANDO o `GameWatcher` abrir o jogo de
`[fifa] processo` (padrão `FIFA22.exe`) e desligá-la QUANDO fechar; nada roda com outros jogos.
- F1.1 ONDE `[fifa] ligado = false` ou o Pedro disser "para de assistir o jogo", NÃO DEVE capturar.

**F2 — Captura sem prompt.** O sistema DEVE capturar o monitor do jogo pelo portal
`org.freedesktop.portal.ScreenCast` com `persist_mode = 2`, guardando o `restore_token`; só a
**primeira** sessão pode mostrar o diálogo do KDE.
- F2.1 SE o token for recusado/expirar, ENTÃO o sistema DEVE avisar por legenda ("preciso da
  permissão de tela de novo") e só pedir de novo QUANDO o Pedro mandar ("pode olhar a tela").
- F2.2 O sistema NÃO DEVE usar `qdbus`/`gdbus` nem chamar KWin/KGlobalAccel por D-Bus.
- F2.3 Os quadros DEVEM ficar só em memória (sem gravar tela), exceto na calibração (F3).

**F3 — Calibração.** O sistema DEVE oferecer `magi-lances calibrar`, que tira **uma** captura
(`spectacle -b -n`), salva em `~/.cache/magi/lances/calibracao.png` e grava o recorte do placar (frações da tela) em
`~/.local/state/magi/lances-recorte.json`, que sobrepõe o `[fifa] recorte`; recortes padrão para
1920×1080 e 2560×1440. Ela NÃO DEVE editar o `config.toml` do Pedro.

**F4 — Leitura do placar.** A cada `[fifa] intervalo_s` (padrão 1,0 s) o sistema DEVE recortar o
placar, ler times (siglas), gols e relógio (spec §3) e só aceitar uma leitura confirmada em
**2 quadros seguidos** iguais.

**F5 — Partida como estado.** O sistema DEVE manter a partida (times, placar, minuto, fase) e emitir
os lances da spec §4: início, gol (lado, placar novo), gol anulado, virada, goleada, intervalo, fim
(com resultado do ponto de vista do Pedro).
- F5.1 Placar só sobe dentro da mesma partida; queda de 1 = `gol_anulado`; mudança de siglas ou
  placar 0×0 com relógio < 1' = partida nova.
- F5.2 Placar sumido (replay, menu, pausa) NÃO DEVE gerar evento; ao voltar, compara com o último.

**F6 — Time do Pedro.** O sistema DEVE decidir o lado do Pedro por `[fifa] meus_times` (siglas);
sem casar, pelo lado de `[fifa] lado_padrao` (padrão "casa"). QUANDO o Pedro disser "tô com o
{time}", DEVE valer para a partida corrente.

**F7 — Rosto (HUD).** QUANDO chegar um lance, o HUD DEVE transformá-lo em **cena** do diretor da
vida (tipos da spec §5) dentro do momento Jogando, com evento de humor dela (vida spec §2), passando
pelas cotas, fila e interrupção da vida.
- F7.1 Gol do Pedro e fim com vitória são vitória (furam a cota de cenas, não o mínimo).
- F7.2 Lance em cima de cena de episódio (FPS/calor) entra na fila; nunca interrompe a cobrança.

**F8 — Voz.** O núcleo DEVE comentar por voz só: início (times), gol do Pedro, gol sofrido que
empata/vira, fim — **≤ 4 por partida e ≥ 90 s entre falas** — pelo `ProactiveSink` (`Priority.VOICE`),
com frases fixas (spec §6) no idioma do `[speech]`. Sem LLM.
- F8.1 ENQUANTO houver call no Discord ou leitura de audiolivro, as falas DEVEM virar legenda.
- F8.2 A zoeira em gol sofrido DEVE respeitar o humor do Pedro (0–1 = sem zoeira; como R3.1 das reações).

**F9 — Card.** O núcleo DEVE mandar ao HUD um card de jogo "PSG 2 × 1 BAR · 67'" no gol e no fim.

**F10 — Registro.** Cada lance DEVE ir para `~/.local/state/magi/lances.jsonl` (hora, partida,
lance, placar, minuto, confiança); leituras rejeitadas contam num resumo por partida.

**F11 — Áudio do narrador (caminho 2, condicional).** Só QUANDO o spike F3.1 for aprovado pelo
Pedro: o sistema DEVE capturar só o fluxo de áudio do jogo, transcrever localmente e emitir
`chance`, `entrada_forte`, `cartao`, `penalti`, `defesa`, `trave` por palavras-chave.

## Fora do escopo

Outros jogos de futebol; modo online/FUT (só funciona igual, mas não é testado); gravar a tela;
ler a memória do processo (design §6); LLM comentando o jogo.

## Decisões em aberto (precisam do Pedro)

- **D1 — Permissão de tela.** O portal mostra o diálogo do KDE **uma vez** (escolher o monitor do
  jogo e "lembrar"). **Padrão: aceitar**; alternativa sem diálogo é chamar o KWin direto, proibido.
- **D2 — Motor de OCR.** (a) `rapidocr-onnxruntime` (pip, sem sudo; o `onnxruntime` já vem com o
  Kokoro); (b) `tesseract` do sistema (`sudo dnf install tesseract`) + `pytesseract`; (c) só
  modelos de dígitos/siglas por comparação de imagem (sem dependência, exige calibrar a fonte).
  **Padrão: (a)** para siglas e (c) para dígitos/relógio quando os modelos existirem (F2.x).
- **D3 — Time do Pedro.** **Padrão: `meus_times = []` e lado "casa"**; o Pedro lista os times dele.
- **D4 — Quanto ela fala.** **Padrão: as 4 falas do F8**; "só no rosto" com `[fifa] falar = false`.
- **D5 — Idioma da narração do jogo** (para o caminho 2): PT-BR ou inglês. **Padrão recomendado: o idioma de áudio
  que o FIFA do Pedro já usa** (o F3.1 confere no `pw-dump`/menu); se tanto faz, PT-BR (Vosk `pt` pequeno).
- **D6 — Caminho 2.** Só segue se o spike mostrar ≤ 10% de CPU de um núcleo e ≥ 80% de acerto
  em "gol"; **padrão: não implementar** sem o "vai" do Pedro.
