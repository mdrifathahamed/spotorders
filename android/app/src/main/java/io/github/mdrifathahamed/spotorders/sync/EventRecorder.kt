package io.github.mdrifathahamed.spotorders.sync

import android.annotation.SuppressLint
import android.content.Context
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import io.github.mdrifathahamed.spotorders.data.AppDb
import io.github.mdrifathahamed.spotorders.data.EventType
import io.github.mdrifathahamed.spotorders.data.Fix
import io.github.mdrifathahamed.spotorders.data.ShiftEvent
import io.github.mdrifathahamed.spotorders.location.LocationLoggerService
import io.github.mdrifathahamed.spotorders.location.PrivacyFilter
import io.github.mdrifathahamed.spotorders.overlay.FloatingButtons
import kotlinx.coroutines.tasks.await
import kotlinx.coroutines.withTimeoutOrNull

/** The single place where a button press becomes data: save locally, then queue the upload. */
object EventRecorder {

    suspend fun record(ctx: Context, type: EventType) {
        val dao = AppDb.get(ctx).dao()
        val now = System.currentTimeMillis()
        // Try for a fresh fix (max 5 s); fall back to the logger's latest one.
        val fresh = freshFix(ctx)
        val atDoor = type == EventType.FREE          // D is pressed at the customer's door
        if (fresh != null && !atDoor && !PrivacyFilter.delivering) dao.insertFix(fresh)
        val fix = fresh ?: dao.lastFix()
        PrivacyFilter.onEvent(type, fix?.lat, fix?.lon, now)
        dao.insertEvent(
            ShiftEvent(
                tsMillis = now, type = type,
                lat = if (atDoor) PrivacyFilter.coarse(fix?.lat) else fix?.lat,
                lon = if (atDoor) PrivacyFilter.coarse(fix?.lon) else fix?.lon,
                accuracyM = fix?.accuracyM,
                fixAgeS = fix?.let { (now - it.tsMillis) / 1000 },
            )
        )
        LocationLoggerService.refreshNotification(ctx, type, now)
        FloatingButtons.onEvent(type)
        SyncWorker.enqueue(ctx)
    }

    @SuppressLint("MissingPermission")
    private suspend fun freshFix(ctx: Context): Fix? = try {
        withTimeoutOrNull(5_000) {
            LocationServices.getFusedLocationProviderClient(ctx)
                .getCurrentLocation(Priority.PRIORITY_HIGH_ACCURACY, null).await()
        }?.let { Fix(tsMillis = it.time, lat = it.latitude, lon = it.longitude,
                     accuracyM = it.accuracy, speedMps = if (it.hasSpeed()) it.speed else null) }
    } catch (e: SecurityException) {
        null
    } catch (e: Exception) {
        null
    }
}
