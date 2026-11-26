package io.github.mdrifathahamed.spotorders.sync

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import io.github.mdrifathahamed.spotorders.data.AppDb
import io.github.mdrifathahamed.spotorders.data.AppSettings
import io.github.mdrifathahamed.spotorders.data.EventType
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.time.Instant
import java.time.ZoneId
import java.util.concurrent.TimeUnit

/**
 * Uploads every not-yet-uploaded button press and GPS fix to the private data repo:
 *   live/events.csv            one line per button press
 *   live/track/YYYY-MM-DD.csv  GPS track per day, every 15 s (older days: live/fixes/)
 * then pokes the public repo so its workflow rebuilds the dataset.
 * Runs whenever there is internet; retries with backoff if offline or GitHub fails.
 */
class SyncWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {

    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val settings = AppSettings(applicationContext)
        if (!settings.isConfigured) return@withContext Result.success()
        val dao = AppDb.get(applicationContext).dao()
        val gh = GitHubClient(settings.token, settings.owner)
        try {
            val events = dao.unsyncedEvents()
            if (events.isNotEmpty()) {
                gh.appendCsv(
                    settings.dataRepo, "live/events.csv", "ts,type,lat,lon,accuracy_m,fix_age_s",
                    events.map { e ->
                        listOf(iso(e.tsMillis), e.type.name, e.lat ?: "", e.lon ?: "",
                            e.accuracyM ?: "", e.fixAgeS ?: "").joinToString(",")
                    },
                    "app: ${events.joinToString(" ") { it.type.name.lowercase() }}",
                )
                dao.markEventsSynced(events.map { it.id })
            }

            val fixes = dao.unsyncedFixes(limit = 5000)
            fixes.groupBy { day(it.tsMillis) }.forEach { (d, list) ->
                gh.appendCsv(
                    settings.dataRepo, "live/track/$d.csv", "ts,lat,lon,accuracy_m,speed_mps,bearing_deg,state",
                    list.map { listOf(iso(it.tsMillis), it.lat, it.lon, it.accuracyM, it.speedMps ?: "",
                        it.bearingDeg ?: "", it.state).joinToString(",") },
                    "app: ${list.size} gps fixes",
                )
                dao.markFixesSynced(list.map { it.id })
            }

            // New order or end of shift: ask the public repo to rebuild the dataset now
            if (settings.publicRepo.isNotBlank() &&
                events.any { it.type == EventType.OFFER || it.type == EventType.EXTRA || it.type == EventType.SHIFT_END }) {
                runCatching { gh.dispatch(settings.publicRepo, "new-app-data") }
            }
            settings.lastSyncMillis = System.currentTimeMillis()
            settings.lastError = ""
            Result.success()
        } catch (e: Exception) {
            settings.lastError = e.message ?: e.javaClass.simpleName
            Result.retry()
        }
    }

    companion object {
        private val zone = ZoneId.of("Europe/Helsinki")
        private fun iso(ms: Long) = Instant.ofEpochMilli(ms).atZone(zone).toOffsetDateTime().toString()
        private fun day(ms: Long) = Instant.ofEpochMilli(ms).atZone(zone).toLocalDate().toString()

        fun enqueue(ctx: Context) {
            val req = OneTimeWorkRequestBuilder<SyncWorker>()
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
                .build()
            WorkManager.getInstance(ctx).enqueueUniqueWork("spotorders-sync", ExistingWorkPolicy.APPEND_OR_REPLACE, req)
        }
    }
}
