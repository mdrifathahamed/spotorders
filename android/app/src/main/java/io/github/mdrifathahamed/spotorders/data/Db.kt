package io.github.mdrifathahamed.spotorders.data

import android.content.Context
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.TypeConverter
import androidx.room.TypeConverters
import kotlinx.coroutines.flow.Flow

/** One GPS fix from the foreground logger. */
@Entity(tableName = "fixes")
data class Fix(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val tsMillis: Long,
    val lat: Double,
    val lon: Double,
    val accuracyM: Float,
    val speedMps: Float?,
    val synced: Boolean = false,
)

/**
 * A one-tap event. FREE = delivered and waiting again, OFFER = got a new task.
 * The time between a FREE and the next OFFER is the waiting time the model predicts.
 */
enum class EventType { SHIFT_START, FREE, OFFER, SHIFT_END }

@Entity(tableName = "events")
data class ShiftEvent(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val tsMillis: Long,
    val type: EventType,
    val lat: Double?,
    val lon: Double?,
    val accuracyM: Float?,
    val fixAgeS: Long?,
    val synced: Boolean = false,
)

@Dao
interface LogDao {
    @Insert suspend fun insertFix(fix: Fix)
    @Insert suspend fun insertEvent(event: ShiftEvent)

    @Query("SELECT * FROM events ORDER BY tsMillis DESC LIMIT 1")
    fun lastEvent(): Flow<ShiftEvent?>

    @Query("SELECT * FROM events ORDER BY tsMillis DESC LIMIT 1")
    suspend fun lastEventNow(): ShiftEvent?

    @Query("SELECT * FROM events ORDER BY tsMillis")
    suspend fun allEvents(): List<ShiftEvent>

    @Query("SELECT * FROM fixes ORDER BY tsMillis")
    suspend fun allFixes(): List<Fix>

    @Query("SELECT * FROM fixes ORDER BY tsMillis DESC LIMIT 1")
    suspend fun lastFix(): Fix?

    @Query("SELECT COUNT(*) FROM fixes")
    fun fixCount(): Flow<Int>

    @Query("SELECT COUNT(*) FROM events WHERE type = 'OFFER' AND tsMillis >= :sinceMillis")
    fun offersSince(sinceMillis: Long): Flow<Int>

    // --- upload queue
    @Query("SELECT * FROM events WHERE synced = 0 ORDER BY tsMillis")
    suspend fun unsyncedEvents(): List<ShiftEvent>

    @Query("UPDATE events SET synced = 1 WHERE id IN (:ids)")
    suspend fun markEventsSynced(ids: List<Long>)

    @Query("SELECT * FROM fixes WHERE synced = 0 ORDER BY tsMillis LIMIT :limit")
    suspend fun unsyncedFixes(limit: Int): List<Fix>

    @Query("UPDATE fixes SET synced = 1 WHERE id IN (:ids)")
    suspend fun markFixesSynced(ids: List<Long>)

    @Query("SELECT COUNT(*) FROM events WHERE synced = 0")
    fun pendingEvents(): Flow<Int>
}

class Converters {
    @TypeConverter fun toType(s: String) = EventType.valueOf(s)
    @TypeConverter fun fromType(t: EventType) = t.name
}

@Database(entities = [Fix::class, ShiftEvent::class], version = 1, exportSchema = false)
@TypeConverters(Converters::class)
abstract class AppDb : RoomDatabase() {
    abstract fun dao(): LogDao

    companion object {
        @Volatile private var instance: AppDb? = null
        fun get(ctx: Context): AppDb = instance ?: synchronized(this) {
            instance ?: Room.databaseBuilder(ctx.applicationContext, AppDb::class.java, "log.db")
                .build().also { instance = it }
        }
    }
}
