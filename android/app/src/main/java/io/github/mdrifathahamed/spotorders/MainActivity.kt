package io.github.mdrifathahamed.spotorders

import android.Manifest
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import android.os.Build
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.ui.Modifier
import io.github.mdrifathahamed.spotorders.map.MapScreen
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.lifecycle.lifecycleScope
import io.github.mdrifathahamed.spotorders.data.AppDb
import io.github.mdrifathahamed.spotorders.data.AppSettings
import io.github.mdrifathahamed.spotorders.data.EventType
import io.github.mdrifathahamed.spotorders.export.CsvExporter
import io.github.mdrifathahamed.spotorders.location.LocationLoggerService
import io.github.mdrifathahamed.spotorders.overlay.FloatingButtons
import io.github.mdrifathahamed.spotorders.overlay.FloatingStyle
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

    /** Re-checked in onResume, after the user comes back from the overlay settings page. */
    private val overlayAllowed = mutableStateOf(false)
    private val floatingStyle by lazy { mutableStateOf(FloatingStyle.load(this)) }

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
                val tab = remember { mutableIntStateOf(0) }
                val refresh = remember { mutableIntStateOf(0) }
                refresh.intValue  // read so the status recomposes after Save / Upload now
                val status = SyncStatus(
                    configured = settings.isConfigured,
                    pending = pending,
                    lastSync = if (settings.lastSyncMillis == 0L) "never"
                               else DateFormat.getTimeInstance(DateFormat.SHORT).format(Date(settings.lastSyncMillis)),
                    lastError = settings.lastError,
                )
                Surface(Modifier.fillMaxSize()) {
                Column(Modifier.fillMaxSize().safeDrawingPadding()) {
                TabRow(selectedTabIndex = tab.intValue) {
                    Tab(selected = tab.intValue == 0, onClick = { tab.intValue = 0 }, text = { Text("Shift") })
                    Tab(selected = tab.intValue == 1, onClick = { tab.intValue = 1 }, text = { Text("Map") })
                }
                if (tab.intValue == 1) {
                    MapScreen(owner = settings.owner, publicRepo = settings.publicRepo.ifBlank { "spotorders" })
                } else HomeScreen(
                    last = last, ordersToday = ordersToday, fixCount = fixes, status = status,
                    config = SyncConfig(settings.owner, settings.dataRepo, settings.publicRepo, settings.token),
                    onEvent = ::record,
                    onSaveConfig = { c ->
                        settings.owner = c.owner; settings.dataRepo = c.dataRepo
                        settings.publicRepo = c.publicRepo; settings.token = c.token
                        refresh.intValue++
                        SyncWorker.enqueue(this@MainActivity)
                    },
                    onSyncNow = { SyncWorker.enqueue(this@MainActivity); refresh.intValue++ },
                    onExport = { lifecycleScope.launch { CsvExporter.export(this@MainActivity) } },
                    overlayAllowed = overlayAllowed.value,
                    onAllowOverlay = {
                        startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                            Uri.parse("package:$packageName")))
                    },
                    onShowButtons = { FloatingButtons.show(this@MainActivity) },
                    floatingStyle = floatingStyle.value,
                    onStyleChange = { st ->
                        st.save(this@MainActivity)
                        floatingStyle.value = st
                        FloatingButtons.restyle(this@MainActivity)
                    },
                )
                }
                }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        overlayAllowed.value = FloatingButtons.canDraw(this)
        // came back from granting the permission mid-shift: show the buttons straight away
        lifecycleScope.launch {
            val last = dao.lastEventNow()
            if (overlayAllowed.value && last != null && last.type != EventType.SHIFT_END) FloatingButtons.show(this@MainActivity)
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
