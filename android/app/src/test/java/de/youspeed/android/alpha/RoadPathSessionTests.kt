package de.youspeed.android.alpha

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

class RoadPathSessionTests {
    private val scope = TSRApplicabilityScope("drive", "bundle", "camera", 1, 1, 1)
    private fun diagnostic(time: Double) = TSRApplicabilityDiagnostic(1,
        TSRFrameCandidateBatch(1, "frame-$time", time*1000, scope, "analyzed", emptyList(), false, 0, "model", "preprocess", null), emptyList(), emptyList())
    private fun frame(time: Double, known: Boolean = true, start: Long = 0) = RoadPathCameraFrame(
        ByteArray(128*72), 128, 72, time, "geometry", null, known, 0.0, start)

    @Test fun futureFixIsNotExposedAsCausalTrajectory() {
        val session = RoadPathSession { 1_000_000 }
        session.recordLocation(11.0, 48.0, 8.0, 0.0, 10.0, .1, .1)
        val result = Json.parseToJsonElement(session.evaluate(frame(10.0), diagnostic(10.0))).jsonObject
        assertEquals(0, result.getValue("trajectorySamples").jsonPrimitive.int)
        assertEquals("shadow", result.getValue("mode").jsonPrimitive.content)
        assertFalse(result.getValue("calibrationAvailable").jsonPrimitive.boolean)
    }

    @Test fun geometryDeadlinePublishesNoPartialOverlay() {
        val session = RoadPathSession { 60_000_000 }
        val result = Json.parseToJsonElement(session.evaluate(frame(10.0), diagnostic(10.0))).jsonObject
        assertTrue(result.getValue("geometryDeadlineExceeded").jsonPrimitive.boolean)
        assertTrue(result.getValue("boundaries").jsonArray.isEmpty())
        assertNull(session.overlay())
    }

    @Test fun totalDeadlineDiscardsAllAssociationsAfterSerialization() {
        val session = RoadPathSession { 201_000_000 }
        val result = Json.parseToJsonElement(session.evaluate(frame(10.0), diagnostic(10.0))).jsonObject
        assertTrue(result.getValue("deadlineExceeded").jsonPrimitive.boolean)
        assertEquals("added_processing_deadline", result.getValue("reason").jsonPrimitive.content)
        assertTrue(result.getValue("associations").jsonArray.isEmpty())
        assertNull(session.overlay())
    }

    @Test fun unknownCaptureClockCannotPublishLiveGeometry() {
        val session = RoadPathSession { 1_000_000 }
        val result = Json.parseToJsonElement(session.evaluate(frame(10.0, false), diagnostic(10.0))).jsonObject
        assertFalse(result.getValue("captureClockKnown").jsonPrimitive.boolean)
        assertNull(session.overlay())
    }

    @Test fun duplicateLocationStartsFreshHistoryRatherThanReinforcingMotion() {
        val session = RoadPathSession { 1_000_000 }
        repeat(2) { session.recordLocation(10.0, 48.0, 8.0, 0.0, 10.0, .1, .1) }
        val result = Json.parseToJsonElement(session.evaluate(frame(10.0), diagnostic(10.0))).jsonObject
        assertEquals(1, result.getValue("trajectorySamples").jsonPrimitive.int)
    }

    private class PausedClock {
        val entered = CountDownLatch(1)
        val resume = CountDownLatch(1)
        private val first = AtomicBoolean(true)
        fun now(): Long {
            if (first.compareAndSet(true, false)) {
                entered.countDown()
                check(resume.await(5, TimeUnit.SECONDS)) { "Test evaluator was not resumed" }
            }
            return 1_000_000L
        }
    }

    @Test fun overlayAndLocationCallbacksDoNotWaitForImageAnalysisAndSnapshotStaysFrozen() {
        val clock = PausedClock()
        val session = RoadPathSession(clock::now)
        session.recordLocation(10.0, 48.0, 8.0, 0.0, 10.0, .1, .1)
        val evaluator = Executors.newSingleThreadExecutor()
        val callbacks = Executors.newSingleThreadExecutor()
        try {
            val evaluation = evaluator.submit<String> { session.evaluate(frame(10.0), diagnostic(10.0)) }
            assertTrue(clock.entered.await(2, TimeUnit.SECONDS))
            // The evaluator remains deliberately blocked. These callbacks must complete before
            // its latch opens; an implementation holding the data lock for analysis deadlocks here.
            callbacks.submit {
                assertNull(session.overlay())
                session.recordLocation(11.0, 48.0001, 8.0, 0.0, 10.0, .1, .1)
            }.get(2, TimeUnit.SECONDS)
            assertFalse(evaluation.isDone)
            clock.resume.countDown()
            val result = Json.parseToJsonElement(evaluation.get(2, TimeUnit.SECONDS)).jsonObject
            assertEquals(listOf(10.0), result.getValue("trajectory").jsonArray.map { it.jsonObject.getValue("timeSeconds").jsonPrimitive.double })
            val next = Json.parseToJsonElement(session.evaluate(frame(11.0), diagnostic(11.0))).jsonObject
            assertEquals(listOf(10.0,11.0), next.getValue("trajectory").jsonArray.map { it.jsonObject.getValue("timeSeconds").jsonPrimitive.double })
        } finally {
            clock.resume.countDown(); evaluator.shutdownNow(); callbacks.shutdownNow()
        }
    }

    @Test fun locationClockResetDiscardsAnEvaluationAlreadyInFlight() {
        val clock = PausedClock()
        val session = RoadPathSession(clock::now)
        session.recordLocation(10.0, 48.0, 8.0, 0.0, 10.0, .1, .1)
        val evaluator = Executors.newSingleThreadExecutor()
        val callbacks = Executors.newSingleThreadExecutor()
        try {
            val evaluation = evaluator.submit<String> { session.evaluate(frame(10.0), diagnostic(10.0)) }
            assertTrue(clock.entered.await(2, TimeUnit.SECONDS))
            callbacks.submit { session.recordLocation(9.0, 48.0, 8.0, 0.0, 10.0, .1, .1) }.get(2, TimeUnit.SECONDS)
            clock.resume.countDown()
            val result = Json.parseToJsonElement(evaluation.get(2, TimeUnit.SECONDS)).jsonObject
            assertEquals("trajectory_clock_discontinuity", result.getValue("reason").jsonPrimitive.content)
            assertTrue(result.getValue("associations").jsonArray.isEmpty())
            assertFalse(result.getValue("deadlineExceeded").jsonPrimitive.boolean)
            assertNull(session.overlay())
        } finally {
            clock.resume.countDown(); evaluator.shutdownNow(); callbacks.shutdownNow()
        }
    }

    @Test fun overlayInvalidationCannotBeUndoneByAnEvaluationAlreadyInFlight() {
        val clock = PausedClock()
        val session = RoadPathSession(clock::now)
        val evaluator = Executors.newSingleThreadExecutor()
        val callbacks = Executors.newSingleThreadExecutor()
        try {
            val evaluation = evaluator.submit<String> { session.evaluate(frame(10.0), diagnostic(10.0)) }
            assertTrue(clock.entered.await(2, TimeUnit.SECONDS))
            callbacks.submit { session.invalidateOverlay() }.get(2, TimeUnit.SECONDS)
            clock.resume.countDown()
            val result = Json.parseToJsonElement(evaluation.get(2, TimeUnit.SECONDS)).jsonObject
            assertFalse(result.getValue("deadlineExceeded").jsonPrimitive.boolean)
            assertNull(session.overlay())
            session.evaluate(frame(10.1), diagnostic(10.1))
            assertNotNull(session.overlay())
        } finally {
            clock.resume.countDown(); evaluator.shutdownNow(); callbacks.shutdownNow()
        }
    }
}
