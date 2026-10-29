package br.com.dekasis.condessa.push

import org.unifiedpush.android.connector.FailedReason
import org.unifiedpush.android.connector.PushService
import org.unifiedpush.android.connector.data.PushEndpoint
import org.unifiedpush.android.connector.data.PushMessage

/** Recebe o Web Push via distribuidor UnifiedPush (spec §6). dono: A6.1. */
class ReceptorPush : PushService() {
    override fun onMessage(message: PushMessage, instance: String) = Unit
    override fun onNewEndpoint(endpoint: PushEndpoint, instance: String) = Unit
    override fun onRegistrationFailed(reason: FailedReason, instance: String) = Unit
    override fun onUnregistered(instance: String) = Unit
}
