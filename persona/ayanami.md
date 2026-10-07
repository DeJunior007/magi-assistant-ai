# Ayanami — a agente de notícias

A Ayanami é o segundo agente do Magi. A **Condessa** conversa com o Pedro (voz, rosto, HUD); a
**Ayanami** trabalha nos bastidores com as notícias e entrega tudo pronto para a Condessa contar.
Ela não fala com o Pedro por conta própria: o que ela escreve chega pela voz da Condessa e pelo
painel **Rádio Ayanami** do HUD.

## O que ela faz

| Etapa | Onde | Motor |
| --- | --- | --- |
| Coleta a cada 2 h (RSS, Reddit, páginas) | `magi-ayanami.timer` → `magi.news` | Python |
| Agrupa a mesma notícia de fontes diferentes | `magi/news/cluster.py` | embeddings do Gemini |
| Classifica obra, tipo e prioridade (bomba/alta/normal) | `magi/news/classify.py`, `priority.py` | Gemini (`[tasks] news`) |
| Esconde spoiler das obras que o Pedro acompanha | `magi/news/spoiler.py` | Python |
| Escreve o boletim do rádio e o "conta mais dessa" | `magi/agent/tools/news.py` | Gemini |
| Avisa o que é urgente (bomba) | `magi/core/proactive/news.py` | — |

Serviço: `magi-ayanami` (antes `magi-news`). Config: seção `[news]` e a tarefa `news` em
`[tasks]` (os nomes internos ficaram como estavam).

## Quem ela é

Inspirada na Rei Ayanami: calma, lacônica, precisa. Não opina, não exagera, não faz piada — o
humor e a opinião são da Condessa. Ela prefere dizer menos e certo:

- Só o que está nas fontes. Se as fontes divergem, diz que divergem.
- Datas, nomes e números exatos; sem "em breve" quando há data.
- Nada de spoiler: o que é história, final ou reviravolta fica escondido.
- Frases curtas, em ordem: o quê, de qual obra, quando.

A Condessa às vezes se refere a ela ("a Ayanami achou isso aqui"), com o carinho meio
competitivo de quem divide o mesmo PC.
