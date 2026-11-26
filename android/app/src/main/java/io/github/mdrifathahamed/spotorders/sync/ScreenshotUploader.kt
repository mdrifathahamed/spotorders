package io.github.mdrifathahamed.spotorders.sync

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import io.github.mdrifathahamed.spotorders.data.AppSettings
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

/**
 * Uploads courier-history screenshots to screenshots/ in the private data repo.
 * GitHub Actions reads them with OCR and adds every task (time, venue, stacked pickups,
 * distance, pay) to the dataset, so the O button no longer has to be pressed on time.
 */
object ScreenshotUploader {
    private val stampFmt = DateTimeFormatter.ofPattern("yyyyMMdd_HHmmss")
    private val nameRe = Regex("""Screenshot_\d{8}_\d{6}""")

    /** Returns a short message for a toast. */
    suspend fun upload(ctx: Context, uris: List<Uri>): String = withContext(Dispatchers.IO) {
        val s = AppSettings(ctx)
        if (!s.isConfigured) return@withContext "Set up GitHub first (GitHub settings)"
        if (uris.isEmpty()) return@withContext "No screenshot chosen"
        val gh = GitHubClient(s.token, s.owner)
        var sent = 0
        var skipped = 0
        try {
            uris.forEachIndexed { i, uri ->
                val shown = displayName(ctx, uri)
                val ext = shown?.substringAfterLast('.', "jpg")?.lowercase()?.takeIf { it in setOf("jpg", "jpeg", "png") } ?: "jpg"
                val base = shown?.let { nameRe.find(it)?.value }
                    ?: "Screenshot_${LocalDateTime.now().format(stampFmt)}_$i"
                val bytes = ctx.contentResolver.openInputStream(uri)?.use { it.readBytes() } ?: return@forEachIndexed
                if (gh.putBytes(s.dataRepo, "screenshots/$base.$ext", bytes, null, "app: history screenshot $base")) sent++
                else skipped++
            }
            if (sent > 0 && s.publicRepo.isNotBlank()) runCatching { gh.dispatch(s.publicRepo, "new-app-data") }
            buildString {
                append("$sent screenshot(s) uploaded")
                if (skipped > 0) append(", $skipped already there")
                if (sent > 0) append(" · the map updates in ~2 min")
            }
        } catch (e: Exception) {
            "Upload failed: ${e.message ?: e.javaClass.simpleName}"
        }
    }

    private fun displayName(ctx: Context, uri: Uri): String? =
        ctx.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
            if (c.moveToFirst()) c.getString(0) else null
        }
}
