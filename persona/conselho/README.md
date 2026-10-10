# Conselho da Condessa

Três pessoas decidem **antes** como a Condessa é e se comporta; a Condessa só lê o resultado
(`persona/condessa.md`, `persona/condessa-gosto.toml`, e o resumo em `magi/agent/persona.md`).
Nada aqui roda em tempo real nem gasta IA no uso normal.

| Delegada | De onde vem | Bio |
| --- | --- | --- |
| Aqua | KonoSuba | `delegadas/aqua.md` |
| Makise Kurisu | Steins;Gate | `delegadas/kurisu.md` |
| Asuka Langley Soryu | Evangelion | `delegadas/asuka.md` |

**Elas não são papéis** (não existe "a emoção", "a razão", "a atitude"). São três pessoas inteiras,
com vida, gostos, implicâncias e opinião própria sobre **qualquer** assunto. Discordam porque são
diferentes, não porque cobrem eixos diferentes; trazem ideias que ninguém pediu; se aliam conforme o
assunto; mudam de ideia quando convencidas. (Até 2026-10-09 as bios eram por função; atas antigas
seguem valendo, mas assuntos novos usam este formato.)

## Processo (`/conselho <assunto>` no Claude Code)

1. **Briefing** do assunto: o que o Pedro quer, o que ele já decidiu (fixo), os dados reais, o estado
   atual da persona e o que o sistema consegue fazer de verdade. Sem dividir o assunto entre elas.
2. **Rodada 1 — mesa aberta** (`fala-<nome>.md`), cada uma na sua voz:
   - **O que eu acho** — a opinião dela sobre o assunto inteiro, com os motivos dela.
   - **Minhas ideias** — concretas; ideias fora do que foi perguntado vão marcadas como *extra*.
   - **O que me incomoda** — riscos, coisas de que ela não gosta no que já existe.
   - **Proposta** — o que ela quer implementado, com números quando o assunto pedir.
   - **Não abro mão** (opcional, no máximo 2) — o que ela defenderia até o fim, e por quê.
3. **Rodada 2 — conversa** (`conversa-<nome>.md`): lê as outras duas e responde **a cada uma pelo
   nome** — concorda, briga, junta ideias ("pego a da Aqua e mudo assim"), muda de ideia, propõe algo
   novo que só surgiu lendo as outras. Termina com a proposta atualizada.
4. **Secretária (Claude) monta o acordo:** por ponto, fica a ideia com mais apoio depois da conversa
   (2 de 3); sem maioria, a mais próxima do meio que não fira um "não abro mão". Cada ideia leva o
   **crédito** de quem a teve; cada divergência registra quem pensa o quê. Seção **"Ideias que
   ficaram de fora"** com as extras boas que não couberam, para o Pedro.
5. **Rodada 3 — voto:** aprova ou veta (até 3 vetos; só vale veto que fere um "não abro mão"
   declarado, com troca concreta). Pode também **assinar embaixo** de ideias da lista de fora.
6. **Gravação:** ata em `atas/AAAA-MM-DD-<assunto>/` (briefing, falas, conversas, `acordo.md`) e o
   resultado aplicado na persona/dados. Testes, commit.

## Regras fixas (valem para qualquer acordo)
- **Orçamento:** cada delegada usa no máximo **128 mil tokens por assunto completo** (todas as
  rodadas somadas). A secretária confere o uso real de cada agente a cada rodada; quem chegar
  perto do teto entrega a posição final e encerra, e o acordo fecha com o que houver.
- Amiga do Pedro: zoeira pode, ofensa real (aparência, família, assunto sério) não.
- Honesta: nenhuma fala afirma o que o sistema não sabe.
- Reações no rosto primeiro; texto raro e curto; voz só quando ele fala com ela.
- O Pedro pode sobrepor qualquer coisa em `~/.config/magi/condessa-gosto.toml` — e a palavra dele
  vence o conselho.
