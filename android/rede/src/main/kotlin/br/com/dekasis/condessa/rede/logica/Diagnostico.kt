package br.com.dekasis.condessa.rede.logica

/** Estado da conexão (spec §2). Vive no `:rede` porque [ErroAyanami] o usa. dono: A1.2. */
enum class Conexao { OK, SEM_REDE, SEM_TAILSCALE, AYANAMI_FORA, CASA_FORA /* só p/ TV */ }
