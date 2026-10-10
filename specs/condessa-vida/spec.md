# Spec — A vida da Condessa

Contratos e regras. Implementa [requirements.md](requirements.md) segundo o [design.md](design.md).
Números: `[vida]` do `persona/condessa-gosto.toml`. Regras detalhadas (tabelas de Δ, faixas,
momentos e grupos, roteiros de cena, metas do replay): **acordo §0–§8** em
`persona/conselho/atas/2026-10-10-ritmo-e-humor/acordo.md` (Conselho novo, unânime). A spec não as
copia; o código as transcreve como tabelas de dados com o número da seção no comentário.

## 1. Contratos (`hud/wired/reacoes/vida.py`)
```python
class Faixa(StrEnum): RADIANTE, CONTENTE, NEUTRA, EMBURRADA          # acordo §2
class Momento(StrEnum): CONVERSA, ALERTA, JOGANDO, ESPERANDO, NO_FLOW, TRABALHANDO_JUNTO,
                        ESTUDANDO, CURTINDO, ATURANDO, OUVINDO, PEDRO_SUMIU, TEDIO, A_TOA  # acordo §3
class Filtro(StrEnum): MADRUGADA, PEDRO_MAL                           # acordo §3 (por cima)
class Fone(StrEnum): CABECA, PESCOCO

@dataclass(frozen=True)
class Evento:            # o que mexe no humor (acordo §1, tabela)
    tipo: str            # "faixa_nota2", "ado", "pedro_volta", "tag_elogio", "truque_aplauso", ...
    fonte: str           # "musica", "pedro", "sistema", "claude"... (habituação e trava por fonte)
    em: float

@dataclass(frozen=True)
class Causa:             # o que o medidor mostra no hover (acordo §6) e o log grava
    texto: str; delta: float; em: float

@dataclass(frozen=True)
class Repouso:           # o rosto parado (acordo §2)
    eyes: str; mouth: str; fone: Fone; mood: str; sway: bool = False; efeitos: tuple[str, ...] = ()

@dataclass
class Cena:              # o que o diretor entrega ao Reactor
    tipo: str; ramo: str | None; causa: str
    passos: tuple[Passo, ...]
    nivel: int           # 1 interrompe · 2 fila · 3 absorve
```

## 2. Humor (`reacoes/estado.py`) — acordo §1
- `Humor.aplicar(evento, agora)`: Δ da tabela; **habituação** 0,6ⁿ para o mesmo tipo em 30 min (Ado e
  Favorita isentas); **trava ±0,6/h por fonte**; **piso de sistema −0,3** (eventos de fonte "sistema"
  não descem abaixo disso); **teto +0,3 com o filtro Pedro mal**. Guarda as últimas causas (para o
  medidor).
- `Humor.tick(agora, hora, ctx)`: volta à base **+0,15** com meia-vida **25 min acima / 8 min abaixo**;
  "Pedro sumido" −0,05 a cada 15 min depois dos primeiros 30; **o silêncio não mexe no ânimo**.
  Energia: alvo pela hora (tabela do `[vida.humor]`), meia-vida 15 min, +0,15 com música nota ≥ 1 e
  com jogo enquanto duram, silêncio > 20 min −0,01/min até −0,2.
- `Humor.faixa(agora)`: limiares do `[vida.humor].limiar`, histerese ±0,05 e 60 s na faixa nova.
- `Humor.medidor() -> (valor -1..+1, cor, momento, causas[3])`.
- Persistência: `Estado.salvar/carregar` (ânimo, energia, faixa, causas, eventos recentes para a
  habituação, postura e contadores do governador; escrita atômica; inválido → base; ao carregar,
  aplica o decaimento do tempo em que o HUD ficou fechado).

## 3. Momentos (`reacoes/momento.py`) — acordo §3
- `decidir(ctx, anterior, agora) -> Momento`: prioridade da tabela; troca só depois de 30 s estável,
  menos Conversa, Alerta e Jogando (imediatos).
- `filtros(ctx) -> set[Filtro]` (madrugada 22h–04h; Pedro mal = humor do Pedro 0–1 do núcleo).
- `GRUPOS[Momento]` e `MEDIA_MIN[Momento]` (do `[vida.passiva_media_min]`), com as regras de cada linha
  (ex.: cabeca_ritmo só com nota ≥ 1; franja ≤ 1 por espera; a **escada do Tédio**: encarando aos 15 min
  1× → `ei_to_aqui` aos 30 min ≤ 1/2 h → beicinho só se ignorado).
- Sinais que o `ctx` passa a ter: `pedro_inativo_s`, `turno_pedro_ha_s`, `lm_on`, `musica_nota`,
  `claude_esperando`, `claude_rodando`, `alerta` (disco cheio, rede caiu, popup), `faixa_agua`.

## 4. Repouso e fone (`reacoes/repouso.py` + retrato) — acordo §2, §3, §5
- `rosto(momento, faixa, filtros, postura, ctx) -> Repouso`: tabela de faixas; energia < 0,3 → B2;
  música nota ≥ 1 com fone → B2 (nota 1) / B4 (nota 2) pela faixa inteira; faixa de água → B3 + sway
  com abertura B2 a cada 20–30 s; filtro Pedro mal → B1 C1 olhando para ele; episódio de jogo → suor +
  `stress`; P10 no repouso de Trabalhando junto (após 2 min) e Estudando, se a arte existir.
- `Postura.fone`: CABECA com música nota ≥ 0 e sem conversa; PESCOCO no resto. Troca só por passo de
  cena (P11); nota −1: põe e tira depois de 8 s; nota −2: nem põe.
- Retrato: `set_rest(repouso)`, fone persistente, **crossfade de 120 ms** em toda troca de olho/boca,
  troca de faixa de repouso dentro de uma piscada; corpo vivo (piscar 3–7 s, respirar, bob) sempre.

## 5. Governador v2 (`reacoes/governador.py`) — acordo §4
Classes `CENA`, `GESTO`, `ATIVA_SOLTA`, `ATENCAO`, `CORPO`. Regras: 25 s entre duas expressões
(cena/gesto/ativa), 60 s sem gesto depois de cena, cenas ≤ 8/h, gestos ≤ 12/h com mínimo de 90 s e peso
×0,3 por uso na última hora, negativas ≤ 3/h somadas com causa ≤ 2 min (§6), truque ≤ 1/dia; `ATENCAO`
e `CORPO` fora de cota. **Furam tudo:** fala do Pedro, clique no rosto, volta do Pedro, rede caiu,
disco cheio. Contadores persistidos no `Estado`, janelas por tempo de parede. As 19 antigas entram
pelo diretor.

## 6. Negativas com causa
`causas_recentes(ctx, agora)`: `pulo_faixa_amada`, `faixa_nota_menos1`, `claude_demorando`,
`claude_esperando`, `ignorada` (escada do Tédio sem resposta), `truque_ignorado`, `episodio_jogo`.
Cada negativa exige uma causa da sua lista e não sai sob os filtros.

## 7. Episódio de jogo (`reacoes/episodio.py`) — acordo §5
FPS e calor = um episódio (termina com 3 min estáveis; novo só depois de 10 min); 1º = cena, depois
estado; ≤ 2 cobranças e 1 recuperação por partida; `game_off` → **relatório pós-batalha** (sem
episódio: vitória do cockpit; com: `eu_avisei`, ou `desconfiada` suave com Pedro mal); `game_on` →
"cockpit" (P12). Notificação em jogo vira só atenção.

## 8. Diretor (`reacoes/diretor.py`) — acordo §4–§5
- Agrupa disparos com **coalescência de 3 s** pela causa; a mesma família é absorvida por 30 s
  (música: 90 s); mesma causa em < 10 min → cena "de novo?" `B7 C12 1000`.
- Roteiros do acordo §5 (música começou com clímax pela nota e as regras −1/−2, faixa trocou, pulos,
  música parou, Pedro fala, jogo abriu/fechou, episódio, Pedro voltou com cochilo/tsundere ou sorriso
  que escapa, Claude terminou > 5 min, truque de salão) em `catalogo.py` como `Def` de classe CENA.
- Acontecimento que não vira cena (absorvido, cota cheia, suprimido em jogo) vira **atenção dirigida**:
  `iris` 400–600 ms para o card dele (player, Claude, sistema, rádio), fora da cota.
- Fila de 1 vaga (30 s, descarte por obsolescência); nível 1 interrompe (sai por B1 C1 200 ms; troca de
  fone atômica); cena interrompida não recomeça.

## 9. Passivas (`reacoes/passivas.py`) — acordo §3–§4
Intervalo exponencial com a média do momento (×0,8 energia ≥ 0,7; ×1,5 energia < 0,3; madrugada ×1/0,7);
grupo do momento ∩ permitidas pela faixa e pelos filtros; **piso de vida**: com o Pedro presente, fora
de Conversa e Jogando, se passaram 6 min sem expressão nem atenção, sai a próxima passiva do grupo (ou,
se vazio, uma atenção dirigida).

## 10. Medidor — acordo §6
`Snapshot.mood_dela` (valor, cor), `Snapshot.momento` (nome) e `Snapshot.causas` (3); painel e espera
desenham a barra, o nome do momento embaixo e as causas no hover do medidor.

## 11. Registro e relatório
`reacoes.jsonl`: `tipo` (`cena`/`gesto`/`ativa`/`atencao`/`repouso`), `momento`, `filtros`, `faixa`,
`animo`, `energia`, `causa`. Sem causa → não toca e grava `descartada_sem_causa`. O relatório mostra
por hora as classes e a distribuição por momento e faixa.

## 12. Critérios de aceite
- **CA-V1** Humor: tabela de Δ, habituação, trava por fonte, piso de sistema, meia-vida assimétrica,
  silêncio só na energia, histerese de faixa.
- **CA-V2** Persistência: reiniciar mantém humor, causas, postura e contadores.
- **CA-V3** Momentos: um teste por linha da tabela + filtros + estabilidade de 30 s + escada do Tédio.
- **CA-V4** Rajada das 21:05 do log real → 1 cena (+ atenções).
- **CA-V5** Fone: nenhum quadro com E2 sem música; −1 tira após 8 s; −2 nem põe.
- **CA-V6 (replay)** O log de 2026-10-09 reproduzido como acontecimentos passa nas **7 metas do acordo
  §8** (12–20 expressões/h; 0 rajadas; nunca > 6 min sem expressão/atenção com o Pedro presente;
  0 negativas sem causa; ≥ 3 faixas no dia, Emburrada < 15 %, Radiante > 0 %; ≥ 1 positiva/h com o
  Pedro presente; toda volta do Pedro vira cena).
- **CA-V7** Jogo: 1 h de partida oscilando → ≤ 2 cobranças + 1 recuperação; relatório ao fechar.
- **CA-V8** Medidor: segue o ânimo dela, mostra o momento e as 3 últimas causas.
- **CA-V9** Tick com tudo ligado ≤ 2 ms (média de 1000).
