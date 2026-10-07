# Requisitos — Condessa Learning Mode

Fonte: *Condessa Learning Mode – Living Specification* (PDF do Pedro, 5 páginas, "Draft / Living
Document") e o mockup *Generated Image October 07, 2026 – 5_52PM* (referência visual). Este arquivo
faz o papel do **PRD**: problema, objetivo, requisitos e critérios de sucesso. Comportamento
detalhado, contratos e casos de borda ficam em [spec.md](spec.md); arquitetura em
[design.md](design.md); implementação em [tasks.md](tasks.md).

**Os IDs do PDF são preservados** (`CTX-`, `PRN-`, `CNV-`, `SEL-`, `IMP-`, `EXP-`, `TRA-`, `VOC-`,
`ASK-`, `ENG-`, `OBS-`, `DAT-`, `MEM-`, `UI-`, `SYS-`) com o texto original. Requisitos que este SDD
acrescenta, vindos do sistema real (voz, HUD, banco, orçamento), usam o prefixo **`LM-`** para não
se misturar com a numeração do Pedro. Cada item leva a classificação da seção 15 do PDF:

| Classificação | Sentido |
| --- | --- |
| **REQUIREMENT** | Obrigatório no MVP (fases 1–4). |
| **CURRENT DECISION** | Decidido para o ciclo atual; pode mudar com atualização deste SDD. |
| **CURRENT DIRECTION** | Direção preferida, não obrigatória; há alternativa provisória. |
| **OPEN QUESTION** | Depende do Pedro; ver design §16. |
| **FUTURE** | Fora do MVP. Fica registrado, **sem task de implementação**. |

Critérios no formato EARS (como em `specs/condessa-engine/`):

- **O Learning Mode DEVE …** — sempre vale.
- **QUANDO** gatilho, **o Learning Mode DEVE** … — reação a um evento.
- **ENQUANTO** estado, **o Learning Mode DEVE** … — vale durante um estado.
- **SE** situação indesejada, **ENTÃO o Learning Mode DEVE** … — tratamento de falha.
- **ONDE** opção ligada, **o Learning Mode DEVE** … — comportamento opcional.

## Problema

A Condessa já conversa em inglês britânico (`[speech] language = "en-gb"`, voz Kokoro
`bf_isabella`, STT com `listen = "auto"`), mas a conversa é só por voz e efêmera: a legenda
(`hud/speech_caption.py`) some, nada do que o Pedro disse fica na tela para ser revisto, e não há
como pedir "isso que eu falei está certo?" sem quebrar o diálogo. Apps de curso resolvem com
lições e correção ativa, o que o Pedro **não** quer (CTX-002): ele quer conversar, e aprender sob
demanda em cima do que já foi dito.

## Objetivo

Um modo de tela em que a **conversa com a Condessa é o centro** (voz e texto, com histórico
selecionável), com quatro ferramentas sob demanda sobre qualquer trecho selecionado (Improve,
Explain, Translate, Vocabulary) e uma análise silenciosa em background que junta **observações**
num indicador recolhível — sem nunca atrasar a resposta da conversa.

## Critérios de sucesso (DoD do PDF §16)

1. O Pedro mantém um diálogo natural sem interrupção: nenhuma correção não pedida aparece no fluxo
   (CNV-002) e a latência da resposta com o Learning Mode ligado não piora mais que 5% (p95) em
   relação ao modo normal (ENG-001).
2. A tela principal "respira": no estado padrão só há conversa, Condessa, entrada de áudio/texto e
   contexto mínimo da sessão; métricas de sistema e observações ficam recolhidas.
3. Qualquer trecho antigo do histórico pode ser selecionado e abre o menu de ações sem quebrar o
   layout nem rolar a conversa.
4. Improve/Explain/Translate/Vocabulary devolvem resultado útil e não intrusivo (balão junto do
   trecho) em até 4 s (p95) com o modelo provisório.
5. Observações geradas em background ficam acessíveis pelo indicador `OBSERVATIONS [nn]`, ocultas
   por padrão.
6. Trocar o modelo das ações ou das observações é mudar uma linha de config, sem mexer no código
   (ENG-002).

## Glossário

| Termo | Significado |
| --- | --- |
| Learning Mode | O modo descrito aqui: tela de conversa de aprendizado de inglês com a Condessa. |
| Sessão | Uma conversa de aprendizado, do "start" ao "end" (ou inatividade). Tem ID `LS-` + data + n. |
| Mensagem | Uma fala/texto do Pedro (`you`) ou da Condessa (`condessa`) dentro de uma sessão. |
| Trecho | Intervalo de caracteres selecionado em uma mensagem (palavra, expressão ou frase). |
| Ação | Improve, Explain, Translate ou Vocabulary aplicada a um trecho. |
| Observação | Achado pedagógico gerado em background (vocabulário, padrão gramatical, recorrência). |
| Learning Engine | Worker assíncrono que gera observações e executa as ações (design §6). |
| Conversation Engine | O pipeline de turno que já existe (`magi/core/turn.py`), usado sem mudar sua latência. |

---

## Grupo CTX — Contexto do sistema (PDF §2)

**História:** como Pedro, quero aprender inglês conversando com a Condessa, não fazendo um curso.

| ID | Texto (PDF) | Classe |
| --- | --- | --- |
| CTX-001 | A experiência principal MUST ser uma conversa natural com a Condessa, recebendo assistência pedagógica contextual apenas quando necessário. | REQUIREMENT |
| CTX-002 | O sistema NÃO deve ser projetado como um aplicativo tradicional de cursos de inglês (módulos fixos, testes bloqueantes ou currículo estrito). | REQUIREMENT |
| CTX-003 | A "Conversa" MUST permanecer o fluxo primário e central do sistema. | REQUIREMENT |

1. O Learning Mode DEVE abrir direto na conversa, sem tela de lição, teste de nivelamento ou menu de módulos. *(CTX-001, CTX-002)*
2. O Learning Mode NÃO DEVE ter lições numeradas, bloqueio de progresso nem currículo. *(CTX-002)*

## Grupo PRN — Princípio de design (PDF §3)

| ID | Texto (PDF) | Classe |
| --- | --- | --- |
| PRN-001 | A interface MUST priorizar: a Conversa, a entidade Condessa, o áudio/input e o contexto mínimo da sessão. | REQUIREMENT |
| PRN-002 | Ferramentas de aprendizado MUST ser sob demanda (On-Demand). | REQUIREMENT |
| PRN-003 | Métricas e dados secundários MUST usar Progressive Disclosure. | REQUIREMENT |
| PRN-004 | Informações de background (correções silenciosas, métricas) NÃO devem competir visualmente com o fluxo de mensagens. | REQUIREMENT |

1. A coluna da conversa DEVE ocupar a maior área da tela e ter o maior contraste de texto. *(PRN-001)*
2. Nenhuma ferramenta de aprendizado DEVE aparecer sem gesto do Pedro (seleção ou clique). *(PRN-002)*
3. QUANDO uma observação nova chegar, o Learning Mode DEVE só atualizar o contador do indicador, sem animação piscante, som ou foco. *(PRN-004)*

## Grupo CNV — Conversação (PDF §5)

| ID | Texto (PDF) | Classe |
| --- | --- | --- |
| CNV-001 | A Condessa MUST responder de forma natural e contextualizada à mensagem do usuário. | REQUIREMENT |
| CNV-002 | O sistema NÃO deve interromper o fluxo da conversa para corrigir ativamente o usuário em tempo real. | REQUIREMENT |
| CNV-003 | Correções, análises gramaticais e observações de vocabulário SHOULD ocorrer em background. | REQUIREMENT |

1. QUANDO o Pedro mandar uma mensagem (voz ou texto), a Condessa DEVE responder em inglês britânico, no tom de conversa, sem apontar erros dele. *(CNV-001, CNV-002)*
2. A persona da Condessa no Learning Mode PODE reformular naturalmente ("What kind of authentication system did you build?") mas NÃO DEVE dizer "you should say…" sem pedido. *(CNV-002)*
3. QUANDO uma mensagem do Pedro for gravada, o Learning Mode DEVE enfileirá-la para análise em background. *(CNV-003)*

## Grupo LM — Acréscimos deste SDD (sistema real)

| ID | Requisito | Classe |
| --- | --- | --- |
| LM-001 | A conversa DEVE aceitar **texto digitado** além de voz, e as duas entradas vão para o mesmo histórico e a mesma sessão. | REQUIREMENT |
| LM-002 | Toda fala do Pedro DEVE entrar no histórico como texto (o `heard` do STT, antes do `Corrector`), e toda resposta da Condessa como texto completo, mesmo quando falada. | REQUIREMENT |
| LM-003 | ENQUANTO a Condessa fala, a mensagem dela DEVE aparecer no histórico revelada em sincronia com a fala (reuso da lógica de `hud/speech_caption.py`); ao terminar, fica inteira e selecionável. | REQUIREMENT |
| LM-004 | O Learning Mode DEVE ter controles de sessão: iniciar, encerrar, mudo do microfone e alternar "falar a resposta" (voz liga/desliga). | REQUIREMENT |
| LM-005 | Entrar/sair do Learning Mode NÃO DEVE quebrar o assistente normal (comandos de voz, HUD wired, standby). | REQUIREMENT |
| LM-006 | Toda chamada de LLM do Learning Mode (ações e observações) DEVE contar no orçamento mensal existente (`[budget]`, tabela `costs`) e ser recusada com mensagem curta quando o teto estourar. | REQUIREMENT |
| LM-007 | SE uma ação falhar (timeout, modelo fora, JSON inválido), ENTÃO o balão DEVE mostrar uma linha de erro com "retry", sem afetar a conversa. | REQUIREMENT |
| LM-008 | O idioma de saída das ações DEVE seguir a regra: Translate em PT-BR; Improve, Explain e Vocabulary em inglês simples, com opção de config para PT-BR. | CURRENT DECISION (proposta; P5) |
| LM-009 | O nível exibido (ex.: `B2 · CONVERSATION`) vem de config manual no MVP. | CURRENT DECISION (proposta; P3) |
| LM-010 | Nenhuma operação do Learning Mode DEVE executar `docker compose down`, `docker rm` ou `DROP` no `magi-pg` (compartilhado); só migrações aditivas. | REQUIREMENT |

## Grupo SEL — Seleção contextual (PDF §6)

**História:** como Pedro, quero selecionar algo que eu (ou ela) disse e pedir ajuda só naquilo.

| ID | Texto (PDF) | Classe |
| --- | --- | --- |
| SEL-001 | Após a seleção de texto, a UI MUST apresentar um menu de ações contextuais. | REQUIREMENT |
| SEL-002 | O menu MUST ser pequeno e posicionado próximo ao contexto. NÃO deve abrir um dashboard ou modal de tela cheia automaticamente. | REQUIREMENT |
| SEL-003 | Ações primárias: Improve, Explain, Translate, Vocabulary, e futuramente "Ask Condessa...". | REQUIREMENT (Ask = FUTURE) |

1. QUANDO o Pedro soltar o mouse com um trecho não vazio selecionado numa mensagem, o Learning Mode DEVE mostrar o menu ancorado logo abaixo do fim da seleção, dentro da coluna da conversa. *(SEL-001, SEL-002)*
2. O menu DEVE mostrar o trecho (`selected: "I make"`) e as quatro ações; "Ask Condessa…" NÃO aparece no MVP. *(SEL-003, ASK-001)*
3. QUANDO a seleção atravessar duas mensagens, o Learning Mode DEVE recortá-la para a mensagem onde começou. *(SEL-001)*
4. QUANDO o Pedro clicar fora, apertar Esc ou mudar a seleção, o menu e o balão DEVEM fechar. *(SEL-002)*
5. Improve DEVE ficar desabilitado em trechos de mensagens da Condessa (só faz sentido no texto do Pedro). *(IMP-003; P7)*

## Grupo IMP — Improve (PDF §6.1)

| ID | Texto (PDF) | Classe |
| --- | --- | --- |
| IMP-001 | MUST mostrar o texto original e a sugestão lado a lado ou de forma comparativa clara. | REQUIREMENT |
| IMP-002 | MUST explicar brevemente o motivo da alteração (diferenciando erro gramatical de "naturalidade"). | REQUIREMENT |
| IMP-003 | MUST preservar a intenção e o significado originais do usuário. | REQUIREMENT |

1. O resultado DEVE ter `original`, `improved`, `kind` (`grammar` | `naturalness` | `both` | `none`) e `why` (≤ 2 frases). *(IMP-001, IMP-002)*
2. QUANDO o trecho já estiver correto e natural, o resultado DEVE dizer isso (`kind = none`) em vez de inventar mudança. *(IMP-003)*
3. A sugestão DEVE considerar a frase inteira como contexto, mas mostrar a comparação no nível da frase que contém o trecho. *(IMP-001)*

## Grupo EXP — Explain (PDF §6.2)

| ID | Texto (PDF) | Classe |
| --- | --- | --- |
| EXP-001 | O objetivo é ensinar a regra ou costume, não apenas substituir a frase. | REQUIREMENT |

1. O resultado DEVE ter uma pergunta curta reformulada (`Why "built" instead of "made"?`) e uma resposta de 1 a 4 frases com a regra ou o costume de uso. *(EXP-001)*

## Grupo TRA — Translate (PDF §6.3)

| ID | Texto (PDF) | Classe |
| --- | --- | --- |
| TRA-001 | A resposta MUST ser proporcional ao pedido (tradução simples para palavra simples, sem gerar aulas extensas). | REQUIREMENT |

1. Para trecho de até 3 palavras, o resultado DEVE ser a tradução (+ no máximo uma nota de uso de 1 linha); para frase, só a tradução. *(TRA-001)*

## Grupo VOC — Vocabulary (PDF §6.4)

| ID | Texto (PDF) | Classe |
| --- | --- | --- |
| VOC-001 | MUST prover: Significado, Contexto na frase, Classe gramatical, Exemplos de uso, Sinônimos e Nível aproximado (CEFR). | REQUIREMENT |
| VOC-002 | A quantidade de informação carregada na UI MUST ser adaptativa (evitando poluição visual). | REQUIREMENT |

1. O balão DEVE mostrar primeiro significado, classe e CEFR; exemplos e sinônimos ficam atrás de "more". *(VOC-002)*
2. QUANDO o trecho for maior que 4 palavras, Vocabulary DEVE ficar desabilitado (não é vocabulário). *(VOC-002)*

## Grupo ASK — Ask Condessa (PDF §6.5) — FUTURE

| ID | Texto (PDF) | Classe |
| --- | --- | --- |
| ASK-001 | A thread gerada MUST reter o contexto estrito do trecho selecionado. | FUTURE |

Sem critérios no MVP. O contrato de ação (spec §5) já leva `message_id` + intervalo para permitir isso depois.

## Grupo ENG — Engine e latência (PDF §7.1)

| ID | Texto (PDF) | Classe |
| --- | --- | --- |
| ENG-001 | A análise de aprendizado NÃO PODE bloquear ou atrasar a geração e exibição da resposta real-time. | REQUIREMENT |
| ENG-002 | A implementação concreta dos Engines e o roteamento dos LLMs podem ser alterados, contanto que obedeçam a restrição de latência não-bloqueante. | REQUIREMENT |
| — | Qwen local para análise/observações em background (PDF §15). | CURRENT DIRECTION (P2) |
| — | Qual modelo de fronteira (cloud vs local) na versão final (PDF §15). | OPEN QUESTION (P2) |

1. O Conversation Engine DEVE só **publicar** a mensagem num canal/fila (custo O(1), sem `await` em rede) e seguir; o Learning Engine consome em outra tarefa. *(ENG-001)*
2. ENQUANTO a Condessa estiver em THINKING ou SPEAKING, o Learning Engine NÃO DEVE iniciar análise de observação (as ações pedidas pelo Pedro podem rodar). *(ENG-001)*
3. SE a fila de observações passar de 50 itens, ENTÃO o Learning Engine DEVE descartar os mais antigos e registrar o descarte. *(ENG-001)*
4. O modelo das ações e o das observações DEVEM ser chaves de config separadas (`[tasks] learning_actions`, `learning_observe`). *(ENG-002)*

## Grupo OBS — Observações (PDF §7.2)

| ID | Texto (PDF) | Classe |
| --- | --- | --- |
| OBS-001 | Indicador de UI MUST ser compacto (ex.: `OBSERVATIONS [03]`). | REQUIREMENT |
| OBS-002 | Ao ser expandido (Drawer/Overlay), MUST agrupar em: Vocabulário, Padrões Gramaticais e Ocorrências Recorrentes. | REQUIREMENT |

1. O indicador DEVE começar recolhido e mostrar a contagem da sessão com 2 dígitos. *(OBS-001)*
2. QUANDO expandido, DEVE mostrar as três categorias; cada item pode ser clicado para destacar a mensagem de origem no histórico. *(OBS-002)*
3. "Recorrentes" no MVP = mesma categoria/regra observada 2+ vezes **na sessão** (recorrência entre sessões é MEM-001, FUTURE). *(OBS-002, MEM-002)*

## Grupo DAT — Persistência (PDF §8)

| ID | Texto (PDF) | Classe |
| --- | --- | --- |
| DAT-001 | Utilizar PostgreSQL + pgvector executados localmente via Docker. | CURRENT DIRECTION (o `magi-pg` já existe) |
| DAT-002 | Entidades previstas: users, sessions, messages, corrections, vocabulary, grammar_patterns, learning_progress, observations. | CURRENT DIRECTION — MVP só sessions, messages, observations, action_results (design §8); o resto é Fase 5 (FUTURE) |
| DAT-003 | pgvector MUST ser usado somente quando houver necessidade real e explícita de busca semântica. | REQUIREMENT |
| — | Uso de contêineres locais para persistência (PDF §15). | CURRENT DECISION |
| — | Malha completa de banco PostgreSQL/pgvector (PDF §12). | FUTURE (fora do ciclo) |

1. O MVP DEVE criar só tabelas novas, prefixadas `learning_`, por migração aditiva (`003_learning.sql`), sem coluna `vector`. *(DAT-003, LM-010)*
2. Os nomes NÃO DEVEM colidir com as tabelas existentes `corrections`, `vocab`, `progress`, `turns`. *(DAT-002)*

## Grupo MEM — Memória longitudinal (PDF §9) — FUTURE

| ID | Texto (PDF) | Classe |
| --- | --- | --- |
| MEM-001 | O sistema deverá correlacionar observations antigas com novas transcrições (ex.: "I have went" nas sessões 12, 27 e 41). | FUTURE |
| MEM-002 | Não exigido no MVP, mas a arquitetura de banco deve permitir. | REQUIREMENT (só o "permitir") |

1. Cada observação DEVE gravar `rule_key` estável (ex.: `grammar.past_simple.irregular`) e `session_id`, para que MEM-001 seja uma consulta futura sem migração destrutiva. *(MEM-002)*

## Grupo UI — Condessa e nível (PDF §10)

| ID | Texto (PDF) | Classe |
| --- | --- | --- |
| UI-001 | A Condessa MUST possuir representação visual clara (slot requerido), comunicando o estado (ex.: TEACHING, LISTENING). | REQUIREMENT |
| UI-002 | Informações do usuário, como Nível (ex.: `B2 · CONVERSATION`), MUST ser exibidas de maneira simples. | REQUIREMENT |
| UI-003 | Métricas detalhadas de proficiência vão para uma visualização dedicada (Learning Profile). | REQUIREMENT (botão) / FUTURE (o painel, Fase 7) |

1. O slot da Condessa DEVE reusar o retrato/mascote existente (`hud/wired/mascot.py`, `portrait*.py`) e mostrar um rótulo de estado mapeado do estado do núcleo (spec §7). *(UI-001)*
2. O botão `[ VIEW LEARNING PROFILE ]` PODE aparecer desabilitado com dica "coming later" no MVP. *(UI-003)*

## Grupo SYS — Informações de sistema (PDF §11)

| ID | Texto (PDF) | Classe |
| --- | --- | --- |
| SYS-001 | Métricas do ecossistema MAGI são permitidas, mas MUST ser secundárias no Learning Mode. | REQUIREMENT |
| SYS-002 | Devem ficar em painéis recolhíveis, ícones ou telas secundárias; não competir com o texto da conversa. | REQUIREMENT |

1. O painel MAGI SYSTEM (Melchior/Balthasar/Casper) DEVE usar texto em `TEXT_DIM` e poder ser recolhido para uma linha. *(SYS-001, SYS-002)*

## Fora de escopo do ciclo atual (PDF §12) — FUTURE, sem tasks

- Malha completa de banco PostgreSQL/pgvector (Fase 5–6).
- Implementação presa ao Qwen (o executor pode variar).
- Gamificação (XP, badges).
- Currículo formal (lições 1 a 100).
- Redesign da identidade visual da base MAGI (o Learning Mode reusa o tema wired).
- Ask Condessa (ASK-001), memória longitudinal (MEM-001), Learning Profile (UI-003, Fase 7),
  personalização da pedagogia pelo nível (Fase 8).

## Requisitos não funcionais

| ID | Requisito | Meta |
| --- | --- | --- |
| RNF-01 | Latência da conversa com Learning Mode ligado | p95 até +5% vs. modo normal; 0 `await` de rede no caminho do turno (ENG-001) |
| RNF-02 | Resposta de uma ação | p95 ≤ 4 s com modelo cloud provisório; balão mostra "thinking…" em ≤ 100 ms |
| RNF-03 | Abrir o menu após soltar o mouse | ≤ 50 ms |
| RNF-04 | Custo | ações + observações ≤ US$ 1/mês em uso típico (30 sessões × 40 mensagens), dentro do `[budget]` |
| RNF-05 | Banco | só migração aditiva; nunca `DROP`/`down`/`rm` no `magi-pg` (LM-010) |
| RNF-06 | Tela | layout pensado para 3440×1440 (ultrawide do Pedro) e funcional em 1920×1080 |
| RNF-07 | Dependências | só o que o projeto já usa (PySide6, psycopg, providers); nada de Node/React no MVP salvo decisão P1 |
| RNF-08 | Privacidade | conversas ficam no Postgres local; só o trecho + mensagem de contexto vão ao modelo cloud |
