package br.com.dekasis.condessa

import android.content.Context
import br.com.dekasis.condessa.estado.MaquinaCondessa

/**
 * DI manual (design §2): dependências criadas uma vez; testes montam um `Grafo` falso.
 * dono: A0.2 (esqueleto); cada tarefa acrescenta o seu campo sem mudar o construtor.
 */
open class Grafo(val contexto: Context, val relogio: () -> Long = System::currentTimeMillis) {
    open val maquina: MaquinaCondessa by lazy { MaquinaCondessa(relogio) }
}
