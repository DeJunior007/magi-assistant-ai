# Spec — Condessa no celular (app Android nativo)

Contratos, números e tabelas. Implementa [requirements.md](requirements.md) (R*, RNF-C*, D*) segundo o
[design.md](design.md) ("design §n"). "Ayanami §n" = `specs/ayanami-central/spec.md`. Valem os padrões
D1a–D12a até o Pedro decidir. Escolhas que o design deixou abertas vêm marcadas **[DSCn]**; versões
marcadas **(S0)** são as últimas estáveis conhecidas e a tarefa A0.2 (spike S0) grava a exata no
`libs.versions.toml` e corrige esta tabela. Critérios de aceite **CA-M1…CA-M44** no fim de cada seção;
todos rodam **sem celular real**: testes JVM (JUnit 4), Robolectric, Compose UI em Robolectric,
`MockWebServer` (Ayanami falsa), testes Python da Ayanami (ASGI em memória e Postgres de teste
`ayanami-pg-teste`, marca `pg`). O que só o aparelho mede fica na §14 (spikes e validação ao vivo).

**Novidade 2026-10-28:** o Minecraft saiu do node 2; a VPS inteira é da Ayanami. O ntfy e as rotas
novas não precisam caber no perfil enxuto (`compose.node2.yml`), mas seguem com `mem_limit` próprio.

## Sumário

1. Estrutura `android/` e versões
2. Contratos Kotlin (`EstadoCondessa`, `RetratoPacote`, `ClienteAyanami`, `PipelineVoz`, `Atualizador`)
3. Tela A e demais telas (layout, cores, tipografia, estados vazio/erro)
4. Retrato (pacote WebP + manifesto, pintura, animação)
5. Voz (gravação, wake word, turno, SSE, Bluetooth)
6. Notificações (UnifiedPush/ntfy)
7. Auto-update
8. Segurança e armazenamento
9. Mudanças na Ayanami (rotas, corpos, escopos, erros)
10. ntfy no Compose
11. CI do APK
12. Comando do PC `magi-retrato`
13. Ayanami falsa e utilitários de teste
14. Spikes e validação ao vivo

### Decisões desta spec

| # | Decisão |
| --- | --- |
| DSC1 | `applicationId` / namespace `br.com.dekasis.condessa` (`:retrato` → `…condessa.retrato`, `:voz` → `…condessa.voz`, `:rede` → `…condessa.rede`). Nome visível "Condessa". |
| DSC2 | JDK de build **21** (toolchain Gradle; o PC tem 21 e 25, o CI usa Temurin 21). SDK local em `~/Android/Sdk` (já existe: `platforms/android-36.1`, `build-tools/36.1.0` e `37.0.0`, sem `cmdline-tools`); `local.properties` fora do git. |
| DSC3 | `:retrato`, `:voz` e `:rede` são módulos Android library, mas a lógica testável fica em pacotes `…logica` sem import de `android.*` (testes JVM puros); o que toca Android fica em `…android`. |
| DSC4 | `GET /v1/retrato/*` aceita escopo `retrato` **ou** `conversa` (o celular pareado antes não tem `retrato`; o PWA não chama). `PUT /v1/retrato` exige tipo `pc` e escopo `retrato-enviar` **ou** `backup` (os tokens `pc` atuais têm `backup`). `retrato` entra no padrão do `celular` e `retrato-enviar` no do `pc` para tokens novos. |
| DSC5 | Transcrição (D9a): campo aditivo `ouvido: str = ""` no `TurnoFim` do elo (o PC preenche com o texto do STT; campo desconhecido já é ignorado, Ayanami §1); a Ayanami publica `turno.ouvido` assim que tem o texto: modo nuvem e long-poll logo depois do STT local; modo PC ao receber o `TurnoFim`, **antes** do `turno.texto`. Turno de texto não publica `turno.ouvido`. |
| DSC6 | ntfy (D5a): `auth-default-access: deny-all`; `everyone` com **write-only** em `up*` (o Web Push não autentica no endpoint); usuário `celular` com **read-only** em `up*` (senha no app ntfy, digitada pelo Pedro, nunca no repo). A Ayanami só posta em endpoint `unifiedpush` cujo host esteja em `[push] ntfy_hosts` (anti-SSRF). S3 pode trocar por token se o ntfy aceitar `?auth=`. |
| DSC7 | Envio do APK ao node 2: verbo novo `app` no comando forçado `ci-deploy.sh` (a chave da CI não faz `scp`): `app <versionCode> <sha256> <versao_b64url>` com o APK no stdin. |
| DSC8 | Comando do PC para a arte (D11a): script novo `magi-retrato enviar` (`magi/elo/retrato.py`, mesmo token/credenciais do `magi-backup`), não `magi ayanami …` (não existe um CLI `magi`). |
| DSC9 | Pacote do retrato = `zip` sem compressão (WebP já é comprimido) com `manifesto.json`; os `.onnx` vão num pacote à parte (`GET /v1/retrato/modelos`) para trocar o modelo sem baixar a arte. |
| DSC10 | Ogg Opus escrito pelo próprio app (`OggOpusEscritor`, ~150 linhas, RFC 7845: `OpusHead` + `OpusTags` + páginas de 20 ms); sem lib de terceiros. Web Push (RFC 8291) decifrado com `javax.crypto` (ECDH P-256, HKDF-SHA256, AES-128-GCM); sem Tink/Bouncy Castle. |

## 1. Estrutura `android/` e versões

```
android/
  settings.gradle.kts            # include(":app", ":retrato", ":voz", ":rede"); repos google()+mavenCentral()
  build.gradle.kts               # plugins apply false
  gradle.properties              # org.gradle.jvmargs=-Xmx3g, android.useAndroidX=true, kotlin.code.style=official
  gradle/libs.versions.toml      # versões abaixo (fonte única)
  gradle/wrapper/…               # gradlew + gradle-wrapper.properties (distributionSha256Sum fixado)
  local.properties               # NÃO versionado (.gitignore): sdk.dir=/home/pedrojr/Android/Sdk
  app/
    build.gradle.kts             # applicationId, versionCode/versionName por -P (CI), signingConfig por env
    proguard-rules.pro           # onnxruntime, kotlinx.serialization, Media3
    src/main/AndroidManifest.xml
    src/main/res/{values,xml,font,drawable,mipmap-*}/   # fontes OFL, ícone próprio, network_security_config
    src/main/kotlin/br/com/dekasis/condessa/
      App.kt  Grafo.kt  MainActivity.kt
      ui/{tema,telaa,gaveta,tv,noticias,tarefas,servidor,ajustes,parear,confirma,diagnostico}/
      estado/ (MaquinaCondessa, UiEstado, Orquestrador)
      push/ (ReceptorPush, DecifradorWebPush, Canais)
      update/ (Instalador, TrabalhoVersao)
    src/test/…                   # JVM + Robolectric + Compose UI
  retrato/src/main/kotlin/…/retrato/{logica/{PortraitToml,Animador,Manifesto},android/{RetratoCache,Pintor}}
  voz/src/main/kotlin/…/voz/{logica/{WakeSpotter,PortaoEnergia,VadEnergia,OggOpusEscritor,Nivel},android/{Gravador,CodificadorOpus,WakeWordOnnx,Tocador,AmplitudeProcessor,SessaoMidia,RotaAudio,Bip}}
  rede/src/main/kotlin/…/rede/{logica/{ParserSse,Modelos,Diagnostico,VerificaApk},android/{ApiAyanami,SseCliente,Conectividade,Atualizador,Cofre}}
```

`libs.versions.toml` (fixadas pela A0.2 em 2026-10-29, conferidas no Google Maven/Maven Central; a fonte
única é `android/gradle/libs.versions.toml`):

| Chave | Versão | Chave | Versão |
| --- | --- | --- | --- |
| `agp` | 9.0.1 | `kotlin` | 2.3.20 |
| `gradle` (wrapper, sha256 fixado) | 9.1.0 | `compose-bom` | 2026.06.01 (Compose 1.11.4) ¹ |
| `activity-compose` | 1.11.0 | `lifecycle` | 2.9.4 |
| `navigation-compose` | 2.9.5 | `media3` | 1.11.1 |
| `onnxruntime-android` | 1.27.0 | `okhttp` (+`okhttp-sse`, `mockwebserver3`) | 5.1.0 |
| `kotlinx-serialization-json` | 1.9.0 | `kotlinx-coroutines` | 1.10.2 |
| `datastore-preferences` | 1.1.7 | `work-runtime-ktx` | 2.10.5 |
| `unifiedpush-connector` (`org.unifiedpush.android:connector`) | 3.0.10 | `core-ktx` | 1.17.0 |
| `junit` | 4.13.2 | `robolectric` | 4.16 |
| `turbine` | 1.2.1 | `androidx-test-ext-junit` / `compose-ui-test-junit4` | 1.3.0 / da BOM |
| `benchmark-macro` (L, `benchmark-macro-junit4`) | 1.4.1 | `jankstats` (`androidx.metrics:metrics-performance`) | 1.0.0 |

¹ A BOM 2026.09.00 (Compose 1.12.1) exige `compileSdk 37` e AGP ≥ 9.1.0; com `compileSdk 36` (D2) e
AGP 9.0.1 a mais nova que compila é a 2026.06.01. Subir para a 2026.09.00 = AGP 9.1+ e `compileSdk 37`.

- `minSdk 29`, `targetSdk 36`, `compileSdk 36` (D2; a S0 anota se o celular do Pedro é ≥ 12 → `minSdk 31`).
  Plataforma `android-36` instalada pela A0.1 se o `android-36.1` local não servir ao AGP.
- `:app` `splits.abi { include("arm64-v8a"); isUniversalApk = false }` (só no release),
  `isMinifyEnabled = true`, `isShrinkResources = true`; debug sem minify.
- `versionCode = (findProperty("vc") ?: "1").toInt()`, `versionName = findProperty("vn") ?: "0.0.0-dev"`.
- Assinatura release só se `CONDESSA_KEYSTORE` (caminho), `CONDESSA_KEYSTORE_SENHA`, `CONDESSA_KEY_ALIAS`,
  `CONDESSA_KEY_SENHA` estiverem no ambiente; sem eles o release sai sem assinatura (CI de PR).
- Sem Hilt/Koin: `Grafo` (no `App`) cria as dependências uma vez; testes montam um `Grafo` falso.

**Aceite.**
- **CA-M1** `./gradlew :retrato:test :voz:test :rede:test :app:testDebugUnitTest lintDebug` verde no PC
  (SDK do usuário) e no CI; `git ls-files android | grep -E 'local.properties|\.jks|\.keystore|\.apk$'` vazio.
- **CA-M2** Teste do manifesto mesclado (`:app:processDebugMainManifest` + leitura do XML no teste):
  as permissões são exatamente as do R10.5 (sem `RECEIVE_BOOT_COMPLETED` no MVP), `allowBackup=false`,
  `dataExtractionRules` vazias, `usesCleartextTraffic` ausente/false, `network_security_config` com
  `cleartextTrafficPermitted="false"`.

## 2. Contratos Kotlin

```kotlin
// :app estado/ — puro
enum class EstadoCondessa { DORMINDO, OUVINDO, PENSANDO, FALANDO }
enum class Gatilho { SEGURAR, WAKE, BOTAO_BT, VOICE_COMMAND, TEXTO }
enum class Modo { PC, NUVEM, DESCONHECIDO }
enum class Conexao { OK, SEM_REDE, SEM_TAILSCALE, AYANAMI_FORA, CASA_FORA /* só p/ TV */ }

sealed interface Evento {                       // entrada da máquina (design §3)
  data class Acordar(val gatilho: Gatilho) : Evento
  data object Soltar : Evento                   // soltar botão | VAD fim | 15 s
  data object Cancelar : Evento                 // arrastar para fora | < 400 ms
  data class Aceito(val turno: String, val modo: Modo) : Evento        // 202
  data class Ouvido(val turno: String, val texto: String) : Evento     // SSE turno.ouvido
  data class Texto(val turno: String, val texto: String) : Evento      // SSE turno.texto
  data class Fim(val turno: String, val ok: Boolean, val audio: Boolean, val erro: String?) : Evento
  data object AudioComecou : Evento; data object AudioAcabou : Evento
  data class Erro(val frase: String) : Evento
  data class Tique(val agoraMs: Long) : Evento  // prazos: 50 s sem fim, +1,5 s depois do áudio
}
data class UiEstado(
  val condessa: EstadoCondessa, val turno: String?, val modo: Modo, val conexao: Conexao,
  val legenda: String, val falaPedro: String, val faixa: Faixa?, val bloqueioUpdate: Boolean,
)
class MaquinaCondessa(private val relogio: () -> Long) {
  val estado: StateFlow<UiEstado>
  fun tratar(e: Evento)                         // única porta; puro, testável sem Android
}

// :retrato logica/
data class Quadro(val olhos: String, val boca: String, val dyRespiracao: Float, val acordada: Boolean)
class Animador(cfg: PortraitToml, private val rng: java.util.Random) {
  fun quadro(estado: EstadoRetrato, nivel: Float, agoraS: Double): Quadro   // porta de portrait.py
  fun fpsAlvo(estado: EstadoRetrato, piscando: Boolean): Int                 // 60 / 30 / 8
}
enum class EstadoRetrato { SLEEPING, IDLE, LISTENING, THINKING, SPEAKING }   // nomes do [states]
data class RetratoPacote(val versao: String, val lado: Int, val manifesto: Manifesto, val dir: java.io.File)
interface RetratoFonte {                          // RetratoCache implementa
  suspend fun atual(): RetratoPacote?             // null → placeholder (R1.5)
  suspend fun atualizar(permitirMovel: Boolean): ResultadoRetrato  // ATUAL | BAIXADO | SEM_ARTE | ERRO
}

// :rede
interface ClienteAyanami {
  suspend fun saude(): Saude                                              // timeout 4 s
  suspend fun trocarCodigo(base: String, codigo: String, nome: String): Pareado
  suspend fun turnoTexto(texto: String): TurnoAceito
  suspend fun turnoAudio(ogg: ByteArray): TurnoAceito                     // audio/ogg;codecs=opus
  fun urlAudio(turno: String): String                                     // ExoPlayer + OkHttpDataSource
  suspend fun confirmar(pedido: String, resposta: Boolean)
  suspend fun casaEstado(): CasaEstado; suspend fun casaAcao(tv: String?, pedido: AcaoPedido): AcaoResultado
  suspend fun feed(antes: String?, n: Int = 30): List<Card>
  suspend fun tarefas(estado: String? = null): List<TarefaOut>; suspend fun cancelarTarefa(id: String)
  suspend fun servidor(): JsonObject
  suspend fun preferencias(p: Preferencias); suspend fun sair()
  suspend fun assinarPush(endpoint: String, p256dh: String, auth: String)
  suspend fun appVersao(): VersaoApp?                                     // 404 → null
  suspend fun baixarApk(destino: java.io.File, aPartirDe: Long): Long     // Range
  suspend fun retratoVersao(): RetratoVersao?; suspend fun baixarRetrato(lado: Int, destino: java.io.File, aPartirDe: Long): Long
  suspend fun baixarModelos(destino: java.io.File): Long
}
sealed class ErroAyanami(val frase: String) : Exception(frase) {          // R9.5: frase pt-BR
  class NaoAutorizado : ErroAyanami("O aparelho saiu da Ayanami; pareie de novo.")   // 401 → apaga token
  class Http(val status: Int, val codigo: String, frase: String) : ErroAyanami(frase)
  class SemConexao(val tipo: Conexao) : ErroAyanami("Sem conexão com a Ayanami.")
}
interface FonteEventos { fun eventos(ultimoId: String?): Flow<EventoSse> }   // reconecta 1→30 s
data class EventoSse(val nome: String, val id: String?, val dados: String)

// :voz
interface PipelineVoz {
  val nivelSaida: StateFlow<Float>               // 0..1, já atrasado pela latência de saída (design §3.1)
  val eventos: SharedFlow<EventoVoz>             // WakeDetectado, FimDeFala, Cancelado, AudioComecou, AudioAcabou
  fun ligarEscuta(ligada: Boolean)               // wake word com app aberto (R2.2)
  suspend fun gravarTurno(origem: Gatilho, rota: RotaAudio.Saida): ByteArray?  // Ogg Opus ou null (<400 ms/cancelado)
  fun soltar(); fun cancelar()
  fun tocar(url: String, cabecalhos: Map<String, String>); fun pararFala()
}

// :rede logica/ + :app update/
data class VersaoApp(val versionCode: Int, val versionName: String, val sha256: String, val bytes: Long,
                     val minimo: Int, val notas: String, val publicado: String, val certSha256: String)
interface Atualizador {
  suspend fun verificar(): EstadoUpdate          // NADA | DISPONIVEL(v) | OBRIGATORIA(v) (minimo > atual)
  suspend fun baixarEConferir(v: VersaoApp): java.io.File   // sha256 + cert + pacote; falha → apaga e lança
  suspend fun instalar(apk: java.io.File)        // só com MaquinaCondessa em DORMINDO (R8.5)
}
object VerificaApk {                              // puro
  fun sha256Hex(f: java.io.File): String
  fun confere(v: VersaoApp, shaArquivo: String, certsApk: List<String>, pacoteApk: String,
              certsInstalado: List<String>, pacoteInstalado: String): Resultado  // OK | SHA | CERT | PACOTE | VERSAO
}
```

Regras da `MaquinaCondessa` (design §3): `Acordar` em `DORMINDO` → `OUVINDO`; em `FALANDO` →
para a fala e `OUVINDO` (barge-in); em `PENSANDO` ou `OUVINDO` → ignora. `Soltar` → `PENSANDO`;
`Cancelar` → `DORMINDO`. `Texto` em `PENSANDO` mostra a legenda e fica em `PENSANDO`.
`AudioComecou` → `FALANDO`. `Fim` sem áudio → legenda e `DORMINDO`; com áudio → espera `AudioAcabou`,
+1,5 s, `DORMINDO`. `Tique` com 50 s desde `Aceito` sem `Fim` → `DORMINDO` + legenda "Ela não
respondeu; tenta de novo?" (R3.6). Eventos de turno com `turno` ≠ atual são descartados.
`bloqueioUpdate` (R8.4) recusa `Acordar` com a faixa "Atualize para continuar".

**Aceite.**
- **CA-M3** `MaquinaCondessaTest` (JVM, relógio falso): tabela de 20 transições do parágrafo acima,
  incluindo barge-in, `Texto` antes de `AudioComecou`, turno alheio descartado, 50 s, +1,5 s e bloqueio.
- **CA-M4** `ErroAyanami`: toda resposta 4xx/5xx de `MockWebServer` (401, 403, 404, 409, 410, 413, 415,
  429, 503 `casa_offline`, 504) vira frase pt-BR sem stack trace; 401 chama `Cofre.apagar()` e emite
  `IrParaParear`.

## 3. Telas

### 3.1 Tema

| Token | Valor | Uso |
| --- | --- | --- |
| `fundo0` / `fundo1` | `#07060b` / `#120c18` | gradiente vertical da tela |
| `rosa` | `#f2a7c3` | brilho radial atrás dela (alfa 0,35, raio 60 % da largura), onda, botão falar |
| `lilas` | `#b392f0` | rótulos, pílulas (borda 1 dp), ícones |
| `texto` / `texto2` | `#efe9f5` / `#9a90a8` | legenda / secundário |
| `ok` / `aviso` / `erro` | `#7ee0a1` / `#f0c674` / `#ff7a8a` | ponto "PC ●", faixas |
| Rajdhani 600 | 14 sp, caixa alta, espaçamento 0,12 em | rótulos, pílulas, gaveta |
| JetBrains Mono 500 | 13 sp | estado (EM ESPERA/OUVINDO/PENSANDO/FALANDO), "PC ● ONLINE" |
| Inter 400/600 | legenda 22 sp (600), fala do Pedro 14 sp, corpo 16 sp | textos |

Fontes empacotadas em `res/font/` (OFL; licenças em `android/app/src/main/assets/licencas/`). Tamanhos em
`sp` (respeitam a fonte do sistema, RNF-C8). Só tema escuro.

### 3.2 Tela A (retrato, 360×800 dp de referência)

```
┌──────────────────────────────── 16 dp margem ─┐
│ ● OUVINDO                     PC ● ONLINE      │  topo 48 dp: estado (mono) | modo
│ [faixa de conexão, 40 dp, quando houver]       │
│                                                │
│           Condessa (Canvas, peso 1,            │  retrato: contain, base alinhada
│           ocupa o resto, ≥ 55 % da altura)     │  ao topo da legenda
│                                                │
│   "apaga a TV da sala"  (Pedro, 14 sp, 2 l.)   │
│   Legenda dela (22 sp, até 4 linhas, rola)     │  bloco legenda: máx 30 % da altura
│   ∿∿∿∿∿ onda 32 dp ∿∿∿∿∿                        │
│ (TV da sala) (Notícias · 3) (Tarefas)          │  pílulas 36 dp, rolagem horizontal
│  [⌨ 48dp]     ( ◉  FALAR  88 dp )    [⋯ 48dp]  │  base 112 dp
│        "CONDESSA" OU SEGURE  (12 sp)           │
└────────────────────────────────────────────────┘
```

- Botão falar: círculo 88 dp, rosa; segurar = `SEGURAR` (R2.1: < 400 ms descarta, arrastar > 48 dp
  para fora cancela, 15 s solta); toque curto com escuta ligada mostra a dica. `contentDescription`
  "Segure para falar com a Condessa". Teclado abre `TextField` acima da base (enviar = `TEXTO`).
- Onda: 24 barras de 3 dp, altura = `nivelSaida` × 32 dp com decaimento de 120 ms; parada = linha.
- Topo direito: `PC ● ONLINE` (`ok`), `NUVEM` (`lilas`), `—` (desconhecido).
- Paisagem: retrato à esquerda (50 %), legenda/pílulas/base à direita.

### 3.3 Estados vazio/erro (faixa da tela A, R9.1)

| `Conexao` / caso | Detecção | Faixa (texto) | Ação | Efeito |
| --- | --- | --- | --- | --- |
| `SEM_REDE` | `ConnectivityManager` sem rede validada | "Sem internet." | — | voz/TV desabilitadas; texto vai à fila |
| `SEM_TAILSCALE` | sem rede `TRANSPORT_VPN` **ou** DNS do host `.ts.net` falha | "Sem conexão com a Ayanami — ligue o Tailscale" | **Abrir Tailscale** (`com.tailscale.ipn`; ausente → loja/navegador não; mostra "instale o Tailscale") | Condessa `DORMINDO`; fila de texto |
| `AYANAMI_FORA` | VPN ok e `GET /saude` falha/timeout 4 s ou `503` | "A Ayanami não respondeu." | **Tentar de novo** | idem |
| PC off (`online.pc=false` ou `modo=nuvem`) | `/saude`, `202` | (sem faixa) topo `NUVEM` | — | conversa normal |
| `CASA_FORA` | `casa.online=false` / `503 casa_offline` | na TV: "A casa está fora do ar (PC desligado ou magi-casa parado)." | — | botões da TV cinza |
| sem TV (`tvs: []`) | `GET /v1/casa/estado` | pílula "TV — parear"; gaveta "Nenhuma TV pareada — no PC: `magi-casa descobrir`" | **Como parear** (texto local) | — |
| sem arte | `RetratoFonte.atual()==null` | (sem faixa) silhueta rosa + estado | Ajustes → "Baixar a arte" | voz/texto normais |
| update obrigatório | `minimo > versionCode` | "Atualize para continuar." | **Atualizar** | turnos bloqueados |
| sem ntfy | sem distribuidor UnifiedPush | (só nos Ajustes) "Instale o ntfy para avisos na hora." | — | recaída WorkManager 30 min |

Fila local (R9.3): ≤ 5 textos, cada um expira em 10 min, sai em ordem quando `Conexao` volta a `OK`;
"(na fila)" ao lado da fala do Pedro. Saúde (R9.2): ao abrir, ao voltar ao 1º plano, a cada 30 s com
a tela A visível, e no `NetworkCallback.onAvailable/onLost`.

### 3.4 Gaveta e telas

`ModalBottomSheet` com 5 linhas de 56 dp: TV, Notícias, Tarefas, Servidor, Ajustes. Rotas internas
(`navigation-compose`): `telaA`, `tv`, `noticias`, `tarefas`, `tarefas/{id}`, `servidor`, `ajustes`,
`parear`, `confirma/{pedido}`, `diagnostico`. URLs do push (`/app/#/confirma/<ulid>`,
`/app/#/tarefas/<id>`, `#/noticias`) mapeiam para essas rotas (`RotaDeUrl`, puro).

- **TV** (R4): lista das TVs; controle com só os botões das `caps`; ligar/desligar pede 2º toque em 3 s;
  vol ± repete a cada 200 ms segurando; teclas de volume físicas viram vol da TV com a tela aberta.
- **Notícias** (R5.2): cards de `GET /v1/feed` paginados por `antes=`; 1ª página em cache
  (`filesDir/cache/feed.json`); `N` da pílula = cards com `ts` > última visita.
- **Tarefas** (R5.3), **Servidor** (R5.4: `/v1/servidor` + `/saude`), **Ajustes** (R5.5: tabela da §8.2).
- **Parear** (R6): campo endereço (`https://…`, só `https`), 6 dígitos, nome `celular-pedro`;
  ler QR do HUD (`Intent` de câmera do sistema não; leitura do QR fica para L — no MVP o código
  e o endereço são digitados); sucesso → grava token no `Cofre`, base no DataStore.
- **Confirma** (R3.5): cartão com descrição, "Confirmar" exige 2 toques em 3 s; expirou → "expirou".
- **Diagnóstico** (design §11): 7 toques na versão; p50/p90 do anel de 200 medições.

**Aceite.**
- **CA-M5** Compose UI (Robolectric) da tela A com `UiEstado` injetado: rótulo do estado e do modo
  para os 4×3 casos; botões ≥ 48 dp e com `contentDescription`; legenda visível com fonte do sistema 1,3×.
- **CA-M6** Uma faixa e uma ação por linha da tabela §3.3 (Compose UI, 8 casos); "Abrir Tailscale"
  dispara `Intent` com o pacote `com.tailscale.ipn` (Robolectric `ShadowApplication`).
- **CA-M7** `Conectividade.classificar(rede, vpn, dns, saude)` (puro): 6 combinações → `Conexao`
  certa; `FilaTexto` com relógio falso: 6º item recusado, item de 11 min descartado, ordem preservada.
- **CA-M8** TV: `tvs: []` mostra o texto do R4.3; `online=false` deixa os botões desabilitados;
  só os botões das `caps` aparecem; desligar sem 2º toque em 3 s não chama `/v1/casa/acao`
  (Ayanami falsa conta as chamadas).
- **CA-M9** `RotaDeUrl`: as 3 URLs do push + URL desconhecida (→ `telaA`).

## 4. Retrato

### 4.1 Pacote (gerado pela Ayanami, §9.3)

`GET /v1/retrato/pacote?lado=768` → `application/zip` (sem compressão, `STORED`):

```
manifesto.json
portrait.toml                # cópia do original (o app lê [states], [speech], breath_*, blink)
camadas/fundo_busto.webp     # back + back_tip (+ tail_l/_tip, tail_r/_tip no MVP: sem pêndulo)
camadas/corpo.webp           # arm_l + arm_r + body
camadas/cabeca.webp          # head
camadas/frente.webp          # lock_l + lock_r + (bangs_c | bangs) + clip
olhos/B1.webp … B3, B13, B14, B15.webp   # recortados na bounding box
bocas/C1.webp … C3, C7.webp
```

`manifesto.json`:
```json
{"v":1,"versao":"<sha256 do tar enviado>","lado":768,"base":1024,
 "camadas":[{"id":"fundo_busto","arq":"camadas/fundo_busto.webp","x":0,"y":0,"w":768,"h":768,"grupo":"busto"},
            {"id":"corpo","arq":"camadas/corpo.webp","x":0,"y":0,"w":768,"h":768,"grupo":"busto"},
            {"id":"cabeca","arq":"camadas/cabeca.webp","x":0,"y":0,"w":768,"h":768,"grupo":"busto"},
            {"id":"olhos","grupo":"busto"},{"id":"boca","grupo":"busto"},
            {"id":"frente","arq":"camadas/frente.webp","x":0,"y":0,"w":768,"h":768,"grupo":"busto"}],
 "olhos":{"B1":{"arq":"olhos/B1.webp","x":301,"y":288,"w":170,"h":60}},
 "bocas":{"C1":{"arq":"bocas/C1.webp","x":350,"y":402,"w":70,"h":38}},
 "sha256":{"camadas/corpo.webp":"…"}}
```

- Ordem de pintura = ordem de `camadas` = R1.1 (back, back_tip, tails, arm_l, arm_r, body, head,
  olhos, boca, lock_l, lock_r, bangs_c|bangs, clip); `olhos`/`boca` são marcadores sem arquivo.
  O gerador lê `PARTS_ORDER` e os grupos do `hud/wired/portrait.py` (não duplica a lista).
- WebP com perda q 90, alfa; tudo em `lado`×`lado` com origem no canto; olhos/bocas com `x,y,w,h`
  da *bounding box* (alfa > 0) já na escala do `lado`. Só o conjunto do MVP (design §7.1);
  arquivos ausentes no original são pulados e o manifesto não os lista.
- Teto: zip 768 ≤ 15 MB, 512 ≤ 8 MB (critério 6); passou → job falha com `retrato_grande`.
- `GET /v1/retrato/modelos` → `application/zip` com `condessa.onnx`, `melspectrogram.onnx`,
  `embedding_model.onnx` (+`silero_vad.onnx` se veio) e `modelos.json` `{"v":1,"limiar":0.6,
  "patience":3,"gate_dbfs":-50,"sha256":{…}}` (limiar/patience copiados do `[satellite]` enviado no tar).

### 4.2 `RetratoCache`

1ª abertura (ou versão nova em `GET /v1/retrato/versao`): lado = 768 se a altura útil do Canvas ≥
1100 px, senão 512; baixa em `noBackupFilesDir/retrato/tmp.zip` com `Range` (retoma), confere o
`sha256` do zip (`/versao` → `pacotes[lado].sha256`) e cada arquivo pelo manifesto, extrai em
`noBackupFilesDir/retrato/<versao>-<lado>/`, troca o ponteiro (DataStore) e apaga a anterior. No 4G
(rede `NOT_METERED` ausente) pergunta antes ("Baixar a arte (≈ N MB) pelo 4G?"). Falha → mantém a
anterior ou placeholder. Mesmo fluxo para `modelos.zip` em `noBackupFilesDir/modelos/<sha>/`.

### 4.3 Animação (`Animador`, porta de `portrait.py`)

| Item | Valor (constante do `portrait.py`) |
| --- | --- |
| Respiração | `dy = breath_px × sin(2π t / breath_period)` (padrões 2 px na base 1024 e 4,5 s; escala `lado/1024`); só acordada; grupo `busto` inteiro |
| Piscada | próxima em `uniform(3, 6)` s (`BLINK_EVERY`), dura 120 ms (`BLINK_LEN`): B2 no 1º terço, B3 no 2º, B2 no 3º; olho base do estado (`blink` do `[states]`) |
| Boca falando | nível `< 0,18` → C1, `< 0,72` → C2, senão C3 (`MOUTH_LEVELS`); cada boca ≥ 70 ms (`MOUTH_HOLD`) |
| Estados | `sleeping` (B14; 23h–7h B15), `idle` (B1, 30 s após o turno), `listening`, `thinking` (B13/C7), `speaking` — olho/boca do `[states]` do `portrait.toml` |
| fps | 60 falando/piscando, 30 parada, 8 dormindo (`PARTS_FPS` 60/40/6 do HUD adaptado); quadro igual ao anterior não invalida |
| Fundo | gradiente + brilho num `ImageBitmap` estático, refeito só ao mudar o tamanho |

`Pintor`: `Modifier.drawWithCache` + `LaunchedEffect { withFrameNanos }` que escreve o `Quadro` num
`mutableStateOf` lido só no `onDrawBehind` (sem recompor). `contain` no retângulo; `translate(dy)` no
grupo `busto`. Para (sem `withFrameNanos`) com `Lifecycle.State < STARTED` (R1.7).

**Aceite.**
- **CA-M10** `AnimadorTest` (JVM): com semente fixa, a sequência de olhos/bocas/dy de 10 s a 60 Hz
  bate com `tests/fixtures/retrato/sequencia.json`, gerada por `scripts/retrato_sequencia.py` a partir
  do `portrait.py` com o mesmo `rng` (gerador `java.util.Random` replicado em Python, LCG 48 bits).
- **CA-M11** Boca: série de níveis sintética → nenhuma boca dura < 70 ms; limiares 0,18/0,72 exatos.
- **CA-M12** `Manifesto` (JVM): parse do exemplo; arquivo com sha errado → `ERRO` e pasta nova apagada;
  zip com `../` no nome recusado; `RetratoCache` com Ayanami falsa: 1ª abertura baixa e extrai,
  versão igual não baixa, versão nova troca e apaga a velha, `Range` retoma depois de corte.
- **CA-M13** `fpsAlvo` e "quadro igual não invalida" (contador de invalidações com relógio falso:
  dormindo 10 s ≤ 80 quadros).

## 5. Voz

### 5.1 Gravação e envio

`AudioRecord(VOICE_RECOGNITION, 16000, MONO, PCM_16BIT)`, blocos de 1280 amostras (80 ms).
`CodificadorOpus`: `MediaCodec` `audio/opus` 24 kb/s, 16 kHz mono, quadros de 20 ms →
`OggOpusEscritor` (granule a 48 kHz, `pre_skip` do `csd-1`) em memória (≤ 50 KB, teto 1 MiB).
Fim: soltar, `VadEnergia` (800 ms abaixo de −45 dBFS depois de fala), 15 s, ou 5 s sem fala após
wake/BT (`wake_no_speech_ms`). < 400 ms → descarta. Envio: `POST /v1/turno` multipart campo `audio`,
`Content-Type: audio/ogg;codecs=opus`, nome `turno.ogg`. O `ByteArray` é zerado e liberado após o
`202` (R2.5).

### 5.2 Wake word (D3a, app aberto)

Porta de `magi/satellite/wake.py`: `PortaoEnergia(−50 dBFS, pré-rolagem 16 blocos, hangover 2 s)` →
`melspectrogram.onnx` → `embedding_model.onnx` (janela 76 quadros mel, passo 8) → `condessa.onnx`
(16 embeddings) → `WakeSpotter(limiar=0,6, patience=3, recarga=2 s)`. ORT: 1 thread intra/inter,
`ORT_SEQUENTIAL`, sem NNAPI. Em `FALANDO` o limiar sobe para 0,9 e o `AcousticEchoCanceler` liga
se `isAvailable()`. Escuta só com a tela A em `RESUMED` e o ajuste ligado (R2.5); `ON_PAUSE` fecha o
`AudioRecord`. Disparo → bip 120 ms 880 Hz (`ToneGenerator`), `OUVINDO`, mesma gravação da §5.1
(os blocos desde o disparo seguem para o codificador). Sem `modelos.zip` → escuta desligada com
"baixe a arte e a voz nos Ajustes".

### 5.3 SSE e áudio

`GET /v1/eventos` com `Accept: text/event-stream`, `Last-Event-ID` do último `id:`; só com o app
visível (RNF-C9). Eventos tratados:

| Nome | `data` | Efeito |
| --- | --- | --- |
| `turno.ouvido` (novo, §9.5) | `{"turno","texto"}` | `Evento.Ouvido` → linha do Pedro |
| `turno.texto` | `{"turno","texto"}` | `Evento.Texto` → legenda |
| `turno.fim` | `TurnoFim` (`turno, ok, texto, fala, cards, expressao, audio, erro, ouvido`) | `Evento.Fim`; `ouvido` não vazio e sem `turno.ouvido` antes → preenche a linha do Pedro |
| `confirma` | `Confirma` | cartão (R3.5); fechado (`resposta`≠null ou expirou) → some |
| `estado` | `Estado` | TV |
| `evento` | `Evento` | dedupe do push pelo `id` (R7.4) |
| `ping` | — | vigia: 45 s sem nada → reconecta |

Reconexão 1, 2, 4, 8, 16, 30 s (teto). `turno.fim` com `audio=true` (ou `modo=pc`, cujo áudio pode
vir depois do fim) → `Tocador.tocar(urlAudio(turno))` já no `202`+`turno.texto`: ExoPlayer com
`OkHttpDataSource.Factory` (cabeçalho `Authorization`), `ProgressiveMediaSource`, `OggExtractor`;
`410` → só legenda. `AmplitudeProcessor` (RMS por 20 ms, pico móvel 1,5 s, piso −50 dBFS) +
atraso da `AudioTrack.getTimestamp` → `nivelSaida`. Turno de texto toca áudio só com `voz_em_texto`.

### 5.4 Bluetooth (D12a)

`SessaoMidia`: `MediaSessionService` (Media3) com `ForwardingPlayer` do `Tocador`; FGS
`mediaPlayback` com notificação mínima "Condessa pronta" no canal `midia`, ativa com o app aberto e
até 10 min depois da última fala. `onMediaButtonEvent`: `KEYCODE_HEADSETHOOK` ou
`KEYCODE_MEDIA_PLAY_PAUSE` curto → `Acordar(BOTAO_BT)` (em `FALANDO` → `pararFala`); outros botões →
ignorados. `MainActivity` com filtro `android.intent.action.VOICE_COMMAND` → abre em `OUVINDO`
(`setShowWhenLocked(true)`, `setTurnScreenOn(true)`). Fone conectado: API 31+
`setCommunicationDevice(fone)` antes de gravar, `clearCommunicationDevice()` depois da fala; API 29–30
`startBluetoothSco`/`stopBluetoothSco` (espera `SCO_AUDIO_STATE_CONNECTED` até 2 s, senão microfone
do aparelho). Ajuste "saída de áudio": automático | sempre alto-falante.

**Aceite.**
- **CA-M14** `OggOpusEscritor` (JVM): pacotes Opus sintéticos → páginas com `OggS`, CRC certo,
  `OpusHead` (versão 1, 1 canal, 16000 Hz original) e granule final = amostras×3; o arquivo gerado é
  aceito pelo `ffprobe` num teste Python da Ayanami (`tests/ayanami/test_turno_ogg.py`, fixture
  binária gerada pelo teste Kotlin e versionada, ≤ 4 KB).
- **CA-M15** `WakeSpotter`/`PortaoEnergia` (JVM): mesma tabela de casos do `tests/satellite`
  (limiar, patience 3, recarga 2 s, portão com pré-rolagem 16 e hangover 2 s), com detector falso.
- **CA-M16** Regras de gravação (JVM, relógio falso): < 400 ms → null; 15 s → solta sozinho; 5 s sem
  fala após wake → cancela; 800 ms de silêncio após fala → fim.
- **CA-M17** `ParserSse` (JVM): `event:`/`id:`/`data:` multilinha, comentários `:`, `retry:`; a
  `FonteEventos` com `MockWebServer` reconecta com `Last-Event-ID` e espera 1→30 s (relógio falso).
- **CA-M18** `Orquestrador` (Robolectric, Ayanami falsa + `PipelineVoz` falso): segurar → `POST
  /v1/turno` multipart `audio/ogg;codecs=opus` → `202` → `turno.ouvido` → `turno.texto` → áudio →
  `FALANDO` → `DORMINDO`; turno de texto sem `voz_em_texto` não pede `/audio`; `410` só legenda.
- **CA-M19** BT (Robolectric): `KEYCODE_HEADSETHOOK` em `DORMINDO` → `Acordar(BOTAO_BT)`; em `FALANDO`
  → `pararFala`; `VOICE_COMMAND` abre a `MainActivity` com a flag de ouvir; o microfone (`Gravador`
  falso) só abre nos 3 casos do R2.5 (contador).

## 6. Notificações (D5a)

Fluxo do design §6. `ReceptorPush : PushService` (connector 3.x): `onNewEndpoint(endpoint)` →
`POST /v1/push/assinar` `{"endpoint","keys":{"p256dh","auth"},"tipo":"unifiedpush"}`;
`onMessage(bytes)` → `DecifradorWebPush.decifrar(bytes)` (RFC 8291 `aes128gcm`: cabeçalho salt 16 +
rs 4 + idlen 1 + keyid = chave pública do servidor de 65 bytes; ECDH com a privada do app; HKDF
`"WebPush: info\0"‖ua_public‖as_public` → IKM; CEK/nonce de `"Content-Encoding: aes128gcm\0"` e
`"Content-Encoding: nonce\0"`; tira o padding `0x02`) → JSON do payload Ayanami §15 →
`Notification` no canal do `tipo`. Chaves: par P-256 gerado no app (`KeyPairGenerator("EC")`), a
privada guardada cifrada pelo `Cofre` (o Keystore não exporta ECDH usável pelo `KeyAgreement` em todo
aparelho); `auth` 16 bytes aleatórios. `onUnregistered` → `DELETE /v1/push/assinar`.

| Canal | Importância | `tipo` |
| --- | --- | --- |
| `confirma`, `lembrete` | HIGH | idem |
| `tarefa`, `monitor`, `operacao` | DEFAULT | idem |
| `noticia` | LOW | idem |
| `midia` (FGS da sessão), `escuta` (FGS L), `update` | MIN / MIN / DEFAULT | — |

Notificação: título = `titulo`, texto = `resumo`, `setOnlyAlertOnce`, id estável por `tag`
(substitui), `PendingIntent` para `RotaDeUrl(url)`; `confirma` **sem** ação "Confirmar" (DS17).
App visível → não notifica (o SSE entrega; `id` em LRU de 200 para dedupe). Sem distribuidor
(`UnifiedPush.getDistributors()` vazio) → `TrabalhoAvisos` (WorkManager periódico 30 min, rede
conectada): `GET /v1/feed?n=10` e notifica `tarefa`/`noticia` novos.

**Aceite.**
- **CA-M20** `DecifradorWebPush` (JVM): decifra o vetor de teste do RFC 8291 §5 e uma mensagem
  gerada pelo `pywebpush` (fixture: `scripts/gerar_vetor_webpush.py` com chaves falsas fixas, saída
  em `android/app/src/test/resources/webpush/`); `auth` errado → falha sem exceção vazando dado.
- **CA-M21** `ReceptorPush` (Robolectric): payload de cada `tipo` vai ao canal certo; `confirma` sem
  `actions`; mesma `tag` substitui; com o app visível não notifica; `id` repetido não notifica 2×.
- **CA-M22** Sem distribuidor: `TrabalhoAvisos` agendado com período 30 min e restrição de rede
  (`WorkManagerTestInitHelper`); com distribuidor, não agendado.

## 7. Auto-update (D8a)

`TrabalhoVersao` (WorkManager periódico 6 h, rede conectada) e ao abrir: `appVersao()` →
`versionCode > instalado` → `baixarApk` em `cacheDir/update/condessa-<vc>.apk` (`Range` retoma) →
`VerificaApk.confere`: sha256 do arquivo = `sha256`; `getPackageArchiveInfo(GET_SIGNING_CERTIFICATES)`
→ pacote = `br.com.dekasis.condessa`, conjunto de SHA-256 dos certificados = do instalado e contém
`cert_sha256`; `versionCode` do arquivo = anunciado. Qualquer diferença → apaga, log local
(`update_recusado:<motivo>`), não instala, tenta de novo só na próxima versão. Passou → espera
`DORMINDO` (R8.5) → `PackageInstaller.Session` `MODE_FULL_INSTALL`, API 31+
`setRequireUserAction(USER_ACTION_NOT_REQUIRED)`, API 34+ `setRequestUpdateOwnership(true)`;
`STATUS_PENDING_USER_ACTION` → notificação "Atualização pronta — toque para instalar" (canal `update`)
com o `Intent` de confirmação. Sem permissão `canRequestPackageInstalls()` → pede uma vez com
explicação; recusada → faixa nos Ajustes "atualização disponível" + botão. `minimo > instalado` →
`bloqueioUpdate` (R8.4). Ajustes → "Procurar atualização" chama o mesmo fluxo na hora.

**Aceite.**
- **CA-M23** `VerificaApk.confere` (JVM): OK, sha diferente, cert diferente, pacote diferente,
  `versionCode` diferente → 5 resultados; arquivo apagado em todos os não-OK (`Atualizador` com
  sistema de arquivos temporário e Ayanami falsa).
- **CA-M24** `Atualizador` (Robolectric): `versionCode` igual não baixa; maior baixa com `Range`
  depois de corte simulado; em `FALANDO` não instala até `DORMINDO`; `minimo` > instalado liga o
  bloqueio; `404` em `/v1/app/versao` = nada publicado, sem erro na tela.

## 8. Segurança e armazenamento

### 8.1 `Cofre`

Chave AES-256-GCM no `AndroidKeyStore` (`alias "condessa-cofre"`, `setRandomizedEncryptionRequired`,
não exportável); guarda `token`, base da Ayanami e a privada do push em
`noBackupFilesDir/cofre.bin` (`iv‖ct` por item, JSON). Logs: `Log` só com códigos (`turno_202`,
`sse_reconecta`), nunca token, URL completa, texto da conversa nem áudio. Interceptor do OkHttp
recusa host que não termine em `.ts.net` **ou** não seja o host pareado, e qualquer `http://`.

### 8.2 Preferências (DataStore `prefs`)

| Chave | Padrão | Sincroniza com a Ayanami |
| --- | --- | --- |
| `nome` | `celular-pedro` | (no pareamento) |
| `push`, `push_com_pc`, `silencio` | true, true, `"23:00-07:30"` | `PUT /v1/dispositivo/preferencias` |
| `tv_padrao` | null | idem |
| `voz_em_texto` | false | idem |
| `escuta_app_aberto` | true | não |
| `escuta_segundo_plano` (L) | false | não |
| `saida_audio` | `auto` | não |
| `ultima_visita_noticias`, `retrato_atual`, `modelos_atual` | — | não |

Histórico do dia (R3.7): `filesDir/historico/<AAAA-MM-DD>.jsonl` (só texto), apagado na 1ª abertura
de outro dia e por `TrabalhoMeiaNoite`.

**Aceite.**
- **CA-M25** `Cofre` (Robolectric com provedor de Keystore falso): grava/lê/apaga; arquivo não contém
  o token em claro; `ApiAyanami` recusa `http://` e host fora do pareado (`MockWebServer` em host
  diferente); varredura do log capturado em CA-M18 sem o token falso.
- **CA-M26** Histórico: virada de dia (relógio falso) apaga o arquivo anterior.

## 9. Mudanças na Ayanami (aditivas, RNF-C7)

Todas em Python, testes em `tests/ayanami/` (ASGI em memória; `pg` onde marcado). O PWA segue sem
mudança (CA-Y57 do Ayanami continua verde).

### 9.1 Escopos (`ayanami/api/auth.py`)

`ESCOPOS_PADRAO["celular"] += ("retrato",)`, `ESCOPOS_PADRAO["pc"] += ("retrato-enviar",)`.
`ESCOPO_DE_ROTA` ganha:

| Método e caminho | Exigência |
| --- | --- |
| `GET /v1/app/versao` | `_e("conversa")` |
| `GET /v1/app/apk` | `_e("conversa")` |
| `GET /v1/retrato/versao` | `_e("retrato", "conversa")` (DSC4) |
| `GET /v1/retrato/pacote` | `_e("retrato", "conversa")` |
| `GET /v1/retrato/modelos` | `_e("retrato", "conversa")` |
| `PUT /v1/retrato` | `Exigencia(escopos=("retrato-enviar", "backup"), tipos=("pc",))` |

`ROTEADORES` (`ayanami/api/app.py`) ganha `"app_android"` e `"retrato"` (módulos novos
`ayanami/api/app_android.py`, `ayanami/api/retrato.py`, cada um com `router`). Limite geral 60/min não
conta `/v1/app/apk` nem `/v1/retrato/pacote|modelos`; esses têm limite próprio de 6/h por dispositivo
(`429` `Retry-After`) — `Range` de um mesmo download conta 1 (mesmo `If-Range`/ETag em 10 min).

### 9.2 `/v1/app/*` (`ayanami/api/app_android.py`)

Diretório `[app] dir` do `ayanami.toml` (padrão `/dados/app`): `versao.json` + `condessa-<vc>.apk`.

| Rota | Respostas |
| --- | --- |
| `GET /v1/app/versao` | `200` `versao.json` (§7: `versionCode`, `versionName`, `sha256`, `bytes`, `minimo`, `notas`, `publicado`, `cert_sha256`), `Cache-Control: no-cache`; `404` `{"erro":"sem_versao"}`; `500` `versao_invalida` se o JSON não valida (chaves, tipos, sha 64 hex, arquivo existe com `bytes` certo) |
| `GET /v1/app/apk` | `200`/`206` `application/vnd.android.package-archive`, `ETag: "<sha256>"`, `Accept-Ranges: bytes`, `Content-Disposition: attachment; filename="condessa-<vc>.apk"`; `Range: bytes=a-` / `a-b`; `If-Range` ≠ ETag → `200` inteiro; faixa inválida → `416`; `404` `sem_versao` |

Auditoria `tipo="app"`, `resumo="apk baixado"` + bytes (sem IP). `/saude` ganha `"app":{"versao":
versionCode|null}`.

### 9.3 `/v1/retrato*` (`ayanami/api/retrato.py`, `ayanami/retrato.py`, job)

| Rota | Corpo | Respostas |
| --- | --- | --- |
| `PUT /v1/retrato` | binário `.tar.zst` (≤ 200 MiB, streaming para `/dados/retrato/entrada/`), `X-Sha256` | `202` `{"versao":<sha>,"job":id}`; `400` sha não confere (apaga); `413`; `422` `tar_invalido` (falta `portrait.toml`/`parts/`, caminho absoluto ou `..`, link simbólico, arquivo fora de `parts/ eyes/ mouth/ wakeword/ portrait.toml satellite.toml`); `409` `mesma_versao` se já existe e íntegra |
| `GET /v1/retrato/versao` | — | `200` `{"versao","lados":[512,768],"pacotes":{"512":{"sha256","bytes"},"768":{…}},"modelos":{"sha256","bytes"}\|null,"gerando":bool}`; `404` `sem_retrato` |
| `GET /v1/retrato/pacote?lado=512\|768` | — | `200`/`206` `application/zip`, `ETag`, `Range` como o APK; `409` `gerando`; `404`; `422` lado inválido |
| `GET /v1/retrato/modelos` | — | idem, `application/zip` |

- Armazenamento `/dados/retrato/<versao>/` (`original.tar.zst`, `pacote-512.zip`, `pacote-768.zip`,
  `modelos.zip`, `ok`); mantém só a versão atual e a anterior. Ponteiro `/dados/retrato/atual`.
- Job novo `retrato.gerar` na fila `lenta` (`Def("retrato.gerar","lenta", 15*60, 1, lock="retrato")`):
  extrai com `tarfile` (filtro `data`), lê `portrait.toml` e a ordem de camadas de
  `hud.wired.portrait` **não** (a imagem da Ayanami não tem o HUD): a ordem e os grupos ficam em
  `ayanami/retrato.py` como constante `ORDEM_PINTURA` copiada do `PARTS_ORDER`/R1.1, com teste que
  compara com o `portrait.py` do repo; compõe com Pillow (`Image.alpha_composite`), reduz com
  `LANCZOS`, recorta olhos/bocas pela `getbbox()` do alfa, salva WebP q 90 `method=6`, monta o zip
  `STORED` e o manifesto da §4.1; grava `ok` por último. Erro → evento `operacao` "retrato falhou".
- Pillow com WebP: já é dependência do extra `ayanami`? A Y-tarefa confere (`uv run python -c
  "from PIL import features; print(features.check('webp'))"`); faltando, anota em *Sobras* (não
  roda `uv sync`/`uv lock` sem o Pedro).
- Auditoria do `PUT` (`tipo="retrato"`, bytes). `/saude` ganha `"retrato":{"versao":sha12|null}`.
- Nada disto entra no restic: `/dados/retrato` e `/dados/app` são regeneráveis (o PC tem a arte, o CI
  o APK); a tarefa só verifica que o backup não varre `/dados` inteiro e anota em *Sobras* se varrer
  (o `ayanami/workers/backup.py` tem mudança local do Pedro: não editar).

### 9.4 `POST /v1/turno` aceita Ogg Opus (D7a)

`ayanami/api/turno.py`: `MIME_AUDIO` vira o conjunto `{"audio/webm", "audio/ogg"}`; o `415` passa a
dizer "áudio só em audio/webm ou audio/ogg (opus)". `Conversor.webm_para_pcm` já usa `ffmpeg`
(`-i pipe:` detecta o contêiner): renomeia para `audio_para_pcm` com alias `webm_para_pcm` mantido;
o `mime` segue até o STT da nuvem (`escuta.transcrever(dados, mime)`). Limites iguais (1 MiB, 15 s).

### 9.5 SSE `turno.ouvido` (D9a, DSC5)

- `magi/elo/mensagens.py`: `TurnoFim.ouvido: str = ""` (≤ 1000 caracteres; `schema.py` atualizado;
  campo desconhecido segue ignorado nos dois lados).
- `magi/elo/ponte.py`: o `TurnPipeline` do celular guarda o texto do `transcribe` e o põe em
  `TurnoFim.ouvido` (turno de texto → vazio).
- `ayanami/turnos.py`: `publicar(dono, "turno.ouvido", {"turno","texto"})` (a) no modo nuvem e no PC
  por long-poll, logo depois do STT local; (b) no modo PC, ao receber `TurnoFim` com `ouvido`, antes
  do `turno.texto`. Nunca vazio, nunca para turno de texto; não vai a log (só tamanho).
- O PWA ignora o evento (nome desconhecido) — sem mudança.

### 9.6 Push `unifiedpush`

- Migração `ayanami/migrations/003_push_tipo.sql`: `ALTER TABLE push_assinaturas ADD COLUMN tipo text
  NOT NULL DEFAULT 'webpush' CHECK (tipo IN ('webpush','unifiedpush'))`.
- `ayanami/api/push.py`: `Assinar.tipo: Literal["webpush","unifiedpush"] = "webpush"`; com
  `unifiedpush`, o host do `endpoint` tem de estar em `[push] ntfy_hosts` (lista no `ayanami.toml`,
  padrão vazia) senão `422` `endpoint_proibido`. Grava o `tipo`.
- `ayanami/push.py`: `Assinatura` ganha `tipo`; envio igual (`pywebpush`, mesmo payload, mesmas
  regras de silêncio/limite/410). Única diferença: `unifiedpush` usa `ttl` mínimo de 60 s (o ntfy
  descarta TTL 0) e não manda `Topic` com mais de 32 caracteres. `ayanami/config.py`: `[push]
  ntfy_hosts: tuple[str, ...] = ()` (cada item `host[:porta]`, sem esquema).

**Aceite.**
- **CA-M27** `ESCOPO_DE_ROTA` (teste existente percorre a tabela): as 6 linhas novas; celular antigo
  (só `conversa`) lê `/v1/retrato/versao`; `PUT /v1/retrato` com `celular` → 403 `tipo_proibido`, com
  `pc` só `backup` → aceito.
- **CA-M28** `/v1/app/versao`: 404 sem arquivo; 200 com o JSON; 500 `versao_invalida` com sha errado
  no JSON. `/v1/app/apk`: `200` inteiro, `206` com `Range: bytes=10-19` (10 bytes, `Content-Range`
  certo), `416` fora, `If-Range` velho → 200; 7º download/h → 429; não conta no 60/min.
- **CA-M29** `PUT /v1/retrato` (`pg`): tar com `..` / link / arquivo estranho → 422 e nada fica; sha
  errado → 400; certo → 202 + job `retrato.gerar` enfileirado (`InMemoryConnector`); mesma versão → 409.
- **CA-M30** Job `retrato.gerar` com arte sintética (PNGs 1024² gerados no teste com Pillow, alfa):
  zip 512 e 768 `STORED`, manifesto válido com ordem = `ORDEM_PINTURA`, olhos/bocas recortados
  (w,h < lado), sha256 do manifesto conferem, `ok` gravado por último; zip acima do teto →
  `retrato_grande`; `ORDEM_PINTURA` bate com `PARTS_ORDER` + extras de `hud/wired/portrait.py`
  (leitura textual com `ast`, sem importar Qt).
- **CA-M31** `GET /v1/retrato/pacote`: `409` com `gerando`, `206` com `Range`, `422` lado 1024.
- **CA-M32** `POST /v1/turno` com `audio/ogg;codecs=opus` (fixture da CA-M14) → 202 e o `Conversor`
  falso recebe os bytes; `audio/mp4` → 415; webm continua (testes existentes verdes).
- **CA-M33** `turno.ouvido`: modo nuvem publica antes de `turno.texto`; modo PC com `TurnoFim.ouvido`
  publica antes de `turno.texto`; turno de texto não publica; `TurnoFim` sem `ouvido` (PC antigo)
  decodifica; `tests/elo` verdes; ponte do PC preenche `ouvido` com o texto do STT falso.
- **CA-M34** Push `unifiedpush` (`pg`): `POST /v1/push/assinar` com host fora de `ntfy_hosts` → 422;
  dentro → 201 com `tipo` gravado; envio com `webpush` falso usa o mesmo payload e TTL ≥ 60; 410 apaga;
  assinatura `webpush` existente sem a coluna (migração) segue `webpush`. `/saude` com `app` e
  `retrato` e sem chaves proibidas (CA-Y9 estendido).

## 10. ntfy no Compose

Serviço novo em `deploy/ayanami/compose.yml` (o node 2 inteiro é da Ayanami desde 2026-10-28):

```yaml
  ntfy:
    image: binwiederhier/ntfy:v2.14.0        # (S0/S3) fixar a tag estável do dia
    command: ["serve"]
    restart: unless-stopped
    ports: ["127.0.0.1:8742:80"]
    volumes: ["./ntfy:/etc/ntfy:ro", "ntfy-cache:/var/cache/ntfy", "ntfy-auth:/var/lib/ntfy"]
    environment: {TZ: America/Sao_Paulo}
    cpus: 0.5
    mem_limit: 128m
    healthcheck: {test: ["CMD", "wget", "-qO-", "http://localhost/v1/health"]}
    networks: [ayanami]
    logging: *logs
```

`deploy/ayanami/ntfy/server.yml` (versionado, sem segredo):
`base-url: "https://<host do tailnet>:8443"` vem de `NTFY_BASE_URL` (env, no `.env`; o arquivo traz
placeholder `https://ayanami.exemplo.ts.net:8443`), `listen-http: ":80"`, `behind-proxy: true`,
`cache-file: /var/cache/ntfy/cache.db`, `cache-duration: "12h"`, `auth-file: /var/lib/ntfy/user.db`,
`auth-default-access: deny-all`, `enable-signup: false`, `enable-login: false`, `web-root: disable`,
`visitor-request-limit-burst: 60`. ACL (DSC6) aplicada pelo runbook com `docker compose exec ntfy ntfy
access everyone 'up*' write-only` e `ntfy user add celular` + `ntfy access celular 'up*' read-only`
(senha digitada pelo Pedro). `deploy/ayanami/host/tailscale.sh` ganha `tailscale serve --bg
--https=8443 http://127.0.0.1:8742`. `compose.node2.yml` ganha `ntfy: {cpuset: "0-7"}` só se o perfil
enxuto continuar em uso (a tarefa de infra da Ayanami decide; aqui não se mexe nos limites dos outros).
`ayanami.example.toml` `[push] ntfy_hosts = ["ayanami.exemplo.ts.net:8443"]`. Runbook
`docs/ayanami/runbook.md` ganha a seção "ntfy" (acrescentar no fim).

**Aceite.**
- **CA-M35** Teste estático do compose (CA-Y29 estendido): `ntfy` publica só `127.0.0.1:8742`, tem
  `restart`, `mem_limit`, `cpus`, `healthcheck`, não monta `.env` nem `docker.sock`; `server.yml`
  carregado tem `auth-default-access: deny-all`, `enable-signup: false` e nenhum host real (regex de
  `.ts.net` só com `exemplo`).

## 11. CI do APK (`.github/workflows/android.yml`)

```yaml
on:
  push: {tags: ["android-v*"]}
  pull_request: {paths: ["android/**", ".github/workflows/android.yml"]}
  push (branches main, paths android/**)   # build + testes, sem assinar
jobs:
  testar:  # ubuntu-latest, timeout 30 min
    - actions/checkout@v4; actions/setup-java@v4 (temurin 21); gradle/actions/setup-gradle@v4
    - android-actions/setup-android@v3 (sdk 36, build-tools 36.0.0)   # (S0) versões
    - ./gradlew --no-daemon :retrato:test :voz:test :rede:test :app:testDebugUnitTest lintDebug
  publicar:  # só tag android-v*, needs testar, environment "android-release", concurrency android-publicar
    - vc = github.run_number + 1000; vn = tag sem "android-v"
    - echo "$ANDROID_KEYSTORE_B64" | base64 -d > "$RUNNER_TEMP/k.jks"   (umask 077)
    - ./gradlew :app:assembleRelease -Pvc=$vc -Pvn=$vn  (env CONDESSA_KEYSTORE=$RUNNER_TEMP/k.jks …)
    - apksigner verify --print-certs → cert_sha256; tamanho ≤ 25 MB senão falha
    - versao.json (python3 -c …: versionCode, versionName, sha256, bytes, minimo = vars.ANDROID_MINIMO ou vc, notas = corpo da tag, publicado, cert_sha256)
    - ssh -i chave AYANAMI_USER@AYANAMI_HOST "app $vc $sha $(base64 -w0 versao.json | tr '+/' '-_' | tr -d '=')" < app-release.apk
    - rm -f k.jks chave (if: always())
```

- Secrets novos: `ANDROID_KEYSTORE_B64`, `ANDROID_KEYSTORE_SENHA`, `ANDROID_KEY_ALIAS`,
  `ANDROID_KEY_SENHA`; reaproveita `AYANAMI_HOST`, `AYANAMI_USER`, `AYANAMI_SSH_KEY` (mesma chave
  restrita). `known_hosts`: secret opcional `AYANAMI_KNOWN_HOSTS`; ausente → `StrictHostKeyChecking=
  accept-new` (mesma pendência de *fingerprint* da Y0.7/Y1.4).
- Nenhum `actions/upload-artifact` com APK; logs sem host (secrets mascarados; o passo não ecoa a URL).
- `deploy/ayanami/host/ci-deploy.sh`, verbo novo (DSC7): `app <vc 1..9 dígitos> <sha 64 hex>
  <b64url ≤ 4096>` → lê no máx. 30 MiB do stdin para `$AYANAMI_DIR/dados/app/.tmp-<vc>.apk`, confere
  sha256 e tamanho, valida o JSON (python3: chaves da §7, `versionCode`=vc, `sha256`=sha, `bytes`
  = tamanho, `versionCode` > o publicado) → `mv` atômico do APK, depois do `versao.json`; mantém os 3
  APKs mais novos; `flock` próprio (`app.lock`). Qualquer falha apaga o `.tmp` e sai 2 com
  "recusado: …". O verbo `deploy`/`saude` não muda.

**Aceite.**
- **CA-M36** `tests/deploy/test_ci_deploy_app.py` (bash real do script com `AYANAMI_DIR=tmp_path`,
  sem rede): APK + JSON certos → arquivos no lugar e 3 mais novos mantidos; sha errado, vc não maior,
  JSON com chave faltando, argumento extra, stdin > 30 MiB → recusado sem resto em `dados/app/`;
  `deploy`/`saude` seguem recusando o que recusavam.
- **CA-M37** Teste estático do `android.yml` (YAML carregado): `publicar` só em tag e com `needs:
  testar`; nenhum `upload-artifact`; keystore apagado em passo `if: always()`; nenhum literal
  `.ts.net`, IP ou chave.

## 12. Comando do PC `magi-retrato`

`magi/elo/retrato.py` + `pyproject.toml` `[project.scripts] magi-retrato = "magi.elo.retrato:main"`.
`magi-retrato enviar [--dir ~/.local/share/magi/condessa] [--modelos ~/.local/share/magi/models/wakeword]`:
monta em `$TMP` um `tar` com `portrait.toml`, `parts/`, `eyes/`, `mouth/`, `wakeword/{condessa,
melspectrogram,embedding_model,silero_vad}.onnx` (os que existirem) e `satellite.toml` (só `wake_threshold`,
`wake_patience`, `wake_gate_dbfs` do `config.toml`), `zstd -10`, `PUT /v1/retrato` com `X-Sha256`
(mesmo cliente/credenciais do `magi-backup`: `magi.elo.credenciais`, `[ayanami] url`); `409` → "já
enviado"; apaga o `$TMP` sempre. `magi-retrato estado` → `GET /v1/retrato/versao` (precisa de escopo
`retrato`/`conversa`: o `pc` tem `conversa`).

**Aceite.**
- **CA-M38** `tests/elo/test_retrato_cli.py`: tar contém só os caminhos permitidos (nada de `*.token`,
  `config.toml` inteiro, links); sha256 do cabeçalho = do corpo; 409 → sai 0; 401 → sai 1 com frase;
  `$TMP` apagado (cliente HTTP falso, `tmp_path` como `~/.local/share`).

## 13. Ayanami falsa e utilitários de teste

- `android/rede/src/testFixtures/…/AyanamiFalsa.kt`: `MockWebServer` com `Dispatcher` que responde às
  rotas da §9 e Ayanami §2.2 usadas pelo app (pareamento, turno, SSE roteirizado, áudio ogg da
  fixture, casa, feed, tarefas, servidor, push, app, retrato), conta chamadas e injeta falhas
  (status, atraso, corte no meio para `Range`). Usada por `:rede`, `:retrato` e `:app` (`testFixtures`).
- Relógio: `fun interface Relogio { fun agoraMs(): Long }` em `:rede` `logica`; `RelogioFalso`.
- Fixtures geradas por script Python versionado (`scripts/retrato_sequencia.py`,
  `scripts/gerar_vetor_webpush.py`), nunca arte real.

**Aceite.**
- **CA-M39** `AyanamiFalsa` cobre todas as rotas de `ClienteAyanami` (teste que chama cada método e
  confere 2xx) e o contrato dos corpos é o da spec (desserialização estrita de `TurnoFim`, `CasaEstado`,
  `TarefaOut`, `VersaoApp`, `RetratoVersao` com campo extra ignorado).

## 14. Spikes e validação ao vivo (precisam do celular)

| Spike | Tarefa | Saída gravada | Critério |
| --- | --- | --- | --- |
| S0 esqueleto e instalação | A0.2 (versões, PC) + F.1 (celular) | `libs.versions.toml`, `docs/spikes/condessa-celular-s0.md` (minSdk final, 1ª instalação, 2ª silenciosa?) | APK vazio ≤ 8 MB |
| S1 wake word no ORT | F.3 | nota ± 0,02 vs PC em 10 gravações; ms/bloco; %/h | critério 5 |
| S2 botão BT | F.3 | caminho que funciona (MediaSession × VOICE_COMMAND), SCO 16 kHz | cenário 1 |
| S3 ntfy + Doze | F.2 | entrega ≤ 30 s tela desligada; consumo | R7.1 |
| S4 retrato fps/memória | F.3 | fps p95, PSS, lado padrão | critérios 2, RNF-C3 |
| S5 latência 4G | F.4 | p50/p90 por cenário | critério 1 |

Validação final (F.4): critérios de sucesso 1–8 com número medido (design §11). Ferramentas de
medição já no app: anel de latência + tela Diagnóstico (A6.x), `JankStats` em debug.

**Aceite (ao vivo, não automatizado).**
- **CA-M40** S0: instalação lateral pelo navegador com o Tailscale ligado; 1ª atualização pede um
  toque; registrada a 2ª.
- **CA-M41** S1–S2: números na nota; decisão do limiar no celular.
- **CA-M42** S3: 10 pushes com a tela desligada, ≥ 9 em ≤ 30 s.
- **CA-M43** S4: fps e memória medidos; lado padrão decidido.
- **CA-M44** F.4: os 8 critérios de sucesso medidos ou com decisão do Pedro.
