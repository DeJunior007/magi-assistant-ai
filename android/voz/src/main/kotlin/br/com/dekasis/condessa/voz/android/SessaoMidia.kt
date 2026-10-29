package br.com.dekasis.condessa.voz.android

import androidx.media3.session.MediaSession
import androidx.media3.session.MediaSessionService

/** Media3: botão BT e FGS `mediaPlayback` (spec §5.4). dono: A3.3. */
class SessaoMidia : MediaSessionService() {
    override fun onGetSession(controllerInfo: MediaSession.ControllerInfo): MediaSession? = null
}
