package de.youspeed.android.alpha

import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.location.Location
import android.os.Handler
import android.os.Looper
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.lang.reflect.InvocationTargetException
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.ExecutorService
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

/** Synthetic state/SQL interleavings for the two 28 October ANR lock cycles. */
@RunWith(AndroidJUnit4::class)
class TrafficSignObservationConcurrencyInstrumentedTest {
    @Test
    fun lookupCityBoundaryDoesNotDeadlockAnObservationPermissionRead() = withHarness { h ->
        val stateHeld = CountDownLatch(1)
        val writerPermissionReached = CountDownLatch(1)
        val evaluationFinished = CountDownLatch(1)
        val writerFinished = CountDownLatch(1)
        val outcome = AtomicReference<Any?>()
        val persisted = AtomicReference<LocalObservation?>()
        val failure = AtomicReference<Throwable?>()
        val event = h.event("old-generation")
        val writer = daemon("anr-observation-writer", failure) {
            check(stateHeld.await(2, TimeUnit.SECONDS))
            persisted.set(h.recordOriginalContract(event) {
                writerPermissionReached.countDown()
                // This is a real store callback reading the controller's real
                // state monitor. No test code acquires the generation gate.
                synchronized(h.stateLock) { event.generation == h.gate.get() }
            })
            writerFinished.countDown()
        }
        val evaluator = daemon("anr-city-evaluator", failure) {
            synchronized(h.stateLock) {
                stateHeld.countDown()
                check(writerPermissionReached.await(2, TimeUnit.SECONDS))
                outcome.set(h.evaluateCityEntry())
            }
            evaluationFinished.countDown()
        }
        h.workers += listOf(writer, evaluator)
        writer.start(); evaluator.start()
        assertTrue("Lookup city transition waited for a writer that needed its state monitor", evaluationFinished.await(3, TimeUnit.SECONDS))
        assertTrue("The stale writer did not finish after the state transition", writerFinished.await(2, TimeUnit.SECONDS))
        rethrow(failure)
        assertNotNull("The actual lookup evaluator must accept the synthetic boundary", outcome.get())
        assertTrue("The boundary must invalidate the producer generation", h.gate.get() > event.generation)
        assertNull(persisted.get())
        h.assertDurableCounts(0, 0)
        h.assertSettingsAndCameraResponsive()
    }

    @Test
    fun lookupGenerationChangeBeforeTerminalAdmissionRollsBackObservationAndReceipt() = withHarness { h ->
        val event = h.event("stale-at-commit")
        h.recordPausedBeforeAdmission(event) {
            assertNotNull(h.evaluateCityEntry())
            h.assertSettingsAndCameraResponsive()
        }.also { assertNull(it) }
        h.assertDurableCounts(0, 0)
    }

    @Test
    fun ocrAuthorityChangeBeforeTerminalAdmissionRollsBackObservationAndReceipt() = withHarness { h ->
        val event = h.event("ocr-at-commit")
        h.recordPausedBeforeAdmission(event) { h.blockOcrParent(event) }.also { assertNull(it) }
        h.assertDurableCounts(0, 0)
    }

    @Test
    fun duplicateAndEquivalentValueBranchesStillCheckTerminalOcrAuthority() {
        for (duplicate in listOf(true, false)) withHarness { h ->
            val original = h.event("already-stored")
            assertNotNull(h.record(original))
            h.assertDurableCounts(1, 1)
            val incoming = if (duplicate) original else h.event("equivalent-value")
            assertNull("A terminally rejected duplicate must not return an old observation", h.recordPausedBeforeAdmission(incoming) {
                h.blockOcrParent(incoming)
            })
            // Equivalent-value processing tentatively inserts a receipt. It must
            // roll back that receipt together with any applicability sidecar.
            h.assertDurableCounts(1, 1)
        }
    }

    @Test
    fun admittedPhysicalCompletionDoesNotBlockUiGates() = withHarness { h ->
        val event = h.event("admitted-before-invalidation")
        val marked = CountDownLatch(1)
        val finishPhysicalTransaction = CountDownLatch(1)
        val writerFinished = CountDownLatch(1)
        val failure = AtomicReference<Throwable?>()
        val persisted = AtomicReference<LocalObservation?>()
        val writer = daemon("anr-admitted-write", failure) {
            persisted.set(h.recordWithAdmission(event) { markSuccessful ->
                    val admitted = h.admit(event, markSuccessful)
                    assertTrue(admitted)
                    marked.countDown()
                    check(finishPhysicalTransaction.await(5, TimeUnit.SECONDS))
                    admitted
            })
            writerFinished.countDown()
        }
        h.workers += writer
        try {
            writer.start()
            assertTrue("Writer did not reach the actual controller's terminal admission", marked.await(2, TimeUnit.SECONDS))
            // The SQL transaction is still physically open. The accepted write
            // precedes this boundary logically, but disk completion owns no gate.
            assertNotNull(h.evaluateCityEntry())
            h.assertSettingsAndCameraResponsive()
        } finally { finishPhysicalTransaction.countDown() }
        assertTrue(writerFinished.await(2, TimeUnit.SECONDS)); rethrow(failure)
        assertNotNull(persisted.get()); h.assertDurableCounts(1, 1)
        assertNull("A delayed old-generation retry must not create a second row", h.record(event))
        h.assertDurableCounts(1, 1)
    }

    @Test
    fun validControllerAdmissionPersistsOnceAndEquivalentValueOnlyAddsItsReceipt() = withHarness { h ->
        val event = h.event("valid-admission")
        val first = h.record(event)
        assertNotNull(first)
        val duplicate = h.record(event)
        assertEquals(first?.id, duplicate?.id)
        h.assertDurableCounts(1, 1)
        assertNull(h.record(h.event("equivalent-valid-admission")))
        h.assertDurableCounts(1, 2)
    }

    private class Harness {
        private val instrumentation = InstrumentationRegistry.getInstrumentation()
        private val context = instrumentation.targetContext
        private val name = "anr-storage-${UUID.randomUUID()}"
        private val root = File(context.cacheDir, name).apply { mkdirs() }
        private val at = Instant.parse("2026-01-01T12:00:00Z")
        private val clock = Clock.fixed(at, ZoneOffset.UTC)
        val workers = mutableListOf<Thread>()
        val controller: ConsumerSessionController
        val gate: TrafficSignWriteGate
        val stateLock: Any
        val store: LocalObservationStore
        private val session = "synthetic-$name"
        private val initialGeneration: Long
        private val position = TrafficSignPositionSample(at.toEpochMilli(), 48.0, 8.0, 90.0, 10.0)
        private val location = Location("synthetic-anr").apply {
            time = at.toEpochMilli(); latitude = 48.0; longitude = 8.0
            accuracy = 3f; speed = 10f; bearing = 90f
        }

        init {
            check(context.packageName.endsWith(".testhost")) { "This concurrency test requires the isolated test host" }
            val value = AtomicReference<ConsumerSessionController>()
            instrumentation.runOnMainSync {
                val created = ConsumerSessionController(context, root,
                    context.getSharedPreferences(name, Context.MODE_PRIVATE), clock,
                    launchScreenshotState = AppScreenshotState.CAMERA_LIMIT_ACTIVE)
                field("isDriving").setBoolean(created, true)
                field("trafficSignDriveSessionId").set(created, session)
                field("latestTrafficSignPosition").set(created, position)
                method("updateState").invoke(created, { state: ConsumerUiState -> state.copy(
                    trafficSignRecognitionEnabled = true, trafficSignRecognitionUnavailable = false,
                ) })
                value.set(created)
            }
            controller = value.get()
            gate = field("trafficSignGeneration").get(controller) as TrafficSignWriteGate
            stateLock = field("trafficSignStateLock").get(controller)
            store = field("localObservationStore").get(controller) as LocalObservationStore
            initialGeneration = gate.incrementAndGet(true)
        }

        fun event(id: String): TrafficSignPassageEvent {
            val context = TrafficSignDetectionContext(
                wayId = "101", latitude = 48.0, longitude = 8.0, headingDegrees = 90.0,
                travelDirection = TrafficSignTravelDirection.FORWARD,
                sourceSignature = TrafficSignRuntimeSourceSignature("bundle:synthetic-anr|way:101", null),
                bundleSha256 = "a".repeat(64), countryCode = "DE",
                routeRelationGroupIds = setOf(1L), sourceRelationIds = setOf(10L),
                continuityCapable = true, matchedWayStable = true,
            )
            return TrafficSignPassageEvent(
                finalizedEventId = id, driveSessionId = session, generation = initialGeneration,
                packId = "synthetic-anr", artifactSha256 = "b".repeat(64),
                preprocessingVersion = "synthetic-rgb", calibrationId = "synthetic-calibration",
                componentRole = "direct_detector", modelComponents = listOf(TrafficSignModelComponentLineage(
                    role = "direct_detector", artifactSha256 = "b".repeat(64),
                    preprocessingVersion = "synthetic-rgb", calibrationId = "synthetic-calibration")),
                physicalTrackId = "track-$id", assemblyId = "assembly-$id", assemblyIds = listOf("assembly-$id"),
                action = TrafficSignAction(TrafficSignActionKind.POSTED_MAXIMUM, 30),
                resolution = TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.NUMERIC, 30),
                firstSeenAtUtc = at.minusSeconds(1), lastSeenAtUtc = at.minusMillis(100),
                firstSeenContext = context, lastSeenContext = context,
                passageBoundary = TrafficSignPassageBoundary(at, context), activationContext = context,
                initialRouteRelationGroupIds = setOf(1L), eligibleRouteRelationGroupIds = setOf(1L), sourceRelationIds = setOf(10L),
                evidence = listOf(TrafficSignPassageFrameEvidence("frame-$id", at.minusMillis(500), .99, .99, .99,
                    NormalizedTrafficSignBoundingBox(.7, .1, .1, .2))),
                lossEvidence = listOf(TrafficSignPassageLossEvidence("missing-$id", at, false)),
                framesSeen = 1, finalConfidence = .99, finalAccumulatedSupport = .99,
                peakConsecutiveFramesSeen = 1, lossReason = "negative_debounce", negativeFramesToCommit = 2,
                overrideEligible = true,
            )
        }

        fun captureContext() = LocalObservationCaptureContext(48.0, 8.0, 90.0, listOf("101"),
            "Synthetic city", "Synthetic road", .99, "synthetic-anr")

        fun admit(event: TrafficSignPassageEvent, markSuccessful: () -> Boolean): Boolean =
            invoke(method("admitFinalizedTrafficSignPassageWrite"), controller, event, markSuccessful) as Boolean

        fun record(event: TrafficSignPassageEvent) = recordWithAdmission(event) { markSuccessful -> admit(event, markSuccessful) }

        // Reflection is confined to selecting the new optional boundary. Keeping
        // the original six-argument API call above allows the deadlock regression
        // to compile and execute against the pre-fix store as a falsification run.
        fun recordOriginalContract(event: TrafficSignPassageEvent, permission: () -> Boolean): LocalObservation? {
            val entry = LocalObservationStore::class.java.declaredMethods.single {
                it.name == "recordComputerVisionPassageIfNeeded" && it.parameterCount in 6..7
            }.apply { isAccessible = true }
            val arguments = arrayOf<Any?>(event, event.resolution, captureContext(), gate,
                { generation: Long -> generation == gate.get() }, permission)
            // Avoid the Kotlin default-argument ABI: the same test APK can call
            // the old six-argument or fixed seven-argument production method.
            return invoke(entry, store, *arguments.copyOf(entry.parameterCount)) as LocalObservation?
        }

        fun recordWithAdmission(event: TrafficSignPassageEvent, admission: ((() -> Boolean) -> Boolean)): LocalObservation? {
            val entry = LocalObservationStore::class.java.declaredMethods.single {
                it.name == "recordComputerVisionPassageIfNeeded" && it.parameterCount == 7
            }.apply { isAccessible = true }
            return invoke(entry, store, event, event.resolution, captureContext(), gate,
                { generation: Long -> generation == gate.get() }, { true }, admission) as LocalObservation?
        }

        fun recordPausedBeforeAdmission(event: TrafficSignPassageEvent, transition: () -> Unit): LocalObservation? {
            val reached = CountDownLatch(1); val resume = CountDownLatch(1); val finished = CountDownLatch(1)
            val result = AtomicReference<LocalObservation?>(); val failure = AtomicReference<Throwable?>()
            val writer = daemon("anr-before-admission", failure) {
                result.set(recordWithAdmission(event) { markSuccessful ->
                        reached.countDown(); check(resume.await(5, TimeUnit.SECONDS))
                        admit(event, markSuccessful)
                })
                finished.countDown()
            }
            workers += writer
            try {
                writer.start(); assertTrue("Writer skipped the terminal admission boundary", reached.await(2, TimeUnit.SECONDS))
                transition()
            } finally { resume.countDown() }
            assertTrue("Writer did not finish after terminal admission", finished.await(2, TimeUnit.SECONDS))
            rethrow(failure)
            return result.get()
        }

        fun evaluateCityEntry(): Any? {
            val token = field("lookupToken").get(controller) as TrafficSignLookupMutationGate
            return invoke(method("evaluateTrafficSignSources"), controller, token.snapshot(), 1L, gate.get(), position,
                lookup(), location, TrafficSignBaseLimit(TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.NUMERIC, 50),
                    EffectiveSpeedLimitSource.BUNDLE, "synthetic-city-entry"),
                "synthetic-anr", "a".repeat(64), File(root, "synthetic.sqlite").path, "DE", null, 90.0, 2)
        }

        fun blockOcrParent(event: TrafficSignPassageEvent) {
            invoke(method("withholdUnverifiedOCRParent"), controller, setOf(event.physicalTrackId), "maxspeed:30", 30,
                "bei Nässe", event.generation, event.driveSessionId, true)
            assertEquals(true, invoke(method("blocksUnverifiedOCRParent"), controller, event.physicalTrackId))
        }

        fun assertSettingsAndCameraResponsive() {
            val settings = CountDownLatch(1); val camera = CountDownLatch(1); val main = CountDownLatch(1)
            val failure = AtomicReference<Throwable?>()
            val settingsThread = daemon("anr-settings-probe", failure) { controller.setSettingsVisible(true); settings.countDown() }
            val cameraThread = daemon("anr-camera-probe", failure) { controller.currentTrafficSignDetectionContext(); camera.countDown() }
            workers += listOf(settingsThread, cameraThread)
            settingsThread.start(); cameraThread.start(); Handler(Looper.getMainLooper()).post { main.countDown() }
            assertTrue("Settings entry waited for physical observation I/O", settings.await(1, TimeUnit.SECONDS))
            assertTrue("Camera admission waited for physical observation I/O", camera.await(1, TimeUnit.SECONDS))
            assertTrue("Main looper stopped processing work", main.await(1, TimeUnit.SECONDS))
            rethrow(failure)
        }

        fun assertDurableCounts(observations: Int, receipts: Int) {
            val path = File(root, "local_observation_store.sqlite")
            SQLiteDatabase.openDatabase(path.path, null, SQLiteDatabase.OPEN_READONLY).use { db ->
                fun count(table: String) = db.rawQuery("SELECT count(*) FROM $table", null).use { cursor -> cursor.moveToFirst(); cursor.getInt(0) }
                assertEquals(observations, count("observations")); assertEquals(receipts, count("cv_event_receipts"))
            }
        }

        fun close() {
            workers.forEach { it.join(100) }
            if (workers.none { it.isAlive }) {
                instrumentation.runOnMainSync { controller.dispose() }
                context.deleteSharedPreferences(name); root.deleteRecursively()
            } else {
                // A baseline regression may deadlock daemon workers. Never send
                // disposal through the same monitors or strand the test runner.
                (field("isDisposed").get(controller) as AtomicBoolean).set(true)
                (field("mainHandler").get(controller) as Handler).removeCallbacksAndMessages(null)
                listOf("executor", "trafficSignDeliveryExecutor", "dataManagerMetadataExecutor", "diagnosticsExecutor").forEach {
                    (field(it).get(controller) as ExecutorService).shutdownNow()
                }
            }
        }

        private fun lookup() = SpeedLookupResult(
            wayId = "101", highway = "primary", streetName = "Synthetic road", streetBaseName = "Synthetic road", streetRef = null,
            speedLimitKmh = 50, isUnlimitedSpeedLimit = false, cityName = "Synthetic city", cityPlaceName = null, cityDistrictName = null,
            insideCity = true, citySource = "settlement:synthetic:high", queryTimeMs = 0.0, candidateCount = 1, speedCandidateCount = 1,
            candidateTraces = emptyList(), nearestCandidateDistanceM = 0.0, nearestSpeedCandidateDistanceM = 0.0, isTunnelSegment = false,
            matchedEndpointProximityM = null, streetRefTokens = emptyList(), nearbyTunnelCandidateWayIds = emptySet(), nearbyTunnelCandidateRefs = emptySet(),
            portalEligibleTunnelWayIds = emptySet(), portalEligibleTunnelRefs = emptySet(), activeCorridorState = null, approachCorridorStateCandidate = null,
            usedWalkingTurnSwitch = false, usedMiniHMM = false, miniHMMCandidateCount = 0, matchHypotheses = emptyList(), selectionTrace = emptyList(),
            travelDirection = TrafficSignTravelDirection.FORWARD, inventoryBoundaryEvent = "city_entry", inventoryBoundarySignId = "synthetic-entry",
        )
    }

    private fun withHarness(body: (Harness) -> Unit) {
        val harness = Harness()
        try { body(harness) } finally { harness.close() }
    }

    companion object {
        private fun field(name: String) = ConsumerSessionController::class.java.getDeclaredField(name).apply { isAccessible = true }
        private fun method(name: String) = ConsumerSessionController::class.java.declaredMethods.single { it.name == name }.apply { isAccessible = true }
        private fun invoke(method: java.lang.reflect.Method, target: Any, vararg arguments: Any?): Any? = try {
            method.invoke(target, *arguments)
        } catch (error: InvocationTargetException) { throw error.targetException }
        private fun daemon(name: String, failure: AtomicReference<Throwable?>, block: () -> Unit) = Thread({
            try { block() } catch (error: Throwable) { failure.compareAndSet(null, error) }
        }, name).apply { isDaemon = true }
        private fun rethrow(failure: AtomicReference<Throwable?>) { failure.get()?.let { throw AssertionError("Concurrent worker failed", it) } }
    }
}
