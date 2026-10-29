package br.com.dekasis.condessa.retrato.logica

import java.util.Random

/** Nomes do `[states]` do `portrait.toml`. */
enum class EstadoRetrato { SLEEPING, IDLE, LISTENING, THINKING, SPEAKING }

data class Quadro(val olhos: String, val boca: String, val dyRespiracao: Float, val acordada: Boolean)

/** Porta de `hud/wired/portrait.py` (puro). dono: A2.1. */
class Animador(private val cfg: PortraitToml, private val rng: Random) {
    fun quadro(estado: EstadoRetrato, nivel: Float, agoraS: Double): Quadro =
        TODO("dono: A2.1 ($cfg $rng $estado $nivel $agoraS)")

    /** 60 / 30 / 8. */
    fun fpsAlvo(estado: EstadoRetrato, piscando: Boolean): Int = TODO("dono: A2.1 ($estado $piscando)")
}
