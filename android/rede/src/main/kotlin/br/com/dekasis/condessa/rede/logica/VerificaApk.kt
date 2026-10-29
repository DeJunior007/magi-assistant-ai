package br.com.dekasis.condessa.rede.logica

import java.io.File

/** Puro (spec §7). dono: A5.1. */
object VerificaApk {
    enum class Resultado { OK, SHA, CERT, PACOTE, VERSAO }

    fun sha256Hex(f: File): String = TODO("dono: A5.1 ($f)")

    fun confere(
        v: VersaoApp,
        shaArquivo: String,
        certsApk: List<String>,
        pacoteApk: String,
        certsInstalado: List<String>,
        pacoteInstalado: String,
    ): Resultado = TODO("dono: A5.1 ($v $shaArquivo $certsApk $pacoteApk $certsInstalado $pacoteInstalado)")
}
