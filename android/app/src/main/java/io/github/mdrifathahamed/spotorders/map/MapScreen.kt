package io.github.mdrifathahamed.spotorders.map

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Color
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.Card
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLifecycleOwner
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import com.google.android.gms.location.LocationServices
import io.github.mdrifathahamed.spotorders.data.AppDb
import kotlinx.coroutines.launch
import kotlinx.coroutines.tasks.await
import org.osmdroid.config.Configuration
import org.osmdroid.tileprovider.tilesource.TileSourceFactory
import org.osmdroid.util.GeoPoint
import org.osmdroid.views.MapView
import org.osmdroid.views.overlay.Marker
import org.osmdroid.views.overlay.Polygon
import org.osmdroid.views.overlay.mylocation.GpsMyLocationProvider
import org.osmdroid.views.overlay.mylocation.MyLocationNewOverlay
import java.io.File
import kotlin.math.roundToInt
import androidx.compose.ui.graphics.Color as ComposeColor

private val HELSINKI = GeoPoint(60.192, 24.962)

/** Colour scale for expected wait (minutes): green = short, red = long. */
private fun waitColor(w: Double): Int = when {
    w <= 10 -> 0x2E7D32
    w <= 14 -> 0x8BC34A
    w <= 18 -> 0xFFC107
    w <= 24 -> 0xFB8C00
    else -> 0xE53935
}

private val LEGEND = listOf("≤10" to 0x2E7D32, "≤14" to 0x8BC34A, "≤18" to 0xFFC107, "≤24" to 0xFB8C00, ">24" to 0xE53935)

@SuppressLint("MissingPermission")
private suspend fun currentLocation(ctx: Context): GeoPoint? {
    AppDb.get(ctx).dao().lastFix()?.let { if (System.currentTimeMillis() - it.tsMillis < 10 * 60_000) return GeoPoint(it.lat, it.lon) }
    return try {
        LocationServices.getFusedLocationProviderClient(ctx).lastLocation.await()?.let { GeoPoint(it.latitude, it.longitude) }
    } catch (_: Exception) {
        null
    }
}

@Composable
fun MapScreen(owner: String, publicRepo: String) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var appMap by remember { mutableStateOf<AppMap?>(null) }
    var source by remember { mutableStateOf("Loading…") }
    var bucket by remember { mutableStateOf(currentBucket()) }
    var here by remember { mutableStateOf<GeoPoint?>(null) }

    fun reload(force: Boolean) = scope.launch {
        val (m, s) = MapRepository.load(ctx, owner, publicRepo, force)
        appMap = m
        source = s
        here = currentLocation(ctx)
    }
    LaunchedEffect(Unit) { reload(false) }

    val mapView = remember {
        Configuration.getInstance().apply {
            load(ctx, ctx.getSharedPreferences("osmdroid", Context.MODE_PRIVATE))
            userAgentValue = ctx.packageName
            osmdroidBasePath = File(ctx.cacheDir, "osmdroid")
            osmdroidTileCache = File(ctx.cacheDir, "osmdroid/tiles")
        }
        MapView(ctx).apply {
            setTileSource(TileSourceFactory.MAPNIK)
            setMultiTouchControls(true)
            controller.setZoom(13.5)
            controller.setCenter(HELSINKI)
        }
    }
    val myLocation = remember { MyLocationNewOverlay(GpsMyLocationProvider(ctx), mapView) }

    val lifecycle = LocalLifecycleOwner.current.lifecycle
    DisposableEffect(lifecycle) {
        val obs = LifecycleEventObserver { _, e ->
            when (e) {
                Lifecycle.Event.ON_RESUME -> { mapView.onResume(); myLocation.enableMyLocation() }
                Lifecycle.Event.ON_PAUSE -> { myLocation.disableMyLocation(); mapView.onPause() }
                else -> Unit
            }
        }
        lifecycle.addObserver(obs)
        mapView.onResume(); myLocation.enableMyLocation()
        onDispose {
            lifecycle.removeObserver(obs)
            myLocation.disableMyLocation()
            mapView.onDetach()
        }
    }

    val rec = remember(appMap, bucket, here) { appMap?.let { recommend(it, bucket, here?.latitude, here?.longitude) } }

    Column(Modifier.fillMaxSize()) {
        Row(
            Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            BUCKET_LABELS.forEach { (b, label) ->
                FilterChip(selected = bucket == b, onClick = { bucket = b }, label = { Text(label) })
            }
        }

        Card(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp)) {
            Column(Modifier.padding(12.dp)) {
                if (rec == null) {
                    Text(if (appMap == null) "No map data yet. Check your internet connection and tap Refresh."
                         else "No good spot within 3 km for this time yet.",
                         style = MaterialTheme.typography.bodyMedium)
                } else {
                    val where = rec.cell.topVenue ?: "this area"
                    Text("Best spot now: near $where", style = MaterialTheme.typography.titleMedium)
                    val dist = rec.distanceM?.let { d ->
                        " · ${if (d < 1000) "${d.roundToInt()} m" else "%.1f km".format(d / 1000)}" +
                            " away (${rec.rideMin!!.roundToInt().coerceAtLeast(1)} min ride)"
                    } ?: ""
                    Text("~${rec.waitMin.roundToInt()} min expected wait$dist", style = MaterialTheme.typography.bodyMedium)
                    val n = rec.cell.n[rec.bucket] ?: 0
                    Text(
                        if (n > 0) "Based on $n of my orders here at this time + ${rec.cell.foodPlaces} food places nearby"
                        else "No orders of mine here at this time yet: estimated from ${rec.cell.foodPlaces} food places nearby",
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("${appMap?.totalOrders ?: 0} orders · $source", style = MaterialTheme.typography.bodySmall)
                    Spacer(Modifier.weight(1f))
                    if (rec != null) TextButton({
                        mapView.controller.animateTo(GeoPoint(rec.cell.lat, rec.cell.lon), 15.0, 600L)
                    }) { Text("Show") }
                    TextButton({ reload(true) }) { Text("Refresh") }
                }
            }
        }

        Box(Modifier.weight(1f).fillMaxWidth()) {
            AndroidView(factory = { mapView }, modifier = Modifier.fillMaxSize(), update = { mv ->
                drawHexes(mv, appMap, bucket, rec, myLocation)
            })
        }

        Row(
            Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text("Wait (min)", style = MaterialTheme.typography.labelSmall)
            LEGEND.forEach { (label, rgb) ->
                Box(Modifier.size(12.dp).background(ComposeColor(0xFF000000 or rgb.toLong())))
                Text(label, style = MaterialTheme.typography.labelSmall)
                Spacer(Modifier.width(2.dp))
            }
        }
        Text(
            "Solid = based on my orders · faint = estimate from restaurant density. Tap a hexagon for details.",
            style = MaterialTheme.typography.labelSmall,
            modifier = Modifier.padding(start = 12.dp, end = 12.dp, bottom = 8.dp),
        )
    }
}

private fun drawHexes(mv: MapView, map: AppMap?, bucket: String, rec: Recommendation?, myLocation: MyLocationNewOverlay) {
    mv.overlays.clear()
    map?.cells?.forEach { c ->
        val w = c.wait[bucket] ?: return@forEach
        val n = c.n[bucket] ?: 0
        val rgb = waitColor(w)
        val alpha = if (n > 0) 0x99 else 0x44
        val poly = Polygon(mv).apply {
            points = c.boundary.map { GeoPoint(it.first, it.second) } + GeoPoint(c.boundary[0].first, c.boundary[0].second)
            fillPaint.color = (alpha shl 24) or rgb
            outlinePaint.color = (0xCC shl 24) or rgb
            outlinePaint.strokeWidth = if (rec?.cell?.h3 == c.h3) 6f else 2f
            if (rec?.cell?.h3 == c.h3) outlinePaint.color = Color.BLACK
            title = c.topVenue ?: "Hexagon"
            snippet = "~${w.roundToInt()} min expected wait (${BUCKET_LABELS[bucket]})<br/>" +
                "My orders here at this time: $n · all times: ${c.myOrders}<br/>" +
                "Food places nearby: ${c.foodPlaces}"
        }
        mv.overlays.add(poly)
    }
    mv.overlays.add(myLocation)
    rec?.let {
        mv.overlays.add(Marker(mv).apply {
            position = GeoPoint(it.cell.lat, it.cell.lon)
            setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_BOTTOM)
            title = "Best spot now"
            snippet = "~${it.waitMin.roundToInt()} min expected wait"
        })
    }
    mv.invalidate()
}
