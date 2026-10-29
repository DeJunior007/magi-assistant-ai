package br.com.dekasis.condessa

import java.io.File
import javax.xml.parsers.DocumentBuilderFactory
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.w3c.dom.Element

/** CA-M2: manifesto mesclado do debug (`:app:processDebugMainManifest`). */
class ManifestoTest {
    private val ns = "http://schemas.android.com/apk/res/android"
    private val manifesto: Element by lazy {
        val caminho = System.getProperty("condessa.manifesto") ?: error("sem condessa.manifesto")
        val f = DocumentBuilderFactory.newInstance().apply { isNamespaceAware = true }
        f.newDocumentBuilder().parse(File(caminho)).documentElement
    }

    private fun filhos(nome: String) = manifesto.getElementsByTagName(nome).let { l ->
        (0 until l.length).map { l.item(it) as Element }
    }

    @Test
    fun permissoesSaoExatamenteAsDoR105() {
        val esperadas = setOf(
            "INTERNET", "RECORD_AUDIO", "POST_NOTIFICATIONS", "BLUETOOTH_CONNECT", "FOREGROUND_SERVICE",
            "FOREGROUND_SERVICE_MICROPHONE", "FOREGROUND_SERVICE_MEDIA_PLAYBACK", "REQUEST_INSTALL_PACKAGES",
            "WAKE_LOCK", "ACCESS_NETWORK_STATE",
        ).map { "android.permission.$it" }.toSet()
        // A permissão de assinatura que o androidx.core declara para o próprio app não é pedido ao usuário.
        val propria = "br.com.dekasis.condessa.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION"
        val pedidas = filhos("uses-permission").map { it.getAttributeNS(ns, "name") }.toSet() - propria
        assertEquals(esperadas, pedidas)
        assertFalse("android.permission.RECEIVE_BOOT_COMPLETED" in pedidas)
    }

    @Test
    fun semBackupESoHttps() {
        val app = filhos("application").single()
        assertEquals("false", app.getAttributeNS(ns, "allowBackup"))
        assertTrue(app.getAttributeNS(ns, "dataExtractionRules").isNotEmpty())
        assertTrue(app.getAttributeNS(ns, "usesCleartextTraffic") in setOf("", "false"))
        assertTrue(app.getAttributeNS(ns, "networkSecurityConfig").isNotEmpty())
        val res = File("src/main/res/xml")
        val nsc = File(res, "network_security_config.xml").readText()
        assertTrue(nsc.contains("cleartextTrafficPermitted=\"false\""))
        assertFalse(nsc.contains("cleartextTrafficPermitted=\"true\""))
        // Regras de extração "vazias": nada sai do aparelho (só exclude, nenhum include).
        val regras = File(res, "regras_extracao.xml").readText()
        assertFalse(regras.contains("<include"))
    }

    @Test
    fun voiceCommandEServicos() {
        val acoes = filhos("action").map { it.getAttributeNS(ns, "name") }
        assertTrue("android.intent.action.VOICE_COMMAND" in acoes)
        val servicos = filhos("service").associate { it.getAttributeNS(ns, "name") to it }
        assertTrue("br.com.dekasis.condessa.voz.android.SessaoMidia" in servicos)
        assertTrue("br.com.dekasis.condessa.push.ReceptorPush" in servicos)
        assertEquals("false", servicos.getValue("br.com.dekasis.condessa.escuta.EscutaService").getAttributeNS(ns, "enabled"))
        assertTrue(filhos("provider").none { it.getAttributeNS(ns, "name").endsWith("FileProvider") })
    }
}
