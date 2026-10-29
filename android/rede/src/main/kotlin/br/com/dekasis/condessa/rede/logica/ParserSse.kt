package br.com.dekasis.condessa.rede.logica

import kotlinx.coroutines.flow.Flow

data class EventoSse(val nome: String, val id: String?, val dados: String)

/** `SseCliente` implementa; reconecta 1→30 s com `Last-Event-ID`. dono: A1.2. */
interface FonteEventos {
    fun eventos(ultimoId: String?): Flow<EventoSse>
}
