package de.youspeed.android.alpha

import android.content.Context
import android.content.ContextWrapper
import android.location.Location
import android.location.LocationManager
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.time.Clock
import java.util.UUID
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class SpeedReferenceRoadInputInstrumentedTest {
    private fun field(name: String) = ConsumerSessionController::class.java.getDeclaredField(name).apply { isAccessible = true }
    private fun method(name: String) = ConsumerSessionController::class.java.declaredMethods.single { it.name == name }.apply { isAccessible = true }

    @Test fun explicitUnlimitedAndMissingMapEvidenceReachTheActualControllerAndLog() = withController { controller ->
        var sequence = 0L
        val runtime = field("speedReference").get(controller) as SpeedReferenceRuntime
        val gate = field("lookupToken").get(controller) as TrafficSignLookupMutationGate
        val generation = field("trafficSignGeneration").get(controller) as TrafficSignWriteGate
        fun apply(result: SpeedLookupResult, speed: Float = 10f, bearing: Float = 90f): EffectiveSpeedLimit {
            val location = Location(LocationManager.GPS_PROVIDER).apply {
                latitude = 48.8; longitude = 8.4; accuracy = 5f; this.speed = speed; this.bearing = bearing
                bearingAccuracyDegrees = 5f; time = System.currentTimeMillis(); elapsedRealtimeNanos = SystemClock.elapsedRealtimeNanos()
            }
            val position = TrafficSignPositionSample(location.time, location.latitude, location.longitude, bearing.toDouble(), speed.toDouble())
            field("latestTrafficSignPosition").set(controller, position)
            method("applyActiveLocalSpeedCorrectionIfNeeded").invoke(controller, result, location)
            val base = method("trafficSignBaseLimit").invoke(controller, null, null, result, "DEU", null, false) as TrafficSignBaseLimit
            assertNotNull(method("evaluateTrafficSignSources").invoke(controller, gate.snapshot(), ++sequence, generation.get(),
                position, result, location, base, "fixture", "a".repeat(64), "fixture.sqlite", "DEU", null, bearing.toDouble(), 10))
            controller.setAudioAlertThresholdKmh(10) // Reprojects the authoritative reference into the actual UI state.
            return requireNotNull(runtime.output()).effective()
        }

        for (highway in listOf("motorway", "motorway_link", "trunk", "trunk_link")) {
            runtime.reset()
            val explicit = result(highway, null, true, DerivedSpeedSource.EXPLICIT_UNLIMITED_TAG)
            val effective = apply(explicit)
            assertEquals("explicit none on $highway", EffectiveSpeedLimitSource.BUNDLE, controller.uiState.effectiveSpeedLimitSource)
            assertTrue(controller.uiState.isUnlimitedSpeedLimitActive)
            assertNull(controller.uiState.speedLimitKmh)
            assertEquals("matched_unlimited", SpeedReferenceRoadInput.lookupStatus(explicit.wayId, effective))
        }

        runtime.reset()
        apply(result("trunk", 80, false, DerivedSpeedSource.EXPLICIT_TAG))
        val missing = result("trunk", null, false, DerivedSpeedSource.NONE)
        val retained = apply(missing)
        assertEquals(80, controller.uiState.speedLimitKmh)
        assertFalse(controller.uiState.isUnlimitedSpeedLimitActive)
        assertEquals(EffectiveSpeedLimitSource.LAST_KNOWN, controller.uiState.effectiveSpeedLimitSource)
        assertEquals("matched_last_known", SpeedReferenceRoadInput.lookupStatus(missing.wayId, retained))

        // An unlimited flag unsupported by explicit map evidence cannot manufacture a current value.
        apply(result("motorway", null, true, DerivedSpeedSource.HIGHWAY_CLASS))
        assertEquals(EffectiveSpeedLimitSource.LAST_KNOWN, controller.uiState.effectiveSpeedLimitSource)
        assertFalse(controller.uiState.isUnlimitedSpeedLimitActive)

        // Native course jitter while stopped must not create a direction-reversal boundary.
        runtime.reset()
        apply(result("trunk", 80, false, DerivedSpeedSource.EXPLICIT_TAG))
        val stopped = apply(result("trunk", 80, false, DerivedSpeedSource.EXPLICIT_TAG).copy(
            travelDirection = TrafficSignTravelDirection.REVERSE), speed = 0f, bearing = 270f)
        assertEquals(EffectiveSpeedLimitSource.BUNDLE, stopped.source)
        assertEquals(80, controller.uiState.speedLimitKmh)
        val reversal = apply(result("trunk", 80, false, DerivedSpeedSource.EXPLICIT_TAG).copy(
            travelDirection = TrafficSignTravelDirection.REVERSE), speed = 10f, bearing = 270f)
        assertEquals("A measured moving reversal still requires the unchanged confirmation", EffectiveSpeedLimitSource.LAST_KNOWN, reversal.source)

        method("ensureDrivingLogsExist").invoke(controller)
        val logLocation = Location(LocationManager.GPS_PROVIDER).apply {
            latitude = 48.8; longitude = 8.4; accuracy = 5f; time = System.currentTimeMillis()
        }
        method("appendMatchLogEntry").invoke(controller, 1, logLocation, 0.0,
            SpeedReferenceRoadInput.lookupStatus(missing.wayId, retained), missing, null, 4, 80, null, retained)
        val log = method("matchLogFile").invoke(controller) as File
        val entry = JSONObject(log.readLines().last())
        assertEquals("matched_last_known", entry.getString("status"))
        assertEquals("last_known", entry.getString("effectiveSpeedLimitSource"))
        assertEquals("numeric", entry.getString("effectiveSpeedLimitKind"))
        assertFalse(entry.getBoolean("effectiveSpeedLimitCurrent"))
        assertEquals("none", entry.getJSONObject("result").getString("speedSource"))
    }

    private fun withController(body: (ConsumerSessionController) -> Unit) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val base = instrumentation.targetContext
        assertTrue("Requires the isolated test host", base.packageName.endsWith(".testhost"))
        val id = "reference-road-input-${UUID.randomUUID()}"
        val root = File(base.cacheDir, id).apply { mkdirs() }
        val isolated = object : ContextWrapper(base) {
            override fun getApplicationContext(): Context = this
            override fun getFilesDir() = File(root, "files").apply { mkdirs() }
            override fun getCacheDir() = File(root, "cache").apply { mkdirs() }
            override fun getNoBackupFilesDir() = File(root, "no-backup").apply { mkdirs() }
            override fun getSharedPreferences(name: String, mode: Int) = base.getSharedPreferences("$id-$name", mode)
        }
        lateinit var controller: ConsumerSessionController
        instrumentation.runOnMainSync {
            controller = ConsumerSessionController(isolated, File(root, "bundle"),
                isolated.getSharedPreferences("youspeed", Context.MODE_PRIVATE), Clock.systemUTC(), null)
        }
        try {
            val deadline = SystemClock.uptimeMillis() + 30_000
            while (controller.uiState.startupDataState == StartupDataState.LOADING && SystemClock.uptimeMillis() < deadline) SystemClock.sleep(100)
            instrumentation.runOnMainSync { field("isDriving").setBoolean(controller, true); body(controller) }
        } finally {
            instrumentation.runOnMainSync { controller.dispose() }
            base.deleteSharedPreferences("$id-youspeed"); root.deleteRecursively()
        }
    }

    private fun result(highway: String, speed: Int?, unlimited: Boolean, source: DerivedSpeedSource) = SpeedLookupResult(
        wayId = "fixture-way", highway = highway, streetName = "Fixture Road", streetBaseName = "Fixture Road", streetRef = "B 500",
        speedLimitKmh = speed, isUnlimitedSpeedLimit = unlimited, cityName = null, cityPlaceName = null, cityDistrictName = null,
        insideCity = null, citySource = null, queryTimeMs = 1.0, candidateCount = 1, speedCandidateCount = if (speed != null || unlimited) 1 else 0,
        candidateTraces = emptyList(), nearestCandidateDistanceM = 0.0, nearestSpeedCandidateDistanceM = null, isTunnelSegment = false,
        matchedEndpointProximityM = 100.0, streetRefTokens = listOf("B500"), nearbyTunnelCandidateWayIds = emptySet(), nearbyTunnelCandidateRefs = emptySet(),
        portalEligibleTunnelWayIds = emptySet(), portalEligibleTunnelRefs = emptySet(), activeCorridorState = null, approachCorridorStateCandidate = null,
        usedWalkingTurnSwitch = false, usedMiniHMM = false, miniHMMCandidateCount = 0, matchHypotheses = emptyList(), selectionTrace = emptyList(),
        speedSource = source, travelDirection = TrafficSignTravelDirection.FORWARD,
    )
}
