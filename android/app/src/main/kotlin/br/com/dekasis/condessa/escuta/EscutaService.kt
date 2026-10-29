package br.com.dekasis.condessa.escuta

import android.app.Service
import android.content.Intent
import android.os.IBinder

/** Escuta com o app fechado (L, R2.4): desabilitada no manifesto do MVP. */
class EscutaService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null
}
