# MAGI Gamer (HUD)

Painel estilo NERV/MAGI que cobre o monitor secundário enquanto eu jogo. É a "tela" onde o
assistente Magui vai morar (ver `specs/magi-assistant/`).

## O que faz

- FPS do jogo (via log em tempo real do MangoHud), CPU/GPU/VRAM/RAM, controles conectados,
  specs do PC, gráfico de histórico.
- Clique em MELCHIOR / BALTHASAR / CASPER: consumo por aplicativo (CPU, GPU, memória).
- Tema segue a cor da placa-mãe no OpenRGB (botão RGB SYNC liga/desliga).
- Tela de ociosidade estilo title card do Evangelion (Meta+M alterna, com cortina animada).
- Troca as cenas do Wallpaper Engine por um print delas enquanto aberto (libera ~580 MB de VRAM).
  A volta é garantida: ao fechar (sinais, closeEvent), pelo `gamerhud` bin e pelo vigia, que roda
  `--restore` se o HUD não está aberto e alguma tela ficou presa num print, mesmo sem
  `wallpaper_state.json`. `GAMERHUD_NO_WALLPAPER=1` (ou offscreen) não toca no papel de parede.
- Vigia (`gamerhud-watch.py`) abre o HUD quando um jogo começa e fecha quando termina.

## Arquivos

| Arquivo | Papel |
| --- | --- |
| `gamerhud.py` | O HUD (PySide6, desenhado na CPU). `--restore`, `--toggle-rgb`, `--install-icons` |
| `gamerhud-watch.py` | Vigia de jogos (Steam `reaper SteamLaunch` + logs do MangoHud) |
| `orgb.py` | Cliente mínimo do SDK do OpenRGB (só leitura de cores) |
| `magi-view.py` | Alterna painel completo / tela de ociosidade (atalho Meta+M) |
| `steam-mangohud.sh` | Abre a Steam com o MangoHud pré-carregado |
| `system/` | Templates de config do sistema (`@HOME@` vira a home no install) |
| `install.sh` | Instala tudo: link do código, menu, autostart, MangoHud, regra do KWin, atalho |

## Instalar

```bash
./hud/install.sh
```

`~/.local/share/gamerhud` vira um link para esta pasta, então editar aqui já vale.

## Ajustes manuais fora do repo

- Plugin do Wallpaper Engine para KDE: a pausa de 5 s ao carregar cena vira 0,5 s
  (o vigia reaplica sozinho; backup em `main.qml.orig-gamerhud`).
- Dead Cells: `deadcells.sh` mantém só o MangoHud no `LD_PRELOAD`
  (backup `deadcells.sh.orig-gamerhud`; a Steam desfaz se verificar os arquivos).

## Configuração

`~/.config/gamerhud/settings.json`: `ui` (`wired` | `eva`), `rgb_sync`, `view` (`full` | `idle`),
`transition`, `wallpaper` (`still` | `pause` | `off`), `auto_open`, `auto_close`.

## Tema "wired" (padrão) e tema eva

`"ui": "wired"` (ou ausente) desenha o redesign do `docs/design/MAGI-HANDOFF.md` (módulos em
`hud/wired/`); `"ui": "eva"` volta ao painel NERV antigo. A troca vale na hora (o HUD relê o
settings.json pelo mtime). Meta+M alterna Painel completo ↔ Tela de espera nos dois temas, com a
mesma cortina.

No wired o HUD não tem quadros de animação: um batimento por segundo coleta os dados e redesenha
só as regiões que mudaram, e o mascote pede quadros sozinho (até 30/s acordada, 1 a cada 4 s
dormindo). Medido offscreen por 60 s: ~1,5% de um núcleo no painel completo e ~0,3% na espera
(~2,6% / ~1,0% com a Magui falando); meta do R23.8: 10% / 3%.

Cliques no Painel completo:

- **LED** (消灯 OFF / 点灯 ON): liga/desliga o RGB Sync (`rgb_sync`, persistido). Ligado, as
  unidades MAGI, o rubor do mascote e o trilho da espera usam a cor atual do OpenRGB; sem resposta
  do OpenRGB volta ao visual off e avisa no rodapé.
- **Anterior / tocar-pausar / próxima** no Now playing: Spotify por MPRIS.
- **Cards CPU / GPU / RAM**: painel de consumo por processo sobre o "cam 01"; clique nele fecha.
- **Mascote**: push-to-talk da Magui.

A Magui (socket do HUD) muda a expressão, a boca, a legenda e o termômetro de humor (0–4, ao
lado do mascote; discreto na tela de espera). O rodapé mostra jogo detectado/fechado, troca de
faixa, Magui ativada e alertas.

`hud/tools/wired_hud.py shots|bench` monta o HUD real offscreen (sem gravar settings) para gerar
PNGs em `~/.cache/gamerhud/wired-demo/` e medir a CPU.
