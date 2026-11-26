package io.github.mdrifathahamed.spotorders.map

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.time.LocalTime
import java.time.ZoneId
import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sqrt

data class HexCell(
    val h3: String,
    val lat: Double,
    val lon: Double,
    val boundary: List<Pair<Double, Double>>,
    val foodPlaces: Int,
    val myOrders: Int,
    val topVenue: String?,
    val wait: Map<String, Double>,
    val n: Map<String, Int>,
    /** Expected number of food places open in each time bucket (OpenStreetMap opening hours). */
    val open: Map<String, Double> = emptyMap(),
    val hoursKnown: Int = 0,
    val woltVenues: Int = 0,
    val cluster: String? = null,
    val clusterPlaces: Int = 0,
)

data class AppMap(val generated: String, val buckets: List<String>, val totalOrders: Int, val cells: List<HexCell>)

data class Recommendation(val cell: HexCell, val bucket: String, val waitMin: Double, val distanceM: Double?, val rideMin: Double?)

val BUCKET_LABELS = linkedMapOf(
    "morning" to "Morning 06–11", "lunch" to "Lunch 11–14", "afternoon" to "Afternoon 14–17",
    "dinner" to "Dinner 17–21", "late" to "Late 21–06",
)

fun currentBucket(): String {
    val h = LocalTime.now(ZoneId.of("Europe/Helsinki")).hour
    return when (h) {
        in 6..10 -> "morning"
        in 11..13 -> "lunch"
        in 14..16 -> "afternoon"
        in 17..20 -> "dinner"
        else -> "late"
    }
}

fun haversineM(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
    val r = 6_371_008.8
    val p1 = Math.toRadians(lat1)
    val p2 = Math.toRadians(lat2)
    val dp = p2 - p1
    val dl = Math.toRadians(lon2 - lon1)
    val a = sin(dp / 2).pow(2) + cos(p1) * cos(p2) * sin(dl / 2).pow(2)
    return 2 * r * asin(sqrt(a))
}

/**
 * Best hexagon to wait in now: lowest expected wait, with riding time there counted at half weight
 * (you can still get an order on the way). Only hexagons within 3 km with real data or several food places.
 */
fun recommend(map: AppMap, bucket: String, lat: Double?, lon: Double?): Recommendation? {
    val candidates = map.cells.filter {
        (it.n[bucket] ?: 0) > 0 || (it.open[bucket] ?: it.foodPlaces.toDouble()) >= 3.0
    }
    return candidates.mapNotNull { c ->
        val w = c.wait[bucket] ?: return@mapNotNull null
        if (lat == null || lon == null) return@mapNotNull Triple(c, w, w)
        val d = haversineM(lat, lon, c.lat, c.lon)
        if (d > 3_000) return@mapNotNull null
        val ride = d / 1000 / 14.0 * 60
        Triple(c, w, w + 0.5 * ride)
    }.minByOrNull { it.third }?.let { (c, w, _) ->
        val d = if (lat != null && lon != null) haversineM(lat, lon, c.lat, c.lon) else null
        Recommendation(c, bucket, w, d, d?.let { it / 1000 / 14.0 * 60 })
    }
}

/** Downloads data/sample/app_map.json from the public repo (no token needed), with caching and offline fallback. */
object MapRepository {
    private const val MAX_AGE_MS = 30 * 60 * 1000L

    private fun url(owner: String, repo: String) =
        "https://raw.githubusercontent.com/$owner/$repo/main/data/sample/app_map.json"

    suspend fun load(ctx: Context, owner: String, repo: String, force: Boolean = false): Pair<AppMap?, String> =
        withContext(Dispatchers.IO) {
            val cache = File(ctx.filesDir, "app_map.json")
            val fresh = cache.exists() && System.currentTimeMillis() - cache.lastModified() < MAX_AGE_MS
            if (force || !fresh) {
                try {
                    val c = URL(url(owner, repo)).openConnection() as HttpURLConnection
                    c.connectTimeout = 10_000
                    c.readTimeout = 20_000
                    c.setRequestProperty("Cache-Control", "no-cache")
                    if (c.responseCode == 200) {
                        val text = c.inputStream.bufferedReader().use { it.readText() }
                        val parsed = parse(text)
                        cache.writeText(text)
                        return@withContext parsed to "Updated just now"
                    }
                } catch (_: Exception) { /* fall through to cache */ }
            }
            if (cache.exists()) {
                runCatching { parse(cache.readText()) }.getOrNull()?.let { return@withContext it to "Offline copy" }
            }
            val bundled = runCatching { ctx.assets.open("app_map.json").bufferedReader().use { it.readText() } }.getOrNull()
            (bundled?.let { runCatching { parse(it) }.getOrNull() }) to "Built-in copy"
        }

    fun parse(text: String): AppMap {
        val js = JSONObject(text)
        val buckets = js.getJSONArray("buckets").let { a -> List(a.length()) { a.getString(it) } }
        val cellsJs = js.getJSONArray("cells")
        val cells = List(cellsJs.length()) { i ->
            val c = cellsJs.getJSONObject(i)
            val b = c.getJSONArray("boundary")
            val w = c.getJSONObject("wait")
            val n = c.getJSONObject("n")
            HexCell(
                h3 = c.getString("h3"), lat = c.getDouble("lat"), lon = c.getDouble("lon"),
                boundary = List(b.length()) { k -> b.getJSONArray(k).let { it.getDouble(0) to it.getDouble(1) } },
                foodPlaces = c.optInt("food_places", 0), myOrders = c.optInt("my_orders", 0),
                topVenue = if (c.isNull("top_venue")) null else c.optString("top_venue"),
                wait = buckets.associateWith { w.optDouble(it, Double.NaN) }.filterValues { !it.isNaN() },
                n = buckets.associateWith { n.optInt(it, 0) },
                open = c.optJSONObject("open")?.let { o ->
                    buckets.associateWith { o.optDouble(it, Double.NaN) }.filterValues { !it.isNaN() }
                } ?: emptyMap(),
                hoursKnown = c.optInt("hours_known", 0),
                woltVenues = c.optInt("wolt_venues", 0),
                cluster = if (c.isNull("cluster")) null else c.optString("cluster").ifBlank { null },
                clusterPlaces = c.optInt("cluster_places", 0),
            )
        }
        return AppMap(js.optString("generated"), buckets, js.optInt("total_orders"), cells)
    }
}
