# Requisitos — Condessa Engine

Fonte: *Condessa Engine – Arquitetura de Desenvolvimento* (PDF, 3 páginas) e as decisões do Pedro
de 2026-10-07 (D1–D10, listadas no fim). Este arquivo faz o papel do **PRD**: problema, objetivo,
requisitos e critérios de sucesso. Comportamento detalhado, contratos e casos de borda ficam em
[spec.md](spec.md); arquitetura em [design.md](design.md); implementação em [tasks.md](tasks.md).
Critérios no formato EARS:

- **O Engine DEVE …** — sempre vale.
- **QUANDO** gatilho, **o Engine DEVE** … — reação a um evento.
- **ENQUANTO** estado, **o Engine DEVE** … — vale durante um estado.
- **SE** situação indesejada, **ENTÃO o Engine DEVE** … — tratamento de falha.
- **ONDE** opção ligada, **o Engine DEVE** … — comportamento opcional.

## Problema

Hoje, quando o Pedro quer uma coisa nova (na Condessa ou num projeto pessoal), ele abre um console e
conduz o Claude Code na mão: explica, revisa, pede teste, faz merge. O autoconserto
(`magi/maintenance/autofix.py`) já automatiza um caso estreito (conserto de serviço caído), mas não
há um caminho seguro e rastreável para **intenções** maiores ("quero um sistema de plugins"), nem
para a Condessa melhorar a si mesma sem que um agente saia mexendo no código sem freio.

## Objetivo

Um harness que transforma uma intenção em artefatos persistentes e verificáveis
(**PRD → DESIGN → SPEC → TASKS**, cada task autocontida em ≤ 128k tokens), executa cada task com um
agente descartável (Claude Code headless), valida tudo com um motor de decisão determinístico
(**Jev**: PASS / RETRY / HUMAN) e só pede o Pedro **uma vez, no merge**.

## Critérios de sucesso

1. Uma intenção pequena real na própria Condessa vai de IDEA a DONE com **um único** "aprova" do Pedro.
2. Nenhuma task chega a REVIEW com gate vermelho, arquivo fora do declarado ou caminho proibido
   (medido no histórico do Jev: 0 casos).
3. Para qualquer linha de código entregue pelo Engine, `magi-engine why <arquivo>:<linha>` mostra
   task → item do spec → componente do design → requisito do PRD.
4. Nenhuma sessão do Claude Code do Engine passa de 128k tokens de contexto sem ser encerrada.
5. Nenhum repositório da empresa (Sume / GitLab) é tocado, nem para leitura, em nenhum teste.

## Glossário

| Termo | Significado |
| --- | --- |
| Engine | O Condessa Engine (sistema descrito aqui), em `engine/` neste repositório. |
| Intenção | Pedido de mudança em um projeto ("quero X"). Tem ID `INT-NNNN`. |
| Projeto | Repositório que declarou seus gates num arquivo do Engine (`engine/validation/projects/<nome>.toml`). |
| Projeto próprio (*self*) | Este repositório (a Condessa). |
| Artefato SDD | PRD, Design, Spec ou Tasks de uma intenção; arquivo Markdown com cabeçalho YAML. |
| Task | Unidade de implementação autocontida (`T001`…), executada por uma sessão em ≤ 128k tokens. |
| Gate | Comando do projeto que precisa passar (lint, test, build). |
| Jev | Motor de decisão determinístico (sem LLM) em `engine/decisions/`. Vereditos: PASS, RETRY, HUMAN. |
| Pacote de contexto | Texto montado pelo harness que a sessão recebe ao começar uma task. |
| Ocupação | Tokens no contexto da sessão numa resposta: entrada + leitura de cache + escrita de cache + saída. |
| Console | Janela do Konsole onde o Engine mostra o andamento ao vivo. |

---

## Requisito 1 — Abrir uma intenção (D5)

**História:** como Pedro, quero dizer "Condessa, quero X no projeto Y" e ter isso virando trabalho rastreado.

1. QUANDO o Pedro abrir uma intenção por voz ("Condessa, quero …"), pelo HUD ou pelo comando `magi-engine open`, o Engine DEVE criá-la no estado IDEA com ID, texto, projeto, origem e horário, e confirmar em voz ou texto com o ID.
2. QUANDO a intenção não disser o projeto, o Engine DEVE assumir a própria Condessa e dizer isso na confirmação.
3. SE o projeto citado não tiver arquivo de projeto no Engine, ENTÃO o Engine DEVE recusar a intenção e dizer qual arquivo falta.
4. SE o projeto for da empresa (Sume ou qualquer remoto GitLab), ENTÃO o Engine DEVE recusar a intenção, mesmo que exista arquivo de projeto, sem ler o repositório.
5. O Engine DEVE guardar o texto da intenção como dado (nunca como instrução de sistema) nos prompts que gerar a partir dela.

## Requisito 2 — Intenções propostas pela Condessa (D5)

**História:** como Pedro, quero que ela perceba sozinha o que dá para melhorar nela mesma, sem nunca mexer nos meus outros projetos por conta própria.

1. QUANDO o mesmo erro aparecer repetido no log dos serviços dela (limiar em spec), o Engine DEVE criar uma intenção com origem `condessa` para o projeto próprio e avisar por voz.
2. QUANDO um pedido do Pedro cair como "não sei fazer" repetidas vezes (limiar em spec), o Engine DEVE criar uma intenção com origem `condessa` descrevendo a capacidade que falta.
3. O Engine NÃO DEVE criar intenção com origem `condessa` para nenhum projeto além do próprio.
4. O Engine DEVE limitar as intenções com origem `condessa` a no máximo 1 aberta por vez e 2 por semana.
5. QUANDO o Pedro disser "descarta a proposta", o Engine DEVE encerrar a intenção proposta em qualquer fase anterior ao merge.
6. Intenções com origem `condessa` NÃO DEVEM alterar `engine/`, `persona/` nem os arquivos de configuração de projeto.

## Requisito 3 — Projetos e gates (D4)

**História:** como Pedro, quero declarar uma vez como cada projeto meu é validado, e só esses projetos entram.

1. O Engine DEVE ler, para cada projeto, um arquivo TOML em `engine/validation/projects/` com: caminho, tipo (`self` ou `pessoal`), ramo principal, comandos de lint/test/build, caminhos proibidos extras e tamanho máximo de diff.
2. O Engine DEVE aplicar a todo projeto a lista fixa de caminhos proibidos (R10.3), somada à lista do projeto.
3. SE o arquivo de projeto estiver inválido (campo faltando, caminho inexistente, gate vazio), ENTÃO o Engine DEVE recusar intenções para ele e mostrar o erro.
4. SE o caminho ou algum remoto git do projeto contiver `sume` ou um host GitLab, ENTÃO o Engine DEVE tratar o projeto como da empresa e recusá-lo (R1.4).

## Requisito 4 — Artefatos SDD persistentes (PDF p.1)

**História:** como Pedro, quero que todo código feito pelo Engine tenha um "porquê" escrito antes.

1. Para cada intenção, o Engine DEVE produzir, nesta ordem, PRD (problema, objetivo, requisitos, critérios de sucesso), Design (arquitetura, componentes, interfaces, decisões técnicas), Spec (comportamento, contratos/schemas, casos de borda, critérios de aceite) e Tasks.
2. O Engine DEVE gravar cada artefato em `engine/sdd/{prd,design,specs,tasks}/` com o ID da intenção no nome e entregá-lo no mesmo merge do código.
3. O Engine DEVE dar a cada requisito, componente, item de spec e task um ID estável e fazer cada um apontar para o(s) ID(s) da fase anterior.
4. Cada critério de aceite DEVE declarar como é verificado (teste, comando, arquivo ou medida); critério "manual" não é verificável.
5. O Engine NÃO DEVE apagar artefatos de intenções encerradas (descartadas ficam marcadas, não somem).

## Requisito 5 — Máquina de estados (PDF p.2)

**História:** como Pedro, quero saber sempre em que fase cada intenção está e por que ela parou.

1. O Engine DEVE conduzir cada intenção pelos estados IDEA → PRD → DESIGN → SPEC → TASK_BREAKDOWN → READY → IMPLEMENT → TEST → REVIEW → HUMAN_OK → MERGE → DONE, com os estados de parada HUMAN, PAUSED e DISCARDED.
2. O Engine DEVE avançar de estado só quando o Jev der PASS aos critérios de saída da fase.
3. O Engine DEVE registrar cada transição (de, para, motivo, veredito, horário) num log de eventos que só cresce.
4. QUANDO o Engine reiniciar, ele DEVE retomar cada intenção do último estado gravado; uma sessão do Claude Code que estava rodando conta como interrompida (R10.9).

## Requisito 6 — Jev nas fases de especificação (D2)

**História:** como Pedro, que só aprova no merge, quero que nenhuma task ruim seja liberada.

1. QUANDO um PRD for gerado, o Jev DEVE exigir: as quatro seções, pelo menos 1 requisito, e todo requisito com pelo menos 1 critério de aceite verificável (R4.4).
2. QUANDO um Design for gerado, o Jev DEVE exigir: todo requisito do PRD coberto por algum componente, e todo componente apontando para requisito existente.
3. QUANDO um Spec for gerado, o Jev DEVE exigir: todo item apontando para componente existente, todo requisito coberto por algum item, e todo item com pelo menos 1 critério de aceite verificável.
4. QUANDO as Tasks forem geradas, o Jev DEVE exigir: toda task referencia pelo menos 1 item do spec; todo item do spec coberto por alguma task; arquivos que a task escreve declarados e fora dos caminhos proibidos; dependências sem ciclo; pacote de contexto estimado ≤ 128k; pelo menos 1 critério verificável por task.
5. SE uma regra falhar, ENTÃO o Jev DEVE dar RETRY com a lista de falhas para o agente refazer o artefato; na 2ª falha com a mesma assinatura ou na 4ª tentativa, HUMAN.

## Requisito 7 — Pacote de contexto e orçamento (PDF p.2, D7)

**História:** como Pedro, quero que cada agente receba só o que precisa, sem carregar o projeto inteiro.

1. O Engine DEVE montar, para cada task, um pacote com os blocos da tabela de orçamento (instruções 8k, PRD 8k, design 12k, spec 15k, decisões anteriores 5k, código 45k, testes 15k, task 5k, reserva de saída 15k), totalizando no máximo 128k.
2. O Engine DEVE incluir no pacote só as seções dos artefatos que a task referencia e só os arquivos que ela declara ler ou escrever.
3. SE um bloco passar do seu limite, ENTÃO o Engine DEVE cortá-lo com um marcador visível; SE o bloco de código passar do limite, ENTÃO a task é grande demais e volta ao Jev (R6.4).
4. O Engine DEVE gravar o pacote montado e a estimativa por bloco junto da execução da task.

## Requisito 8 — Execução com Claude Code headless (D1)

**História:** como Pedro, quero que as tasks rodem na minha assinatura do Claude Code, isoladas, como o autoconserto já faz.

1. O Engine DEVE executar cada task com `claude -p` numa worktree própria, num branch da task criado a partir do branch da intenção.
2. O Engine DEVE passar `--permission-mode acceptEdits`, uma lista `--allowedTools` restrita (edição, leitura e os gates do projeto) e um limite de turnos; NÃO DEVE permitir `git push`, `systemctl`, `docker` ou rede.
3. Os agentes que escrevem artefatos SDD e o revisor DEVEM rodar sem permissão de editar código do projeto (só leitura + escrita do próprio artefato).
4. O Engine DEVE rodar no máximo `max_parallel` tasks ao mesmo tempo (padrão 1) e respeitar as dependências entre tasks.
5. ENQUANTO houver jogo aberto, o Engine NÃO DEVE iniciar nova sessão do Claude Code (as que já rodam terminam).
6. SE o Claude Code avisar limite de uso da assinatura, ENTÃO o Engine DEVE pausar (PAUSED) até o fim da janela de 5 h e retomar sozinho.

## Requisito 9 — Monitoramento de tokens (D7)

**História:** como Pedro, quero ver quanto cada task gasta e ter certeza de que nenhuma passa do teto.

1. O Engine DEVE acompanhar a ocupação de cada sessão a cada resposta do modelo, em tempo real.
2. SE a ocupação passar de 128k, ou a sessão compactar o contexto, ENTÃO o Engine DEVE encerrar a sessão e entregar ao Jev o resultado `OVER_BUDGET`.
3. O Engine DEVE somar o consumo (tokens novos e leitura de cache) por task e por intenção e gravá-lo no estado.
4. O Engine DEVE avisar no console quando uma sessão passar de 85% do teto.

## Requisito 10 — Jev na implementação (D8)

**História:** como Pedro, quero regras simples e previsíveis decidindo se uma task passou.

1. QUANDO uma task terminar, o Engine DEVE rodar os gates do projeto na worktree; o Jev DEVE exigir todos verdes.
2. O Jev DEVE exigir que o diff da task toque só os arquivos que ela declarou escrever.
3. O Jev DEVE recusar diff que toque caminho proibido: `~/.config`, arquivos de systemd, arquivos do Docker, segredos e `.git/`, mais os do projeto. Este caso é sempre HUMAN, nunca RETRY.
4. O Jev DEVE recusar diff maior que o máximo do projeto (padrão em spec).
5. O Jev DEVE exigir que os critérios verificáveis da task passem (testes ou comandos declarados).
6. SE a mesma falha (mesma assinatura) acontecer 2 vezes na task, ENTÃO o Jev DEVE dar HUMAN (loop).
7. O Jev DEVE dar no máximo 3 RETRY por task; a 4ª falha é HUMAN.
8. QUANDO o resultado for `OVER_BUDGET`, o Jev DEVE dar RETRY pedindo a divisão da task na 1ª vez e HUMAN na 2ª.
9. SE a sessão terminar por erro, tempo esgotado ou reinício do Engine, ENTÃO o Jev DEVE tratar como falha comum (conta RETRY).
10. O Jev DEVE ser determinístico: mesma entrada, mesmo veredito, sem chamar LLM.
11. O Engine DEVE registrar cada veredito com regra, motivo e evidência (trecho de saída cortado).

## Requisito 11 — Revisão automática (REVIEW)

**História:** como Pedro, quero que alguém confira o código contra o spec antes de chegar em mim.

1. QUANDO todas as tasks da intenção tiverem PASS, o Engine DEVE rodar os gates no branch da intenção e um agente revisor só de leitura que compara o diff total com o spec.
2. O revisor DEVE devolver achados em formato fixo (spec); o Jev DEVE dar RETRY (nova task de correção) para achado bloqueante e PASS sem bloqueantes.
3. O Engine DEVE anexar o resumo da revisão ao pedido de aprovação.

## Requisito 12 — Aprovação humana e merge (D2, D4)

**História:** como Pedro, quero aprovar uma vez só, sabendo o que vai entrar, e poder voltar atrás.

1. QUANDO a revisão passar, o Engine DEVE ir para HUMAN_OK e avisar por voz e no HUD com um resumo de 1 frase, o número de arquivos e linhas e o consumo de tokens.
2. QUANDO o Pedro aprovar ("Condessa, aprova o merge", HUD ou `magi-engine approve`), o Engine DEVE pedir confirmação falada e só então fazer o merge.
3. ONDE o projeto for pessoal, o merge DEVE ser local (`--no-ff`) no ramo principal, sem push.
4. ONDE o projeto for o próprio, o Engine DEVE fazer o merge e reiniciar os serviços afetados com o vigia de rollback existente; se algum não subir em 30 s, desfazer com `git revert` e avisar.
5. SE o repositório de destino tiver mudança sem commit ou o merge der conflito, ENTÃO o Engine NÃO DEVE fazer o merge; DEVE avisar e manter HUMAN_OK.
6. QUANDO o Pedro disser "descarta", o Engine DEVE encerrar a intenção (DISCARDED), apagar worktrees e manter branches e artefatos.
7. O Engine NÃO DEVE fazer merge sem aprovação do Pedro em nenhum projeto, nem fazer push.

## Requisito 13 — Rastreabilidade (PDF p.3)

**História:** como Pedro, quero perguntar "por que esse código existe?" e ter a resposta até o PRD.

1. O Engine DEVE pôr em todo commit de task os trailers `Engine-Intent`, `Engine-Task` e `Engine-Spec`.
2. QUANDO o Pedro rodar `magi-engine why <arquivo>:<linha>`, o Engine DEVE mostrar a cadeia commit → task → itens do spec → componentes → requisitos → objetivo do PRD.
3. SE a linha não vier de commit do Engine, ENTÃO o Engine DEVE dizer isso e mostrar só o commit.

## Requisito 14 — Console no Konsole (D6)

**História:** como Pedro, quero acompanhar o Engine ao vivo numa janela de terminal.

1. QUANDO uma intenção sair de IDEA e o console não estiver aberto, o Engine DEVE abrir uma janela do Konsole com a visão ao vivo: intenção e fase, task rodando, ocupação de tokens, últimos vereditos do Jev.
2. O Engine DEVE abrir o Konsole só por linha de comando (`konsole …`); NÃO DEVE chamar D-Bus do KGlobalAccel nem métodos D-Bus de escrita não validados no spike S-E2.
3. QUANDO o Pedro fechar o console, o Engine DEVE seguir trabalhando; `magi-engine console` reabre.
4. ONDE `[engine] console = false`, o Engine NÃO DEVE abrir janela.

## Requisito 15 — HUD e voz (D9)

**História:** como Pedro, quero ver e controlar o Engine pelo painel "Claude Code" e pela voz.

1. O painel "Claude Code" do HUD DEVE mostrar: intenções abertas com fase, tasks rodando com ocupação, último veredito e o que espera o ok do Pedro.
2. O painel DEVE continuar mostrando o consumo da janela de 5 h que já mostra, incluindo as sessões do Engine.
3. O Engine DEVE responder por voz a: "quero …", "aprova o merge", "descarta", "como tá o engine?", "o que tá esperando?" e "continua" (sai de HUMAN com nova tentativa).
4. QUANDO uma intenção entrar em HUMAN ou HUMAN_OK, o Engine DEVE avisar por voz uma vez (ou na próxima vez que ela acordar, se houver jogo aberto).

## Requisito 16 — Autoconserto como caso do Engine (D10)

**História:** como Pedro, quero um só caminho para mudar código, e o autoconserto entra nele.

1. QUANDO o Pedro disser "prepara um conserto" depois de um diagnóstico, o Engine DEVE abrir uma intenção do tipo `conserto` no projeto próprio, com o diagnóstico como texto da intenção.
2. Intenções `conserto` DEVEM passar pelos mesmos estados e regras do Jev; o PRD e o Design podem ser curtos (spec).
3. "aplica o conserto", "descarta o conserto" e "como tá o conserto?" DEVEM continuar funcionando como sinônimos de aprovar, descartar e status da intenção de conserto.
4. O diagnóstico (nível 0) DEVE continuar como está (só leitura, fora do Engine).
5. Decisões de personalidade NÃO DEVEM virar intenção do Engine; continuam no Conselho da Condessa (`persona/conselho/`).

## Requisito 17 — Memória de decisões (PDF p.2)

**História:** como Pedro, quero que o Engine aprenda com o que já decidiu sem repetir erro.

1. O Engine DEVE guardar, por projeto, as decisões técnicas dos designs aprovados e as falhas do Jev com sua assinatura.
2. QUANDO montar o bloco "decisões anteriores" (R7.1), o Engine DEVE incluir as decisões do mesmo projeto que citam os arquivos da task, até 5k tokens, mais recentes primeiro.

---

## Requisitos não funcionais

| ID | Requisito | Meta |
| --- | --- | --- |
| RNF-01 | Contexto por sessão do Claude Code | ≤ 128k tokens de ocupação (encerra ao passar) |
| RNF-02 | CPU do Engine ocioso | até 0,5% de um núcleo; nada roda durante jogo além das sessões já em curso |
| RNF-03 | RAM do serviço `magi-engine` | até 80 MB (sem contar as sessões do Claude Code) |
| RNF-04 | Decisão do Jev | até 1 s por veredito (sem contar os gates) |
| RNF-05 | Isolamento | nenhuma escrita fora da worktree da task e de `~/.local/share/magi/engine/` |
| RNF-06 | Empresa | zero acesso a repositórios Sume/GitLab |
| RNF-07 | Sessão KDE | zero chamadas D-Bus de escrita fora das validadas no spike S-E2 |
| RNF-08 | Recuperação | reinício do serviço não perde estado nem deixa worktree órfã por mais de 1 ciclo |
| RNF-09 | Dependências | só biblioteca padrão + o que o projeto já usa (sem banco novo) |

## Decisões do Pedro (2026-10-07)

| ID | Decisão |
| --- | --- |
| D1 | Executor: Claude Code headless (`claude -p`) na assinatura, como o autoconserto; consumo no painel "Claude Code" (janela de 5 h). |
| D2 | Aprovação humana só no merge; Jev rígido nas fases intermediárias. |
| D3 | `engine/` novo neste repositório, sem mover nada do que existe. |
| D4 | Escopo: a Condessa + projetos pessoais com arquivo de gates; Sume/GitLab fora sempre; pessoal = merge local sem push; própria = merge + reinício com vigia. |
| D5 | Pedro abre intenção para qualquer projeto; a Condessa só propõe para ela mesma. |
| D6 | Console = Konsole, aberto só por formas validadas (risco do KGlobalAccel). |
| D7 | 128k monitorado, não imposto token a token; estourou → encerra e o Jev decide. |
| D8 | Regras iniciais do Jev (R10). |
| D9 | Estado do Engine no painel "Claude Code"; aprovação por voz. |
| D10 | Autoconserto vira caso do Engine; Conselho continua para personalidade. |
