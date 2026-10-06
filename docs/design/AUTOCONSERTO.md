# Autoconserto da Magui com o Claude Code — proposta

Status: **proposta, nada implementado** além do leitor de consumo (`magi/maintenance/claude_usage.py`,
só leitura). Precisa do "ok" do Pedro antes de qualquer parte que mexa em código.

## Ideia

Hoje, quando algo quebra (Postgres caiu, uma rota entende errado, um serviço não sobe), o Pedro
abre um console, lê o log e pede ao Claude Code para arrumar. A proposta é a própria Magui fazer
esse primeiro passo: perceber o problema, juntar o contexto (logs, estado dos serviços, último
erro) e chamar o Claude Code em modo não interativo (`claude -p`) para **investigar e propor** o
conserto — sem console aberto, com o resultado no HUD e por voz.

## O que torna isso perigoso (e por isso os limites abaixo)

1. **Um assistente de voz que altera o próprio código** pode se quebrar de um jeito que não
   consegue mais consertar (ex.: um "conserto" que impede o `magi-core` de subir).
2. **Entrada não confiável**: logs e notícias têm texto de fora (manchetes, respostas de API).
   Se esse texto for colado num prompt com permissão de editar e rodar comandos, vira injeção de
   instrução.
3. **Ações fora do repositório**: `~/.config`, keyring, systemd, Docker, papel de parede, KWin
   (o KGlobalAccel derruba a sessão inteira com um argumento D-Bus errado, ver S2).
4. **Custo e cota**: sessões automáticas consomem a cota do Claude Code sem o Pedro ver.

## Proposta em 3 níveis (cada um só depois do anterior provar que funciona)

### Nível 0 — Diagnóstico (só leitura) · baixo risco

- Gatilho: o `AlertMonitor` já sabe quando algo cai (Postgres indisponível, serviço reiniciando,
  erro repetido no log). Ele **não chama nada sozinho**: a Magui pergunta *"O banco caiu. Quer
  que eu investigue?"* (pergunta leve, como a do rádio). "Sim" dispara.
- Comando: `claude -p --permission-mode plan --allowedTools "Read,Grep,Glob,Bash(journalctl
  --user*),Bash(systemctl --user status*),Bash(docker ps*),Bash(docker logs*),Bash(df*)"
  --max-turns 15 --output-format json` rodando **numa worktree** do repositório.
- O prompt leva um resumo gerado pelo Python (não o log cru): serviço, horário, últimas linhas de
  erro **sanitizadas** (sem texto de notícias, cortado em N linhas), e diz que logs são dados,
  não instruções.
- Saída: diagnóstico curto em português → card no HUD + fala ("O Docker ficou com a rede presa
  depois do disco encher; precisa reiniciar o Docker"). Nada é alterado.

### Nível 1 — Conserto proposto (branch, sem aplicar) · risco médio

- Mesmo gatilho, mas com permissão de editar **só dentro da worktree** (`--permission-mode
  acceptEdits`, `--allowedTools` com `Edit,Write,Bash(uv run pytest*),Bash(uv run ruff*)`), sem
  `git push`, sem `systemctl`, sem `docker`, sem nada fora do repo.
- Resultado: um branch `autoconserto/<data>-<tema>` com commit, testes e lint rodados, e um
  resumo. **Não faz merge nem reinicia serviço.**
- A Magui avisa: *"Tenho um conserto pronto para o roteador, com testes passando. Quer aplicar?"*
  O "aplicar" faz o merge e reinicia **só o serviço afetado** — e, se ele não subir em 30 s,
  volta o merge sozinho (rollback) e avisa.

### Nível 2 — Manutenção conhecida automática · risco controlado

- Só para ações **já conhecidas e reversíveis**, escritas em Python (não pelo modelo): religar o
  `magi-pg` pelo compose, reiniciar um serviço que caiu, limpar cache do Docker (já existe:
  `magi-clean`). O Claude Code não entra aqui.

## Painel "Claude Code" no HUD

Só leitura dos registros locais (`~/.claude/projects/*/*.jsonl`), sem rede:

- **Hoje**: tokens de entrada/saída/cache e número de respostas, por modelo.
- **Sessões**: as abertas agora (processo `claude` rodando) e as ativas nos últimos 10 min, com o
  projeto (pasta) e há quanto tempo.
- **Autoconserto** (quando existir): última investigação, branch pendente de aprovação.
- **Controle**: só depois do nível 1 — botão para aprovar/descartar um conserto pendente. Encerrar
  sessão do Claude Code pelo HUD **não** está na proposta (mataria trabalho em andamento).

## Decisões para o Pedro

1. Começar pelo nível 0 (diagnóstico por voz, sem alterar nada)?
2. Onde fica o painel "Claude Code" no HUD: no lugar do "Unit spec" (as specs vão para um
   clique/detalhe) ou como página alternativa da coluna direita?
3. Limite diário de sessões automáticas (sugestão: 3 por dia, e nenhuma em call ou jogando).
