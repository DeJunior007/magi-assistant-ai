package br.com.dekasis.condessa.voz.logica

/** O que acordou a Condessa (spec §2). Vive no `:voz` porque [PipelineVoz] o usa e o `:app` depende do `:voz`. */
enum class Gatilho { SEGURAR, WAKE, BOTAO_BT, VOICE_COMMAND, TEXTO }
