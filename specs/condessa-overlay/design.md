# Design — Overlay da Condessa

Implementa [requirements.md](requirements.md). Seções citadas por `§`.

## 1. Onde mora hoje

```
núcleo (HudServer, N clientes) ──linhas JSON──▶ hud_bridge.HudBridge ──sinais Qt──▶ gamerhud.HUD
gamerhud: WiredUI.build (1 Hz, sensores) ──Snapshot──▶ Reactor.observe ──▶ mascot.react ──▶ PartsPortrait.paint
gamerhud.face_down/face_move/face_up ──▶ WiredUI.on_click("face") / on_hover(...)
```
- `hud/hud_bridge.py`: `HudBridge(QObject)` cliente do `hud.sock`, reconecta com backoff, sinais
  `stateChanged`, `mouth`, `mood`, `turnTag`, `connectedChanged`. Roda com o Python do sistema.
- `magi/core/hud_client.py`: `HudServer` manda cada linha a **todos** os clientes e reenvia o último
  `state` a quem conecta — o overlay é só mais um cliente, **nada muda no núcleo**.
- `hud/wired/portrait.py`: `PartsAssets(pasta)`, `PartsPortrait(assets)` (API do `Mascot`:
  `set_expression`, `set_level`, `react`, `tick`, `paint(p, rect, accent, now)`); o fundo vem de
  `_backdrop` (linha ~1003 do `paint`); `renderer = "gl"` desenha fora da tela e devolve `QImage`,
  então funciona numa janela transparente comum.
- `hud/wired/reactions.py`: `Reactor(..., detectores=, registro_file=, atividade=)`, `observe(snap,
  now)`, `active(now)`, `on_click`, `on_hover`.
- `hud/install.sh` (`install_hud`): `render` dos `.desktop`, regra `gamerhud-rule` no
  `kwinrulesrc` com `kwriteconfig6`, e um `reconfigure` do KWin no fim.

## 2. Princípio: processo novo, peças velhas

O overlay é um **processo próprio** (D1 = a) com um arquivo de entrada e um módulo puro:

| Arquivo | Papel | Dono |
| --- | --- | --- |
| `hud/wired/overlay.py` | puro (sem janela): `Config` (lê/grava `overlay.toml`), `Gestos` (máquina de estados de clique/duplo/longo/arrasto → eventos do `Reactor`), `snapshot_leve(...)`, `regiao_entrada(img, limiar) -> list[QRect]`, `canto_para_posicao(...)`, `hud_aberto(lock)` | O0.1, O1.x |
| `hud/condessa_overlay.py` | janela Qt (`OverlayWindow`), `main()`, trava de instância, laço de tempo do retrato | O1.3, O1.4 |
| `hud/system/bin/condessa-overlay`, `hud/system/autostart/condessa-overlay.desktop`, `hud/system/applications/condessa-overlay.desktop` | comando liga/desliga, autostart, menu | O2.1 |
| `hud/install.sh` | instala os três acima e a regra `condessa-overlay-rule` | O2.1 |
| `hud/wired/portrait.py` | só um atributo `fundo: bool = True` no `PartsPortrait` (pula `_backdrop`) | O1.1 |

O `gamerhud.py` **não muda**: a lógica de gestos é reescrita pequena e testável em `overlay.Gestos`
(as constantes `FACE_DBL_MS`, `FACE_LONG_S`, `FACE_DRAG` são copiadas, não importadas, para não
carregar o HUD inteiro).

## 3. Fluxo

1. `main()`: `QGuiApplication.setDesktopFileName("condessa-overlay")` (vira o `app_id` do Wayland
   que a regra do KWin casa), trava `~/.cache/gamerhud/overlay.lock`, lê `Config`, confere
   `is_parts`, cria `PartsPortrait` com `fundo=False`, `HudBridge`, `Reactor` reduzido.
2. Sinais da ponte → `portrait.set_expression`, `set_level`; `mood`/`turn_tag` guardados para o
   `snapshot_leve`.
3. A 1 Hz: `snapshot_leve(magui, mouth, mood, turn_tag, track, gaming)` → `Reactor.observe` →
   `portrait.react(reactor.active(now), reactor.until)`.
4. O redesenho segue o `portrait.tick(now)` (mesmo relógio do HUD: 60/40/6 fps), com um `QTimer`
   de disparo único reprogramado para o próximo quadro.
5. Quando a silhueta muda de forma (troca de tamanho, pose de corpo, reação com braço), recalcula a
   região de entrada (`regiao_entrada`) e aplica `setMask(QRegion)` — no Wayland vira a região de
   entrada da superfície; fora dela o clique atravessa. Nunca por quadro (≤ 1×/s).
6. Mouse: esquerdo → `Gestos` → `Reactor`; meio arrastando ou menu "Mover" →
   `windowHandle().startSystemMove()`; direito → menu (Mover, Tamanho ±, Esconder 1 h, Sair).

## 4. Convivência

- **Núcleo:** mais um cliente; `send_cmd` não é usado (o overlay não manda comandos na v1).
- **HUD principal (D2 = a):** cada um com o seu `Reactor`. Para não dobrar a validação, o overlay
  grava em `~/.local/state/magi/reacoes-overlay.jsonl` e usa um arquivo de atividade próprio
  (`atividade-overlay.json`) — o bom-dia do HUD não é "roubado". Com D2 = b, `hud_aberto()` testa a
  trava `~/.cache/gamerhud/hud.lock` (flock não bloqueante, solta na hora) a cada 5 s.
- **Jogo (D3 = a):** o overlay esconde enquanto `gaming` for verdadeiro (spec §3).

## 5. KWin e Wayland

No Wayland o app não escolhe a própria posição. A regra `condessa-overlay-rule` (casada por
`wmclass=condessa-overlay`) faz: acima de tudo, sem foco, fora de Alt+Tab/pager/barra, sem
moldura, **posição "Lembrar"** (o KWin grava a última posição na própria regra) e posição inicial
calculada do `overlay.toml` pelo `install.sh`. Nenhuma chamada nova de D-Bus: a regra é escrita
antes do `reconfigure` que o `install.sh` já faz. Recaída D4 = b: com `MAGI_OVERLAY_XCB=1`, o
`main()` põe `QT_QPA_PLATFORM=xcb`, usa `move()` e grava `x`, `y` no `overlay.toml` ao soltar.

## 6. Riscos

| Risco | Mitigação |
| --- | --- |
| `setMask` não vira região de entrada no Qt Wayland desta versão | O1.3 mede ao vivo (O3.1); recaída D4 = b (XWayland faz *shape* de entrada) |
| GPU: segundo contexto OpenGL do retrato | `renderer` do overlay é `cpu` por padrão (quadro pequeno); `gl` por chave |
| Duas Condessas reagindo diferente em dois monitores | D2; registro separado para medir; (c) espelho depois |
| Fica por cima de jogo em tela cheia | D3 = a; e a regra não força "acima de tela cheia" |
| Derrubar a sessão KDE | R10: zero `qdbus`/`gdbus`; teste de `grep` |
| Estado da `condessa-vida` (humor dela persistido) escrito por dois processos | o overlay abre o estado da vida só para leitura (nota para a V0.8) |
