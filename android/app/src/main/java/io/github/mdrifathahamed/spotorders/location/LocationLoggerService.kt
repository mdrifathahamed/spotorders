package io.github.mdrifathahamed.spotorders.location

import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.Looper
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import com.google.android.gms.location.LocationCallback
import com.google.android.gms.location.LocationRequest
import com.google.android.gms.location.LocationResult
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import io.github.mdrifathahamed.spotorders.MainActivity
import io.github.mdrifathahamed.spotorders.data.AppDb
import io.github.mdrifathahamed.spotorders.data.EventType
import io.github.mdrifathahamed.spotorders.data.Fix
import io.github.mdrifathahamed.spotorders.overlay.FloatingButtons
import io.github.mdrifathahamed.spotorders.sync.EventReceiver
import io.github.mdrifathahamed.spotorders.sync.SyncWorker
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/**
 * Foreground service: records a GPS fix every 15 s (or 20 m) during a shift and shows a
 * notification with "Got order" / "Free again" buttons, so the app never needs to be opened.
 * Uploads the GPS track to GitHub every 15 minutes.
 */
class LocationLoggerService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var started = false
    private val client by lazy { LocationServices.getFusedLocationProviderClient(this) }

    private val callback = object : LocationCallback() {
        override fun onLocationResult(result: LocationResult) {
            val dao = AppDb.get(this@LocationLoggerService).dao()
            result.locations.forEach { loc ->
                scope.launch {
                    dao.insertFix(Fix(tsMillis = loc.time, lat = loc.latitude, lon = loc.longitude,
                        accuracyM = loc.accuracy, speedMps = if (loc.hasSpeed()) loc.speed else null))
                }
            }
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    @SuppressLint("MissingPermission")
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val type = if (Build.VERSION.SDK_INT >= 29) ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION else 0
        ServiceCompat.startForeground(this, NOTIF_ID, buildNotification(this, "Waiting for an order"), type)
        FloatingButtons.show(this)          // O / D bubble over every app (if allowed)
        if (started) return START_STICKY   // e.g. "Show O/D" tapped: buttons shown above, nothing else to redo
        started = true
        val req = LocationRequest.Builder(Priority.PRIORITY_HIGH_ACCURACY, 15_000L)
            .setMinUpdateDistanceMeters(20f)
            .build()
        try {
            client.requestLocationUpdates(req, callback, Looper.getMainLooper())
        } catch (e: SecurityException) {
            stopSelf()
        }
        scope.launch {
            while (isActive) {
                delay(15 * 60 * 1000L)
                SyncWorker.enqueue(this@LocationLoggerService)
            }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        client.removeLocationUpdates(callback)
        FloatingButtons.hide()
        scope.cancel()
        SyncWorker.enqueue(this)   // flush the rest of the track
        super.onDestroy()
    }

    companion object {
        private const val CHANNEL = "shift_logging"
        private const val NOTIF_ID = 42
        const val ACTION_SHOW_BUTTONS = "io.github.mdrifathahamed.spotorders.SHOW_BUTTONS"
        private val hhmm = DateTimeFormatter.ofPattern("HH:mm").withZone(ZoneId.of("Europe/Helsinki"))

        fun start(ctx: Context) = ctx.startForegroundService(Intent(ctx, LocationLoggerService::class.java))
        fun stop(ctx: Context) = ctx.stopService(Intent(ctx, LocationLoggerService::class.java))

        /** Update the notification text after a button press ("Order logged 18:32"). */
        fun refreshNotification(ctx: Context, type: EventType, atMillis: Long) {
            val text = when (type) {
                EventType.OFFER -> "Order logged ${hhmm.format(Instant.ofEpochMilli(atMillis))} · tap Free again after delivery"
                EventType.FREE -> "Free since ${hhmm.format(Instant.ofEpochMilli(atMillis))} · waiting for an order"
                EventType.SHIFT_START -> "Waiting for an order"
                EventType.SHIFT_END -> return
            }
            ctx.getSystemService(NotificationManager::class.java).notify(NOTIF_ID, buildNotification(ctx, text))
        }

        fun buildNotification(ctx: Context, text: String): Notification {
            val nm = ctx.getSystemService(NotificationManager::class.java)
            if (Build.VERSION.SDK_INT >= 26) {
                nm.createNotificationChannel(
                    NotificationChannel(CHANNEL, "Shift logging", NotificationManager.IMPORTANCE_LOW))
            }
            val flags = PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
            fun action(a: String, code: Int) = PendingIntent.getBroadcast(
                ctx, code, Intent(ctx, EventReceiver::class.java).setAction(a), flags)
            val open = PendingIntent.getActivity(ctx, 0, Intent(ctx, MainActivity::class.java), flags)
            val showButtons = PendingIntent.getForegroundService(
                ctx, 3, Intent(ctx, LocationLoggerService::class.java).setAction(ACTION_SHOW_BUTTONS), flags)
            return NotificationCompat.Builder(ctx, CHANNEL)
                .setContentTitle("Spotorders · on shift")
                .setContentText(text)
                .setSmallIcon(android.R.drawable.ic_menu_mylocation)
                .setContentIntent(open)
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .addAction(0, "Got order", action(EventReceiver.ACTION_OFFER, 1))
                .addAction(0, "Free again", action(EventReceiver.ACTION_FREE, 2))
                .addAction(0, "Show O/D", showButtons)
                .build()
        }
    }
}
