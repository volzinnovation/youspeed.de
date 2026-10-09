package de.youspeed.android.alpha

import java.io.File
import kotlinx.serialization.json.*
import org.junit.Assert.assertSame
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class TrafficSignFusionEngineTests {
    @Test fun sharedShadowSelectionMatchesIPhoneAndRetainsOriginalIdentity() {
        val path = listOf("shared", "../shared", "../../shared").map { File(it, "tsr/applicability/shadow-selection-fixtures.json") }.first(File::exists)
        val cases = Json.parseToJsonElement(path.readText()).jsonObject.getValue("cases").jsonArray
        for (item in cases) {
            val c = item.jsonObject
            val name = c.getValue("id").jsonPrimitive.content
            val candidates = c.getValue("candidates").jsonArray.map { element ->
                val d = element.jsonObject
                val box = d.getValue("box").jsonArray.map { it.jsonPrimitive.double }
                val value = d["value"]?.jsonPrimitive?.intOrNull
                TrafficSignDetection(TrafficSignCandidate(
                    rawClassId = d.getValue("id").jsonPrimitive.content,
                    rawLabel = d.getValue("id").jsonPrimitive.content,
                    semantic = TrafficSignSemantic(TrafficSignSemanticKind.fromWire(d.getValue("semantic_kind").jsonPrimitive.content), value, if (value == null) null else "km/h"),
                    rawScore = d.getValue("raw_score").jsonPrimitive.double,
                    calibratedConfidence = d["calibrated_confidence"]?.jsonPrimitive?.doubleOrNull,
                    boundingBox = NormalizedTrafficSignBoundingBox(box[0], box[1], box[2], box[3]),
                ))
            }
            val thresholds = c.getValue("candidates").jsonArray.associate { d -> d.jsonObject.getValue("id").jsonPrimitive.content to d.jsonObject.getValue("class_threshold").jsonPrimitive.double }
            val engine = TrafficSignFusionEngine(TrafficSignThresholds(0.6, 0.8, c.getValue("unknown_threshold").jsonPrimitive.double, 2, 1500, 0.2),
                if (c.getValue("runtime_output").jsonPrimitive.content == "raw_score") TrafficSignCalibrationOutput.RAW_SCORE else TrafficSignCalibrationOutput.CALIBRATED_CONFIDENCE, thresholds)
            val withheld = c.getValue("withheld_indices").jsonArray.map { it.jsonPrimitive.int }.toSet()
            val selected = engine.selectPrimaryDetection(candidates.filterIndexed { index, _ -> index !in withheld })
            val expected = c["expected_candidate_id"]?.jsonPrimitive?.contentOrNull
            assertEquals(name, expected, selected?.candidate?.rawClassId)
            if (expected != null) assertSame(name, candidates.first { it.candidate.rawClassId == expected }, selected)
            assertEquals(name, expected, engine.observe(selected, 0).candidate?.rawClassId)
        }
    }

    @Test fun survivorSelectionRejectsBoxBeyondImageEvenWithinConstructorTolerance() {
        val outside = detection(NormalizedTrafficSignBoundingBox(0.9, 0.2, 0.10000000001, 0.2))
        val inside = detection(box(0.4, 0.2), rawClassId = "inside")
        assertSame(inside, engine().selectPrimaryDetection(listOf(outside, inside)))
        assertNull(engine().selectPrimaryDetection(listOf(outside)))
    }

    private fun endEngine(classId: String) = TrafficSignFusionEngine(
        thresholds = TrafficSignThresholds(0.45, 0.7, 0.25, 3, 1500, 0.2),
        scoreSource = TrafficSignCalibrationOutput.RAW_SCORE, classThresholds = mapOf(classId to 0.7))

    private fun endDetection(classId: String, score: Double) = detection(box(0.6, 0.3)).let {
        it.copy(candidate = it.candidate.copy(rawClassId = classId,
            semantic = TrafficSignSemantic(TrafficSignSemanticKind.RESTRICTION_END),
            rawScore = score, proposalRawScore = score, classifierRawScore = 0.99))
    }

    @Test fun endSignsContributeApproachEvidenceWithoutRelaxingConfirmation() {
        for (classId in listOf("B31", "B33-50", "C46", "282", "F08", "2.58")) {
            val engine = endEngine(classId)
            listOf(0.30, 0.36, 0.85).forEachIndexed { index, score ->
                val detection = endDetection(classId, score)
                assertTrue(detection.candidate.isQualifiedObservation(TrafficSignCalibrationOutput.RAW_SCORE, 0.25, 0.7))
                val event = engine.observe(detection, observedAtMs = index * 400L)
                assertEquals(if (index == 2) TrafficSignRecognitionState.CONFIRMED else TrafficSignRecognitionState.PROVISIONAL, event.state)
                assertEquals(index + 1, event.candidate?.evidenceFrames)
                assertEquals(score, event.candidate?.rawScore)
            }
        }
    }

    @Test fun weakEndObservationsNeverConfirmByRepetitionAlone() {
        val engine = endEngine("B31")
        repeat(10) { index ->
            assertEquals(TrafficSignRecognitionState.PROVISIONAL,
                engine.observe(endDetection("B31", 0.36), observedAtMs = index * 100L).state)
        }
    }

    @Test fun endObservationRejectsWeakMissingNonfiniteAndUncalibratedEvidence() {
        val valid = endDetection("B31", 0.3).candidate
        for (candidate in listOf(
            valid.copy(semantic = TrafficSignSemantic(TrafficSignSemanticKind.MAXIMUM_SPEED, 50, "km/h")),
            valid.copy(rawScore = 0.24, proposalRawScore = 0.24),
            valid.copy(classifierRawScore = 0.69), valid.copy(proposalRawScore = Double.NaN),
            valid.copy(classifierRawScore = Double.POSITIVE_INFINITY),
            valid.copy(proposalRawScore = null, classifierRawScore = null)
        )) assertTrue(!candidate.isQualifiedObservation(TrafficSignCalibrationOutput.RAW_SCORE, 0.25, 0.7))
        assertTrue(!valid.copy(calibratedConfidence = 0.3, proposalCalibratedConfidence = null, classifierCalibratedConfidence = null)
            .isQualifiedObservation(TrafficSignCalibrationOutput.CALIBRATED_CONFIDENCE, 0.25, 0.7))
    }

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
