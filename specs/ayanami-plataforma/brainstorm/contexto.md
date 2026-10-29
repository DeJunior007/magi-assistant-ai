# Contexto do brainstorm — "potencial máximo da VPS como MCP da Ayanami" (2026-10-28)

Pedido do Pedro: derrubar o Minecraft (feito) e pensar de verdade no que colocar no node 2 para usar o
máximo dele como **MCP/cérebro da Ayanami**. A Condessa é o rosto (HUD no PC, app Android em SDD);
a Ayanami é o cérebro invisível.

Recursos: node 2 Contabo, 8 vCPU, 23 GiB RAM, SSD 300 GB (221 GB livres), swap 8 GiB, **sem GPU**,
Ubuntu 24.04, Docker Compose, Tailscale (tailnet privado; nada público além de SSH), domínio
`*.dekasis.com.br`. Hoje a Ayanami usa ~320 MiB e ~3% CPU parada.

O que já existe na Ayanami (`specs/ayanami-central/`): API FastAPI + Postgres/pgvector + fila
procrastinate (rápida/lenta/agendada), workers: notícias (coleta/cluster/classifica), tarefas longas do
agente (pesquisar, lembrete, monitores de preço/disponibilidade), voz Kokoro em CPU, STT faster-whisper
assíncrono, embeddings e5-small, backups (pg_dump do PC + restic, sem B2 ainda), vigia (CPU/RAM/disco +
Telegram sem token ainda), **servidor MCP em /mcp/** (10 tools: notícias, memória leitura, tarefas,
casa/TV com confirmação, estado, servidor), modo nuvem (Condessa responde com o PC desligado, sub-teto
US$ 2/mês), ponte de turno PC↔celular, eventos/SSE/push, pareamento de dispositivos. Budget geral de
API paga: US$ 5/mês (a Ayanami não deve estourar isso).

O que existe no PC (repo `magi-assistant-ai`): núcleo de voz da Condessa, HUD, Learning Mode (inglês),
audiolivro (Kokoro + Qwen local), espera viva, casa/TVs (`magi-casa`), notícias locais, Claude Code
usado pelo Pedro para programar (projetos: magi-assistant-ai, MultiVideos (Laravel, produção no node 1),
gold-crm/ourijoias (produção no node 1), AotMine/tensura-mine (sites Next.js na Vercel), KPCeramica,
scraperr), spec `condessa-engine` (orquestrar Claude Code headless — não começado), `fifa-lances`
(OCR de placar), `condessa-angulos`.

Node 1 (produção de clientes: MultiVideos, gold-crm, wedding) — **não tocar** sem o Pedro; dá para
pensar em monitorar/fazer backup dele a partir do node 2, só leitura.

Restrições: tudo privado no tailnet salvo decisão do Pedro; dados pessoais só em infra dele; custo
mensal baixo; sem GPU (LLM local só pequeno/lento em CPU, lote noturno); nada que o Pedro precise
operar manualmente no dia a dia (CI/CD e vigia cuidam).
