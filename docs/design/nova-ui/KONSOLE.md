# KONSOLE // CLAUDE CODE — terminal interativo no painel

Pedido do Pedro (2026-10-08): o card KONSOLE é um **terminal interativo de verdade** com o
Claude Code (o mesmo fluxo do autoconserto/"self implement", `docs/design/AUTOCONSERTO.md`), não
um card de estatísticas.

## Comportamento

- **Card (compacto, 310×333 no mockup):** moldura do mockup (barra de título com ícone,
  "KONSOLE // CLAUDE CODE", NODE 01 ●, –/□/×; aba "SESSION 01 ×  +"; barra de status em 2
  linhas). O miolo mostra as **últimas linhas** da tela do terminal em fonte mono pequena.
- **Sessão:** um processo `claude` num pty, `cwd` = repositório da MAGI
  (`~/Documentos/magi-assistant-ai`, configurável). Sobe **sob demanda** (primeiro clique no card),
  não com o HUD. Saiu → miolo mostra `[sessão encerrada · clique para abrir outra]`.
- **Expandido (para usar de verdade):** clique no card abre o Konsole grande por cima das colunas
  2–3 (área da câmera + Condessa + load history + unit spec, base 1920 ≈ x 553–1519, y 143–986),
  com a mesma moldura. Só no expandido o HUD aceita foco e teclado (mesma troca de
  `WindowDoesNotAcceptFocus` usada pela entrada do Learning, LM0.3/LM1.6). O redimensionamento
  ajusta o pty (`TIOCSWINSZ`) ao tamanho em células.
- **Sair do expandido:** botão "–" da barra de título ou clique fora; `Esc` vai para o Claude
  (ele usa Esc para interromper). A sessão continua rodando ao recolher.
- **Nada pisca** com o terminal ocioso (cursor fixo).

## Peças

- `hud/konsole_term.py` (sem Qt): `KonsoleSession` — pty + `subprocess` (`claude`), leitura não
  bloqueante, `pyte.Screen`/`ByteStream`, `resize(cols, rows)`, `write(bytes)`, `alive`,
  `lines()` / células com atributos; `qt_key_to_bytes(key, text, modifiers)` puro (setas, Enter,
  Backspace, Tab, Esc, Ctrl+letra, PgUp/PgDn, Home/End, Delete).
- `hud/wired/konsole_view.py`: pintura QPainter das células (paleta do mockup; cores ANSI
  mapeadas para a paleta), modo compacto (miolo do card) e expandido (janela inteira com
  moldura).
- `gamerhud.py`: ciclo de vida da sessão, bomba de leitura (QSocketNotifier no fd do pty),
  foco/teclado no expandido, clique para expandir/recolher.
- Dependência: `pyte` (puro Python). Testes via `uv` (pyproject); em runtime o HUD usa o
  Python do sistema → `sudo dnf install python3-pyte` (ou `pip install --user pyte`).
