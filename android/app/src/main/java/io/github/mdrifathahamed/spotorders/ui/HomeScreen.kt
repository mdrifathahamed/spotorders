package io.github.mdrifathahamed.spotorders.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import io.github.mdrifathahamed.spotorders.data.EventType
import io.github.mdrifathahamed.spotorders.data.ShiftEvent

/**
 * Big, one-tap buttons only (never used while riding).
 * Phase 2 adds the floating bubble over the Wolt Partner app; this screen is the fallback.
 */
@Composable
fun HomeScreen(
    last: ShiftEvent?,
    fixCount: Int,
    onEvent: (EventType) -> Unit,
    onExport: () -> Unit,
) {
    val onShift = last != null && last.type != EventType.SHIFT_END
    Column(
        Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text("Spotorders", style = MaterialTheme.typography.headlineMedium)
        Text(
            if (onShift) "On shift · last: ${last?.type} · $fixCount GPS fixes" else "Off shift",
            style = MaterialTheme.typography.bodyLarge,
        )
        Spacer(Modifier.height(8.dp))
        if (!onShift) {
            Button({ onEvent(EventType.SHIFT_START) }, Modifier.fillMaxWidth().height(72.dp)) { Text("Start shift") }
        } else {
            Button({ onEvent(EventType.OFFER) }, Modifier.fillMaxWidth().height(96.dp)) { Text("Got an order") }
            Button({ onEvent(EventType.FREE) }, Modifier.fillMaxWidth().height(96.dp)) { Text("Delivered · free again") }
            OutlinedButton({ onEvent(EventType.SHIFT_END) }, Modifier.fillMaxWidth()) { Text("End shift") }
        }
        Spacer(Modifier.height(8.dp))
        OutlinedButton(onExport, Modifier.fillMaxWidth()) { Text("Export CSV") }
    }
}
