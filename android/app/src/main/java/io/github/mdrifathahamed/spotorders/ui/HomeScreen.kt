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
) {
    val onShift = last != null && last.type != EventType.SHIFT_END
    var showSettings by remember { mutableStateOf(!status.configured) }

    Column(
        Modifier.fillMaxSize().safeDrawingPadding().padding(24.dp).verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Text("Spotorders", style = MaterialTheme.typography.headlineMedium)
        Text(
            if (onShift) "On shift · $ordersToday orders today · $fixCount GPS points"
            else "Off shift · $ordersToday orders today",
            style = MaterialTheme.typography.bodyLarge,
        )

        if (!onShift) {
            Button({ onEvent(EventType.SHIFT_START) }, Modifier.fillMaxWidth().height(80.dp)) { Text("Start shift") }
        } else {
            val waitingForOrder = last?.type != EventType.OFFER
            Button({ onEvent(EventType.OFFER) }, Modifier.fillMaxWidth().height(96.dp), enabled = waitingForOrder) {
                Text("Got an order")
            }
            Button({ onEvent(EventType.FREE) }, Modifier.fillMaxWidth().height(96.dp), enabled = !waitingForOrder) {
                Text("Delivered · free again")
            }
            OutlinedButton({ onEvent(EventType.SHIFT_END) }, Modifier.fillMaxWidth()) { Text("End shift") }
        }

        HorizontalDivider()
        if (overlayAllowed) {
            Text("Floating buttons: O = got an order, D = delivered. They appear over every app during a shift. " +
                 "Drag to move, drag onto the ✕ to hide.", style = MaterialTheme.typography.bodyMedium)
            if (onShift) OutlinedButton(onShowButtons, Modifier.fillMaxWidth()) { Text("Show floating O / D buttons") }
        } else {
            Text("Allow \"Display over other apps\" to get the floating O / D buttons on top of the Wolt app.",
                 style = MaterialTheme.typography.bodyMedium)
            Button(onAllowOverlay, Modifier.fillMaxWidth()) { Text("Allow floating buttons") }
        }

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
