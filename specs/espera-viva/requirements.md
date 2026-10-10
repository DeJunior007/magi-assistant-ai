# Requisitos — Espera viva

Fonte: `docs/PROXIMOS-PASSOS.md` §2 ("Latência do agente — meta aceita; o foco vira a espera"),
regras da persona em `persona/condessa.md` e `magi/agent/persona.md`. Este arquivo é o **PRD**.
Arquitetura em [design.md](design.md); contratos e números em [spec.md](spec.md); implementação em
[tasks.md](tasks.md). Critérios em EARS:

- **O sistema DEVE …** — sempre vale. **QUANDO** gatilho, **o sistema DEVE** … — reação a evento.
- **ENQUANTO** estado, **o sistema DEVE** … · **SE** falha, **ENTÃO** … · **ONDE** opção ligada, …

"Núcleo" = `magi/core` + `magi/agent`; "HUD" = `hud/` (tema wired); "turno de agente" = turno cuja
rota é `RouteKind.AGENT` (pergunta ao modelo), não comando local.

## Problema

Pergunta ao agente leva p90 **3,39 s** do fim da fala até a voz (`docs/perf/fase1.md`, medição
após a 1.24): STT ~0,7 s + modelo ~1–1,5 s + primeiro byte do TTS ~0,6–0,9 s, em série. O Pedro
aceitou o número pela qualidade da resposta. O que incomoda é a espera **morta**: o retrato fica no
mesmo ciclo de olhares do `thinking`, sem som nenhum até a resposta, e pedidos de várias partes
só falam depois que tudo termina (ou, no máximo, a frase de espera que o modelo escreve antes de uma
ferramenta, que só sai depois do primeiro token do modelo).

## Objetivo

Sem cortar tempo, deixar a espera viva em três camadas, cada uma útil sozinha:
1. **Rosto:** "pensando" com etapas pelo tempo de espera e pelo que o núcleo está fazendo.
2. **Voz:** uma frase curta, ligada ao pedido, que soa logo depois da transcrição, sem mentir.
3. **Lotes:** em pedido de várias partes, ela entrega a parte pronta e segue preparando a próxima.

## Critérios de sucesso

1. Em turno de agente, o **primeiro som** (frase de espera ou resposta) sai com p90 ≤ **1,8 s** do
   fim da fala (medido por `tools/perf.py latency`, campo novo); o p90 da **resposta** não piora
   mais que 0,1 s (3,39 s → ≤ 3,5 s).
2. Nenhuma frase de espera do catálogo afirma ação, resultado, fonte ou prazo (teste do linter,
   spec §4) — CA-03.
3. Em 20 turnos reais seguidos, nenhuma frase de espera repete a anterior e no máximo 1 por turno.
4. Pedido de 2–3 partes ("como tá o tempo e quem ganhou o jogo") fala a 1ª parte antes de a
   última ferramenta terminar (teste com chat e ferramentas falsos) — CA-07.
5. CPU do HUD continua ≤ 10% de um núcleo com o "pensando" novo (mesma medida das reações).
6. Uma semana de uso real sem o Pedro achar a frase de espera "chata" ou "falsa" (nota em
   `docs/perf/espera.md`).

## Requisitos

**R1 — Pensando em etapas (HUD).** ENQUANTO a Magui estiver em `thinking` (ou no silêncio do
`speaking` que o retrato já trata como pensar, `PartsPortrait.thinking`), o HUD DEVE mudar a pose
pelo tempo desde o início da espera: **hm** (0–1,2 s), **pensando** (1,2–3,5 s), **concentrada**
(> 3,5 s), cada uma com olhar, efeito e corpo da spec §2.
- R1.1 A troca de etapa DEVE ser suave (a mesma suavização `_think_k` de hoje) e nunca piscar
  entre etapas.
- R1.2 SE um asset da pose não existir, ENTÃO o HUD DEVE pular só aquele item (como as reações,
  R1.1 de `specs/condessa-reacoes`).
- R1.3 Saindo de `thinking`/silêncio (voz começou), o HUD DEVE largar a pose em ≤ 1 quadro de fala.

**R2 — Rosto sabe o que ela está fazendo.** QUANDO o núcleo começar uma ferramenta do agente, ele
DEVE mandar ao HUD `{"t":"think","v":"tool","tool":<nome>}` (spec §1), e o HUD DEVE:
- R2.1 olhar para o painel ligado à ferramenta (tabela da spec §2.3), se houver;
- R2.2 trocar o chip `Thinking · 思考中` pelo rótulo da ferramenta (spec §2.4) até a fala começar.

**R3 — Frase de espera (núcleo).** QUANDO, num turno de agente, a transcrição estiver pronta e
nada tiver sido falado em `[espera] frase_apos_ms` (padrão 700 ms), o núcleo DEVE falar **uma**
frase de espera do catálogo (spec §3), escolhida pelo tópico do pedido.
- R3.1 A frase DEVE sair do cache de TTS (`phrases.yaml`, `lazy`/`templates`) para tocar sem ida
  à nuvem depois da 1ª vez.
- R3.2 A frase DEVE entrar no mesmo envio de áudio da resposta (`EarlySpeech`), antes dela, e não
  conta no limite de 2 frases da resposta final.
- R3.3 SE a resposta (ou a frase de espera do próprio modelo) já começou a tocar, ENTÃO o núcleo
  NÃO DEVE falar a frase de espera.
- R3.4 QUANDO a frase local já tocou, o núcleo DEVE descartar a 1ª frase de espera do modelo se
  ela for do mesmo tipo ("deixa eu ver…", "um segundo…": spec §3.4); frase de espera com conteúdo
  ("o tempo eu já sei: …") segue.
- R3.5 O núcleo NÃO DEVE falar frase de espera em comando local, confirmação, resposta a oferta,
  "não peguei", dispensa, aviso proativo nem no Learning Mode.
- R3.6 Cota (padrão, D2): no máximo 1 por turno; nunca a mesma frase de 2 turnos atrás; pula 1
  turno de agente a cada 3 se os 2 anteriores tiveram frase (para não virar tique).

**R4 — Honestidade da espera.** Toda frase de espera DEVE obedecer à spec §4: fala do que ela está
fazendo **agora** com a própria cabeça ("deixa eu pensar", "hm, {jogo}…"), nunca afirma ação de
ferramenta ("vou pesquisar"), resultado ("achei"), certeza ("sei sim"), fonte nem prazo
("rapidinho"). Teste de linter roda sobre o catálogo inteiro e os moldes preenchidos.

**R5 — Respostas em lotes (agente).** QUANDO o pedido tiver várias partes e o modelo responder uma
parte antes de chamar ferramenta para a próxima, o núcleo DEVE falar essa parte **na hora** como
**lote**, sem esperar o resto.
- R5.1 Cada lote DEVE ter no máximo 2 frases; no máximo `[espera] lotes_max` lotes (padrão 3) e
  `[espera] lotes_frases_max` frases faladas no turno (padrão 6), contando a resposta final.
- R5.2 Lote não conta como frase de espera (`INTERIM_MAX`) e a resposta final NÃO DEVE repetir o
  que um lote já disse (`EarlySpeech.missing`).
- R5.3 Entre um lote e o próximo, o núcleo DEVE mandar `{"t":"think","v":"lote","n":<n>}` e o HUD
  DEVE voltar à pose de **pensando** (sem reiniciar no "hm") e o chip a `Thinking`.
- R5.4 A legenda completa (`subtitle.full`) DEVE trazer os lotes e a resposta final, em ordem.
- R5.5 Ferramentas pedidas na mesma volta do modelo DEVEM rodar em paralelo (hoje são em série no
  `_tools_node`), menos as que pedem confirmação.

**R6 — Interrupção.** QUANDO o Pedro ativar de novo (wake/PTT) durante a frase de espera ou entre
lotes, o núcleo DEVE cancelar tudo como hoje (`EarlySpeech.cancel`, `_cancel_work`), e o HUD sair
da pose de pensando.

**R7 — Configuração.** O núcleo DEVE ler `[espera]` do `config.toml` (spec §5); ONDE
`frase = false`, R3 fica desligado; ONDE `lotes = false`, R5.1–R5.4 ficam desligados (comportamento
de hoje). Sem a seção, valem os padrões.

**R8 — Medida.** `tools/perf.py latency` DEVE medir, por turno, "fim da fala → primeiro som" além
de "fim da fala → resposta", e o núcleo DEVE logar em INFO `espera: frase "<texto>" em <ms>` e
`espera: lote <n> em <ms>`.

## Fora do escopo

- Cortar latência de STT/modelo/TTS (meta aceita). R5.5 só tira a espera em série das ferramentas.
- Frase de espera gerada por LLM extra (ver D1).
- Arte nova obrigatória: tudo funciona com os assets de hoje (R1.2).

## Decisões em aberto (precisam do Pedro)

- **D1 — Fonte da frase de espera.** (a) catálogo local por tópico, com cache de TTS e molde com o
  jogo em foco (zero custo, toca em ~0 s); (b) chamada a um modelo pequeno em paralelo (mais
  "ligada ao pedido", +custo, +~0,7 s de TTS sem cache, risco de prometer coisa); (c) nada novo, só
  a frase do modelo principal (hoje). **Padrão da spec: (a).**
- **D2 — Frequência.** (a) cota do R3.6 (1/turno, sem repetir, pula 1 a cada 3); (b) toda vez que
  passar do limiar; (c) só quando o pedido parece demorado (ferramenta provável pelo tópico).
  **Padrão: (a), limiar 700 ms após a transcrição.**
- **D3 — Lotes furam o "1 a 2 frases".** A persona manda 1–2 frases faladas. Lotes chegam a 6.
  (a) até 3 lotes / 6 frases só em pedido de várias partes explícitas; (b) 2 lotes / 4 frases;
  (c) lote só no HUD (falado continua 2 frases). **Padrão: (a)**, e a regra nova vai ao Conselho
  junto com o catálogo (E2.1).
- **D4 — Texto das frases pelo Conselho.** O catálogo (spec §3) sai de um `/conselho` (Aqua, Kurisu,
  Asuka) com a regra de honestidade da spec §4 como restrição. **Padrão: sim (tarefa E2.1)**; o
  Pedro pode vetar frases depois em `~/.config/magi/condessa-gosto.toml` `[espera] vetadas`.
- **D5 — Arte da etapa "concentrada".** Com mão no queixo (`extra/P14.png`) e olhos semicerrados
  (`eyes/B18.png`) fica melhor; sem elas a etapa usa B13 + efeito. **Padrão: código pronto, arte
  quando o Pedro gerar** (como D3 das reações).
