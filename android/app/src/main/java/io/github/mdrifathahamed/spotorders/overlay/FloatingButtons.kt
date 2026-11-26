package io.github.mdrifathahamed.spotorders.overlay

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.VibrationEffect
import android.os.Vibrator
import android.provider.Settings
import android.util.TypedValue
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.view.WindowManager
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import io.github.mdrifathahamed.spotorders.data.AppDb
import io.github.mdrifathahamed.spotorders.data.EventType
import io.github.mdrifathahamed.spotorders.sync.EventRecorder
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlin.math.abs
import kotlin.math.hypot

/**
 * Chat-head style floating buttons shown over every app during a shift:
 *   O = got an order, D = delivered / free again.
 * Drag to move (snaps to the nearest screen edge), drag onto the ✕ at the bottom to hide.
 * The button you are expected to press next is bright; the other one is dimmed but still works.
 */
object FloatingButtons {
    private val main = Handler(Looper.getMainLooper())
    private val io = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private var wm: WindowManager? = null
    private var root: LinearLayout? = null
    private var btnO: TextView? = null
    private var btnD: TextView? = null
    private var params: WindowManager.LayoutParams? = null
    private var trash: TextView? = null

    private var lastType: EventType? = null
    private var lastTap = mutableMapOf<EventType, Long>()

    private const val ORANGE = 0xFFFF7A00.toInt()
    private const val BLUE = 0xFF1E88E5.toInt()
    private const val DIM = 0x99555555.toInt()
    private const val GREEN = 0xFF2E7D32.toInt()
    private const val DEBOUNCE_MS = 4_000L   // ignore accidental double taps of the same button

    fun canDraw(ctx: Context) = Settings.canDrawOverlays(ctx)
    val isShowing get() = root != null

    fun show(ctx: Context) = main.post { if (root == null && canDraw(ctx)) create(ctx.applicationContext) }

    fun hide() = main.post { removeAll() }

    /** Called after every recorded event so the right button lights up. */
    fun onEvent(type: EventType) = main.post {
        lastType = type
        refresh()
    }

    // ------------------------------------------------------------------ build
    private fun dp(ctx: Context, v: Float) =
        TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, ctx.resources.displayMetrics).toInt()

    private fun circle(color: Int, strokeDp: Int = 0, ctx: Context? = null) = GradientDrawable().apply {
        shape = GradientDrawable.OVAL
        setColor(color)
        if (strokeDp > 0 && ctx != null) setStroke(dp(ctx, strokeDp.toFloat()), Color.WHITE)
    }

    private fun overlayType() = WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY

    @SuppressLint("ClickableViewAccessibility")
    private fun create(ctx: Context) {
        val windowManager = ctx.getSystemService(WindowManager::class.java)
        val size = dp(ctx, 64f)
        val gap = dp(ctx, 10f)

        fun button(label: String, type: EventType) = TextView(ctx).apply {
            text = label
            setTextColor(Color.WHITE)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 28f)
            typeface = Typeface.DEFAULT_BOLD
            gravity = Gravity.CENTER
            elevation = dp(ctx, 6f).toFloat()
            layoutParams = LinearLayout.LayoutParams(size, size).apply { setMargins(0, gap / 2, 0, gap / 2) }
            tag = type
            contentDescription = if (type == EventType.OFFER) "Got an order" else "Delivered, free again"
        }

        val o = button("O", EventType.OFFER)
        val d = button("D", EventType.FREE)
        val layout = LinearLayout(ctx).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(gap / 2, gap / 2, gap / 2, gap / 2)
            addView(o)
            addView(d)
        }

        val prefs = ctx.getSharedPreferences("floating_buttons", Context.MODE_PRIVATE)
        val screenW = ctx.resources.displayMetrics.widthPixels
        val screenH = ctx.resources.displayMetrics.heightPixels
        val lp = WindowManager.LayoutParams(
            WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.WRAP_CONTENT,
            overlayType(),
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.TOP or Gravity.START
            x = prefs.getInt("x", screenW - size - gap * 2)
            y = prefs.getInt("y", (screenH * 0.35).toInt())
        }

        val touch = DragOrTap(ctx, windowManager, lp, prefs)
        o.setOnTouchListener(touch)
        d.setOnTouchListener(touch)

        windowManager.addView(layout, lp)
        wm = windowManager; root = layout; btnO = o; btnD = d; params = lp
        refresh()

        // light up the right button from the last stored event
        io.launch {
            val last = AppDb.get(ctx).dao().lastEventNow()?.type
            main.post { lastType = last; refresh() }
        }
    }

    private fun refresh() {
        val o = btnO ?: return
        val d = btnD ?: return
        val waitingForOrder = lastType != EventType.OFFER
        o.background = circle(if (waitingForOrder) ORANGE else DIM, 2, o.context)
        d.background = circle(if (!waitingForOrder) BLUE else DIM, 2, d.context)
    }

    private fun flash(v: TextView) {
        v.background = circle(GREEN, 2, v.context)
        main.postDelayed({ refresh() }, 600)
    }

    private fun vibrate(ctx: Context) {
        val vib = ctx.getSystemService(Vibrator::class.java) ?: return
        vib.vibrate(VibrationEffect.createOneShot(70, VibrationEffect.DEFAULT_AMPLITUDE))
    }

    private fun showTrash(ctx: Context) {
        if (trash != null) return
        val size = dp(ctx, 72f)
        val t = TextView(ctx).apply {
            text = "✕"
            setTextColor(Color.WHITE)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 30f)
            gravity = Gravity.CENTER
            background = circle(0xCC000000.toInt(), 2, ctx)
        }
        val lp = WindowManager.LayoutParams(
            size, size, overlayType(),
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE,
            PixelFormat.TRANSLUCENT,
        ).apply {
            gravity = Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL
            y = dp(ctx, 48f)
        }
        wm?.addView(t, lp)
        trash = t
    }

    private fun hideTrash() {
        trash?.let { runCatching { wm?.removeView(it) } }
        trash = null
    }

    private fun removeAll() {
        hideTrash()
        root?.let { runCatching { wm?.removeView(it) } }
        root = null; btnO = null; btnD = null; params = null
    }

    // ------------------------------------------------------------------ touch
    private class DragOrTap(
        private val ctx: Context,
        private val windowManager: WindowManager,
        private val lp: WindowManager.LayoutParams,
        private val prefs: android.content.SharedPreferences,
    ) : View.OnTouchListener {
        private val slop = ViewConfiguration.get(ctx).scaledTouchSlop * 2
        private var downX = 0f
        private var downY = 0f
        private var startX = 0
        private var startY = 0
        private var dragging = false

        private fun overTrash(rawX: Float, rawY: Float): Boolean {
            val m = ctx.resources.displayMetrics
            val cx = m.widthPixels / 2f
            val cy = m.heightPixels - TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, 84f, m)
            return hypot(rawX - cx, rawY - cy) < TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, 70f, m)
        }

        @SuppressLint("ClickableViewAccessibility")
        override fun onTouch(v: View, e: MotionEvent): Boolean {
            when (e.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    downX = e.rawX; downY = e.rawY
                    startX = lp.x; startY = lp.y
                    dragging = false
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = e.rawX - downX
                    val dy = e.rawY - downY
                    if (!dragging && (abs(dx) > slop || abs(dy) > slop)) {
                        dragging = true
                        showTrash(ctx)
                    }
                    if (dragging) {
                        lp.x = startX + dx.toInt()
                        lp.y = startY + dy.toInt()
                        root?.let { windowManager.updateViewLayout(it, lp) }
                        trash?.scaleX = if (overTrash(e.rawX, e.rawY)) 1.3f else 1f
                        trash?.scaleY = trash?.scaleX ?: 1f
                    }
                }
                MotionEvent.ACTION_UP -> {
                    if (dragging) {
                        val dismissed = overTrash(e.rawX, e.rawY)
                        hideTrash()
                        if (dismissed) {
                            removeAll()
                            Toast.makeText(ctx, "Buttons hidden. Bring them back from the notification.", Toast.LENGTH_LONG).show()
                        } else {
                            snapToEdge(v)
                        }
                    } else {
                        tap(v as TextView)
                    }
                }
                MotionEvent.ACTION_CANCEL -> {
                    hideTrash()
                    dragging = false
                }
            }
            return true
        }

        private fun snapToEdge(v: View) {
            val w = ctx.resources.displayMetrics.widthPixels
            val h = ctx.resources.displayMetrics.heightPixels
            val rootW = root?.width ?: v.width
            val rootH = root?.height ?: v.height
            lp.x = if (lp.x + rootW / 2 < w / 2) 0 else w - rootW
            lp.y = lp.y.coerceIn(0, (h - rootH).coerceAtLeast(0))
            root?.let { windowManager.updateViewLayout(it, lp) }
            prefs.edit().putInt("x", lp.x).putInt("y", lp.y).apply()
        }

        private fun tap(v: TextView) {
            val type = v.tag as EventType
            val now = System.currentTimeMillis()
            if (now - (lastTap[type] ?: 0L) < DEBOUNCE_MS) return
            lastTap[type] = now
            flash(v)
            vibrate(ctx)
            io.launch { EventRecorder.record(ctx, type) }
        }
    }
}
