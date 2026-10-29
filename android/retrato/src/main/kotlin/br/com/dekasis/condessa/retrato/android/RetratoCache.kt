package br.com.dekasis.condessa.retrato.android

import br.com.dekasis.condessa.retrato.logica.ResultadoRetrato
import br.com.dekasis.condessa.retrato.logica.RetratoFonte
import br.com.dekasis.condessa.retrato.logica.RetratoPacote

/** Download/verificação do pacote (spec §4.2). dono: A2.2. */
class RetratoCache : RetratoFonte {
    override suspend fun atual(): RetratoPacote? = null
    override suspend fun atualizar(permitirMovel: Boolean): ResultadoRetrato = TODO("dono: A2.2 ($permitirMovel)")
}
