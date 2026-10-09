# Condessa — reações: instalação dos sinais

SDD: `specs/condessa-reacoes/`. Aqui fica só o que o Pedro instala à mão.

## Hooks do Claude Code (sinal C → reações 54 e 55)

**Instalado em 2026-10-09** (com autorização do Pedro) em `~/.claude/settings.json`, usando `PostToolUseFailure` (só dispara quando a ferramenta falha) e `async: true`; backup em `~/.claude/settings.json.bak-hooks`. Para desligar: `/hooks` no Claude Code ou apagar as três entradas.

O script `hud/tools/claude_hook.py` lê o JSON do hook no stdin e acrescenta uma linha em
`~/.cache/magi/claude-events.jsonl` (`{"t": epoch, "ev": "fail"|"notify"|"stop", "proj": "<pasta>"}`;
gira em 1 MB para `claude-events.jsonl.1`). Só biblioteca padrão, nunca imprime nada e sempre sai
com código 0 — não interfere no Claude Code.

| Hook | Evento | Reação |
|---|---|---|
| `PostToolUse` | `fail` (só quando a resposta da ferramenta indica erro) | 54 `claude_erro` |
| `Notification` | `notify` (Claude esperando você / pedindo permissão) | 55 `claude_espera` |
| `Stop` | `stop` (registrado; o 53 já sai da transição rodando → parado) | — |

Trecho para `~/.claude/settings.json` (juntar com um `"hooks"` que já exista):

```json
{
  "hooks": {
    "PostToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": "python3 /home/pedrojr/Documentos/magi-assistant-ai/hud/tools/claude_hook.py fail"}]}],
    "Notification": [{"hooks": [{"type": "command", "command": "python3 /home/pedrojr/Documentos/magi-assistant-ai/hud/tools/claude_hook.py notify"}]}],
    "Stop": [{"hooks": [{"type": "command", "command": "python3 /home/pedrojr/Documentos/magi-assistant-ai/hud/tools/claude_hook.py stop"}]}]
  }
}
```

Se a versão do Claude Code tiver o hook `PostToolUseFailure`, dá para trocar a chave
`PostToolUse` por ela (mesmo comando): aí o script grava toda chamada, sem precisar adivinhar o
erro pela resposta.

Teste rápido, sem o Claude Code:

```sh
echo '{"hook_event_name":"Notification","cwd":"/tmp/x"}' | python3 hud/tools/claude_hook.py notify
tail -1 ~/.cache/magi/claude-events.jsonl
```

No HUD, o `ClaudeStats` (a cada 15 s) lê só as linhas novas — o que já estava no arquivo quando o
HUD abriu não reage — e o `det_claude` toca 54/55 uma vez por evento, se ele tiver ≤ 2 min.
