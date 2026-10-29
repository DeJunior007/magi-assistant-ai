package br.com.dekasis.condessa.rede.android

import br.com.dekasis.condessa.rede.logica.VersaoApp
import java.io.File

/** NADA | DISPONIVEL(v) | OBRIGATORIA(v) (minimo > atual). dono: A5.1. */
sealed interface EstadoUpdate {
    data object Nada : EstadoUpdate
    data class Disponivel(val v: VersaoApp) : EstadoUpdate
    data class Obrigatoria(val v: VersaoApp) : EstadoUpdate
}

/** dono: A5.1. */
interface Atualizador {
    suspend fun verificar(): EstadoUpdate
    /** sha256 + cert + pacote; falha → apaga e lança. */
    suspend fun baixarEConferir(v: VersaoApp): File
    /** Só com a `MaquinaCondessa` em DORMINDO (R8.5). */
    suspend fun instalar(apk: File)
}
