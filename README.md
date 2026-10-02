# MAGI Assistant AI ("Magui")

Assistente de voz em PT-BR especializada em cultura pop (games, anime e cultura japonesa),
integrada ao MAGI Gamer, o HUD estilo NERV do segundo monitor. Desenvolvimento guiado por spec (SDD).

| Caminho | Conteúdo |
| --- | --- |
| [`docs/PRD.md`](docs/PRD.md) | PRD (cópia; o doc editável é a fonte da verdade: https://claude.ai/code/artifact/5504dd26-a040-4fda-9931-590a2883e45f) |
| [`specs/magi-assistant/requirements.md`](specs/magi-assistant/requirements.md) | Requisitos em formato EARS, ligados aos RF do PRD |
| [`specs/magi-assistant/design.md`](specs/magi-assistant/design.md) | Design técnico: processos, protocolos, dados, algoritmos, erros, testes |
| [`specs/magi-assistant/tasks.md`](specs/magi-assistant/tasks.md) | Plano de tarefas por fase (0 a 6) com critério de pronto |
| [`hud/`](hud/) | MAGI Gamer (HUD) e instalador; `~/.local/share/gamerhud` aponta para cá |

## Estado

- HUD: funcionando (FPS, sensores, RGB sync, tela de ociosidade, abre sozinho quando um jogo começa).
- Assistente: especificada; próximo passo é a Fase 0 (base do projeto e spikes).

## Instalar o HUD

```bash
./hud/install.sh
```
