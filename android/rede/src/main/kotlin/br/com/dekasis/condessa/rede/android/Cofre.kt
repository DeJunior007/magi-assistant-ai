package br.com.dekasis.condessa.rede.android

/** AES-256-GCM no AndroidKeyStore, `noBackupFilesDir/cofre.bin` (spec §8.1). dono: A1.1. */
interface Cofre {
    fun ler(chave: String): String?
    fun gravar(chave: String, valor: String)
    fun apagar()
}
