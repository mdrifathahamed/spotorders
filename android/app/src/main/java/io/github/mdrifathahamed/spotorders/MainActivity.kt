package io.github.mdrifathahamed.spotorders

import android.Manifest
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.lifecycle.lifecycleScope
import io.github.mdrifathahamed.spotorders.data.AppDb
import io.github.mdrifathahamed.spotorders.data.EventType
import io.github.mdrifathahamed.spotorders.data.ShiftEvent
import io.github.mdrifathahamed.spotorders.export.CsvExporter
import io.github.mdrifathahamed.spotorders.location.LocationLoggerService
import io.github.mdrifathahamed.spotorders.ui.HomeScreen
import kotlinx.coroutines.launch

class MainActivity : ComponentActivity() {
    private val dao by lazy { AppDb.get(this).dao() }

    private val askPermissions = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        askPermissions.launch(arrayOf(
            Manifest.permission.ACCESS_FINE_LOCATION,
            Manifest.permission.ACCESS_COARSE_LOCATION,
            Manifest.permission.POST_NOTIFICATIONS,
        ))
        setContent {
            MaterialTheme {
                val last by dao.lastEvent().collectAsState(initial = null)
                val fixes by dao.fixCount().collectAsState(initial = 0)
                HomeScreen(last, fixes, onEvent = ::record, onExport = {
                    lifecycleScope.launch { CsvExporter.export(this@MainActivity) }
                })
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
            val fix = dao.lastFix()  // position of the tap = most recent GPS fix
            dao.insertEvent(ShiftEvent(tsMillis = System.currentTimeMillis(), type = type, lat = fix?.lat, lon = fix?.lon))
        }
    }
}
