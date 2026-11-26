package io.github.mdrifathahamed.spotorders

import android.Manifest
import android.os.Build
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.lifecycle.lifecycleScope
import io.github.mdrifathahamed.spotorders.data.AppDb
import io.github.mdrifathahamed.spotorders.data.AppSettings
import io.github.mdrifathahamed.spotorders.data.EventType
import io.github.mdrifathahamed.spotorders.export.CsvExporter
import io.github.mdrifathahamed.spotorders.location.LocationLoggerService
import io.github.mdrifathahamed.spotorders.sync.EventRecorder
import io.github.mdrifathahamed.spotorders.sync.SyncWorker
import io.github.mdrifathahamed.spotorders.ui.HomeScreen
import io.github.mdrifathahamed.spotorders.ui.SyncConfig
import io.github.mdrifathahamed.spotorders.ui.SyncStatus
import kotlinx.coroutines.launch
import java.text.DateFormat
import java.time.LocalDate
import java.time.ZoneId
import java.util.Date

class MainActivity : ComponentActivity() {
    private val dao by lazy { AppDb.get(this).dao() }
    private val settings by lazy { AppSettings(this) }

    private val askPermissions = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val perms = mutableListOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION)
        if (Build.VERSION.SDK_INT >= 33) perms += Manifest.permission.POST_NOTIFICATIONS
        askPermissions.launch(perms.toTypedArray())

        val midnight = LocalDate.now(ZoneId.of("Europe/Helsinki"))
            .atStartOfDay(ZoneId.of("Europe/Helsinki")).toInstant().toEpochMilli()

        setContent {
            MaterialTheme {
                val last by dao.lastEvent().collectAsState(initial = null)
                val fixes by dao.fixCount().collectAsState(initial = 0)
                val pending by dao.pendingEvents().collectAsState(initial = 0)
                val ordersToday by dao.offersSince(midnight).collectAsState(initial = 0)
                val refresh = remember { mutableIntStateOf(0) }
                refresh.intValue  // read so the status recomposes after Save / Upload now
                val status = SyncStatus(
                    configured = settings.isConfigured,
                    pending = pending,
                    lastSync = if (settings.lastSyncMillis == 0L) "never"
                               else DateFormat.getTimeInstance(DateFormat.SHORT).format(Date(settings.lastSyncMillis)),
                    lastError = settings.lastError,
                )
                HomeScreen(
                    last = last, ordersToday = ordersToday, fixCount = fixes, status = status,
                    config = SyncConfig(settings.owner, settings.dataRepo, settings.publicRepo, settings.token),
                    onEvent = ::record,
                    onSaveConfig = { c ->
                        settings.owner = c.owner; settings.dataRepo = c.dataRepo
                        settings.publicRepo = c.publicRepo; settings.token = c.token
                        refresh.intValue++
                        SyncWorker.enqueue(this)
                    },
                    onSyncNow = { SyncWorker.enqueue(this); refresh.intValue++ },
                    onExport = { lifecycleScope.launch { CsvExporter.export(this@MainActivity) } },
                )
            }
        }
    }

    private fun record(type: EventType) {
        when (type) {
            EventType.SHIFT_START -> LocationLoggerService.start(this)
            EventType.SHIFT_END -> LocationLoggerService.stop(this)
            else -> Unit
        }
        lifecycleScope.launch {
            EventRecorder.record(applicationContext, type)
            val msg = when (type) {
                EventType.SHIFT_START -> "Shift started"
                EventType.OFFER -> "Order logged"
                EventType.FREE -> "Free again"
                EventType.SHIFT_END -> "Shift ended"
            }
            Toast.makeText(this@MainActivity, msg, Toast.LENGTH_SHORT).show()
        }
    }
}
