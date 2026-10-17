package de.youspeed.android.alpha

import java.time.Instant
import org.junit.Assert.*
import org.junit.Test

class TrafficSignSupplementaryRetryTests {
    private val start = Instant.parse("2026-10-16T10:00:00Z")
    private val scope = TrafficSignSupplementaryScope(7, "drive")
    private fun primary(width: Double = .1, height: Double = .1, numeric: Boolean = false) = TrafficSignCandidate(
        if (numeric) "maxspeed:30" else "hazard:school", "sign",
        if (numeric) TrafficSignSemantic(TrafficSignSemanticKind.MAXIMUM_SPEED, 30, "km/h") else TrafficSignSemantic(TrafficSignSemanticKind.UNKNOWN),
        .95, null, NormalizedTrafficSignBoundingBox(.1, .05, width, height))
    private fun TrafficSignSupplementaryTextTracker.frame(c: TrafficSignCandidate, at: Long, id: String = "physical",
        deferred: Boolean = false, generation: Long = 7, frameId: String = "frame-$at") =
        begin(c, id, frameId, start.plusMillis(at), scope.copy(generation = generation), true, 2, 960, 540, deferred)

    @Test fun undersizeAndCriticalDeferralsDoNotConsumeTheAttemptBudget() {
        val tracker = TrafficSignSupplementaryTextTracker()
        assertNull(tracker.frame(primary(.03, .04, true), 0).request)
        assertNull(tracker.frame(primary(.03, .04, true), 201).request)
        assertNull(tracker.frame(primary(numeric = true), 400, deferred = true).request)
        val attempt = requireNotNull(tracker.frame(primary(numeric = true), 700).request)
        assertEquals(1, attempt.attemptNumber)
        assertEquals(start, attempt.firstSeenAt)
    }

    @Test fun fractionalCropEdgesCannotAdmitFortySevenPixelsAsFortyEight() {
        // Exact primary geometry from a failed 17 October drive attempt: separately
        // rounding its left/right edges gave 48px, while Bitmap retained only 47px.
        val tooSmall = primary(numeric = true).copy(boundingBox = NormalizedTrafficSignBoundingBox(
            .571162109375, .52197265625, .029296875, .0400390625))
        val tracker = TrafficSignSupplementaryTextTracker()
        assertNull(supplementaryOCRContextPixelRect(tooSmall.boundingBox, 1600, 1200))
        assertNull(supplementaryTextPixelRect(tooSmall.boundingBox, 1600, 1200))
        assertNull(tracker.begin(tooSmall, "physical", "small", start, scope, true, 2, 1600, 1200).request)

        val clearer = tooSmall.copy(boundingBox = tooSmall.boundingBox.copy(width = .03))
        val admitted = requireNotNull(tracker.begin(clearer, "physical", "clearer", start.plusMillis(400),
            scope, true, 2, 1600, 1200).request)
        assertEquals(1, admitted.attemptNumber)
        val crop = requireNotNull(supplementaryOCRContextPixelRect(admitted.candidate.boundingBox, 1600, 1200))
        val lower = requireNotNull(supplementaryTextPixelRect(admitted.candidate.boundingBox, 1600, 1200))
        assertEquals(48, crop.width)
        assertEquals(crop.width, lower.width)
        assertEquals(crop.y + crop.height / 2, lower.y)
        assertEquals(crop.height / 2, lower.height)
    }

    @Test fun pictogramsNeedTwoIndependentFramesAndNewPhysicalSignsResetTheirEvidence() {
        val tracker = TrafficSignSupplementaryTextTracker()
        assertNull(tracker.frame(primary(), 0).request)
        assertNull(tracker.frame(primary(), 100, frameId = "frame-0").request)
        val request = requireNotNull(tracker.frame(primary(), 201).request)
        assertNull(request.annotation("Schule").primarySpeedKmh)
        assertTrue(request.annotation("Schule").matchesPictogram("hazard:school"))
        assertFalse(request.annotation("Schule").matchesNumeric(30, true))
        tracker.finish(request, request.annotation("Schule"))
        assertNull(tracker.frame(primary(), 400, id = "new-physical").presentation)
        assertNotNull(tracker.frame(primary(), 601, id = "new-physical").request)
    }

    @Test fun retryNeedsBothSpacingAndMaterialNativePixelGrowthAndPreservesSuccessfulText() {
        val tracker = TrafficSignSupplementaryTextTracker()
        val first = requireNotNull(tracker.frame(primary(numeric = true), 0).request)
        tracker.finish(first, first.annotation(null))
        assertNull(tracker.frame(primary(.2, .2, true), 201).request)
        assertNull(tracker.frame(primary(numeric = true), 400).request)
        val later = requireNotNull(tracker.frame(primary(.2, .2, true), 600).request)
        assertEquals(2, later.attemptNumber)
        val successful = requireNotNull(tracker.finish(later, later.annotation("Mo-Fr 6-18h")))
        assertEquals("frame-600", successful.presentation?.frameId)
        val larger = requireNotNull(tracker.frame(primary(.4, .35, true), 1000).request)
        val failed = requireNotNull(tracker.finish(larger, larger.annotation(null, failed = true)))
        assertEquals("Mo-Fr 6-18h", failed.presentation?.rawText)
        assertEquals(TrafficSignSupplementaryOCRStatus.FAILED, failed.latestAttempt?.status)
        assertEquals("frame-1000", failed.latestAttempt?.frameId)
        assertEquals(start.plusMillis(600), failed.presentation?.sourceObservedAt)
    }

    @Test fun explicitTrackSurvivesRapidGrowthButStopsAtSixAttemptsAndGenerationClearsEverything() {
        val tracker = TrafficSignSupplementaryTextTracker()
        repeat(7) { i ->
            val factor = Math.pow(1.4, i.toDouble())
            val result = tracker.frame(primary(.05 * factor, .06 * factor, true), i * 400L)
            if (i < 6) {
                val request = requireNotNull(result.request)
                assertEquals(i + 1, request.attemptNumber)
                tracker.finish(request, request.annotation(null))
            } else assertNull(result.request)
        }
        val next = requireNotNull(tracker.frame(primary(numeric = true), 3000, generation = 8).request)
        assertEquals(1, next.attemptNumber)
        assertEquals(start.plusMillis(3000), next.firstSeenAt)
    }
}
