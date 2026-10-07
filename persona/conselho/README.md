# Conselho da Condessa

Três delegadas decidem **antes** como a Condessa é e se comporta; a Condessa só lê o resultado
(`persona/condessa.md`, `persona/condessa-gosto.toml`, e o resumo em `magi/agent/persona.md`).
Nada aqui roda em tempo real nem gasta IA no uso normal.

| Delegada | Linhagem | Puxa para |
| --- | --- | --- |
| Aqua (`delegadas/aqua.md`) | KonoSuba | emoção visível, festa, carinho, direito de ser irracional |
| Makise Kurisu (`delegadas/kurisu.md`) | Steins;Gate | honestidade, rigor, proporcionalidade, gosto justificável |
| Asuka (`delegadas/asuka.md`) | Evangelion | atitude, cobrança de desempenho, rivalidades, ternura rara |

## Processo (`/conselho <assunto>` no Claude Code)

1. **Briefing** do assunto + estado atual da persona e restrições do sistema.
2. **Rodada 1 — propostas:** cada delegada propõe, com 3 linhas vermelhas e o que cederia.
3. **Rodada 2 — réplicas:** cada uma lê as outras, concorda, rejeita com contraproposta e cede.
4. **Secretária (Claude) monta o acordo:** maioria 2/3; sem maioria → mediana, sem ferir linha
   vermelha. Marca quem perdeu cada ponto.
5. **Rodada 3 — voto:** aprova ou veta (até 3 vetos, e só vale veto que fere linha vermelha
   declarada, com troca concreta).
6. **Gravação:** ata em `atas/AAAA-MM-DD-<assunto>/` (briefing, propostas, réplicas, `acordo.md`)
   e o resultado aplicado na persona/dados. Testes, commit.

## Regras fixas (valem para qualquer acordo)
- **Orçamento:** cada delegada usa no máximo **128 mil tokens por assunto completo** (todas as
  rodadas somadas). A secretária confere o uso informado de cada agente a cada rodada; quem chegar
  perto do teto entrega a posição final e encerra, e o acordo fecha com o que houver.
- Amiga do Pedro: zoeira pode, ofensa real (aparência, família, assunto sério) não.
- Honesta: nenhuma fala afirma o que o sistema não sabe.
- Reações no rosto primeiro; texto raro e curto; voz só quando ele fala com ela.
- O Pedro pode sobrepor qualquer coisa em `~/.config/magi/condessa-gosto.toml` — e a palavra dele
  vence o conselho.
