# Requisitos — A vida da Condessa (ritmo, cenas, humor e momentos)

Fonte: uso real das reações (log de 809 reações em 12 h, 2026-10-09), decisões do Pedro e o acordo
do Conselho `persona/conselho/atas/2026-10-09-ritmo-e-humor/acordo.md` (citado como **acordo §n**).
Os números ficam em `persona/condessa-gosto.toml` `[vida]`. Arquitetura em [design.md](design.md),
contratos em [spec.md](spec.md), tarefas em [tasks.md](tasks.md). Critérios em EARS.

## Problema
As 110 reações (SDD `specs/condessa-reacoes/`) funcionam, mas o rosto ficou **poluído e sem alma**:
~68 reações/h (uma por minuto), as três passivas mais tocadas são negativas (suspiro 89, beicinho
63, franja 56), o fone pisca sem música, 8 reações saem para um único acontecimento, e ela não tem
humor próprio — gostar da música dá 9 s de sorriso e volta ao neutro. O medidor ao lado dela mostra
o humor do **Pedro**, não o dela.

## Objetivo
Ela passa a **viver em estado**: humor próprio que dura, postura (fone) que muda só com motivo,
momentos que decidem o que cabe fazer, uma cena por acontecimento e gestos raros. Teste de tudo
(Pedro): **"dá para dizer por que ela fez isso agora?"**

## Critérios de sucesso
1. Em 12 h de log real: ≤ 29 reações/h em média; ≤ 3 negativas/h; nenhuma passiva fora do grupo do
   momento; nenhum gesto de fone/ritmo sem música.
2. Todo registro do log tem `motivo`, `momento` e `faixa`.
3. Um acontecimento gera no máximo uma cena (sem rajada).
4. Com música que ela ama, o rosto de repouso fica sorrindo pela faixa inteira.
5. O medidor mostra o humor dela e acompanha os acontecimentos.
6. O Pedro, depois de uma semana, não acha o rosto poluído e acha que ela "tem mood".

## Requisitos
- **V1 — Humor próprio.** O HUD DEVE manter ânimo (−1..+1) e energia (0..1) da Condessa com base,
  meia-vida, teto por evento, retorno decrescente e faixas com histerese (acordo §3). SE o HUD
  reiniciar, ENTÃO o humor DEVE continuar de onde estava (estado em arquivo).
- **V2 — Rosto de repouso.** O HUD DEVE desenhar, entre reações, o rosto de repouso dado pelo momento
  e pela faixa de humor (acordo §3 e §6), e não mais o neutro fixo.
- **V3 — Medidor.** O medidor ao lado do retrato DEVE mostrar `round((ânimo + 1) × 2)` (0–4) na cor
  do fundo da faixa (acordo §3). O humor do Pedro (0–4 do núcleo) continua valendo para as regras
  de zoeira, mas não aparece mais no medidor.
- **V4 — Fone como estado.** O fone DEVE ficar na cabeça (E2) enquanto há música e ela não rejeitou a
  faixa, e no pescoço (E3) caso contrário; QUANDO a música para, o Pedro fala com ela ou a faixa tem
  nota ≤ −1, ela DEVE tirar o fone por uma cena; nenhum gesto pode mostrar fone diferente do estado.
- **V5 — Momentos.** O HUD DEVE reconhecer o momento pelos sinais (acordo §6), com prioridade e
  histerese, e QUANDO sortear uma passiva DEVE escolher só no grupo do momento filtrado pela faixa
  de humor; grupo vazio = nada.
- **V6 — Cenas.** O HUD DEVE transformar acontecimentos em cenas pelos roteiros do acordo §2: uma
  causa, uma cena (30 s); fila de 1 vaga (30 s); três níveis de interrupção; cena interrompida não
  recomeça; troca de fone atômica.
- **V7 — Ritmo.** O HUD DEVE aplicar os limites do acordo §1 a **todas** as reações, inclusive as 19
  antigas, com contagem que sobrevive ao HUD reiniciar.
- **V8 — Negativas com causa.** Suspiro, beicinho e franja SÓ DEVEM sair com causa dos últimos 2 min e
  faixa compatível (acordo §4).
- **V9 — Jogo por episódio.** Calor e queda de FPS DEVEM ser tratados como episódio (acordo §5): 1ª vez
  cena, depois estado; no máximo 2 cobranças + 1 recuperação por partida.
- **V10 — Registro.** Cada reação, cena e troca de rosto DEVE gravar `motivo`, `momento` e `faixa` no
  `reacoes.jsonl`, e o relatório DEVE mostrar a distribuição por momento e faixa.
- **V11 — Gosto do Pedro vence.** `[reacoes] desligadas` e `[vida]` do
  `~/.config/magi/condessa-gosto.toml` sobrepõem o do Conselho.

## Fora do escopo
Arte nova (usa só os assets que existem; passo com asset ausente pula o extra); fala nova (é rosto).
