package de.youspeed.android.alpha

import java.io.File
import java.time.Instant
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class SupplementaryOCRAnnotationTests {
    private val root = File("../../shared/tsr/collection-contract-v1")
    private val at = Instant.parse("2026-10-16T08:00:00Z")
    private fun gate() = SignCollectionContractGate { File(root, it).readBytes() }
    private fun fixture() = SignCollectionJson.parse(File(root, "fixtures/sighting-batch-v1.json").readText())
        .jsonObject.getValue("events").jsonArray[0].jsonObject
    private fun annotation(raw: String? = "Mo–Fr\n22–6 h\nbei Nässe", status: SupplementaryOCRAnnotation.Status = SupplementaryOCRAnnotation.Status.READ) =
        SupplementaryOCRAnnotation("maxspeed:30", 30, "physical-1", "ocr-frame-2", at.plusMillis(200), at, raw, status,
            SupplementaryOCRAnnotation.Box(.1, .1, .2, .2), SupplementaryOCRAnnotation.Box(.1, .3, .2, .2),
            "mlkit-latin", "16.0.1", null)

    @Test fun unparsedRawTextSurvivesSightingAndCropContractWithoutChangingClassification() {
        val annotation = annotation(); val original = fixture()
        val sighting = JsonObject(original + ("supplementary_ocr" to annotation.wire))
        gate().validate(sighting, "sighting")
        assertEquals(original.getValue("classification"), sighting.getValue("classification"))
        val saved = SignCollectionJson.parse(SignCollectionJson.canonical(sighting)).jsonObject.getValue("supplementary_ocr").jsonObject
        assertEquals("Mo–Fr\n22–6 h\nbei Nässe", saved.getValue("raw_text").jsonPrimitive.content)
        assertEquals(JsonNull, saved["parsed_time_window"])
        val crop = SignCollectionJson.parse(File(root, "fixtures/crop-v1.json").readText()).jsonObject
        gate().validate(JsonObject(crop + ("supplementary_ocr" to annotation.wire)), "crop")
    }

    @Test fun rejectedRawReadSurvivesConsentContractWithoutATimeWindow() {
        val value = annotation("Mo-Fr\n6:30-17:20 h", SupplementaryOCRAnnotation.Status.NO_TEXT)
        gate().validate(JsonObject(fixture() + ("supplementary_ocr" to value.wire)), "sighting")
        assertEquals("Mo-Fr\n6:30-17:20 h", value.wire.getValue("raw_text").jsonPrimitive.content)
        assertEquals(JsonNull, value.wire["parsed_time_window"])
    }

    @Test fun noTextAndFailureRemainExplicitAndMatchingRejectsOtherSigns() {
        for (status in listOf(SupplementaryOCRAnnotation.Status.NO_TEXT, SupplementaryOCRAnnotation.Status.FAILED)) {
            val value = annotation(null, status)
            gate().validate(JsonObject(fixture() + ("supplementary_ocr" to value.wire)), "sighting")
            assertEquals(JsonNull, value.wire["raw_text"])
        }
        val value = annotation()
        assertTrue(value.matches("maxspeed:30", 30, listOf(.1, .1, .2, .2)))
        assertFalse(value.matches("maxspeed:50", 30, listOf(.1, .1, .2, .2)))
        assertFalse(value.matches("maxspeed:30", 50, listOf(.1, .1, .2, .2)))
        assertFalse(value.matches("maxspeed:30", 30, listOf(.7, .7, .2, .2)))
    }

    @Test fun secondFrameCommitsRawAnnotationAndLaterCropsKeepOriginalOCRFrame() {
        val observer = SignCollectionObserver(); val annotation = annotation()
        val first = SignCollectionObserver.Detection("maxspeed:30", listOf(.1, .1, .2, .2), fixture(), "primary")
        val second = first.copy(supplementaryOCR = annotation)
        val sightings = mutableListOf<JsonObject>(); val crops = mutableListOf<SignCollectionObserver.CropCandidate>()
        val capture: (SignCollectionObserver.CropCandidate) -> SignCollectionObserver.CropCaptureResult = { crops += it; SignCollectionObserver.CropCaptureResult.STORED }
        observer.observe(at, listOf(first), captureCrop = capture, commit = sightings::add)
        assertTrue(sightings.isEmpty())
        observer.observe(at.plusMillis(200), listOf(second), captureCrop = capture, commit = sightings::add)
        observer.observe(at.plusMillis(800), listOf(first), captureCrop = capture, commit = sightings::add)
        assertEquals(1, sightings.size); assertEquals(2, crops.size)
        assertEquals(annotation.rawText, sightings.single().getValue("supplementary_ocr").jsonObject.getValue("raw_text").jsonPrimitive.content)
        crops.forEach { assertEquals("ocr-frame-2", it.supplementaryOCR?.frameId); assertEquals(at.plusMillis(200), it.supplementaryOCR?.observedAt) }
        assertEquals(at.plusMillis(800), crops.last().frameAt)
        assertEquals(crops.first().observationId, crops.last().observationId)
    }

    @Test fun tinyConfirmedSightingCollectsBeforeOCRAndLaterAttemptsAreImmutableAndDeduplicated() {
        val observer = SignCollectionObserver()
        val base = fixture()
        val payload = JsonObject(base + ("classification" to JsonObject(base.getValue("classification").jsonObject +
            mapOf("model_label" to JsonPrimitive("maxspeed:30"), "value" to JsonPrimitive(30)))))
        val detection = SignCollectionObserver.Detection("numeric", listOf(.1,.1,.2,.2), payload, "primary")
        val sightings = mutableListOf<JsonObject>(); val events = mutableListOf<JsonObject>()
        val crops = mutableListOf<SignCollectionObserver.CropCandidate>()
        val capture: (SignCollectionObserver.CropCandidate) -> SignCollectionObserver.CropCaptureResult = { crops += it; SignCollectionObserver.CropCaptureResult.STORED }
        observer.observe(at, listOf(detection), frameId = "frame-1", commit = sightings::add)
        observer.observe(at.plusMillis(200), listOf(detection), frameId = "ocr-frame-2", captureCrop = capture, commit = sightings::add)
        assertEquals(1, sightings.size); assertNull(sightings.single()["supplementary_ocr"])
        val original = SignCollectionJson.canonical(sightings.single())
        val first = annotation(null, SupplementaryOCRAnnotation.Status.NO_TEXT)
        observer.recordSupplementaryOCR(first, at.plusMillis(300), events::add)
        observer.recordSupplementaryOCR(first, at.plusMillis(400), events::add)
        observer.observe(at.plusMillis(800), listOf(detection), frameId = "clear-frame-3", commit = sightings::add)
        val clearer = annotation("22–6 h").copy(frameId = "clear-frame-3", observedAt = at.plusMillis(800))
        observer.recordSupplementaryOCR(clearer, at.plusMillis(900), events::add)
        observer.observe(at.plusMillis(1400), listOf(detection), frameId = "frame-4", captureCrop = capture, commit = sightings::add)
        assertEquals(2, events.size); assertEquals(1, sightings.size)
        assertEquals(original, SignCollectionJson.canonical(sightings.single()))
        assertEquals(2, sightings.single().getValue("evidence").jsonObject.getValue("analyzed_frames").jsonPrimitive.int)
        events.forEach { event ->
            gate().validate(event, "media-status")
            assertEquals("exact", event.getValue("association_status").jsonPrimitive.content)
            assertEquals(sightings.single().getValue("event_id"), event["observation_id"])
            assertEquals(JsonNull, event["crop_id"])
        }
        assertNotEquals(events[0]["ocr_attempt_id"], events[1]["ocr_attempt_id"])
        assertEquals("clear-frame-3", crops.last().supplementaryOCR?.frameId)
        assertEquals("22–6 h", crops.last().supplementaryOCR?.rawText)
    }

    @Test fun unresolvedAttemptAndResetNeverInventAnObservationAssociation() {
        val observer = SignCollectionObserver(); val events = mutableListOf<JsonObject>()
        observer.recordSupplementaryOCR(annotation(), at.plusSeconds(1), events::add)
        gate().validate(events.single(), "media-status")
        assertEquals(JsonNull, events.single()["observation_id"])
        assertEquals("unresolved", events.single().getValue("association_status").jsonPrimitive.content)
        observer.reset()
        observer.recordSupplementaryOCR(annotation(), at.plusSeconds(1), events::add)
        assertEquals(2, events.size)
        assertEquals(events[0]["ocr_attempt_id"], events[1]["ocr_attempt_id"])
        assertNotEquals(events[0]["event_id"], events[1]["event_id"])
        for (change in listOf(mapOf("association_status" to JsonPrimitive("exact")),
            mapOf("created_at" to JsonPrimitive(at.toString())), mapOf("status" to JsonPrimitive("expired")))) {
            assertTrue(runCatching { gate().validate(JsonObject(events[0] + change), "media-status") }.isFailure)
        }
    }

    @Test fun pictogramNullableSpeedPreservesRawTextAndClassGeometryMatching() {
        val value = annotation("Schule").copy(primaryClassId = "hazard:school", primarySpeedKmh = null)
        assertEquals(JsonNull, value.wire["primary_speed_kmh"])
        assertTrue(value.matches("hazard:school", 100, listOf(.1,.1,.2,.2)))
        assertFalse(value.matches("hazard:children", null, listOf(.1,.1,.2,.2)))
        gate().validate(JsonObject(fixture() + ("supplementary_ocr" to value.wire)), "sighting")
    }
}
