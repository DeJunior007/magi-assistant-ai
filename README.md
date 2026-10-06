# MAGI Assistant AI ("Magui")

Duas coisas que vivem juntas no segundo monitor:

- **MAGI Gamer**: o HUD estilo NERV/"wired" (FPS, sensores, Spotify, RGB, tela de espera), que abre
  sozinho quando um jogo começa.
- **Magui**: assistente de voz em PT-BR, especializada em games, anime e cultura japonesa. Acorda
  com **"Condessa"** (ou "hey/oi/oh Condessa"), com a tecla **Pause**, com **PS + Share** no DualSense
  ou com um clique no mascote do HUD. Mora no HUD como um rosto/mascote.

Desenvolvimento guiado por spec (SDD): PRD → requisitos → design → tarefas.

**Como usar no dia a dia: [`docs/GUIA.md`](docs/GUIA.md).** O que falta: [`docs/PROXIMOS-PASSOS.md`](docs/PROXIMOS-PASSOS.md).

## Estado (2026-10-06)

Todas as fases do MVP estão implementadas e rodando como serviços `systemd --user`
(`specs/magi-assistant/tasks.md`):

| Fase | O que entrega | Estado |
| --- | --- | --- |
| 0 | Base do projeto, config, chaves no keyring, Postgres, spikes S1–S3 | feita |
| 0.7 / 0.8 | Wake word "Condessa" | em uso (`wake_threshold = 0.6`, `wake_patience = 3`); 0 falso/h, mas acerto 90,9% (meta 95%) |
| 1 | Voz: satélite, núcleo, roteador local, ações, TTS, HUD com rosto, conversa contínua | feita |
| 2 | Spotify (MPRIS + Web API, gosto, "coloca uma boa") | feita |
| 3 | Agente (LangGraph), persona, visão, pesquisa, autoconhecimento | feita |
| 4 | Memória, perfil, humor, ajuda no jogo | feita, menos 4.6 (precisa de 2 semanas de uso) |
| 5 | Call no Discord, alertas, sugestão de música | feita |
| 6 | Notícias com anti-spoiler | feita |
| U | Interface "wired" do HUD | feita |
| 7 | Medição final e 2 semanas de uso real | pendente |

Desempenho medido (`docs/perf/fase1.md`): CPU dormindo 1,12%, RAM dormindo 233 MB, comando conhecido
p90 1,17 s (todos dentro da meta); pergunta ao agente p90 **3,39 s** (meta 3 s, fora por pouco).

## Mapa do repositório

| Caminho | O que tem |
| --- | --- |
| `magi/satellite/` | `magi-satellite`: microfone, wake word (openWakeWord), VAD (Silero), atalho (Pause/DualSense), reprodução da voz, ducking, mudo no Discord |
| `magi/core/` | `magi-core`: serviço Wyoming, turno, STT/TTS, roteador local (`intents.yaml`), ações (jogos, HUD, volume, RGB, Spotify), música, alertas, entrega de notícias, recarga do config |
| `magi/agent/` | Agente LangGraph, persona (`persona.md`), ficha de autoconhecimento e ferramentas (`tools/`) |
| `magi/memory/` | Repositórios do Postgres: memórias, correções, custos, gosto musical, humor, perfil, ajuda no jogo; migrações |
| `magi/news/` | `magi-news`: coletores (RSS, Steam, AniList, Reddit, scraping), agrupamento, classificação, anti-spoiler, prioridade; fontes em `sources.toml` |
| `magi/providers/` | Provedores OpenAI e Gemini, rodízio de chaves (KeyPool) e registro por tarefa |
| `magi/common/` | Config (`config.py`), chaves (`secrets.py`), contratos e eventos do protocolo |
| `magi/cli/` | `magi-keys` e `magi-spotify-login` |
| `hud/` | MAGI Gamer (PySide6): `gamerhud.py`, vigia, ponte com a Magui, tema `wired/`, instalador. Ver [`hud/README.md`](hud/README.md) |
| `deploy/` | `docker-compose.yml` (Postgres + pgvector) e units `systemd/` |
| `tools/` | `perf.py` (medição de desempenho) e `wakeword/` (gravar, treinar e avaliar a "Condessa") |
| `spikes/` | Scripts dos spikes S1–S3 |
| `tests/` | Testes (`uv run pytest -q`) |
| `docs/` | PRD, spikes, medições, design do HUD, guia e próximos passos |
| `specs/magi-assistant/` | Requisitos, design técnico e tarefas |
| `config.example.toml` | Modelo do `~/.config/magi/config.toml` |

## Instalar

Pré-requisitos: Fedora/Nobara com KDE Plasma (Wayland), PipeWire, Docker, [`uv`](https://docs.astral.sh/uv/),
Spotify (flatpak), Steam com MangoHud, OpenRGB (opcional).

```bash
./hud/install.sh            # HUD + Magui (uv sync, Postgres, config, units systemd)
./hud/install.sh --start    # idem e já sobe os serviços
./hud/install.sh --no-hud   # só a Magui
./hud/install.sh --dry-run  # mostra o que faria na parte da Magui
```

O instalador:

1. Liga `~/.local/share/gamerhud` a `hud/` (editar no repo já vale), instala menu, autostart do vigia,
   MangoHud, regra do KWin e o atalho Meta+M.
2. Roda `uv sync`, sobe o Postgres (`docker compose -f deploy/docker-compose.yml up -d`, container
   `magi-pg`, `127.0.0.1:54329`, 256 MB) se ainda não estiver rodando.
3. Copia `config.example.toml` para `~/.config/magi/config.toml` se ele não existir.
4. Gera as units em `~/.config/systemd/user/` (trocando `@REPO@` pelo caminho do repo) e habilita
   `magi-satellite`, `magi-core` e `magi-news.timer` (coleta de notícias a cada 2 h).

Depois:

```bash
uv run magi-keys add openai-1        # chaves no KWallet (serviço "magi-assistant"); o config só tem nomes
uv run magi-keys add gemini-1
uv run magi-keys list                # nomes do config e se estão no keyring
uv run magi-spotify-login            # OAuth do Spotify (app em developer.spotify.com, redirect http://127.0.0.1:8765/callback)
systemctl --user restart magi-core magi-satellite
```

Se mover o repositório, rode `hud/install.sh` de novo: as units guardam o caminho.

## Documentos

| Caminho | Conteúdo |
| --- | --- |
| [`docs/GUIA.md`](docs/GUIA.md) | Guia de uso: comandos, HUD, onde fica cada coisa, config, logs, Condessa, problemas comuns |
| [`docs/PROXIMOS-PASSOS.md`](docs/PROXIMOS-PASSOS.md) | O que fica para depois, com o porquê e como validar |
| [`docs/PRD.md`](docs/PRD.md) | PRD (cópia; o doc editável é a fonte da verdade: https://claude.ai/code/artifact/5504dd26-a040-4fda-9931-590a2883e45f) |
| [`specs/magi-assistant/requirements.md`](specs/magi-assistant/requirements.md) | Requisitos em formato EARS, ligados aos RF do PRD |
| [`specs/magi-assistant/design.md`](specs/magi-assistant/design.md) | Design técnico: processos, protocolos, dados, algoritmos, erros, testes |
| [`specs/magi-assistant/tasks.md`](specs/magi-assistant/tasks.md) | Tarefas por fase com critério de pronto |
| [`docs/spikes/`](docs/spikes/) | S1 áudio, S2 atalho, S3 modelos e custos, S4 wake word "Condessa" |
| [`docs/perf/fase1.md`](docs/perf/fase1.md) | Medições de CPU, RAM e latência |
| [`docs/design/MAGI-HANDOFF.md`](docs/design/MAGI-HANDOFF.md) | Design da interface "wired" do HUD |
| [`hud/README.md`](hud/README.md) | HUD: arquivos, settings, temas, cliques |
