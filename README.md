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

## Ayanami central, casa e celular (`specs/ayanami-central/`)

Código no `main` (2026-10-21); **ainda não está no ar**: falta o Pedro provisionar o node 2 e fazer
o primeiro deploy, e a validação ao vivo (F.1). O que está aqui descreve o código; números e
comportamento real ficam "a confirmar no F.1".

- **Ayanami** (`ayanami/`, comando `ayanami`): a API central da Condessa no node 2 (VPS), só no
  Tailscale. Fila de jobs (rápida, agendada, lenta), notícias para o PC (`magi-news-sync`), backup
  do PC e da própria Ayanami (`magi-backup`, restic), MCP, modo nuvem (responde quando o PC está
  desligado e depois reconcilia) e Web Push. Operação no node 2: [`docs/ayanami/runbook.md`](docs/ayanami/runbook.md).
- **Casa** (`magi/casa/`, comando `magi-casa`): controla as TVs (Samsung, Roku, Android TV) pela
  rede local, sem nuvem obrigatória. A Condessa usa pelas intents `tv.*` ("liga a TV da sala").
- **Celular** (`ayanami/pwa/`, servido em `/app/` pela Ayanami): PWA para Android com conversa
  (texto e voz), controle das TVs, confirmações e notificações push.

```bash
uv run magi-casa descobrir                         # acha TVs na rede (SSDP + mDNS)
uv run magi-casa nomear 1 sala "TV da sala"        # grava a TV no ~/.config/magi/casa.toml
uv run magi-casa parear sala                       # código ou "Permitir" na tela da TV
uv run magi-casa testar sala volume volume=+2      # roda uma ação e mostra o resultado
uv run magi-casa estado                            # estado de cada TV
uv run magi-casa servir                            # sobe a API local (unit magi-casa.service)
uv run python -m magi.elo.parear --nome celular    # código de pareamento do celular
ayanami --help                                     # no contêiner: migrar, worker, voz, dispositivo, backup, push
```

Como usar: [`docs/GUIA.md`](docs/GUIA.md) §15. O que falta: [`docs/PROXIMOS-PASSOS.md`](docs/PROXIMOS-PASSOS.md) §13.

## Mapa do repositório

| Caminho | O que tem |
| --- | --- |
| `magi/satellite/` | `magi-satellite`: microfone, wake word (openWakeWord), VAD (Silero), atalho (Pause/DualSense), reprodução da voz, ducking, mudo no Discord |
| `magi/core/` | `magi-core`: serviço Wyoming, turno, STT/TTS, roteador local (`intents.yaml`), ações (jogos, HUD, volume, RGB, Spotify), música, alertas, entrega de notícias, recarga do config |
| `magi/agent/` | Agente LangGraph, persona (`persona.md`), ficha de autoconhecimento e ferramentas (`tools/`) |
| `magi/memory/` | Repositórios do Postgres: memórias, correções, custos, gosto musical, humor, perfil, ajuda no jogo; migrações |
| `magi/news/` | **Ayanami**, o agente de notícias (`magi-ayanami`, persona em `persona/ayanami.md`): coletores (RSS, Steam, AniList, Reddit, scraping), agrupamento, classificação, anti-spoiler, prioridade; fontes em `sources.toml` |
| `magi/providers/` | Provedores OpenAI e Gemini, rodízio de chaves (KeyPool) e registro por tarefa |
| `magi/common/` | Config (`config.py`), chaves (`secrets.py`), contratos e eventos do protocolo |
| `magi/casa/` | `magi-casa`: TVs da casa (descoberta, pareamento, drivers Samsung/Roku/Android TV, API local) |
| `magi/elo/` | Ligação do PC com a Ayanami: cliente, notícias, backup, pareamento do celular, reconciliação |
| `ayanami/` | Ayanami central (node 2): API, fila e workers, MCP, voz (Kokoro), push e o PWA (`ayanami/pwa/`) |
| `magi/cli/` | `magi-keys` e `magi-spotify-login` |
| `hud/` | MAGI Gamer (PySide6): `gamerhud.py`, vigia, ponte com a Magui, tema `wired/`, instalador. Ver [`hud/README.md`](hud/README.md) |
| `deploy/` | `docker-compose.yml` (Postgres + pgvector), units `systemd/` e `ayanami/` (compose, perfil do node 2, vigia, scripts do host) |
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
   `magi-satellite`, `magi-core` e `magi-ayanami.timer` (a Ayanami coleta notícias a cada 2 h).

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
| [`docs/ayanami/runbook.md`](docs/ayanami/runbook.md) | Runbook da Ayanami no node 2: provisionar, deploy, perfil compartilhado, rollback, restore, alertas |
| [`specs/ayanami-central/`](specs/ayanami-central/) | SDD da Ayanami central, da casa e do celular |
| [`docs/spikes/`](docs/spikes/) | S1 áudio, S2 atalho, S3 modelos e custos, S4 wake word "Condessa" |
| [`docs/perf/fase1.md`](docs/perf/fase1.md) | Medições de CPU, RAM e latência |
| [`docs/design/MAGI-HANDOFF.md`](docs/design/MAGI-HANDOFF.md) | Design da interface "wired" do HUD |
| [`hud/README.md`](hud/README.md) | HUD: arquivos, settings, temas, cliques |
