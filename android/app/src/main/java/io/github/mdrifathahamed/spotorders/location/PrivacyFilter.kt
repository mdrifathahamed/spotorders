package io.github.mdrifathahamed.spotorders.location

import io.github.mdrifathahamed.spotorders.data.EventType
import io.github.mdrifathahamed.spotorders.map.haversineM
import kotlin.math.roundToLong

/**
 * Keeps customers' addresses out of the data:
 *  - no GPS is stored while delivering (between O and D),
 *  - the D tap is stored rounded to ~100 m,
 *  - after D, logging resumes only once you are 200 m away or 3 minutes have passed.
 * The model only needs where you WAIT, so nothing useful is lost.
 */
object PrivacyFilter {
    @Volatile var delivering = false
    @Volatile private var freeAt = 0L
    @Volatile private var freeLat = Double.NaN
    @Volatile private var freeLon = Double.NaN

    private const val RESUME_AFTER_MS = 3 * 60_000L
    private const val RESUME_AFTER_M = 200.0

    fun onEvent(type: EventType, lat: Double?, lon: Double?, atMillis: Long) {
        when (type) {
            EventType.OFFER -> delivering = true
            EventType.FREE -> {
                delivering = false
                freeAt = atMillis
                freeLat = lat ?: Double.NaN
                freeLon = lon ?: Double.NaN
            }
            EventType.SHIFT_START, EventType.SHIFT_END -> { delivering = false; freeAt = 0L }
        }
    }

    /** True if this GPS fix must not be stored. */
    fun drop(lat: Double, lon: Double, tsMillis: Long): Boolean {
        if (delivering) return true
        if (freeAt > 0 && tsMillis - freeAt < RESUME_AFTER_MS && !freeLat.isNaN() &&
            haversineM(lat, lon, freeLat, freeLon) < RESUME_AFTER_M) return true
        return false
    }

    /** ~100 m precision (3 decimals is ~110 m north–south, ~55 m east–west in Helsinki). */
    fun coarse(v: Double?): Double? = v?.let { (it * 1000).roundToLong() / 1000.0 }
}
