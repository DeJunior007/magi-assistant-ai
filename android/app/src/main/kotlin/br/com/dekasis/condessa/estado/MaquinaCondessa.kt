package br.com.dekasis.condessa.estado

import br.com.dekasis.condessa.rede.logica.Conexao
import br.com.dekasis.condessa.voz.logica.Gatilho
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

// Contratos da spec §2 (`:app estado/`, puro). dono: A4.1.
// `Gatilho` vive em `:voz` e `Conexao` em `:rede` (o `:app` depende deles; o contrário faria ciclo).

enum class EstadoCondessa { DORMINDO, OUVINDO, PENSANDO, FALANDO }

enum class Modo { PC, NUVEM, DESCONHECIDO }

/** Faixa da tela A (spec §3.3). dono: A4.1. */
data class Faixa(val texto: String, val acao: String? = null)

/** Entrada da máquina (design §3). */
sealed interface Evento {
    data class Acordar(val gatilho: Gatilho) : Evento
    data object Soltar : Evento
    data object Cancelar : Evento
    data class Aceito(val turno: String, val modo: Modo) : Evento
    data class Ouvido(val turno: String, val texto: String) : Evento
    data class Texto(val turno: String, val texto: String) : Evento
    data class Fim(val turno: String, val ok: Boolean, val audio: Boolean, val erro: String?) : Evento
    data object AudioComecou : Evento
    data object AudioAcabou : Evento
    data class Erro(val frase: String) : Evento
    data class Tique(val agoraMs: Long) : Evento
}

data class UiEstado(
    val condessa: EstadoCondessa,
    val turno: String?,
    val modo: Modo,
    val conexao: Conexao,
    val legenda: String,
    val falaPedro: String,
    val faixa: Faixa?,
    val bloqueioUpdate: Boolean,
)

/** Máquina da Condessa: única porta [tratar]; pura, testável sem Android. dono: A4.1. */
class MaquinaCondessa(private val relogio: () -> Long) {
    private val _estado = MutableStateFlow(
        UiEstado(EstadoCondessa.DORMINDO, null, Modo.DESCONHECIDO, Conexao.OK, "", "", null, false),
    )
    val estado: StateFlow<UiEstado> = _estado.asStateFlow()

    fun tratar(e: Evento) {
        TODO("dono: A4.1 ($e em ${relogio()})")
    }
}
