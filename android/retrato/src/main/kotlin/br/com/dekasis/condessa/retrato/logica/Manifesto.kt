package br.com.dekasis.condessa.retrato.logica

import java.io.File

/** `manifesto.json` do pacote do retrato (spec §4.1). dono: A2.1. */
data class Manifesto(val versao: String, val arquivos: Map<String, String>)

data class RetratoPacote(val versao: String, val lado: Int, val manifesto: Manifesto, val dir: File)

enum class ResultadoRetrato { ATUAL, BAIXADO, SEM_ARTE, ERRO }

/** `RetratoCache` implementa (A2.2). */
interface RetratoFonte {
    /** null → placeholder (R1.5). */
    suspend fun atual(): RetratoPacote?
    suspend fun atualizar(permitirMovel: Boolean): ResultadoRetrato
}
