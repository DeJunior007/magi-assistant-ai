# Latência do turno com o Learning Engine (tarefa LM4.2; CA-01, ENG-001, RNF-01)

## CA-01 automatizado: `tests/learning/test_latency.py`

200 turnos falsos pelo `TurnPipeline` real (roteador e agente falsos, agente "pensa" com
`asyncio.sleep`), na ordem do `TurnMachine._think`: `respond` → entrega → `after_delivery`. O relógio
mede do início do turno até a entrega. Com o engine ligado: `install` real, sessão aberta, mensagens
gravadas em `JsonlRepo`, observação por `FakeModel` com 10 ms de "rede" e 3 ms de pausa entre turnos.
Assim a observação de um turno ainda está em voo quando o próximo começa (o pior caso). Nada de
rede nem de banco.

Medido em 2026-10-09 (máquina do Pedro, Python 3.12):

| Turno falso | p95 desligado | p95 ligado | Razão p95 | Sobra absoluta |
| --- | --- | --- | --- | --- |
| 50 ms (o que o teste usa) | 50,3–50,4 ms | 51,1–51,2 ms | **1,015–1,018** | ~0,8 ms |
| 20 ms (estresse) | 20,3–20,5 ms | 22,1 ms | 1,080–1,086 | ~1,6 ms |
| 200 ms | 200,3 ms (mediana) | 200,8 ms (mediana) | 1,004 | ~0,5 ms |

Também conferido no teste:

- toda chamada de "rede" da observação começa com o núcleo em `listening` (gate), nunca durante o
  turno: nenhum `await` de rede antes da entrega;
- `after_delivery` → `on_turn` é síncrono e só agenda (máximo 0,6 ms, teto do teste 5 ms);
- 200 de 200 mensagens observadas (o engine trabalhou de verdade durante a medição);
- o `TurnMachine` só chama `after_delivery` depois de `_deliver`.

**Leitura.** A sobra vem só quando a observação termina *durante* o turno seguinte (gravação das
observações, `lm_obs`, decodificação do jsonl no mesmo loop): sem observação em voo (pausa de 40 ms
ou "rede" instantânea) a razão é 0,999. É uma sobra absoluta de ~1–1,5 ms por turno, que só passa
de 5% com turnos falsos mais curtos que ~30 ms. Turnos reais (LLM + TTS) levam de 0,5 a 4 s
(`docs/perf/fase1.md`), então a sobra fica abaixo de 0,3%. Por isso o teste usa 50 ms, ainda 10×
mais rápido que um turno real, e também exige sobra absoluta no p95 ≤ 3 ms, que não depende do
tamanho do turno falso. Não foi preciso propor o worker em processo à parte (design §1, riscos item 4).

## Medição real com o núcleo (pendente: Pedro, no teste ponta a ponta LMF.1)

Ainda não foi feita: precisa do núcleo no ar e de conversa com a Condessa, e gasta API.

Roteiro curto, usando o mesmo cliente de `docs/perf/fase1.md` (§ Latência):

1. Núcleo no ar com `[learning] enabled = true`. Abrir o modo pelo botão ou pela voz.
2. **Ligado:** com `[learning] observe = true`, rodar
   `uv run python -m tools.perf latency --turns 10 --phrase "yesterday I make a new feature" --gap 3 --json lm-on.json`.
3. **Desligado:** com `observe = false` (ou com o modo fechado), recarregar o núcleo quando o Pedro
   puder e repetir o comando com `--json lm-off.json`.
4. Comparar o p95 (fim da fala → primeiro áudio). Meta: ligado ≤ 1,05 × desligado. Com 10 turnos
   a amostra é pequena, então vale anotar também a média e conferir nos logs do núcleo que as
   observações (`learning:`) saíram depois de cada resposta.
5. Registrar os números numa tabela aqui e no PR.
