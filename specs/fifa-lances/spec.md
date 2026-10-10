# Spec — Lances do FIFA 22

Contratos, números, pipeline, máquina da partida, cenas e frases. Implementa
[requirements.md](requirements.md) segundo o [design.md](design.md).

## 1. Contratos (`magi/lances/contratos.py`)

```python
class Fase(StrEnum): ESPERANDO, PRIMEIRO, INTERVALO, SEGUNDO, PRORROGACAO, FIM
class TipoLance(StrEnum):
    INICIO, GOL_PRO, GOL_CONTRA, GOL_ANULADO, VIRADA_PRO, VIRADA_CONTRA, GOLEADA_PRO, GOLEADA_CONTRA,
    INTERVALO, FIM_VITORIA, FIM_DERROTA, FIM_EMPATE, SEM_PLACAR
    # caminho 2 (F11): CHANCE, ENTRADA_FORTE, CARTAO, PENALTI, DEFESA, TRAVE

@dataclass(frozen=True)
class Recorte:                    # frações da tela (0..1), independentes da resolução
    x: float; y: float; w: float; h: float

@dataclass(frozen=True)
class Leitura:                    # um quadro lido (ou confirmado)
    casa: str; fora: str          # siglas 2–4 letras, maiúsculas
    gols_casa: int; gols_fora: int
    relogio_s: int | None         # tempo de jogo em segundos (None = não lido neste quadro)
    confianca: float              # 0..1 (menor confiança dos campos)

@dataclass
class Partida:
    id: str                       # "AAAAMMDD-HHMM-CASA-FORA"
    casa: str; fora: str; lado_pedro: Literal["casa", "fora"]
    gols_casa: int = 0; gols_fora: int = 0; relogio_s: int = 0; fase: Fase = Fase.ESPERANDO
    n_lances: int = 0

@dataclass(frozen=True)
class Lance:
    tipo: TipoLance; partida: str; n: int
    placar: tuple[int, int]; minuto: int | None
    casa: str; fora: str; lado_pedro: str; confianca: float
    def json(self) -> str: ...    # uma linha do protocolo (§2) e do lances.jsonl
```

## 2. Captura e protocolo

Pipeline (montado por `captura.py`; `{fd}` herdado via `pass_fds`; recorte em pixels a partir do
`Recorte` e da resolução que o portal informa em `streams[0].size`):

```
gst-launch-1.0 -q pipewiresrc fd={fd} path={node} do-timestamp=true keepalive-time=1000 \
  ! video/x-raw,max-framerate={2}/1 ! videorate drop-only=true max-rate={1} \
  ! videocrop left={l} right={r} top={t} bottom={b} ! videoconvert ! videoscale \
  ! video/x-raw,format=GRAY8,width={W},height={H} ! fdsink fd=1 sync=false
```
- Quadro = `W×H` bytes (`W` = 2 × largura do recorte em px, até 640; `H` proporcional).
- `captura.Quadros(...)` lê exatamente `W*H` bytes por quadro; EOF/erro → `CapturaCaiu`.
- Sem `gst-launch-1.0` ou sem `pipewiresrc` → erro claro ao subir (não tenta de novo).

Protocolo do `magi-lances olhar` (stdout, uma linha JSON por evento; stderr = log):
```
{"t":"pronto","w":2560,"h":1440}
{"t":"lance","v":"gol_pro","partida":"20261010-2130-PSG-BAR","n":3,"placar":[2,1],"min":67,
 "casa":"PSG","fora":"BAR","lado":"casa","conf":0.93}
{"t":"sem_placar","s":300}      # 1×/partida, F-riscos
{"t":"permissao"}               # token recusado/expirado (F2.1)
{"t":"resumo","partida":"…","lidas":5400,"rejeitadas":37}
```

## 3. OCR (`ocr.py`)

1. Recorte do placar dividido em duas sub-regiões fixas (frações dentro do recorte, do `[fifa]`):
   `placar` (siglas + gols) e `relogio`.
2. Pré-processo: normaliza contraste, limiar de Otsu (numpy), inverte se o fundo for claro.
3. **Pula o OCR** da sub-região se a diferença média de pixels para o último quadro lido for < 2%
   (o placar quase nunca muda; o relógio é lido no máximo a cada `relogio_a_cada_s` = 5 s).
4. Motor (D2): `rapidocr` com lista de caracteres `A–Z 0–9 : - +`; ou modelos de dígitos.
5. Interpretação, independente da ordem dos campos no layout:
   - relógio: `(\d{1,3}):(\d{2})` (+ `\+\d` de acréscimo ignorado);
   - siglas: as duas sequências `[A-Z]{2,4}` mais à esquerda e mais à direita;
   - gols: os dois números `\d{1,2}` entre as siglas (separador `-`, `|` ou espaço).
   - Falta campo → `None` (quadro descartado). Confiança < `confianca_min` (0,6) → descartado.
6. Confirmação: a `Leitura` só sai do `ocr` quando (siglas, gols) se repetem em 2 quadros seguidos.

## 4. Máquina da partida (`partida.py`)

`Maquina(meus_times, lado_padrao).alimentar(leitura | None, agora) -> list[Lance]`; pura, relógio
injetado. Regras, em ordem:

| Situação | Efeito |
| --- | --- |
| sem partida e leitura com relógio < 60 s ou siglas novas | nova `Partida`; lado do Pedro (F6); `INICIO` |
| siglas diferentes da partida corrente (2 confirmações) | fecha a corrente sem lance de fim (abandono) e abre outra |
| gols de um lado +1, outro igual | `GOL_PRO`/`GOL_CONTRA`; se o placar passou de atrás para à frente → **mais** `VIRADA_*`; diferença ≥ 3 → `GOLEADA_*` (1×/partida por lado) |
| um lado +2 ou os dois mudaram | aceita o placar novo, emite **um** gol por lado (ordem casa→fora) com `confianca` × 0,5 |
| um lado −1 | `GOL_ANULADO`; placar volta |
| queda maior que 1 | ignora a leitura (erro de OCR) e conta rejeição |
| relógio parado em 45:00–45:59+ e depois sem placar ≥ 10 s, ou ≥ 46:00 visto após < 45:00 | `INTERVALO` (1×) |
| relógio ≥ 90:00 visto e depois sem placar ≥ 20 s, ou jogo fechou | `FIM_VITORIA`/`FIM_DERROTA`/`FIM_EMPATE` pelo lado do Pedro |
| relógio ≥ 105:00 | fase `PRORROGACAO` (fim só depois de ≥ 120:00) |
| sem placar ≥ 300 s com partida aberta | `SEM_PLACAR` 1×/partida (não fecha a partida) |

Minuto = `relogio_s // 60 + 1`, limitado a 90/120.

## 5. Cenas e humor (HUD, vida)

`det_lances` (novo, `hud/wired/reacoes/det_lances.py`) lê `snap.lance = (dict, monotônico)`;
cada lance reage 1× (chave `(partida, n)`), > 15 s de idade é ignorado. Emite
`Disparo("lance", motivo, variante=<tipo>, fmt={...}, causa=f"lance:{partida}:{grupo}")` com
`grupo` = `gol` para gols/virada/goleada, senão o próprio tipo.

Roteiros (passos no formato do catálogo; ajustáveis pelo Conselho/Pedro; só assets que existem):

| Tipo de cena | Passos | Prioridade (vida) | Humor (ânimo, energia) |
| --- | --- | --- | --- |
| `partida_comeca` | F5 500 · B6 C8 1200 | 2 fila | +0,03, +0,10 |
| `gol_pro` | B4 C10 D5 600 · B4 C10 D9 1500 · B6 C8 1000 | 2 fila | +0,15, +0,15 |
| ↳ ramo `virada` | troca o último passo: B4 C5 D9 1800 (bob) | vitória | +0,20, +0,20 |
| ↳ ramo `goleada` | B4 C10 D9 2000 (bob, tails) | vitória | +0,10, +0,10 |
| `gol_contra` | B7 C11 800 · B2 C9 1500 | 2 fila | −0,08, +0,05 |
| ↳ ramo `virada` | F7 C11 1200 · B7 C12 1000 | 2 fila | −0,12, 0 |
| `gol_anulado` | D4 F4 800 · B7 C12 1000 | 3 absorve se houver cena | −0,03 (do lado do Pedro) / +0,03 |
| `intervalo` | B2 C5 1000 | 3 absorve | 0, −0,05 |
| `fim_vitoria` | B4 C10 D9 1500 · B4 C5 1500 | vitória | +0,20, +0,05 |
| `fim_derrota` | B7 C11 1000 · B2 C9 1500 | 2 fila | −0,10, −0,10 |
| `fim_empate` | B2 C5 1200 | 2 fila | 0, −0,05 |

Bloqueios herdados: humor do Pedro 0–1 → sem C11/C12 (troca por C9, regra R3.1 das reações);
Ado/blush nunca em lance. Números de humor vão em `[vida.lances]` do `persona/condessa-gosto.toml`.

## 6. Falas (núcleo, `servico.py`)

No máximo `falas_por_partida` (4), ≥ `falas_intervalo_s` (90 s) entre elas, `Priority.VOICE`,
2 s depois do lance (deixa o grito do narrador passar). Frases pt-br no código, traduzidas pelo
`i18n.tr` (entradas novas em `magi/core/i18n/en-gb.yaml`). `{casa}`/`{fora}` pelo `times.toml`.

| Lance | Frase (sorteio entre 2–3 por lance, sem repetir na partida) |
| --- | --- |
| `INICIO` | "{casa} x {fora}, hein? Bora." · "{meu} hoje. Vamos ver." |
| `GOL_PRO` (1º ou que desempata) | "Golaço!" · "Isso! {placar}." · "Aí sim." |
| `GOL_CONTRA` que empata ou vira | "Ih, {placar}." · "Acordou, Pedro?" (zoeira: só humor do Pedro ≥ 2) |
| `FIM_VITORIA` / `FIM_DERROTA` / `FIM_EMPATE` | "Ganhou de {placar}. Gostei." · "Perdeu, né. Próxima." · "Empate. Justo, até." |

Card (F9): `CardMsg` de jogo "{casa} {gc} × {gf} {fora} · {min}'" em todo gol, anulado e fim.

## 7. Configuração (`[fifa]` em `~/.config/magi/config.toml`)

```toml
[fifa]
ligado = true
processo = "FIFA22.exe"
intervalo_s = 1.0
relogio_a_cada_s = 5.0
confianca_min = 0.6
recorte = { x = 0.03, y = 0.03, w = 0.30, h = 0.06 }   # ESTIMATIVA; a calibração grava o real em lances-recorte.json
sub_placar = { x = 0.25, y = 0.0, w = 0.75, h = 1.0 }  # frações dentro do recorte
sub_relogio = { x = 0.0, y = 0.0, w = 0.25, h = 1.0 }
meus_times = []                 # D3: ex. ["PSG", "BAR"]
lado_padrao = "casa"
falar = true                    # D4
falas_por_partida = 4
falas_intervalo_s = 90
ocr = "rapidocr"                # D2: "rapidocr" | "tesseract" | "modelos"
```

## 8. Critérios de aceite

- **CA-F1** Portal com `dbus-next` falso: sem token → `persist_mode=2` e grava o token novo; com
  token → manda o `restore_token`; recusa (`response` ≠ 0) → `{"t":"permissao"}` e sai limpo.
- **CA-F2** Captura com processo falso que escreve N quadros `W×H`: lê N quadros inteiros; quadro
  cortado no fim → `CapturaCaiu`; nenhum `qdbus`/`gdbus`/`KWin` em `magi/lances/**` (teste de grep).
- **CA-F3** OCR: 20 imagens sintéticas de placar (geradas no teste com PIL, 2 fontes, ruído) + as
  capturas reais da calibração quando existirem → leitura certa em ≥ 19/20; sub-região parada não
  chama o motor.
- **CA-F4** Máquina: uma tabela de sequências (gol simples, 2 gols num quadro, anulado, replay sem
  placar, virada, goleada, intervalo, fim, abandono, prorrogação, OCR com queda de 2) → lances
  exatos; zero gol fantasma em 2 h simuladas com 2% de leituras ruidosas.
- **CA-F5** Serviço com `GameWatcher`, `ProactiveSink` e subprocesso falsos: liga só no FIFA;
  ≤ 4 falas/partida e ≥ 90 s entre elas; em call vira legenda; card em cada gol; `lances.jsonl` gravado.
- **CA-F6** HUD: `LanceMsg` decodificado pelo `events.py` e pelo `hud_bridge`; `det_lances` emite um
  `Disparo` por lance com a causa certa; diretor da vida gera **1** cena para 3 gols em 40 s.
- **CA-F7** (ao vivo) critérios 1–4 do requirements em 2 partidas.
