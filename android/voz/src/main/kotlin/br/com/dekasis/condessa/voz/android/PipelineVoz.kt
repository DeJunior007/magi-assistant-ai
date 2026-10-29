package br.com.dekasis.condessa.voz.android

import br.com.dekasis.condessa.voz.logica.Gatilho
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow

/** Eventos da voz (spec §2). dono: A3.2. */
sealed interface EventoVoz {
    data object WakeDetectado : EventoVoz
    data object FimDeFala : EventoVoz
    data object Cancelado : EventoVoz
    data object AudioComecou : EventoVoz
    data object AudioAcabou : EventoVoz
}

/** `PipelineVozReal` implementa (A3.2). */
interface PipelineVoz {
    /** 0..1, já atrasado pela latência de saída (design §3.1). */
    val nivelSaida: StateFlow<Float>
    val eventos: SharedFlow<EventoVoz>
    /** Wake word com o app aberto (R2.2). */
    fun ligarEscuta(ligada: Boolean)
    /** Ogg Opus, ou null (< 400 ms/cancelado). */
    suspend fun gravarTurno(origem: Gatilho, rota: RotaAudio.Saida): ByteArray?
    fun soltar()
    fun cancelar()
    fun tocar(url: String, cabecalhos: Map<String, String>)
    fun pararFala()
}
