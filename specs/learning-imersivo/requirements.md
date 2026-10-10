# Requisitos — Learning imersivo (entrevista pela vaga)

Fonte: pedido do Pedro em `docs/PROXIMOS-PASSOS.md` §13 ("Learning Mode mais imersivo") e o SDD
original `specs/learning-mode/` (citado como **LM** para requisitos, **LM design §n**, **LM spec §n**).
Este arquivo é o **PRD**. Arquitetura em [design.md](design.md); contratos, números e mensagens em
[spec.md](spec.md); implementação em [tasks.md](tasks.md). Critérios em EARS:

- **O núcleo/HUD DEVE …** — sempre vale. **QUANDO** gatilho, **… DEVE** … — reação a evento.
- **ENQUANTO** estado, **… DEVE** … · **SE** falha, **ENTÃO** … · **ONDE** opção ligada, …

## Problema

O tema `interview` (LM1.8) é uma entrevista **genérica** (`DEFAULT_ROLE` ou `[learning]
interview_role` fixo na config), sem roteiro, sem fim e sem retorno: a Condessa pergunta "sobre
projetos e trade-offs" até o Pedro trocar de assunto. O Pedro quer treinar para **uma vaga real**:
colar a descrição, a Condessa entender o que a vaga pede e conduzir uma simulação com começo, meio
e fim, e dizer no final como ele foi.

Limites do sistema atual que a feature esbarra:
- o campo de texto da tela learning é um `QLineEdit` de **uma linha**, até **2000** caracteres
  (`LM_SAY_MAX`); descrições de vaga têm 2–8 mil caracteres e quebras de linha;
- o bloco de tema no prompt é cortado em **1500** caracteres (`TOPIC_BLOCK_MAX`);
- o `TopicBuilder` **não chama LLM nem rede** (LM spec §10.1 item 3);
- a persona do Learning proíbe correção explícita e o LM-013 regra 9 diz que tema "não vira roteiro".

## Objetivo

Um modo **entrevista pela vaga** dentro do Learning Mode: o Pedro manda a vaga (área de
transferência, arquivo ou a última usada, por botão ou voz), a Condessa extrai o perfil (cargo,
empresa, senioridade, stack, requisitos), monta um roteiro de etapas com tempo, conduz a simulação
em inglês (uma pergunta por vez, follow-ups) e, no fim, entrega um retorno escrito por requisito.
Os outros temas continuam como estão. Temas novos de roleplay ficam como **proposta** (D5).

## Critérios de sucesso

1. Do "colar a vaga" ao chip `INTERVIEW // <cargo>` confirmado em ≤ 8 s (p95, modelo cloud atual).
2. Em 3 vagas reais do Pedro (backend, full-stack, dados), o perfil extraído acerta cargo,
   senioridade e ≥ 80% dos itens de stack (conferência à mão no LIF.1).
3. Uma simulação de 30 min percorre todas as etapas do roteiro, sem repetir pergunta e sem a
   Condessa sair do papel de entrevistadora.
4. O retorno final cita cada requisito obrigatório como coberto / raso / não tocado, com um trecho
   da resposta do Pedro como evidência, e chega em ≤ 20 s depois do "end the interview".
5. Custo por simulação completa (extração + 30 min de conversa + retorno) ≤ US$ 0,15 e dentro do
   `[budget]` (LM-006).
6. Nada muda para os temas free/game/news nem fora do modo (LM-005); `tests/learning`,
   `tests/core` e `tests/hud` verdes.

## Glossário

- **Vaga** (`JobPost`): o texto bruto colado/lido + metadados de origem.
- **Perfil** (`JobProfile`): o que a extração tirou da vaga (spec §2).
- **Roteiro** (`InterviewPlan`): etapas ordenadas com cota de perguntas e tempo (spec §4).
- **Simulação** (`InterviewRun`): a execução do roteiro numa sessão (etapa atual, contagem, relógio).
- **Retorno** (`InterviewDebrief`): o feedback do fim (spec §6).

## Requisitos

**R1 — Mandar a vaga.** O Pedro DEVE poder entregar a descrição da vaga por:
- R1.1 **área de transferência**: botão `[ PASTE JOB ]` no seletor de tema (linha Tech interview) e
  no chip da entrevista; o HUD lê o clipboard (`QClipboard`, texto puro, com quebras de linha) e
  manda `lm_job` (spec §7). Não passa pelo `QLineEdit` nem pelo limite de 2000.
- R1.2 **colar no campo**: QUANDO o Pedro colar no campo de texto um texto com > 600 caracteres ou
  com quebra de linha, o HUD DEVE perguntar numa linha do rodapé `use as job description? [ YES ] [ NO ]`
  em vez de mandar como fala; `YES` lê o clipboard inteiro (R1.1).
- R1.3 **arquivo**: ONDE existir a pasta de vagas (D2), a lista do seletor DEVE mostrar as 3 vagas
  mais recentes (arquivos `.txt`/`.md` e as já usadas), e escolher uma DEVE carregá-la.
- R1.4 **voz**: "prepare the interview for the job I copied" / "treinar para a vaga que eu copiei"
  DEVE ter o mesmo efeito de R1.1 (o núcleo pede ao HUD o clipboard, spec §7 `lm_job_req`);
  "treinar de novo para a última vaga" / "same job again" DEVE recarregar a última vaga usada.
- R1.5 Texto vazio, < 200 caracteres ou > 12 000 caracteres DEVE ser recusado com uma linha curta
  (`too short to be a job post` / `job post too long — trimmed to 12k`; acima de 12k corta, não recusa).

**R2 — Preparar.** QUANDO uma vaga chegar, o núcleo DEVE:
- R2.1 responder `lm_interview {"state":"preparing"}` em ≤ 100 ms;
- R2.2 extrair o `JobProfile` com **uma** chamada ao `LearningModel` (tarefa `learning_job`, schema
  JSON da spec §2), contando no orçamento (LM-006);
- R2.3 montar o `InterviewPlan` **sem LLM**, por regra, a partir do perfil (spec §4);
- R2.4 guardar vaga, perfil e roteiro (spec §8) e confirmar `lm_topic` com `topic = interview`,
  `label = INTERVIEW // <CARGO>` e `lm_interview {"state":"ready",…}`;
- R2.5 SE a extração falhar (timeout, orçamento, JSON inválido), ENTÃO DEVE mostrar a linha de erro
  com `retry` (padrão LM-007) e manter o tema anterior; vaga já gravada não se perde.
- R2.6 A mesma vaga (mesmo hash do texto normalizado) NÃO DEVE ser extraída de novo: reusa o perfil.

**R3 — Conduzir.** ENQUANTO houver simulação ativa, a Condessa DEVE:
- R3.1 agir como entrevistadora da empresa da vaga, em inglês, **uma pergunta por vez**, seguindo a
  etapa atual do roteiro (spec §5), com no máximo `followups` follow-ups por pergunta;
- R3.2 abrir a simulação sozinha (abertura P11 do LM) com a etapa 1 (apresentação);
- R3.3 avançar de etapa quando a cota de perguntas da etapa fechar ou o tempo da etapa estourar
  (o que vier primeiro), e anunciar a transição numa frase natural ("Let's move on to…");
- R3.4 aceitar comandos do Pedro por voz e texto: próxima pergunta, repetir, pular etapa, pausar e
  encerrar (spec §5.3);
- R3.5 NÃO DEVE corrigir o inglês durante a simulação (persona do LM vale; recast permitido);
- R3.6 NÃO DEVE dar nota, veredito ou retorno no meio; se o Pedro pedir ("how am I doing?"), DEVE
  dizer em uma frase que o retorno vem no fim e seguir.

**R4 — Encerrar e retornar.** QUANDO a simulação terminar (todas as etapas, "end the interview",
botão `[ END INTERVIEW ]` ou fim da sessão com ≥ 3 respostas do Pedro na simulação), o núcleo DEVE:
- R4.1 gerar o `InterviewDebrief` com **uma** chamada ao `LearningModel` (tarefa `learning_job`)
  sobre as mensagens da simulação + perfil + roteiro (spec §6);
- R4.2 publicar `lm_debrief` e uma `lm_msg` curta da Condessa (2 frases, falada se `speak_replies`)
  dizendo que o retorno está na tela;
- R4.3 o retorno DEVE ter: cobertura por requisito obrigatório (`covered` | `thin` | `missed`, com
  evidência citada), até 3 pontos fortes, até 3 pontos a melhorar, até 2 respostas reescritas
  ("a stronger answer could be…") e as observações de inglês da simulação vindas do engine LM4
  (sem chamada nova); **sem nota numérica** (D3);
- R4.4 SE o encerramento vier com < 3 respostas do Pedro, ENTÃO não gera retorno e diz isso numa linha.
- R4.5 Fim de sessão por `idle`/`shutdown` com simulação ativa DEVE gerar o retorno em segundo plano,
  gravar e não publicar (aparece na próxima abertura do modo, R5.2).

**R5 — Persistir e retomar.**
- R5.1 Vagas, perfis, simulações e retornos DEVEM ir para tabelas novas aditivas (migração
  `004_learning_jobs.sql`) e para o backend JSONL equivalente (LM-010, RNF-05).
- R5.2 QUANDO o modo abrir com um retorno ainda não visto, a tela DEVE mostrá-lo uma vez.
- R5.3 Sessão retomada (LM spec §10) com simulação ativa DEVE voltar à mesma etapa e contagem.

**R6 — Tela.** A tela learning DEVE mostrar, ENQUANTO houver simulação: o chip
`INTERVIEW // <CARGO> · <EMPRESA>`, a etapa (`STAGE 3/6 · TECHNICAL — PYTHON`), o tempo da simulação
e o botão `[ END INTERVIEW ]`; e um painel do perfil (stack e requisitos) que abre ao clicar no chip.
O retorno abre num painel no lugar do drawer de observações, fechável.

**R7 — Honestidade e privacidade.**
- R7.1 A Condessa NÃO DEVE afirmar nada sobre a empresa além do que está na vaga (sem "a Acme usa
  Kafka" se a vaga não diz). O prompt de extração e o de condução DEVEM tratar a vaga como dado.
- R7.2 O texto da vaga DEVE ir ao modelo cloud só na extração; a condução usa o perfil, não o texto
  bruto. Nenhum dado pessoal do Pedro além das mensagens da simulação vai no retorno.
- R7.3 Nada de rede além do modelo: sem baixar a vaga de URL (D4).

**R8 — Sem quebrar o resto.** `interview` sem vaga continua o tema genérico de hoje (P14). Os
temas free/game/news, a persona e as ações do menu não mudam. Tudo atrás de `[learning] enabled`.

## Mudança de decisão do LM (precisa de "ok" do Pedro, já pedida por ele)

- **LM-013 regra 9** ("o tema NÃO DEVE virar lição nem roteiro"): passa a valer **exceto** para a
  entrevista com vaga, que tem roteiro e fim por pedido explícito do Pedro (§13). Free/game/news
  seguem sem roteiro.
- **"Sem nota nem avaliação"** do `interview.md`: na entrevista com vaga passa a haver retorno no
  fim (R4), ainda sem nota numérica (PDF §12, sem gamificação).

## Decisões em aberto (precisam do Pedro)

- **D1 — Como a vaga chega por voz.** O clipboard é do HUD (Wayland). (a) o núcleo manda
  `lm_job_req` e o HUD responde com `lm_job` do clipboard; (b) só botão/arquivo, sem voz para colar.
  **Padrão: (a).**
- **D2 — Pasta de vagas.** (a) `~/Documentos/vagas/` (visível, o Pedro salva ali); (b)
  `~/.local/share/magi/learning/jobs/` (escondida); (c) sem pasta, só clipboard. **Padrão: (a),
  configurável em `[learning] jobs_dir`; a tarefa LI3.1 só roda depois do "ok".**
- **D3 — Nota no retorno.** (a) sem nota, só cobertura por requisito e pontos; (b) nota de 1–5 por
  etapa. **Padrão: (a)** (PDF §12 proíbe gamificação).
- **D4 — Vaga por URL** (LinkedIn/Gupy): exige rede e scraping frágil. **Padrão: fora** (colar o texto).
- **D5 — Temas imersivos novos (proposta):** roleplay de situações do dia a dia em inglês — check-in
  no hotel, pedir comida, consulta médica, ligação com suporte, daily standup de time gringo, small
  talk num meetup, negociação de salário. Cada cenário é um arquivo de dados com papel, cenário e
  objetivo, sem LLM para montar. **Padrão: não implementar até o "ok"; a tarefa LI4.1 fica
  bloqueada.** Se aprovado: quais cenários entram primeiro?
- **D6 — Duração padrão da simulação.** 20, 30 ou 45 min. **Padrão: 30** (`[learning] interview_minutes`).
- **D7 — Idioma do retorno.** (a) inglês simples (como as ações, P5 do LM); (b) PT-BR. **Padrão:
  (a), com `[learning] explain_language` valendo também aqui.**
- **D8 — Modelo da extração/retorno.** Reusar `[tasks] learning_actions` ou tarefa própria
  `learning_job` (pode ser um modelo maior). **Padrão: tarefa própria, caindo para
  `learning_actions` se não configurada.**
