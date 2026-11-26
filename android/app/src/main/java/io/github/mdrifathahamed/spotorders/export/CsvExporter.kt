package io.github.mdrifathahamed.spotorders.export

import android.content.Context
import android.content.Intent
import androidx.core.content.FileProvider
import io.github.mdrifathahamed.spotorders.data.AppDb
import java.io.File
import java.time.Instant
import java.time.ZoneId

/** Writes events.csv and fixes.csv to the cache and opens the Android share sheet. */
object CsvExporter {
    private val zone = ZoneId.of("Europe/Helsinki")
    private fun iso(ms: Long) = Instant.ofEpochMilli(ms).atZone(zone).toOffsetDateTime().toString()

    suspend fun export(ctx: Context) {
        val dao = AppDb.get(ctx).dao()
        val dir = File(ctx.cacheDir, "exports").apply { mkdirs() }
        val events = File(dir, "events.csv").apply {
            writeText("ts,type,lat,lon\n" + dao.allEvents().joinToString("\n") {
                "${iso(it.tsMillis)},${it.type},${it.lat ?: ""},${it.lon ?: ""}" })
        }
        val fixes = File(dir, "fixes.csv").apply {
            writeText("ts,lat,lon,accuracy_m,speed_mps\n" + dao.allFixes().joinToString("\n") {
                "${iso(it.tsMillis)},${it.lat},${it.lon},${it.accuracyM},${it.speedMps ?: ""}" })
        }
        val auth = "${ctx.packageName}.files"
        val uris = arrayListOf(events, fixes).map { FileProvider.getUriForFile(ctx, auth, it) }
        val send = Intent(Intent.ACTION_SEND_MULTIPLE).apply {
            type = "text/csv"
            putParcelableArrayListExtra(Intent.EXTRA_STREAM, ArrayList(uris))
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        ctx.startActivity(Intent.createChooser(send, "Export shift log").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }
}
