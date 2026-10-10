# Design — A vida da Condessa

Implementa [requirements.md](requirements.md). Seções citadas por `§`.

## 1. Hoje
`Reactor.observe` (1 Hz) → detectores `det_*` emitem `Disparo` → `governador.escolher` (cotas) →
`Reactor.tocar` (sequência de passos) → `active(now)` dá ao retrato um `Reaction` de 1 rosto;
passivas sorteadas por `passivas.sortear` com pesos de `humor.fatores` (fatores do contexto, sem
estado dela). Fora disso o retrato mostra o rosto do estado da Magui (dormindo de dia = B1 C1).
As 19 reações antigas tocam por `Reactor.fire`, fora do governador.

## 2. Depois: estado → momento → cena → gesto
```
Snapshot/eventos ─▶ detectores ─▶ Disparo(causa) ─┐
                                                  ▼
            estado.Humor ◀── eventos ── diretor.Diretor ── cena (roteiro) ──▶ Reactor.tocar
                 │                         ▲   │
                 ▼                         │   └─ fila (1 vaga) / interrupção / absorção
           momento.decidir ──▶ repouso.rosto ──▶ retrato (rosto de repouso + fone + fundo)
                 │
                 └─▶ passivas.sortear(grupo do momento ∩ faixa) ──▶ governador v2 ──▶ Reactor.tocar
```
- **Estado** (`reacoes/estado.py`): `Humor` (ânimo, energia, decaimento, retorno decrescente,
  faixa com histerese) e `Postura` (fone CABECA/PESCOCO, com motivo). Persistido em
  `~/.local/state/magi/condessa-estado.json` junto com os contadores do governador (V1, V7).
- **Momento** (`reacoes/momento.py`): função pura `decidir(ctx, anterior) -> Momento` com prioridade,
  histerese de 30 s e os filtros (madrugada, Pedro mal, faixa Baixa); tabela de grupos.
- **Repouso** (`reacoes/repouso.py`): `rosto(momento, faixa, postura, episodio) -> Repouso`
  (olhos, boca, fone, fundo, balanço). O retrato passa a usar isso no lugar do neutro quando parado.
- **Diretor** (`reacoes/diretor.py`): recebe todos os `Disparo`, agrupa por **causa** em 30 s, escolhe
  o roteiro da cena (acordo §2) e o ramo (Ado > chefe > amou > dançante > comum), aplica fila e
  interrupção, e entrega **uma** cena ao `Reactor`. Disparos absorvidos só mexem no humor/estado.
- **Governador v2** (`reacoes/governador.py`): números do `[vida]`, todas as reações (inclusive as
  19 antigas, via o diretor), contadores persistentes, negativas com causa (V8).
- **Jogo** (`reacoes/episodio.py`): episódio FPS+calor com histerese, estado de cobrança e tetos por
  partida (V9); o `det_sistema` passa a perguntar ao episódio antes de emitir.

## 3. O retrato
Dois acréscimos ao `PartsPortrait`, sem mudar o contrato das reações:
1. `set_rest(repouso)` — o rosto parado (olhos, boca, fone, fundo, balanço) quando não há reação nem
   fala; hoje é sempre B1 C1.
2. Fone persistente: o `corpo` `fone_on/off` de um passo vale só durante o passo; fora dele vale o
   `repouso.fone`. Troca de fone é feita pela cena (passo com P11 E2→E3), nunca por gesto.

## 4. O medidor
`Snapshot.mood_dela` (0–4) e `mood_dela_cor`; `main_screen` e `standby_screen` desenham o
medidor a partir deles. O `snap.mood` (Pedro) continua no `ctx` para as regras de zoeira.

## 5. Ordem de implementação (paralelismo)
`V0.1` cria os módulos novos como stubs registrados e o leitor de `[vida]`; depois `estado`,
`momento`, `episodio` e o governador v2 podem andar em paralelo (cada um no seu arquivo); `repouso`
+ retrato e `diretor` dependem de `estado`/`momento`; a ligação no `Reactor` fecha tudo.

## 6. Riscos
| Risco | Mitigação |
| --- | --- |
| Ela ficar "parada demais" | é o pedido; o rosto de repouso muda com o humor e o momento, e as cenas continuam; calibrar `[vida]` na semana |
| Regressão nas 110 reações | testes atuais continuam; as reações viram passos de cena ou gestos de grupo, não somem |
| CPU | decisões a 1 Hz e por evento; humor é aritmética; nada a 60 fps fora do retrato |
| Estado corrompido | arquivo com escrita atômica; inválido → começa da base |
