package de.youspeed.android.alpha

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class TrafficSignContractTests {
    @Test
    fun decodesAndValidatesSharedDirectPack() {
        val pack = fixture("de-direct-pack-v1.json").readText().let(TrafficSignModelPackJson::decode)

        assertEquals(1, pack.schemaVersion)
        assertEquals("de-speed-signs-fixture-v1", pack.packId)
        assertEquals(listOf("DE"), pack.countries)
        assertEquals(TrafficSignPipeline.DIRECT_DETECTION, pack.pipeline)
        assertEquals(TrafficSignArtifactFormat.TFLITE, requireNotNull(pack.androidArtifact()).format)
        assertEquals("yolo_nms_xyxy_scores_classes_v1", pack.androidArtifact()?.outputSchema)
        assertNull(pack.classifier)
        assertTrue(TrafficSignModelPackValidator.validate(pack).isEmpty())
        assertTrue(TrafficSignRuntimeFoundation.state is TrafficSignRuntimeState.Unavailable)
    }

    @Test
    fun decodesSharedRecognitionEventsIntoOneNormalizedContract() {
        val pack = fixture("de-direct-pack-v1.json").readText().let(TrafficSignModelPackJson::decode)
        val events = fixture("recognition-events-v1.json").readText().let(TrafficSignRecognitionJson::decodeList)

        assertEquals(listOf(TrafficSignRecognitionState.PROVISIONAL, TrafficSignRecognitionState.CONFIRMED), events.map { it.state })
        assertTrue(events.all { TrafficSignRecognitionJson.validate(it, pack).isEmpty() })
        val candidate = requireNotNull(events.last().candidate)
        assertEquals(TrafficSignSemanticKind.MAXIMUM_SPEED, candidate.semantic.kind)
        assertEquals(30, candidate.semantic.value)
        assertEquals(TrafficSignConditionState.RESOLVED, candidate.conditionState)
        assertEquals(TrafficSignRestrictionKind.WEATHER, candidate.restrictions.single().kind)
        assertEquals("wet", candidate.restrictions.single().normalizedValue)
        assertEquals("fixture-assembly-1", candidate.assemblyId)
        assertEquals("123456", events.last().roadContext?.wayId)
        assertEquals(TrafficSignTravelDirection.FORWARD, events.last().roadContext?.travelDirection)
    }

    @Test
    fun proposalPipelineRequiresClassifier() {
        val invalid = fixture("de-direct-pack-v1.json").readText()
            .replace("\"pipeline\": \"direct_detection\"", "\"pipeline\": \"proposal_classification\"")

        val failure = assertThrows(IllegalArgumentException::class.java) {
            TrafficSignModelPackJson.decode(invalid)
        }

        assertTrue(failure.message.orEmpty().contains("requires a classifier"))
    }

    @Test
    fun maximumSpeedRequiresValueAndUnit() {
        val invalid = fixture("de-direct-pack-v1.json").readText()
            .replace("\"unit\": \"km/h\"", "\"unit\": null")

        val failure = assertThrows(IllegalArgumentException::class.java) {
            TrafficSignModelPackJson.decode(invalid)
        }

        assertTrue(failure.message.orEmpty().contains("maximum_speed requires km/h or mph"))
    }

    @Test
    fun assemblyAndRoadContextSurviveSharedJsonDecoding() {
        val event = TrafficSignRecognitionJson.decodeList(fixture("recognition-events-v1.json").readText()).first()
        val candidate = requireNotNull(event.candidate)

        assertEquals("fixture-assembly-1", candidate.assemblyId)
        assertEquals(TrafficSignConditionState.RESOLVING, candidate.conditionState)
        assertTrue(candidate.restrictions.isEmpty())
        assertEquals("123456", event.roadContext?.wayId)
        assertEquals(82.0, event.roadContext?.headingDegrees)
        assertEquals("bundle:fixture-v1|way:123456|maxspeed:50", event.roadContext?.sourceSignature?.osmRevision)
    }

    @Test
    fun normalizedBoundingBoxIouUsesTopLeftUnitCoordinates() {
        val left = NormalizedTrafficSignBoundingBox(x = 0.1, y = 0.1, width = 0.4, height = 0.4)
        val right = NormalizedTrafficSignBoundingBox(x = 0.3, y = 0.1, width = 0.4, height = 0.4)
        val separate = NormalizedTrafficSignBoundingBox(x = 0.8, y = 0.8, width = 0.1, height = 0.1)

        assertEquals(1.0 / 3.0, left.intersectionOverUnion(right), 1e-9)
        assertEquals(0.0, left.intersectionOverUnion(separate), 0.0)
        assertFalse(left.intersectionOverUnion(right).isNaN())
        assertThrows(IllegalArgumentException::class.java) {
            NormalizedTrafficSignBoundingBox(x = 0.9, y = 0.9, width = 0.2, height = 0.2)
        }
    }

    private fun fixture(name: String): File {
        val candidates = listOf(
            File("shared/tsr/fixtures/$name"),
            File("../shared/tsr/fixtures/$name"),
            File("../../shared/tsr/fixtures/$name"),
        )
        return candidates.firstOrNull { it.exists() }
            ?: error("Unable to locate shared TSR fixture $name from ${System.getProperty("user.dir")}")
    }
}
