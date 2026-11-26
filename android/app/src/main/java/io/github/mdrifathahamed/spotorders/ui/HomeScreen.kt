package io.github.mdrifathahamed.spotorders.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import io.github.mdrifathahamed.spotorders.data.EventType
import io.github.mdrifathahamed.spotorders.data.ShiftEvent
import io.github.mdrifathahamed.spotorders.overlay.FloatingStyle
import androidx.compose.foundation.layout.Row
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Slider
import kotlin.math.roundToInt
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.rememberCoroutineScope
import io.github.mdrifathahamed.spotorders.sync.ScreenshotUploader
import kotlinx.coroutines.launch
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Switch
import androidx.compose.ui.Alignment
import androidx.compose.ui.platform.LocalContext
import io.github.mdrifathahamed.spotorders.data.AppSettings
import io.github.mdrifathahamed.spotorders.location.PrivacyFilter

data class SyncConfig(val owner: String, val dataRepo: String, val publicRepo: String, val token: String)

data class SyncStatus(val configured: Boolean, val pending: Int, val lastSync: String, val lastError: String)

/**
 * Big one-tap buttons. During a shift the same buttons also sit in the notification,
 * so in practice the app only needs to be opened to start and end a shift.
 */
@Composable
fun HomeScreen(
    last: ShiftEvent?,
    ordersToday: Int,
    fixCount: Int,
    status: SyncStatus,
    config: SyncConfig,
    onEvent: (EventType) -> Unit,
    onSaveConfig: (SyncConfig) -> Unit,
    onSyncNow: () -> Unit,
    onExport: () -> Unit,
    overlayAllowed: Boolean = false,
    onAllowOverlay: () -> Unit = {},
    onShowButtons: () -> Unit = {},
    floatingStyle: FloatingStyle = FloatingStyle(),
    onStyleChange: (FloatingStyle) -> Unit = {},
) {
    val onShift = last != null && last.type != EventType.SHIFT_END
    var showSettings by remember { mutableStateOf(!status.configured) }

    Column(
        Modifier.fillMaxSize().padding(24.dp).verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Text(
            if (onShift) "On shift · $ordersToday orders today · $fixCount GPS points"
            else "Off shift · $ordersToday orders today",
            style = MaterialTheme.typography.bodyLarge,
        )

        if (!onShift) {
            Button({ onEvent(EventType.SHIFT_START) }, Modifier.fillMaxWidth().height(80.dp)) { Text("Start shift") }
        } else {
            val waitingForOrder = last?.type !in setOf(EventType.OFFER, EventType.EXTRA, EventType.DROP)
            if (waitingForOrder) {
                Button({ onEvent(EventType.OFFER) }, Modifier.fillMaxWidth().height(96.dp)) { Text("Got an order") }
            } else {
                Button({ onEvent(EventType.EXTRA) }, Modifier.fillMaxWidth().height(72.dp)) { Text("+ Another order") }
            }
            Button({ onEvent(EventType.FREE) }, Modifier.fillMaxWidth().height(96.dp), enabled = !waitingForOrder) {
                Text("Delivered")
            }
            OutlinedButton({ onEvent(EventType.SHIFT_END) }, Modifier.fillMaxWidth()) { Text("End shift") }
        }

        HorizontalDivider()
        if (overlayAllowed) {
            Text("Floating buttons: O = got an order, D = delivered. They appear over every app during a shift. " +
                 "Drag to move, drag onto the ✕ to hide.", style = MaterialTheme.typography.bodyMedium)
            if (onShift) OutlinedButton(onShowButtons, Modifier.fillMaxWidth()) { Text("Show floating O / D buttons") }
            FloatingStyleControls(floatingStyle, onStyleChange)
        } else {
            Text("Allow \"Display over other apps\" to get the floating O / D buttons on top of the Wolt app.",
                 style = MaterialTheme.typography.bodyMedium)
            Button(onAllowOverlay, Modifier.fillMaxWidth()) { Text("Allow floating buttons") }
        }

        HorizontalDivider()
        RouteRecordingControls()

        HorizontalDivider()
        Text(
            when {
                !status.configured -> "GitHub upload is not set up yet: data stay on the phone."
                status.lastError.isNotBlank() -> "Upload problem: ${status.lastError} (${status.pending} waiting, will retry)"
                status.pending > 0 -> "${status.pending} button press(es) waiting for internet"
                else -> "All uploaded · last ${status.lastSync}"
            },
            style = MaterialTheme.typography.bodyMedium,
        )
        Spacer(Modifier.height(4.dp))
        OutlinedButton(onSyncNow, Modifier.fillMaxWidth(), enabled = status.configured) { Text("Upload now") }
        ScreenshotUploadButton()
        OutlinedButton(onExport, Modifier.fillMaxWidth()) { Text("Export CSV") }
        TextButton({ showSettings = !showSettings }) { Text(if (showSettings) "Hide GitHub settings" else "GitHub settings") }

        if (showSettings) SettingsForm(config, onSaveConfig) { showSettings = false }
    }
}

@Composable
private fun SettingsForm(config: SyncConfig, onSave: (SyncConfig) -> Unit, onDone: () -> Unit) {
    var owner by remember { mutableStateOf(config.owner) }
    var dataRepo by remember { mutableStateOf(config.dataRepo) }
    var publicRepo by remember { mutableStateOf(config.publicRepo) }
    var token by remember { mutableStateOf(config.token) }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedTextField(owner, { owner = it }, Modifier.fillMaxWidth(), label = { Text("GitHub username") }, singleLine = true)
        OutlinedTextField(dataRepo, { dataRepo = it }, Modifier.fillMaxWidth(), label = { Text("Private data repo") }, singleLine = true)
        OutlinedTextField(publicRepo, { publicRepo = it }, Modifier.fillMaxWidth(), label = { Text("Public repo") }, singleLine = true)
        OutlinedTextField(
            token, { token = it }, Modifier.fillMaxWidth(),
            label = { Text("Fine-grained access token") }, singleLine = true,
            visualTransformation = PasswordVisualTransformation(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
        )
        Text("The token is stored encrypted on this phone and only sent to api.github.com.",
            style = MaterialTheme.typography.bodySmall)
        Button({ onSave(SyncConfig(owner, dataRepo, publicRepo, token)); onDone() }, Modifier.fillMaxWidth()) {
            Text("Save")
        }
    }
}


@Composable
private fun FloatingStyleControls(style: FloatingStyle, onChange: (FloatingStyle) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text("Button size", style = MaterialTheme.typography.labelLarge)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf("Small" to 52, "Medium" to 64, "Large" to 76).forEach { (label, dp) ->
                FilterChip(selected = style.sizeDp == dp, onClick = { onChange(style.copy(sizeDp = dp)) },
                    label = { Text(label) })
            }
        }
        Text("Shape", style = MaterialTheme.typography.labelLarge)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            FilterChip(selected = !style.square, onClick = { onChange(style.copy(square = false)) }, label = { Text("Round") })
            FilterChip(selected = style.square, onClick = { onChange(style.copy(square = true)) }, label = { Text("Square") })
        }
        Text("See-through when idle: ${(100 - style.idleAlpha * 100).roundToInt()} %",
            style = MaterialTheme.typography.labelLarge)
        var alpha by remember(style.idleAlpha) { mutableStateOf(style.idleAlpha) }
        Slider(
            value = alpha,
            onValueChange = { alpha = it },
            onValueChangeFinished = { onChange(style.copy(idleAlpha = alpha)) },
            valueRange = 0.15f..1f,
        )
    }
}


/** Route recording: the GPS track is always kept while waiting; this adds delivery trips. */
@Composable
private fun RouteRecordingControls() {
    val ctx = LocalContext.current
    val settings = remember { AppSettings(ctx) }
    var trips by remember { mutableStateOf(settings.recordDeliveryTrips) }
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text("Route recording", style = MaterialTheme.typography.titleSmall)
        Text("During a shift your position is saved every 15 s, moving or standing still, " +
             "so that stops and rides can be learnt from later.",
             style = MaterialTheme.typography.bodySmall)
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Record delivery trips too", style = MaterialTheme.typography.bodyMedium)
                Text(if (trips) "Full route and exact drop-off points (private repo only)."
                     else "Off: no GPS between O and D, drop-offs rounded to ~100 m.",
                     style = MaterialTheme.typography.bodySmall)
            }
            Spacer(Modifier.width(8.dp))
            Switch(checked = trips, onCheckedChange = {
                trips = it
                settings.recordDeliveryTrips = it
                PrivacyFilter.recordTrips = it
            })
        }
    }
}


/**
 * End of shift: pick the courier-history screenshot(s) of the day. They are read with OCR in
 * GitHub Actions, which fixes late or forgotten O presses and records stacked orders.
 */
@Composable
private fun ScreenshotUploadButton() {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var busy by remember { mutableStateOf(false) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.PickMultipleVisualMedia(10)) { uris ->
        if (uris.isEmpty()) return@rememberLauncherForActivityResult
        busy = true
        scope.launch {
            val msg = ScreenshotUploader.upload(ctx, uris)
            busy = false
            Toast.makeText(ctx, msg, Toast.LENGTH_LONG).show()
        }
    }
    Button(
        { picker.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) },
        Modifier.fillMaxWidth(), enabled = !busy,
    ) { Text(if (busy) "Uploading…" else "Add history screenshot(s)") }
    Text("After the shift, screenshot the day in the courier history and add it here: " +
         "it corrects late or forgotten O presses and records stacked orders.",
         style = MaterialTheme.typography.bodySmall)
}
