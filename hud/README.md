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

`~/.config/gamerhud/settings.json`: `rgb_sync`, `view` (`full` | `idle`), `transition`,
`wallpaper` (`still` | `pause` | `off`), `auto_open`, `auto_close`.
