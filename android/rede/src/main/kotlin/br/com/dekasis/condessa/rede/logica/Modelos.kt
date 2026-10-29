package br.com.dekasis.condessa.rede.logica

import java.io.File
import kotlinx.serialization.json.JsonObject

// Contratos da spec §2 (`:rede`). Os modelos nascem vazios; dono: A1.1 (campos), sem mudar os nomes.

class Saude
class Pareado
class TurnoAceito
class CasaEstado
class AcaoPedido
class AcaoResultado
class Card
class TarefaOut
class Preferencias
class RetratoVersao

data class VersaoApp(
    val versionCode: Int,
    val versionName: String,
    val sha256: String,
    val bytes: Long,
    val minimo: Int,
    val notas: String,
    val publicado: String,
    val certSha256: String,
)

/** R9.5: toda falha vira frase pt-BR. */
sealed class ErroAyanami(val frase: String) : Exception(frase) {
    /** 401 → apaga o token. */
    class NaoAutorizado : ErroAyanami("O aparelho saiu da Ayanami; pareie de novo.")
    class Http(val status: Int, val codigo: String, frase: String) : ErroAyanami(frase)
    class SemConexao(val tipo: Conexao) : ErroAyanami("Sem conexão com a Ayanami.")
}

/** `ApiAyanami` implementa (A1.1). */
interface ClienteAyanami {
    /** Timeout 4 s. */
    suspend fun saude(): Saude
    suspend fun trocarCodigo(base: String, codigo: String, nome: String): Pareado
    suspend fun turnoTexto(texto: String): TurnoAceito
    /** `audio/ogg;codecs=opus`. */
    suspend fun turnoAudio(ogg: ByteArray): TurnoAceito
    /** ExoPlayer + OkHttpDataSource. */
    fun urlAudio(turno: String): String
    suspend fun confirmar(pedido: String, resposta: Boolean)
    suspend fun casaEstado(): CasaEstado
    suspend fun casaAcao(tv: String?, pedido: AcaoPedido): AcaoResultado
    suspend fun feed(antes: String?, n: Int = 30): List<Card>
    suspend fun tarefas(estado: String? = null): List<TarefaOut>
    suspend fun cancelarTarefa(id: String)
    suspend fun servidor(): JsonObject
    suspend fun preferencias(p: Preferencias)
    suspend fun sair()
    suspend fun assinarPush(endpoint: String, p256dh: String, auth: String)
    /** 404 → null. */
    suspend fun appVersao(): VersaoApp?
    /** Com `Range`. */
    suspend fun baixarApk(destino: File, aPartirDe: Long): Long
    suspend fun retratoVersao(): RetratoVersao?
    suspend fun baixarRetrato(lado: Int, destino: File, aPartirDe: Long): Long
    suspend fun baixarModelos(destino: File): Long
}
