# Requisitos — Ângulos do retrato da Condessa

Fonte: `docs/PROXIMOS-PASSOS.md` §13 ("Retrato com ângulos de verdade") e a folha de 16 rostos
da Condessa que o Pedro tem. Este arquivo é o **PRD**. Arquitetura em [design.md](design.md);
contratos, números e a **lista de imagens a gerar** em [spec.md](spec.md); implementação em
[tasks.md](tasks.md). Critérios em EARS:

- **O retrato DEVE …** — sempre vale. **QUANDO** gatilho, **o retrato DEVE** … — reação a evento.
- **ENQUANTO** estado, **o retrato DEVE** … · **SE** falha, **ENTÃO** … · **ONDE** opção ligada, …

## Problema

O retrato em partes (`PartsPortrait`) é uma pose só, de frente: a vida vem de piscar, boca, olhar
com parallax e inclinação de poucos graus. Quando ela "olha para o painel que reagiu", só os olhos
e a cabeça andam alguns px; não há como virar o rosto, ficar de perfil pensando ou pôr a mão no
queixo.

## Objetivo

"2.5D de troca": cada ângulo da folha vira um **conjunto de camadas próprio** (como a A1 hoje) e a
mudança entre ângulos é uma **transição curta** (dissolve + leve deslocamento/escala na direção do
giro), sem animação de verdade. Começa pela fase mínima viável: **3/4 esquerda e 3/4 direita, sem
fala nesses ângulos**.

## Critérios de sucesso

1. Com G2/G3 montados, ela vira para o lado do painel que reagiu em ≥ 80% das reações com `look`
   lateral de ≥ 1,2 s (teste com reações sintéticas) e volta de frente sozinha.
2. A transição dura 160–260 ms, sem quadro com o busto "fantasma" (alfa total do busto ≥ 0,9 em
   todo quadro da transição, medido no teste).
3. Nenhum ângulo sem arte quebra nada: sem `angulos/`, o retrato é idêntico ao de hoje
   (`tests/hud/test_wired_portrait.py` verde sem mudar asserção).
4. CPU do HUD continua ≤ 10% de um núcleo (medida de `docs/PROXIMOS-PASSOS.md` §7) com trocas
   frequentes (1 troca a cada 8 s por 10 min).
5. O Pedro acha que "parece que ela virou", não "trocou de foto" (nota dele na A3.2).

## Requisitos

**R1 — Conjunto por ângulo.** O retrato DEVE carregar, de `angulos/<ID>/` na pasta montada,
cada ângulo como um busto inteiro (`base.png`) com remendos opcionais de olhos (`eyes/B2.png`,
`eyes/B3.png`) e de boca (`mouth/C2.png`, `mouth/C3.png`) e um `angulo.toml` (spec §2).
- R1.1 SE um ângulo não tiver `base.png` válido, ENTÃO ele NÃO DEVE existir para o seletor.
- R1.2 O ângulo de frente (`G1`) DEVE ser sempre o retrato em partes atual, nunca uma imagem plana.

**R2 — Transição.** QUANDO o ângulo muda, o retrato DEVE fazer a transição do spec §4 (dissolve
em duas metades + deslocamento e escala no sentido do giro), sem passar por um quadro vazio.

**R3 — Seletor.** O retrato DEVE escolher o ângulo por um seletor puro (spec §3) a partir do
estado da Magui, da reação atual (`look`, `corpo`) e dos ângulos disponíveis, com tempo mínimo e
máximo fora de frente e intervalo mínimo entre giros.

**R4 — Fala de frente (fase mínima).** ENQUANTO a Magui estiver `speaking` ou `listening`, o retrato
DEVE ficar em `G1`; QUANDO a fala começa num ângulo sem bocas, DEVE voltar a `G1` antes da 1ª sílaba
visível (transição curta de 160 ms). ONDE o ângulo tiver `mouth/C2.png` e `mouth/C3.png` e
`fala = true` no `angulo.toml`, PODE falar nele (fase 3).

**R5 — Piscar no ângulo.** ONDE o ângulo tiver `eyes/B2.png` e `eyes/B3.png`, o retrato DEVE
piscar nele com o mesmo relógio da frente; sem eles, o ângulo dura no máximo 2,5 s (ninguém fica
sem piscar mais que isso).

**R6 — Vida no ângulo.** No ângulo, o retrato DEVE manter respiração (sobe-e-desce do busto),
balanço lento, fundo/brilho e efeitos (`_reaction_effect`) acompanhando a cabeça; cabelo em
pêndulo e íris solta ficam só em `G1` (fase mínima).

**R7 — Reações pedem ângulo.** Um passo de reação PODE pedir ângulo com `corpo` `angulo:<ID>` (mesmo
canal dos extras `braco:`/`iris:`); pedido de ângulo sem arte é ignorado (como asset ausente nas
reações, R1.1 do SDD de reações).

**R8 — Montagem.** O `condessa_build.py` DEVE gerar `angulos/<ID>/` a partir de `G<n>.png`,
`G<n>_B2.png`, `G<n>_B3.png`, `G<n>_C2.png`, `G<n>_C3.png` da pasta de origem, alinhando o busto
pela faixa dos ombros (spec §5); arquivo ausente → aviso "falta X (opcional)".

**R9 — Gosto do Pedro.** ONDE `~/.config/magi/condessa-gosto.toml` tiver `[angulos] desligados =
["G4", ...]` ou `ligado = false`, o seletor NÃO DEVE usar esses ângulos.

## Decisões em aberto (precisam do Pedro)

- **D1 — Lado.** "3/4 esquerda" = rosto virado para a **esquerda da tela** (de quem olha), que é o
  que o `look` dos painéis usa. **Padrão: lado da tela.**
- **D2 — IDs da folha.** A folha tem 16 rostos; o spec §6 numera G1–G16 pela lista do §13 e
  completa G12–G16 com propostas. **Padrão: os IDs do spec §6**; o Pedro corrige a tabela antes
  da A3.1 se a folha for diferente.
- **D3 — Fase mínima.** **Padrão: G2 e G3, base + piscada (B2, B3), sem fala.** Sem piscada, só a
  base (R5 limita a 2,5 s).
- **D4 — Pensando.** Pensando > 3 s vai para `G9` (mão no queixo) ou para `G4`/`G5` (perfil)?
  **Padrão: G9 quando existir; senão fica de frente** (perfil "some" com o rosto no painel pequeno).
- **D5 — Overlay.** O overlay (`specs/condessa-overlay/`) usa ângulos? **Padrão: sim, o mesmo
  `PartsPortrait`;** no quadro pequeno a transição é a mesma.
- **D6 — Frequência.** Teto de giros: **padrão 6 por minuto**, mínimo 8 s entre giros não pedidos
  por reação.
