package br.com.dekasis.condessa

import android.app.Application

/** Application: cria o [Grafo] uma vez (spec §1, sem Hilt/Koin). */
class App : Application() {
    lateinit var grafo: Grafo
        private set

    override fun onCreate() {
        super.onCreate()
        grafo = Grafo(this)
    }
}
