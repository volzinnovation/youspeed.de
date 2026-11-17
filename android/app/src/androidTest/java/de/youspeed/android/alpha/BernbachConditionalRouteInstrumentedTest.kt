package de.youspeed.android.alpha

import android.content.Context
import android.content.Intent
import android.location.Location
import android.os.SystemClock
import androidx.activity.compose.setContent
import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.graphics.toPixelMap
import androidx.compose.ui.test.assertContentDescriptionEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.createEmptyComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.test.core.app.ActivityScenario
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.rule.GrantPermissionRule
import java.io.File
import java.time.Clock
import java.time.Instant
import java.time.ZoneId
import java.time.ZoneOffset
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Rule
import org.junit.Test

class BernbachConditionalRouteInstrumentedTest {
    @get:Rule val compose = createEmptyComposeRule()
    @get:Rule val permission = GrantPermissionRule.grant(
        android.Manifest.permission.ACCESS_FINE_LOCATION, android.Manifest.permission.ACCESS_COARSE_LOCATION)

    @Test fun fullBundleWeekdayClockAndDashboard() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        check(context.packageName.endsWith(".testhost"))
        val root = File(context.filesDir, "bernbach-replay/bundle")
        val activeFile = File(root, "active_bundle.json")
        assumeTrue("Stage the full BW generation in files/bernbach-replay/bundle.", activeFile.isFile)
        val active = JSONObject(activeFile.readText())
        val path = active.getString("db_path")
        val clock = object : Clock() {
            var at = System.currentTimeMillis()
            override fun millis() = at
            override fun instant() = Instant.ofEpochMilli(at)
            override fun getZone(): ZoneId = ZoneOffset.UTC
            override fun withZone(zone: ZoneId): Clock = this
        }
        val rows = JSONArray()
        RuntimeMapDatabase.open(path).use { runtime ->
            for (direction in listOf(1, -1)) for (day in 16..22) {
                for ((time, activeTime) in listOf("06:29:59" to false, "06:30:00" to true,
                    "17:29:59" to true, "17:30:00" to false)) {
                    val at = java.time.OffsetDateTime.parse("2026-11-${day}T${time}+01:00").toInstant()
                    val expected = if (day <= 20 && activeTime) 30 else 50
                    val result = requireNotNull(ConditionalSpeedRules.resolve(runtime.database, "966531279",
                        direction, 50, false, at.toEpochMilli(), countryCode = "DEU"))
                    assertEquals("$day $time $direction", expected, result.kmh)
                    assertFalse(result.unresolved)
                    assertEquals(if (expected == 50) ConditionalSpeedPreview(30, "Mo-Fr 06:30-17:30") else null,
                        result.inactivePreview)
                    rows.put(JSONObject().put("day", day).put("time", time).put("direction", direction)
                        .put("kmh", result.kmh).put("preview", result.inactivePreview?.speedKmh ?: JSONObject.NULL))
                }
            }
        }
        val preference = "bernbach-replay-${System.nanoTime()}"
        val preferences = context.getSharedPreferences(preference, Context.MODE_PRIVATE)
        preferences.edit().putBoolean(OnboardingPolicy.COMPLETED_KEY, true)
            .putBoolean("youspeed.audio_alerts_enabled", false)
            .putBoolean("youspeed.traffic_sign_recognition_enabled", false)
            .putBoolean("youspeed.hide_welcome_screen", true)
            .putBoolean("youspeed.panoramax.capture_enabled", false).commit()
        lateinit var controller: ConsumerSessionController
        instrumentation.runOnMainSync {
            controller = ConsumerSessionController(context, root, preferences, clock, null)
            controller.setApplicationActive(true)
        }
        val output = File(context.cacheDir, "bernbach-results").apply { mkdirs() }
        try {
            val deadline = SystemClock.elapsedRealtime() + 90_000
            while (SystemClock.elapsedRealtime() < deadline && controller.uiState.startupDataState != StartupDataState.READY) {
                instrumentation.runOnMainSync { controller.keepStartupLogs() }
                Thread.sleep(100)
            }
            assertEquals(StartupDataState.READY, controller.uiState.startupDataState)
            assertEquals("2026-11-17-packed-v1-conditional", controller.uiState.activeBundleVersion)
            instrumentation.runOnMainSync {
                controller.startDriving()
                method("stopLocationUpdates").invoke(controller)
            }
            val intent = Intent(context, MainActivity::class.java).putExtra("screenshot_state", "camera-limit-active")
            ActivityScenario.launch<MainActivity>(intent).use { scenario ->
                scenario.onActivity { activity ->
                    activity.setContent {
                        MaterialTheme { MainScreen(controller, controller.uiState, true, {}, {}, {}, {}, {}, {}, {}, {}, {}) }
                    }
                }
                for (bearing in listOf(160f, 340f)) {
                    for (index in 0 until 11) {
                        instrumentation.runOnMainSync {
                            clock.at = System.currentTimeMillis()
                            val location = Location("gps").apply {
                                latitude = 48.8237069; longitude = 8.4159062
                                time = clock.millis(); elapsedRealtimeNanos = SystemClock.elapsedRealtimeNanos()
                                accuracy = 2f; speed = 30f / 3.6f; this.bearing = bearing; bearingAccuracyDegrees = 2f
                            }
                            method("consumeLocation", Location::class.java).invoke(controller, location)
                        }
                        Thread.sleep(1000)
                    }
                    assertEquals("966531279", controller.uiState.limitWayId)
                    for ((time, expected) in listOf("06:29:59" to 50, "06:30:00" to 30,
                        "17:29:59" to 30, "17:30:00" to 50)) {
                        instrumentation.runOnMainSync {
                            clock.at = java.time.OffsetDateTime.parse("2026-11-17T${time}+01:00").toInstant().toEpochMilli()
                            field("conditionalClockMinute").set(controller, null)
                            (field("speedReferenceTick").get(controller) as Runnable).run()
                        }
                        compose.waitForIdle()
                        val state = controller.uiState
                        val reference = field("speedReference").get(controller) as SpeedReferenceRuntime
                        val diagnostics = "$bearing $time driving=${field("isDriving").get(controller)} active=${field("applicationActive").get(controller)} " +
                            "context=${field("latestTrafficSignContext").get(controller)} clock=${field("conditionalClockContext").get(controller)} " +
                            "pending=${reference.contextPending()} source=${state.effectiveSpeedLimitSource} db=${state.activeDBPath} " +
                            "generation=${(field("trafficSignGeneration").get(controller) as TrafficSignWriteGate).get()}"
                        android.util.Log.i("BernbachReplay", diagnostics)
                        assertEquals(diagnostics, expected, state.speedLimitKmh)
                        assertEquals(diagnostics, if (expected == 50) ConditionalSpeedPreview(30, "Mo-Fr 06:30-17:30") else null,
                            state.inactiveSpeedLimitPreview)
                        if (expected == 50) {
                            val preview = compose.onNodeWithTag("inactive-speed-limit").assertIsDisplayed()
                                .assertContentDescriptionEquals("30 km/h, Mo-Fr 06:30-17:30")
                            val bounds = preview.fetchSemanticsNode().boundsInRoot
                            val main = compose.onNodeWithTag("speed-sign").fetchSemanticsNode().boundsInRoot
                            assertTrue(bounds.center.x < main.center.x)
                            assertTrue(bounds.center.y > main.center.y)
                            val pixels = preview.captureToImage().toPixelMap()
                            val top = pixels[pixels.width / 2, (pixels.height * 0.04).toInt()]
                            assertEquals(0x7a / 255f, top.red, 0.035f)
                            assertEquals(0x80 / 255f, top.green, 0.035f)
                            assertEquals(0x87 / 255f, top.blue, 0.035f)
                        } else compose.onNodeWithTag("inactive-speed-limit").assertDoesNotExist()
                        rows.put(JSONObject().put("controller", true).put("bearing", bearing).put("time", time)
                            .put("kmh", state.speedLimitKmh).put("preview", state.inactiveSpeedLimitPreview?.speedKmh ?: JSONObject.NULL))
                        if (bearing == 160f && time in listOf("06:30:00", "17:30:00")) {
                            File(output, "bernbach-$expected.png").outputStream().use {
                                compose.onNodeWithTag("main-root").captureToImage().asAndroidBitmap()
                                    .compress(android.graphics.Bitmap.CompressFormat.PNG, 100, it)
                            }
                        }
                    }
                }
            }
            V3SpeedLimitLookup(path, "DEU").use { service ->
                val pin = service.lookup(48.823257, 8.416530, 50.0, 256, 110.0,
                    speedKmh = 30.0, horizontalAccuracyM = 2.0, headingAccuracyDeg = 2.0)
                assertEquals("966531278", pin.wayId)
                assertEquals(50, pin.speedLimitKmh)
                assertNull(pin.conditionalRuleContext)
            }
        } finally {
            File(output, "results.json").writeText(rows.toString(2))
            instrumentation.runOnMainSync { controller.dispose() }
            context.deleteSharedPreferences(preference)
        }
    }
    private fun field(name: String) = ConsumerSessionController::class.java.getDeclaredField(name).apply { isAccessible = true }
    private fun method(name: String, vararg types: Class<*>) =
        ConsumerSessionController::class.java.getDeclaredMethod(name, *types).apply { isAccessible = true }
}
