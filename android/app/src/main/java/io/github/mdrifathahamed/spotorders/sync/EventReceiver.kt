package io.github.mdrifathahamed.spotorders.sync

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import io.github.mdrifathahamed.spotorders.data.EventType
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

/** Handles the "Got order" / "Free again" buttons in the notification, without opening the app. */
class EventReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val type = when (intent.action) {
            ACTION_OFFER -> EventType.OFFER
            ACTION_FREE -> EventType.FREE
            else -> return
        }
        val pending = goAsync()
        CoroutineScope(Dispatchers.IO).launch {
            try {
                EventRecorder.record(context.applicationContext, type)
            } finally {
                pending.finish()
            }
        }
    }

    companion object {
        const val ACTION_OFFER = "io.github.mdrifathahamed.spotorders.OFFER"
        const val ACTION_FREE = "io.github.mdrifathahamed.spotorders.FREE"
    }
}
