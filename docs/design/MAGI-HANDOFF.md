# MAGI-01 — Handoff do redesign "wired"

Canvas de referência (Claude Design): https://claude.ai/artifact/5AB86Ks3rDN8DSmJTbQy1H
Duas telas, 1920×1080: **Painel completo** (Main) e **Tela de espera** (Standby).

## Regras para quem implementa
1. **Leia o SDD do projeto antes de tudo.** O design foi feito só a partir de prints, sem o SDD. Onde ele conflitar com o SDD, o SDD vence (stack, fontes de dados, atalhos).
2. **Não copie o código do canvas.** Os arquivos `.dc.html` usam um runtime próprio do editor (`<x-dc>`, `<sc-for>`, `{{holes}}`, `DCLogic`). Use-os só como referência visual e de comportamento, e reescreva tudo no stack que o projeto já usa.
3. **Mantenha as fontes de dados que já existem** (CPU, GPU, RAM, FPS, controle). O redesign é só visual. As exceções são as duas integrações novas: Spotify e LED/RGB.
4. **Nada de arte da personagem do anime.** O clima vem do cenário de fios e postes, das scanlines e dos textos em japonês, que já estão no design.
5. **Sem dados falsos em produção.** No canvas, os valores são simulados (séries com seno, faixa `[Nome da faixa]`). Quando não houver dado, mostre `– –` ou um estado vazio.

## Tokens
| Token | Valor | Uso |
|---|---|---|
| bg | `#09080d` | fundo da tela |
| panel | `#0f0e15` | fundo dos painéis |
| line | `#26232f` | bordas, divisórias |
| line-strong | `#3a3646` | botões, trilhos, segmento apagado mais forte |
| seg-off | `#1d1b25` | segmento de barra apagado |
| text | `#d8d3e6` | texto principal |
| text-dim | `#8f89a6` | rótulos (passa 4.5:1 sobre o panel) |
| deco | `#5c576b` | só decoração (parênteses do mascote) |
| cpu / Melchior | `#b392f0` | |
| gpu / Balthasar | `#5fd38d` | |
| ram / Casper | `#c9c4d6` | |
| warn | `#e8b04a` | temperatura alta, progresso da música |
| hot | `#e5695b` | últimos 3 segmentos de temperatura |

**Fontes (Google Fonts):**
- **Shippori Mincho 700:** títulos e relógio em kanji.
- **Barlow Condensed 500/600:** números grandes e títulos de painel em CAIXA ALTA.
- **JetBrains Mono 400/500:** rótulos e dados.
- **Zen Kaku Gothic New:** texto em japonês corrido.

**Painel:**
- Borda de 1px `line` e canto chanfrado de 14px (clip-path) em cima-direita e embaixo-esquerda.
- Traço de 56×3px `line-strong` no topo-esquerdo.
- Overlay de scanlines (linhas de 1px a 2,5% de branco, a cada 3px) no cenário e na capa do álbum.

## Layout — Painel completo
Grid com padding de 28px, gap de 20px, colunas `360px | 1fr | 540px` e linhas `96px | 1fr | 28px`.
- **Header:** título 汎用監視システム à esquerda, frase "私は、ここにいる。" no centro, data e relógio HH:MM (segundos menores) à direita.
- **Esquerda:** cards FPS (maior), CPU, GPU, RAM e Network, cada um com barra de 24 segmentos ou sparkline.
- **Centro, em cima:** cena de fios e postes (SVG) + mascote kaomoji, chip de estado e falas em JP/EN.
- **Centro, embaixo:** Load History (CPU, GPU, RAM nos últimos 60 min) + Unit Spec com Pilots.
- **Direita, em cima:** MAGI SYSTEM com 3 unidades (nome, 2 barras de 20 segmentos, valores, selo 正常) e o **botão LED** no cabeçalho.
- **Direita, embaixo:** Now Playing (Spotify).
- **Rodapé:** "MAGI multi agent guidance interface", ticker do log, atalho `meta+m`.

## Layout — Tela de espera
- **Esquerda (x=160, top/bottom 170):** trilho vertical de 4px + MAGI SYSTEM 待機中, hora em kanji (拾九時 / 拾壱分), hora por extenso em inglês e a data.
- **Direita (x=1180, largura 440, mesmo topo e base do relógio):** três blocos.
  - Em cima, o status com o LED.
  - No meio, o mascote pequeno (200px) e a fala.
  - Embaixo, o mini player.
- **Cenário:** o poste fica em x≈1760, à direita do conteúdo. Os fios saem para cima/fora e os prédios ficam só abaixo de y≈900. **Nada do cenário pode passar atrás do texto.**

## Estados
- **standby / gaming:**
  - Em gaming, o FPS mostra o número, min/avg/max e sparkline. Em standby, mostra `– –` com "NO SIGNAL ゲーム未検出".
  - O mascote dorme (olhos em traço + zz) ou acorda (olhos redondos).
  - A cor do chip de estado e as falas mudam junto.
- **Temperatura:** os segmentos a partir de 75% ficam `warn` e os 3 últimos ficam `hot`. O valor da GPU fica `warn` a partir de 75°C.
- **LED off/on:**
  - Off: cada MAGI usa a própria cor.
  - On: as 3 unidades MAGI (texto, borda `rgb+88`, fundo `rgb+14`, segmentos), o ponto do botão (com glow), o rubor do mascote e, na tela de espera, o trilho do relógio e o indicador usam a cor atual do RGB.
  - O botão mostra 消灯 OFF ou 点灯 ON, usa `aria-pressed` e o estado deve persistir.

## Integração LED (OpenRGB — confirmar com o usuário)
- Ler a cor atual pelo SDK server do OpenRGB (TCP, porta padrão 6742; o "SDK Server" precisa estar ligado no OpenRGB).
- Usar a cor do dispositivo ou zona principal. Em efeito arco-íris, atualizar a cada ~1s e suavizar a transição em ~600ms.
- Se o servidor não responder: o LED volta para off visualmente e aparece um aviso discreto no log, sem quebrar a tela.

## Integração Spotify
- Usar o Authorization Code with PKCE e guardar o refresh token localmente.
- Escopos: `user-read-currently-playing` e `user-read-playback-state`. Para os botões de controle, também `user-modify-playback-state`; o controle de playback exige Premium.
- Fazer polling de `GET /v1/me/player/currently-playing` a cada 3–5s e interpolar o progresso localmente a cada segundo.
- A fila vem de `GET /v1/me/player/queue`.
- Mostrar: capa (`album.images`, a de ~300px), faixa, artista, álbum · ano, progresso / duração e a próxima faixa.
- Estados:
  - Nada tocando: card esmaecido com "– –".
  - Pausado: o equalizador cai para 4px.
  - Sem login: botão "conectar Spotify".
- Conferir no painel de desenvolvedor do Spotify as regras atuais do app em modo de desenvolvimento (cotas e usuários permitidos).

## Acessibilidade
- Botões reais (`<button>`) com `aria-label` nos que só têm ícone, e área de toque de no mínimo 44px.
- Texto secundário nunca abaixo de `text-dim`, e a cor sozinha nunca carrega informação: o selo 正常 sempre vem com "NORMAL".
