package de.youspeed.android.alpha

import java.io.File
import java.time.Instant
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import org.junit.Assume.assumeTrue

class SignCollectionRepeatCropTests {
    private val root = File("../../shared/tsr/collection-contract-v1")
    private val fixture = SignCollectionJson.parse(File(root, "fixtures/sighting-batch-v1.json").readText())
        .jsonObject.getValue("events").jsonArray[0].jsonObject
    private val start = Instant.ofEpochSecond(1_770_000_000)
    private fun detection(size: Double = .2, x: Double = .1) =
        SignCollectionObserver.Detection("sign", listOf(x, .1, size, size), fixture, "display")

    @Test fun recordedDashcamTraceMatchesSwiftCropSelection() {
        val path = System.getenv("YOUSPEED_REPEAT_CROP_REPLAY_TRACE")
        assumeTrue("Optional private replay trace", !path.isNullOrBlank())
        val observer = SignCollectionObserver()
        var frames = 0
        File(path!!).forEachLine { line ->
            val row = SignCollectionJson.parse(line).jsonObject
            val seconds = row.getValue("frame_seconds").jsonPrimitive.double
            val at = Instant.ofEpochSecond(0, Math.round(seconds * 1_000_000_000))
            val detections = row.getValue("detections").jsonArray.map { value ->
                val detection = value.jsonObject
                SignCollectionObserver.Detection(detection.getValue("key").jsonPrimitive.content,
                    detection.getValue("box").jsonArray.map { it.jsonPrimitive.double }, fixture, null)
            }
            var count = 0
            observer.observe(at, detections, captureCrop = { candidate ->
                assertEquals(at, candidate.frameAt)
                assertTrue(detections.any { it.box == candidate.box })
                if (count >= 4) SignCollectionObserver.CropCaptureResult.SKIPPED
                else { count++; SignCollectionObserver.CropCaptureResult.STORED }
            }, commit = {})
            assertEquals("Recorded frame $seconds", row.getValue("sequence_count").jsonPrimitive.int, count)
            frames++
        }
        assertTrue("Trace has multiple analyzed frames", frames > 1)
    }

    @Test fun sharedCadenceGrowthRetryAndOrderingVectorsKeepOneSighting() {
        val vectors = SignCollectionJson.parse(File("../../tests/tsr/collection/repeat-crops-v1.json").readText()).jsonObject
        val gate = SignCollectionContractGate { File(root, it).readBytes() }
        for (scenario in vectors.getValue("scenarios").jsonArray) {
            val name = scenario.jsonObject.getValue("name").jsonPrimitive.content
            val observer = SignCollectionObserver()
            val sightings = mutableListOf<JsonObject>()
            val attempts = mutableListOf<SignCollectionObserver.CropCandidate>()
            var stored = 0
            for (step in scenario.jsonObject.getValue("frames").jsonArray) {
                val row = step.jsonObject
                val ms = row.getValue("milliseconds").jsonPrimitive.long
                observer.observe(start.plusMillis(ms), listOf(detection(row.getValue("size").jsonPrimitive.double)), captureCrop = { candidate ->
                    attempts += candidate
                    when (row.getValue("result").jsonPrimitive.content) {
                        "stored" -> { stored++; SignCollectionObserver.CropCaptureResult.STORED }
                        "failed" -> SignCollectionObserver.CropCaptureResult.FAILED
                        else -> SignCollectionObserver.CropCaptureResult.SKIPPED
                    }
                }, commit = sightings::add)
                assertEquals("$name at $ms ms: attempts", row.getValue("attempts").jsonPrimitive.int, attempts.size)
                assertEquals("$name at $ms ms: stored", row.getValue("stored").jsonPrimitive.int, stored)
                assertEquals("one sighting", if (ms >= 100) 1 else 0, sightings.size)
                attempts.lastOrNull()?.let { assertEquals(sightings[0].getValue("event_id").jsonPrimitive.content, it.observationId) }
            }
            gate.validate(sightings.single(), "sighting")
            assertEquals(start.plusMillis(100).toString(), sightings.single().getValue("representative_frame_at").jsonPrimitive.content)
            observer.freeze("feedback", "display")
            assertEquals(sightings.single()["event_id"], observer.correction("feedback", "voice", start.plusSeconds(5))!!["target_id"])
        }
    }

    @Test fun perFrameCapacityRetainsIndependentSameClassSignsAndResets() {
        val observer = SignCollectionObserver()
        val sightings = mutableListOf<JsonObject>()
        val captured = mutableListOf<SignCollectionObserver.CropCandidate>()
        val detections = (0 until 5).map { detection(size = .1, x = it * .18).copy(presentationTrack = null) }
        fun sample(ms: Long) {
            var used = 0
            observer.observe(start.plusMillis(ms), detections, captureCrop = { candidate ->
                if (used >= 4) SignCollectionObserver.CropCaptureResult.SKIPPED
                else { used++; captured += candidate; SignCollectionObserver.CropCaptureResult.STORED }
            }, commit = sightings::add)
        }
        sample(0); sample(100); sample(200)
        assertEquals(5, sightings.size); assertEquals(5, captured.size)
        assertEquals(5, captured.map { it.observationId }.toSet().size)
        observer.observe(start.plusMillis(2201), emptyList(), commit = sightings::add)
        sample(2300); sample(2400)
        assertEquals(10, sightings.size); assertEquals(9, captured.size)
        observer.reset(); sample(2500); sample(2600)
        assertEquals(15, sightings.size); assertEquals(13, captured.size)
    }

    @Test fun cropWaitsForDurableSightingAndUsesItsCurrentFrame() {
        val observer = SignCollectionObserver()
        val sightings = mutableListOf<JsonObject>()
        val captured = mutableListOf<SignCollectionObserver.CropCandidate>()
        observer.observe(start, listOf(detection()), commit = sightings::add)
        assertThrows(IllegalStateException::class.java) {
            observer.observe(start.plusMillis(100), listOf(detection()), captureCrop = { candidate ->
                captured += candidate; SignCollectionObserver.CropCaptureResult.STORED
            }) { error("storage unavailable") }
        }
        assertTrue(captured.isEmpty())
        for ((ms, size) in listOf(200L to .2, 700L to .3)) {
            observer.observe(start.plusMillis(ms), listOf(detection(size)), captureCrop = { candidate ->
                assertEquals(1, sightings.size)
                captured += candidate; SignCollectionObserver.CropCaptureResult.STORED
            }, commit = sightings::add)
        }
        assertEquals(1, sightings.size); assertEquals(2, captured.size)
        assertEquals(captured[0].observationId, captured[1].observationId)
        assertEquals(start.plusMillis(700), captured[1].frameAt)
        assertEquals(listOf(.1, .1, .3, .3), captured[1].box)
    }
}
