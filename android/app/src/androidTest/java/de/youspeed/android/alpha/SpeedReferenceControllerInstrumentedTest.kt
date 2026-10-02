package de.youspeed.android.alpha

import android.content.Context
import android.content.ContextWrapper
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.time.Clock
import java.time.Instant
import java.util.UUID
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class SpeedReferenceControllerInstrumentedTest {
    private val t0 = Instant.now()
    private fun field(name: String) = ConsumerSessionController::class.java.getDeclaredField(name).apply { isAccessible = true }

    @Test fun roadRecoveryAndUserDismissalReachTheControllerPresentation() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val base = instrumentation.targetContext
        val id = "reference-test-${UUID.randomUUID()}"
        val root = File(base.cacheDir, id).apply { mkdirs() }
        val isolated = object : ContextWrapper(base) {
            override fun getApplicationContext(): Context = this
            override fun getFilesDir(): File = File(root, "files").apply { mkdirs() }
            override fun getCacheDir(): File = File(root, "cache").apply { mkdirs() }
            override fun getNoBackupFilesDir(): File = File(root, "no-backup").apply { mkdirs() }
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
            instrumentation.runOnMainSync {
                field("isDriving").setBoolean(controller, true)
                val runtime = field("speedReference").get(controller) as SpeedReferenceRuntime
                val resolver = field("trafficSignResolver").get(controller) as TrafficSignRuntimeSourceResolver
                val baseLimit = TrafficSignBaseLimit(TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.NUMERIC, 80), EffectiveSpeedLimitSource.BUNDLE, "test-map")
                field("latestTrafficSignBase").set(controller, baseLimit)
                val offer = ConsumerSessionController::class.java.getDeclaredMethod("offerCameraReference", EffectiveSpeedLimit::class.java, TrafficSignPassageEvent::class.java).apply { isAccessible = true }
                fun publish(effective: EffectiveSpeedLimit, event: TrafficSignPassageEvent? = null) {
                    offer.invoke(controller, effective, event)
                    // Ordinary controller publication reprojects the authoritative reference.
                    controller.setAudioAlertThresholdKmh(10)
                }
                runtime.bundle("map", SpeedReferenceValue("numeric", 80))
                val end = passage(action = TrafficSignAction(TrafficSignActionKind.MAXIMUM_SPEED_END, 30))
                val unresolved = resolver.commit(end, baseLimit)
                publish(unresolved, end)
                repeat(10) {
                    runtime.bundle("fresh-map", SpeedReferenceValue("numeric", 80))
                    publish(resolver.effective(baseLimit))
                    assertEquals(80, controller.uiState.speedLimitKmh)
                    assertEquals(EffectiveSpeedLimitSource.BUNDLE, controller.uiState.effectiveSpeedLimitSource)
                }
                resolver.clear()
                val sign = passage(at = t0.plusSeconds(2))
                publish(resolver.commit(sign, baseLimit), sign)
                assertEquals(EffectiveSpeedLimitSource.CAMERA, controller.uiState.effectiveSpeedLimitSource)
                assertTrue(controller.canDisregardVision)
                controller.disregardVision()
                assertNull(resolver.activeAssertion())
                assertEquals(80, controller.uiState.speedLimitKmh)
                assertEquals(EffectiveSpeedLimitSource.BUNDLE, controller.uiState.effectiveSpeedLimitSource)
                assertFalse(controller.canDisregardVision)
                runtime.camera("new-sign", SpeedReferenceValue("numeric", 40))
                runtime.voice("spoken", SpeedReferenceValue("numeric", 70))
                controller.disregardVision()
                assertEquals(70, controller.uiState.speedLimitKmh)
                assertEquals(EffectiveSpeedLimitSource.LOCAL_CORRECTION, controller.uiState.effectiveSpeedLimitSource)

                // Country presentation follows fresh GPS even while the map
                // still points at a neighboring extract (iPhone parity).
                val selection = field("penaltyCountrySelection").get(controller) as PenaltyCountrySelection
                val catalog = field("regionalPackCatalog").get(controller) as RegionalPackCatalog
                val now = System.currentTimeMillis() / 1000.0
                assertEquals("DEU", selection.update(catalog, 48.8259633333, 8.12651, 8.0, now, now))
                controller.onTrafficSignBundleSelected("FRA", "test_overlapping_map")
                assertEquals("DEU", controller.uiState.activePenaltyRules.countryCode)
                assertTrue(controller.uiState.activePenaltyRules.isAvailable)
                assertEquals(10, controller.uiState.activePenaltyRules.bandCount)
                // The map must not restore rules after location evidence is invalidated.
                selection.update(catalog, 48.8259633333, 8.12651, 101.0, now + 1, now + 1)
                controller.onTrafficSignBundleSelected("DEU", "test_invalid_location")
                assertFalse(controller.uiState.activePenaltyRules.isAvailable)
            }
        } finally {
            instrumentation.runOnMainSync { controller.dispose() }
            base.deleteSharedPreferences("$id-youspeed")
            root.deleteRecursively()
        }
    }
    private fun passage(
        action: TrafficSignAction = TrafficSignAction(TrafficSignActionKind.POSTED_MAXIMUM, 30),
        context: TrafficSignDetectionContext? = context("100", setOf(1)),
        lastSeenContext: TrafficSignDetectionContext? = context ?: context("100", setOf(1)),
        at: Instant = t0,
    ) = TrafficSignPassageEvent(
        finalizedEventId = "event-${action.kind.wireValue}-${at.toEpochMilli()}",
        driveSessionId = "drive-test",
        generation = 1,
        packId = "pack-v1",
        artifactSha256 = "a".repeat(64),
        preprocessingVersion = "rgb-v1",
        calibrationId = "calibration-test",
        componentRole = "direct_detector",
        modelComponents = listOf(
            TrafficSignModelComponentLineage(
                role = "direct_detector",
                artifactSha256 = "a".repeat(64),
                preprocessingVersion = "rgb-v1",
                calibrationId = "calibration-test",
            ),
        ),
        physicalTrackId = "track-${at.toEpochMilli()}",
        assemblyId = null,
        assemblyIds = listOf("assembly-${at.toEpochMilli()}"),
        action = action,
        resolution = resolveDirectAction(action),
        firstSeenAtUtc = at.minusSeconds(1),
        lastSeenAtUtc = at.minusMillis(100),
        firstSeenContext = lastSeenContext,
        lastSeenContext = lastSeenContext,
        passageBoundary = TrafficSignPassageBoundary(at, context),
        activationContext = context,
        initialRouteRelationGroupIds = lastSeenContext?.routeRelationGroupIds.orEmpty(),
        eligibleRouteRelationGroupIds = lastSeenContext?.routeRelationGroupIds.orEmpty(),
        sourceRelationIds = lastSeenContext?.sourceRelationIds.orEmpty(),
        evidence = listOf(
            TrafficSignPassageFrameEvidence(
                frameId = "seen-${at.toEpochMilli()}",
                timestampUtc = at.minusSeconds(1),
                rawScore = 0.9,
                calibratedConfidence = 0.88,
                accumulatedSupport = 0.91,
                boundingBox = NormalizedTrafficSignBoundingBox(0.7, 0.1, 0.1, 0.2),
            ),
        ),
        lossEvidence = listOf(
            TrafficSignPassageLossEvidence(
                frameId = "missing-${at.toEpochMilli()}",
                timestampUtc = at,
                strongPassGeometry = false,
            ),
        ),
        framesSeen = 1,
        finalConfidence = 0.88,
        finalAccumulatedSupport = 0.91,
        peakConsecutiveFramesSeen = 1,
        lossReason = "consecutive_analyzed_misses",
        negativeFramesToCommit = 1,
        overrideEligible = true,
    )

    private fun context(wayId: String, groups: Set<Int>) = TrafficSignDetectionContext(
        wayId = wayId,
        latitude = 49.0,
        longitude = 8.4,
        headingDegrees = 90.0,
        travelDirection = TrafficSignTravelDirection.FORWARD,
        sourceSignature = TrafficSignRuntimeSourceSignature("bundle-v1|way:$wayId|maxspeed:50", "local-v1"),
        bundleSha256 = "a".repeat(64),
        routeRelationGroupIds = groups.map(Int::toLong).toSet(),
        sourceRelationIds = groups.map { it.toLong() + 9_000L }.toSet(),
        continuityCapable = true,
        traversalEpoch = 1,
    )

}
