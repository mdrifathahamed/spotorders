package io.github.mdrifathahamed.spotorders.overlay

import android.content.Context

/** Look of the floating buttons, Floating-Toucher style: size, see-through when idle, round or square. */
data class FloatingStyle(
    val sizeDp: Int = 64,          // 52 small · 64 medium · 76 large
    val idleAlpha: Float = 0.45f,  // opacity after 3 s without a touch (1 = solid)
    val square: Boolean = false,   // false = chat-head circles, true = rounded squares
) {
    fun save(ctx: Context) = prefs(ctx).edit()
        .putInt("size_dp", sizeDp).putFloat("idle_alpha", idleAlpha).putBoolean("square", square).apply()

    companion object {
        private fun prefs(ctx: Context) = ctx.getSharedPreferences("floating_buttons", Context.MODE_PRIVATE)
        fun load(ctx: Context) = prefs(ctx).let {
            FloatingStyle(it.getInt("size_dp", 64), it.getFloat("idle_alpha", 0.45f), it.getBoolean("square", false))
        }
    }
}
