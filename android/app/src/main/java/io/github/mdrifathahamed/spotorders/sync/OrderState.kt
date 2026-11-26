package io.github.mdrifathahamed.spotorders.sync

import android.content.Context
import io.github.mdrifathahamed.spotorders.data.AppDb
import io.github.mdrifathahamed.spotorders.data.EventType

/**
 * How many accepted orders are still on board.
 *   O  (while free)        -> 1 on board             recorded as OFFER
 *   +  (while delivering)  -> one more on board      recorded as EXTRA
 *   D  with 2+ on board    -> one fewer              recorded as DROP
 *   D  with 1 on board     -> free again             recorded as FREE
 * So O, +, + means three orders and three D presses.
 */
object OrderState {
    @Volatile var onBoard = 0
        private set
    @Volatile private var restored = false

    /** Rebuild the count from the stored log (after the app or phone restarted). */
    suspend fun restore(ctx: Context) {
        if (restored) return
        var n = 0
        for (e in AppDb.get(ctx).dao().recentEvents()) {          // newest first
            when (e.type) {
                EventType.FREE, EventType.SHIFT_START, EventType.SHIFT_END -> break
                EventType.OFFER, EventType.EXTRA -> n++
                EventType.DROP -> n--
            }
        }
        onBoard = n.coerceAtLeast(0)
        restored = true
    }

    /** Turns a button press into the event to store, and updates the count. */
    @Synchronized
    fun resolve(tap: EventType): EventType {
        val type = when (tap) {
            EventType.OFFER, EventType.EXTRA -> if (onBoard == 0) EventType.OFFER else EventType.EXTRA
            EventType.FREE, EventType.DROP -> when {
                onBoard >= 2 -> EventType.DROP
                else -> EventType.FREE
            }
            else -> tap
        }
        onBoard = when (type) {
            EventType.OFFER -> 1
            EventType.EXTRA -> onBoard + 1
            EventType.DROP -> onBoard - 1
            else -> 0
        }
        return type
    }
}
