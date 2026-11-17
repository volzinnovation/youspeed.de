package de.youspeed.android.alpha

import android.graphics.Bitmap
import android.graphics.Color
import android.widget.FrameLayout
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.platform.ComposeView
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.time.Instant
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Rule
import org.junit.Test

class MapillaryPackedReplayInstrumentedTest {
    @get:Rule val compose = createEmptyComposeRule()

    @Test fun compareInstalledPackedRoutes() {
        assumeTrue(InstrumentationRegistry.getArguments().getString("localMapillaryReplay") == "true")
        val app = InstrumentationRegistry.getInstrumentation().targetContext
        val fixture = File(app.filesDir, "mapillary-eval-replay")
        val paths = JSONObject(File(fixture, "paths.json").readText())
        val baseline = File(app.filesDir, paths.getString("baseline"))
        val trial = File(app.filesDir, paths.getString("trial"))
        val art = mutableSetOf<String>()
        val displaySamples = mutableMapOf<String, InventorySign>()
        val report = mutableMapOf<String, MutableMap<String, Int>>()
        V3SpeedLimitLookup(baseline.path, "DEU", MatcherDebugProfile.M7.lookupModel).use { old ->
            V3SpeedLimitLookup(trial.path, "DEU", MatcherDebugProfile.M7.lookupModel).use { new ->
                InventorySignDatabase(baseline.path, amendmentStore = null).use { oldSigns ->
                    InventorySignDatabase(trial.path, amendmentStore = null).use { newSigns ->
                        var routeId = ""
                        var previous: SpeedLookupResult? = null
                        var oldRuntime = InventorySignRuntime {}
                        var newRuntime = InventorySignRuntime {}
                        File(fixture, "replay.tsv").useLines { lines ->
                            lines.forEach { line ->
                                val (id, latitude, longitude, heading) = line.split('\t')
                                if (routeId != id) {
                                    routeId = id
                                    previous = null
                                    oldRuntime = InventorySignRuntime {}
                                    newRuntime = InventorySignRuntime {}
                                }
                                val counts = report.getOrPut(id) { mutableMapOf() }
                                fun hit(key: String) { counts[key] = (counts[key] ?: 0) + 1 }
                                val lat = latitude.toDouble()
                                val lon = longitude.toDouble()
                                val bearing = heading.toDouble()
                                val continuity = WayMatchContext(preferredWayId = previous?.wayId, recentWayIds = listOfNotNull(previous?.wayId),
                                    preferredStreetRef = previous?.streetRef, matchedFixCount = if (previous == null) 0 else 3)
                                val a = old.lookup(lat, lon, 50.0, 256, bearing, 40.0, 5.0, 4, continuity, 5.0)
                                val b = new.lookup(lat, lon, 50.0, 256, bearing, 40.0, 5.0, 4, continuity, 5.0)
                                previous = a
                                val label = "$id at $lat,$lon"
                                assertEquals(label, listOf(a.wayId,a.speedLimitKmh,a.isUnlimitedSpeedLimit,a.insideCity,a.citySource,a.bundleSpeedProvenance),
                                    listOf(b.wayId,b.speedLimitKmh,b.isUnlimitedSpeedLimit,b.insideCity,b.citySource,b.bundleSpeedProvenance))
                                val direction = when (a.travelDirection) {
                                    TrafficSignTravelDirection.FORWARD -> 1
                                    TrafficSignTravelDirection.REVERSE -> -1
                                    else -> 0
                                }
                                val before = oldSigns.read(lat, lon, a.wayId, direction)
                                val after = newSigns.read(lat, lon, b.wayId, direction)
                                assertEquals(label, before.rules.sortedBy { it.id }, after.rules.sortedBy { it.id })
                                val now = Instant.ofEpochSecond(1_790_000_000 + counts.getOrDefault("fixes", 0).toLong())
                                val input = InventorySignFix(lat, lon, now, 5.0, a.wayId, direction, a.matchedWayStable, "route", bearing, 5.0)
                                val beforeDecision = oldRuntime.evaluate(before, input, now, false, false)
                                val afterDecision = newRuntime.evaluate(after, input, now, false, false)
                                assertEquals(label, listOf(beforeDecision.speedRule,beforeDecision.boundary,beforeDecision.boundarySignId,beforeDecision.insideCityContext),
                                    listOf(afterDecision.speedRule,afterDecision.boundary,afterDecision.boundarySignId,afterDecision.insideCityContext))
                                oldRuntime.acknowledgeBoundary(beforeDecision.boundarySignId)
                                newRuntime.acknowledgeBoundary(afterDecision.boundarySignId)
                                hit("fixes")
                                if (beforeDecision.speedRule?.sign?.sourceId == "mobidata-bw-vzk") hit("mobidataRuleFixes")
                                if (beforeDecision.boundarySignId?.startsWith("mobidata-bw-vzk:") == true &&
                                    beforeDecision.boundary in setOf("city_entry", "city_exit")) hit("mobidataTownEvents")
                                for (sign in after.signs.filter { it.sourceId == "mapillary-eval" &&
                                    InventorySignRuntime.distance(lat,lon,it.latitude,it.longitude) <= it.radiusMeters }) {
                                    val path = requireNotNull(sign.pictogramPath)
                                    if (art.add(path)) app.assets.open(path).use { assertTrue(it.read() >= 0) }
                                    hit("mapillaryHits")
                                    if (sign.code == "DE:274.1") {
                                        hit("zoneEntranceHits")
                                        displaySamples[id] = sign
                                    }
                                    assertFalse(afterDecision.captureSignIds.contains(sign.id))
                                }
                            }
                        }
                    }
                }
            }
        }
        assertEquals(setOf("ss-r03", "ss-r04"), report.keys)
        for (route in report.values) {
            assertTrue(route.getOrDefault("zoneEntranceHits", 0) > 0)
        }
        val output = JSONObject()
        for ((id, counts) in report) {
            output.put(id, JSONObject().apply { counts.forEach { (key, value) -> put(key, value) } })
        }
        File(fixture, "result.json").writeText(output.toString())
        if (paths.optString("renderPictograms") == "true") {
            val catalog = app.assets.open(TrafficSignDisplayCatalog.ASSET_PATH).bufferedReader().use {
                TrafficSignDisplayCatalog.decode(it.readText(), "DE")
            }
            for (id in listOf("ss-r03", "ss-r04")) {
                val sign = requireNotNull(displaySamples.getValue(id).pictogram(catalog))
                ActivityScenario.launch(MainActivity::class.java).use { scenario ->
                    scenario.onActivity { activity ->
                        activity.setContentView(FrameLayout(activity).apply {
                            setBackgroundColor(Color.WHITE)
                            addView(ComposeView(activity).apply {
                                setContent {
                                    Box(Modifier.background(androidx.compose.ui.graphics.Color.White)) {
                                        RecognizedTrafficSignPictogram(sign)
                                    }
                                }
                            }, FrameLayout.LayoutParams(-2, -2))
                        })
                    }
                    val image = compose.onNodeWithTag("last-traffic-sign-pictogram").captureToImage().asAndroidBitmap()
                    val pixels = IntArray(image.width * image.height)
                    image.getPixels(pixels, 0, image.width, 0, 0, image.width, image.height)
                    assertTrue("Rendered sign should contain black lettering and border", pixels.count {
                        Color.red(it) < 95 && Color.green(it) < 95 && Color.blue(it) < 95
                    } > 50)
                    File(fixture, "pictogram-$id.png").outputStream().use {
                        assertTrue(image.compress(Bitmap.CompressFormat.PNG, 100, it))
                    }
                }
            }
        }
    }
}
