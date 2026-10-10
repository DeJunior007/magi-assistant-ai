# Spec — A vida da Condessa

Contratos e regras. Implementa [requirements.md](requirements.md) segundo o [design.md](design.md).
Números: `[vida]` do `persona/condessa-gosto.toml`. Regras detalhadas (tabelas de eventos, faixas,
roteiros de cena, momentos): **acordo §1–§6** em
`persona/conselho/atas/2026-10-09-ritmo-e-humor/acordo.md` — a spec não as copia; o código as
transcreve como tabelas de dados com o número da seção no comentário.

## 1. Contratos (`hud/wired/reacoes/vida.py`, novo)
```python
class Faixa(StrEnum): RADIANTE, BEM, NEUTRA, IRRITADA, ABATIDA, BAIXA
class Momento(StrEnum): CONVERSA, JOGANDO, ESTUDANDO, NO_FLOW, CURTINDO, ATURANDO, OUVINDO,
                        MADRUGADA, ESPERANDO, TEDIO, AUSENTE, A_TOA, OCIOSA_FELIZ
class Fone(StrEnum): CABECA, PESCOCO

@dataclass(frozen=True)
class Evento:            # o que mexe no humor (acordo §3, tabela de eventos)
    tipo: str            # "faixa_nota2", "ado", "pedro_volta", "tag_elogio", "silencio_longo", ...
    em: float            # monotônico

@dataclass(frozen=True)
class Repouso:           # o rosto parado (§3 do design)
    eyes: str; mouth: str; fone: Fone; mood: str; bob: bool = False; efeitos: tuple[str, ...] = ()

@dataclass
class Cena:              # o que o diretor entrega ao Reactor
    tipo: str            # "musica_comeca", "faixa_ama", "faixa_nao_gosta", "jogo_abre", ...
    ramo: str | None     # "ado", "chefe", "favorita_pedro", ...
    causa: str           # chave de agrupamento (ex.: "faixa:<titulo>|<artista>")
    passos: tuple[Passo, ...]
    prioridade: int      # 1 interrompe, 2 fila, 3 absorve (acordo §2 "Interrupção")
```

## 2. Humor (`reacoes/estado.py`)
- `Humor.aplicar(evento, agora)`: Δ da tabela (acordo §3), teto ±`teto_evento`, retorno decrescente
  (mesmo tipo em `repeticao_janela_min`: ×0,5, ×0,25…), regras de Pedro mal (−0,10 uma vez,
  positivos ×0,5, teto +0,3) e piso do silêncio (`piso_silencio` só para essa causa).
- `Humor.tick(agora, hora, jogo)`: decaimento exponencial rumo à base (meia-vidas do `[vida.humor]`);
  energia-base pela hora/jogo.
- `Humor.faixa(agora)`: limiares ±0,15/±0,5; Irritada × Abatida pela energia (> 0,5); troca só com
  histerese 0,1 **e** 2 min na faixa nova.
- `Humor.medidor()`: `round((animo + 1) * 2)` em 0..4.
- Persistência: `Estado.salvar/carregar(caminho)` com ânimo, energia, faixa, eventos recentes (para
  o retorno decrescente), postura, e os contadores do governador (§5); escrita atômica; arquivo
  inválido → base. Carregar aplica o decaimento do tempo em que o HUD ficou fechado.

## 3. Momentos (`reacoes/momento.py`)
- `decidir(ctx, anterior, agora) -> Momento`: tabela de prioridade do acordo §6 com os sinais do
  `ctx`; histerese `momento_histerese_s` (Conversa e Jogando entram na hora); Radiante transforma
  Esperando/Tédio/À toa em Ociosa feliz.
- `GRUPOS: dict[Momento, frozenset[str]]` (chaves das passivas) e `filtros(ctx)` (madrugada, Pedro
  mal, faixa Baixa) — acordo §6.
- Sinais que faltam no `ctx` hoje e esta spec cria: `pedro_inativo_s` (da `atividade`),
  `pedro_ativo_s` (tempo contínuo de atividade), `turno_pedro_ha_s`, `lm_on`, `musica_nota`,
  `musica_media_15min`.

## 4. Repouso e fone (`reacoes/repouso.py` + retrato)
- `rosto(momento, faixa, postura, episodio, energia) -> Repouso` — tabelas do acordo §3 (faixas) e
  §6 (rosto por momento); o momento manda, a faixa Baixa sobrepõe; episódio de jogo aberto = B6 C8
  D2 + `stress`.
- `Postura.fone`: CABECA se há música e a faixa não foi rejeitada (nota ≥ 0); PESCOCO caso contrário.
  Mudança de postura só acontece **dentro** de uma cena (passo com P11). Se a música começar/parar
  sem cena (cota cheia), a postura muda no fim do mínimo de 20 s com o passo curto de troca
  (P11 600 ms) — nunca pisca.
- Retrato: `PartsPortrait.set_rest(repouso)`; `eyes_id`/`mouth_id` usam o repouso quando parada; o
  `fone` do repouso desenha E2/E3 sempre (extra de passo só sobrepõe durante o passo); fundo
  `repouso.mood`.

## 5. Governador v2 (`reacoes/governador.py`)
Todos os números do acordo §1 vindos de `[vida]`. Classes novas: `CENA`, `GESTO` (passiva),
`ATIVA_SOLTA`. Regras: mínimo entre duas reações (exceto fala/clique; volta = 5 s); assentamento de
45 s após cena (sem gesto); cotas por hora de cenas/gestos/ativas; mesma passiva ≤ 2/h e ≥ 20 min;
mesmo tipo de cena ≥ 10 min (música ≥ 3 min, troca de faixa isenta); negativas ≤ 3/h somadas e ≤ 2/h
cada com causa dos últimos 2 min (§6 desta spec); diárias e blush como hoje. **Contadores
persistidos** no estado (§2) e janelas por tempo de parede (sobrevivem ao reinício). As 19 antigas
entram pelo diretor como cena ou ativa solta — `Reactor.fire` deixa de tocar direto.

## 6. Negativas com causa
`causas_recentes(ctx, agora)` devolve o conjunto de causas vivas nos últimos `negativa_causa_s`:
`silencio_longo`, `claude_demorando`, `pulo_faixa_amada`, `faixa_nota_menos1`, `ignorada` (Pedro
ativo ≥ 15 min sem música nem conversa), `calor_fora_jogo`. Cada negativa exige uma causa da sua
lista (acordo §4) **e** faixa compatível.

## 7. Episódio de jogo (`reacoes/episodio.py`)
`Episodio.atualizar(snap, agora) -> list[Disparo]`: limiares e histerese do `[vida.jogo]`; FPS e
calor = um episódio; emite `cobranca` (1º alarme), `piorou` (vergonha), `eu_avisei` (episódio > 10
min, conta no teto), `recuperou` (só se cobrou); estado `aberto` para o repouso; contadores por
partida (`game_on` zera). O `det_sistema` deixa de emitir `hot`/`fps_drop` repetidos por conta
própria.

## 8. Diretor (`reacoes/diretor.py`)
- `Diretor.receber(disparos, agora, ctx) -> Cena | None`: agrupa por `causa` em `mesma_causa_s`;
  mapeia para o tipo de cena (acordo §2, lista "viram cena"); escolhe o ramo; o resto vira
  `ATIVA_SOLTA` (olhar F4/F5) ou só evento de humor.
- Roteiros: tabela `ROTEIROS[tipo][ramo] -> passos` transcrita do acordo §2 (em `catalogo.py`, como
  `Def` com classe `CENA`), reaproveitando as `Def` existentes como passos quando couber.
- Fila de 1 vaga com validade `fila_validade_s`, substituição pela mesma prioridade e descarte por
  obsolescência (a causa mudou); interrupção nível 1 sai por B1 C1 200 ms; troca de fone atômica.
- Durante cena: gestos e ativas soltas descartados; acontecimento da mesma família vira ramo (troca
  de faixa reinicia no ramo novo sem repetir "coloca o fone").

## 9. Registro e relatório
`reacoes.jsonl` ganha `momento`, `faixa`, `animo`, `energia` e `tipo` (`cena`/`gesto`/`ativa`/
`repouso`); troca de rosto de repouso também grava (no máximo 1 linha por troca). O
`reacoes_relatorio` mostra por hora: cenas, gestos, ativas; e a distribuição por momento e faixa.

## 10. Critérios de aceite
- **CA-V1** Humor: sequência de eventos sintéticos dá os valores esperados (tabela do acordo §3),
  decaimento correto em 20/15 min, teto ±0,3, retorno decrescente, histerese de faixa.
- **CA-V2** Persistência: reiniciar o `Reactor` com o mesmo arquivo mantém humor, postura e
  contadores (a "corando" não passa de 1/dia entre reinícios).
- **CA-V3** Momentos: um caso por linha da tabela do acordo §6 + desempates + histerese.
- **CA-V4** Rajada: os 8 disparos da música às 21:05 do log real viram **1** cena.
- **CA-V5** Fone: nenhum quadro com E2 sem música; tira e põe só por cena.
- **CA-V6** Simulação de 12 h com o log real reproduzido como acontecimentos: média ≤ 29/h,
  negativas ≤ 3/h, todas as passivas dentro do grupo do momento.
- **CA-V7** Jogo: oscilação de FPS/calor por 1 h de partida dá ≤ 2 cobranças + 1 recuperação.
- **CA-V8** Medidor: segue o ânimo dela; o humor do Pedro não aparece nele.
- **CA-V9** Tempo do tick com tudo ligado ≤ 2 ms (média de 1000).
