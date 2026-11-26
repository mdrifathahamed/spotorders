package io.github.mdrifathahamed.spotorders.map

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import io.github.mdrifathahamed.spotorders.data.AppSettings
import java.util.concurrent.TimeUnit

/**
 * Keeps the map's data fresh without installing anything: downloads the newest app_map.json
 * (rebuilt by GitHub Actions after every shift and every night) into the phone's offline copy.
 *  - 12 minutes after "End shift" (time for the rebuild to finish), retried if offline;
 *  - every 12 hours, whenever there is internet.
 * A new app version is only needed for new features; the model and the map update themselves.
 */
class MapUpdateWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result {
        val s = AppSettings(applicationContext)
        val owner = s.owner.ifBlank { "mdrifathahamed" }
        val repo = s.publicRepo.ifBlank { "spotorders" }
        return if (MapRepository.refresh(applicationContext, owner, repo)) Result.success() else Result.retry()
    }

    companion object {
        private val net = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()

        fun schedulePeriodic(ctx: Context) {
            val req = PeriodicWorkRequestBuilder<MapUpdateWorker>(12, TimeUnit.HOURS).setConstraints(net).build()
            WorkManager.getInstance(ctx).enqueueUniquePeriodicWork("map-refresh", ExistingPeriodicWorkPolicy.KEEP, req)
        }

        fun afterShift(ctx: Context) {
            val req = OneTimeWorkRequestBuilder<MapUpdateWorker>()
                .setInitialDelay(12, TimeUnit.MINUTES).setConstraints(net).build()
            WorkManager.getInstance(ctx).enqueueUniqueWork("map-after-shift", ExistingWorkPolicy.REPLACE, req)
        }
    }
}
