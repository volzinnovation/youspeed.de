package de.youspeed.android.alpha

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class TrafficSignFusionEngineTests {
    @Test
    fun repeatedOverlappingEvidenceProgressesFromProvisionalToConfirmed() {
        val engine = engine()

        val first = engine.observe(detection(box(0.70, 0.15), calibrated = 0.78), observedAtMs = 0)
        val second = engine.observe(detection(box(0.69, 0.14), calibrated = 0.81), observedAtMs = 400)
        val third = engine.observe(detection(box(0.68, 0.14), calibrated = 0.84), observedAtMs = 800)

        assertEquals(TrafficSignRecognitionState.PROVISIONAL, first.state)
        assertEquals(TrafficSignRecognitionState.PROVISIONAL, second.state)
        assertEquals(TrafficSignRecognitionState.CONFIRMED, third.state)
        assertEquals(3, third.candidate?.evidenceFrames)
        assertEquals(first.candidate?.trackId, third.candidate?.trackId)
        assertTrue(requireNotNull(third.fusedScore) >= 0.7)
    }

    @Test
    fun rawClassesMappedToSameSemanticShareTemporalEvidence() {
        val engine = engine()

        val first = engine.observe(
            detection(box(0.70, 0.15), rawClassId = "speed_limit_30_front"),
            observedAtMs = 0,
        )
        engine.observe(
            detection(box(0.69, 0.14), rawClassId = "speed_limit_30_alt"),
            observedAtMs = 400,
        )
        val third = engine.observe(
            detection(box(0.68, 0.14), rawClassId = "speed_limit_30_front"),
            observedAtMs = 800,
        )

        assertEquals(TrafficSignRecognitionState.CONFIRMED, third.state)
        assertEquals(first.candidate?.trackId, third.candidate?.trackId)
        assertEquals(3, third.candidate?.evidenceFrames)
    }

    @Test
    fun expiredEvidenceDoesNotConfirm() {
        val engine = engine()
        engine.observe(detection(box(0.10, 0.10)), observedAtMs = 0)
        engine.observe(detection(box(0.70, 0.10)), observedAtMs = 200)
        val third = engine.observe(detection(box(0.70, 0.10)), observedAtMs = 1_701)

        assertEquals(TrafficSignRecognitionState.PROVISIONAL, third.state)
        assertEquals(1, third.candidate?.evidenceFrames)
    }

    @Test
    fun displacedBoxesForTheSameSemanticShareOnePassageTrack() {
        val engine = engine()

        val first = engine.observe(detection(box(0.05, 0.15)), observedAtMs = 0)
        engine.observe(detection(box(0.45, 0.30)), observedAtMs = 400)
        val third = engine.observe(detection(box(0.82, 0.55)), observedAtMs = 800)

        assertEquals(TrafficSignRecognitionState.CONFIRMED, third.state)
        assertEquals(first.candidate?.trackId, third.candidate?.trackId)
        assertTrue(requireNotNull(third.candidate?.trackId).matches(Regex("[0-9a-f-]{36}")))
    }

    @Test
    fun classThresholdRejectsWeakKnownClassAndUnknownSemanticNeverCreatesTrack() {
        val engine = engine()

        val none = engine.observe(detection(box(0.2, 0.2), calibrated = 0.20), observedAtMs = 0)
        val belowClassThreshold = engine.observe(
            detection(box(0.2, 0.2), calibrated = 0.60),
            observedAtMs = 100,
        )
        val unknown = engine.observe(
            detection(box(0.2, 0.2), calibrated = 0.90).let { detection ->
                detection.copy(
                    candidate = detection.candidate.copy(
                        rawClassId = "other_sign",
                        rawLabel = "Other sign",
                        semantic = TrafficSignSemantic(TrafficSignSemanticKind.UNKNOWN, null, null),
                    ),
                )
            },
            observedAtMs = 200,
        )
        val provisional = engine.observe(detection(box(0.2, 0.2), calibrated = 0.75), observedAtMs = 300)

        assertEquals(TrafficSignRecognitionState.NO_RECOGNITION, none.state)
        assertNull(none.candidate)
        assertEquals(TrafficSignRecognitionState.NO_RECOGNITION, belowClassThreshold.state)
        assertNull(belowClassThreshold.candidate)
        assertEquals(TrafficSignRecognitionState.UNKNOWN, unknown.state)
        assertNull(unknown.candidate?.trackId)
        assertEquals(TrafficSignRecognitionState.PROVISIONAL, provisional.state)
        assertEquals(1, provisional.candidate?.evidenceFrames)
    }

    @Test
    fun calibratedModeNeverFallsBackToRawScore() {
        val engine = engine()
        val withoutCalibration = detection(box(0.2, 0.2), calibrated = 0.80).let { detection ->
            detection.copy(
                candidate = detection.candidate.copy(
                    rawScore = 0.99,
                    calibratedConfidence = null,
                ),
            )
        }

        val result = engine.observe(withoutCalibration, observedAtMs = 0)

        assertEquals(TrafficSignRecognitionState.NO_RECOGNITION, result.state)
        assertNull(result.candidate)
    }

    @Test
    fun fusionKeepsBestCropButDropsSupplementaryConditions() {
        val engine = engine()
        val wet = TrafficSignRestriction(
            TrafficSignRestrictionKind.WEATHER,
            normalizedValue = "wet",
        )
        val first = detection(
            box = box(0.50, 0.20, width = 0.05, height = 0.08),
            cropQuality = 0.2,
            assemblyId = "frame-1-assembly-1",
            conditionState = TrafficSignConditionState.RESOLVING,
        )
        val best = detection(
            box = box(0.49, 0.19, width = 0.08, height = 0.12),
            cropQuality = 0.9,
            assemblyId = "frame-2-assembly-1",
            conditionState = TrafficSignConditionState.RESOLVED,
            restrictions = listOf(wet),
        )
        val third = detection(
            box = box(0.49, 0.19, width = 0.07, height = 0.11),
            cropQuality = 0.5,
            assemblyId = "frame-3-assembly-1",
            conditionState = TrafficSignConditionState.NONE,
            restrictions = emptyList(),
        )

        val firstResult = engine.observe(first, 0)
        engine.observe(best, 300)
        val result = engine.observe(third, 600)

        assertEquals(TrafficSignRecognitionState.CONFIRMED, result.state)
        assertEquals(firstResult.candidate?.trackId, result.candidate?.trackId)
        assertEquals(best.candidate.boundingBox, result.bestCropBoundingBox)
        assertEquals("frame-3-assembly-1", result.candidate?.assemblyId)
        assertEquals(TrafficSignConditionState.NONE, result.candidate?.conditionState)
        assertTrue(result.candidate?.restrictions.orEmpty().isEmpty())
    }

    @Test
    fun rawScorePackCanConfirmWithoutCalibratedConfidence() {
        val engine = TrafficSignFusionEngine(
            thresholds = TrafficSignThresholds(
                provisional = 0.45,
                confirmed = 0.70,
                unknown = 0.25,
                confirmationFrames = 3,
                confirmationWindowMs = 1_500,
                minimumTrackIou = 0.20,
            ),
            scoreSource = TrafficSignCalibrationOutput.RAW_SCORE,
            classThresholds = mapOf("speed_limit_30" to 0.70),
        )
        val rawOnly = detection(box(0.2, 0.2), calibrated = 0.80).let { detection ->
            detection.copy(candidate = detection.candidate.copy(rawScore = 0.90, calibratedConfidence = null))
        }

        engine.observe(rawOnly, 0)
        engine.observe(rawOnly, 300)
        val result = engine.observe(rawOnly, 600)

        assertEquals(TrafficSignRecognitionState.CONFIRMED, result.state)
        assertEquals(3, result.candidate?.evidenceFrames)
    }

    private fun engine() = TrafficSignFusionEngine(
        thresholds = TrafficSignThresholds(
            provisional = 0.45,
            confirmed = 0.70,
            unknown = 0.25,
            confirmationFrames = 3,
            confirmationWindowMs = 1_500,
            minimumTrackIou = 0.20,
        ),
        scoreSource = TrafficSignCalibrationOutput.CALIBRATED_CONFIDENCE,
        classThresholds = mapOf("speed_limit_30" to 0.70),
    )

    private fun detection(
        box: NormalizedTrafficSignBoundingBox,
        rawClassId: String = "speed_limit_30",
        calibrated: Double = 0.80,
        cropQuality: Double = box.area,
        assemblyId: String? = null,
        conditionState: TrafficSignConditionState = TrafficSignConditionState.NONE,
        restrictions: List<TrafficSignRestriction> = emptyList(),
    ) = TrafficSignDetection(
        candidate = TrafficSignCandidate(
            rawClassId = rawClassId,
            rawLabel = "Maximum speed 30",
            semantic = TrafficSignSemantic(TrafficSignSemanticKind.MAXIMUM_SPEED, 30, "km/h"),
            rawScore = calibrated + 0.05,
            calibratedConfidence = calibrated,
            boundingBox = box,
            assemblyId = assemblyId,
            conditionState = conditionState,
            restrictions = restrictions,
        ),
        cropQuality = cropQuality,
    )

    private fun box(
        x: Double,
        y: Double,
        width: Double = 0.09,
        height: Double = 0.13,
    ) = NormalizedTrafficSignBoundingBox(x, y, width, height)
}
