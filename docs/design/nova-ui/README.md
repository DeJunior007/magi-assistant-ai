# Nova UI do painel (Meta+M · PAINEL COMPLETO) — 2026-10-08

Fonte da verdade: `painel.dc.html` (mockup aprovado pelo Pedro, versão 12 do artefato
"Condessa Learning Console"). Referências: `ref/e53ab4ec-….png` (composição),
`ref/Captura_de_tela_20261008_093840.png` (Konsole), `ref/Captura_de_tela_20261008_094546.png`
(Rádio Ayanami). Alvo: monitor 2, DP-1, 2560×1440.

## Conversão de coordenadas

O mockup é desenhado em **1672×941**; o HUD desenha na base **1920×1080** e escala pela largura.
Fator `F = 1920 / 1672 = 1.14833` (vertical 1080/941 = 1.14772; use `F` nos dois eixos e
arredonde a 0.5 px). Tamanhos de fonte também × F. Todo valor do mockup vira `valor × F`.

Caixas do mockup (x, y, w, h) → base 1920:

| bloco | mockup | base 1920 (≈) |
|---|---|---|
| MAGI SYSTEM | 23,125 440×353 | 26.4,143.5 505.3×405.4 |
| SYSTEM ACTIVITY | 23,493 440×218 | 26.4,566.1 505.3×250.3 |
| NETWORK | 23,727 440×132 | 26.4,834.8 505.3×151.6 |
| CAM 01 | 482,125 509×428 | 553.5,143.5 584.5×491.5 |
| LOAD HISTORY | 482,572 509×287 | 553.5,656.8 584.5×329.6 |
| CONDESSA | 1012,125 310×428 | 1162.1,143.5 356×491.5 |
| UNIT SPEC | 1012,572 310×287 | 1162.1,656.8 356×329.6 |
| NOW PLAYING | 1340,125 310×240 | 1538.8,143.5 356×275.6 |
| RÁDIO AYANAMI | 1340,381 310×128 | 1538.8,437.5 356×147 |
| KONSOLE | 1340,526 310×333 | 1538.8,604 356×382.4 |
| linha do topo | y 100 | y 114.8 |
| linha do rodapé | y 876 | y 1006 |

## O que muda em relação ao painel atual

1. **Topo:** título, centro "私は、ここにいる。", **botão LEARNING** (196×52 no mockup, em
   1068,30) no lugar dos indicadores; data + relógio grande (76 px no mockup) com segundos em lilás.
   O botão LEARNING sai do card da Condessa (hoje `LEARN_BTN`) e vai para o topo, mesmo alvo
   `"learning"` no `hit_test`.
2. **MAGI SYSTEM 3×3×3:** botão LED (`消灯 LED OFF` / `点灯 LED ON`, mesma ação de hoje) acima
   do MELCHIOR; MELCHIOR = load, temp, clock; BALTHASAR = load, temp, vram; CASPER = ram, swap,
   disk. Sai a linha "CONDESSA 自己" de baixo.
3. **SYSTEM ACTIVITY** (novo, junta FPS + rede + uso próprio): esquerda FPS com sparkline,
   ネットワーク ↓↑, NO SIGNAL/ゲーム未検出; direita **MAGI 自己 · USO PRÓPRIO** com CPU, GPU,
   RAM, VRAM do próprio processo (o que hoje é a linha "CONDESSA 自己").
4. **NETWORK:** IP, GATEWAY, DNS + ↓↑ + sparkline; `接続中 ●`.
5. **CAM 01** e **LOAD HISTORY:** como hoje, nas caixas novas.
6. **CONDESSA:** retrato **272×272** no mockup (o maior elemento do card), chip pequeno
   (14 px), fala numa **caixa de terminal** (fundo #08070d, borda #262333, barra esquerda 2 px:
   lilás falando / #3d3752 parada) com `›` e o texto **revelado 1 caractere por vez acompanhando
   a fala** (mesma fonte de tempo da legenda atual, `speech_caption`); cursor em bloco lilás fixo
   só enquanto fala; **nada pisca** parado. Chip `SPEAKING · 発話中` em lilás durante a fala.
7. **UNIT SPEC** com PILOTS; **NOW PLAYING** compacto (capa 80, controles 36×32, EQ).
8. **RÁDIO AYANAMI:** desenho da Rei à direita (`assets/rei.png`, mix lighten ~0.85),
   `LIVE HH:MM`, duas linhas de texto.
9. **KONSOLE // CLAUDE CODE:** terminal **interativo de verdade** rodando o Claude Code
   (pty + emulador VT), com a moldura do mockup (barra de título, aba SESSION 01, barra de
   status com projeto | branch | +/- | CLAUDE CODE | TOKENS | ● ONLINE). Ver `KONSOLE.md`.
10. **Rodapé:** MAGI MULTI AGENT GUIDANCE INTERFACE · log de eventos · META+M · PAINEL COMPLETO.
11. **Clima:** scanlines discretas + vinheta; nenhum elemento pisca quando ocioso.

Paleta (mockup): fundo #09080f, painel #0e0d15, borda #262333, texto #e2deee/#ddd8ea,
secundário #a39eb8, lilás #b49af0, verde #5fd38d, laranja da capa #f2832a.
Fontes: Barlow Condensed (títulos), JetBrains Mono (texto), Noto Sans JP / Noto Serif JP.
