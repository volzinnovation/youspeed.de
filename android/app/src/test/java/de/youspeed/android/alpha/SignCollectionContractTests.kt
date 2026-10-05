package de.youspeed.android.alpha

import java.io.File
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class SignCollectionContractTests {
    private val root = File("../../shared/tsr/collection-contract-v1")
    private fun gate() = SignCollectionContractGate { File(root, it).readBytes() }
    @Test fun pinnedVectorsAndSchemasPassWithVerifiedTransport() {
        val gate = gate(); assertTrue(gate.verified); assertTrue(gate.liveTransportAllowed)
        listOf("sighting", "manual").forEach { name ->
            val batch = SignCollectionJson.parse(File(root, "fixtures/$name-batch-v1.json").readText())
            gate.validate(batch, "batch"); batch.jsonObject.getValue("events").jsonArray.forEach { gate.validate(it, "sighting") }
        }
        listOf("correction", "consent", "deletion", "crop", "media-status").forEach { name ->
            gate.validate(SignCollectionJson.parse(File(root, "fixtures/$name-v1.json").readText()), name)
        }
        val changed = File(root, "manifest.json").readBytes() + 32.toByte()
        assertThrows(IllegalArgumentException::class.java) { SignCollectionContractGate { if (it == "manifest.json") changed else File(root, it).readBytes() } }
    }
    @Test fun backendBinary64EdgeCasesMatch() {
        val vectors = SignCollectionJson.parse(File("../../tests/tsr/collection/canonical-edge-cases.json").readText()).jsonArray
        vectors.forEach { vector ->
            val o = vector.jsonObject
            assertEquals(o.getValue("canonical").jsonPrimitive.content, SignCollectionJson.canonical(o.getValue("input")))
            assertEquals(o.getValue("sha256").jsonPrimitive.content, SignCollectionJson.digest(o.getValue("input")))
        }
    }
    @Test fun ambiguousOrUnsafeJsonCannotChangeEventIdentity() {
        listOf("{\"a\":1,\"a\":2}", "9007199254740992", "NaN", "[1,]", "1 garbage", "unquoted").forEach {
            assertThrows(Exception::class.java) { SignCollectionJson.parse(it) }
        }
        val input = JsonArray(listOf(1e23, 1e-6, -0.0, 0.30000000000000004, Double.MIN_VALUE, 1.2345678901234567).map(::JsonPrimitive))
        val result = SignCollectionJson.canonical(input)
        assertEquals("[1e+23,0.000001,0,0.30000000000000004,5e-324,1.2345678901234567]", result)
        File("/private/tmp/youspeed-collection-results").mkdirs()
        File("/private/tmp/youspeed-collection-results/kotlin-numbers.json").writeText(result)
        val unicode = JsonObject(mapOf("😀" to JsonPrimitive(2), "\uE000" to JsonPrimitive(1)))
        assertEquals("{\"\uE000\":1,\"😀\":2}", SignCollectionJson.canonical(unicode))
    }
    @Test fun cropUsesActualHeightBelowAndClipsWithoutPadding() {
        val o = SignCollectionJson.parse(File(root, "fixtures/crop-v1.json").readText()).jsonObject
        val geometry = SignCollectionCropGeometry.resolve(o.getValue("source_width").jsonPrimitive.int, o.getValue("source_height").jsonPrimitive.int, o.getValue("supplied_box").jsonObject.mapValues { it.value.jsonPrimitive.double })
        geometry.wire.forEach { (key, expected) -> assertEquals(SignCollectionJson.canonical(o.getValue(key)), SignCollectionJson.canonical(expected)) }
        val edge = SignCollectionCropGeometry.resolve(100, 100, mapOf("x" to .129, "y" to .749, "width" to .101, "height" to .201))
        assertEquals(listOf(12,74,23,95), edge.original); assertEquals(listOf(12,74,23,116), edge.requested); assertEquals(listOf(12,74,23,100), edge.actual)
        assertThrows(Exception::class.java) { SignCollectionCropGeometry.resolve(100, 100, mapOf("x" to .9, "y" to .5, "width" to .2, "height" to .1)) }
    }
    @Test fun schemasRejectUnknownFieldsAndInvalidManualProvenance() {
        val gate = gate()
        val manual = SignCollectionJson.parse(File(root, "fixtures/manual-batch-v1.json").readText()).jsonObject.getValue("events").jsonArray[0].jsonObject
        assertThrows(Exception::class.java) { gate.validate(JsonObject(manual + ("unknown_reason" to JsonPrimitive("no model"))), "sighting") }
        val scores = manual.getValue("scores").jsonObject
        assertThrows(Exception::class.java) { gate.validate(JsonObject(manual + ("scores" to JsonObject(scores + ("detector_raw" to JsonPrimitive(.9))))), "sighting") }
        assertThrows(Exception::class.java) { gate.validate(JsonObject(manual + ("schema_version" to JsonPrimitive(true))), "sighting") }
    }
    @Test fun ordinaryCollectionQualifiesAllSignClassesAndFreezesSpeechTargets() {
        val fixture = SignCollectionJson.parse(File(root, "fixtures/sighting-batch-v1.json").readText()).jsonObject.getValue("events").jsonArray[0].jsonObject
        val observer = SignCollectionObserver()
        val first = SignCollectionObserver.Detection("non-speed", listOf(.1,.1,.2,.2), fixture, "presentation-1")
        val second = first.copy(key = "supplementary", box = listOf(.6,.1,.2,.2), presentationTrack = "presentation-2")
        val at = java.time.Instant.parse("2026-10-05T10:00:00Z")
        val sightings = mutableListOf<JsonObject>()
        observer.observe(at, listOf(first, second), sightings::add)
        observer.observe(at.plusMillis(100), listOf(first, second), sightings::add)
        observer.observe(at.plusMillis(200), listOf(first, second), sightings::add)
        assertEquals(2, sightings.size)
        sightings.forEach { gate().validate(it, "sighting") }
        observer.freeze("attempt-1", "presentation-1")
        observer.observe(at.plusSeconds(3), emptyList(), sightings::add)
        val correction = observer.correction("attempt-1", "voice", at.plusSeconds(3))!!
        assertEquals(sightings[0]["event_id"], correction["target_id"])
        gate().validate(correction, "correction")
        assertNull(observer.correction("attempt-1", "voice", at.plusSeconds(3)))
        observer.freeze("attempt-after-feedback", "presentation-1")
        assertEquals(sightings[0]["event_id"], observer.correction("attempt-after-feedback", "voice", at.plusSeconds(3))!!["target_id"])
        observer.freeze("attempt-unassociated", "unknown")
        assertNull(observer.correction("attempt-unassociated", "voice", at.plusSeconds(3)))
    }
    @Test fun capabilityContractIgnoresCommercialAndExternalProcessorFlags() {
        val capabilities = buildJsonObject {
            put("contract_manifest_sha256", SignCollectionContractGate.MANIFEST_SHA256); put("schema_versions", JsonArray(listOf(JsonPrimitive(1))))
            put("one_way_uploads", true); put("durability", "live_eu_committed")
            put("limits", buildJsonObject { put("metadata_bytes", 524288); put("event_bytes", 16384) })
            put("disclosure_versions", buildJsonObject {
                put("sign_metadata", JsonArray(listOf(JsonPrimitive(SignCollectionCapabilities.metadataDisclosure))))
                put("crop_storage", JsonArray(listOf(JsonPrimitive(SignCollectionCapabilities.cropDisclosure))))
            }); put("enforcement_enabled", true); put("external_processor_enabled", true)
        }
        assertEquals(16384, SignCollectionCapabilities.decode(capabilities).eventBytes)
        assertThrows(Exception::class.java) { SignCollectionCapabilities.decode(JsonObject(capabilities + ("contract_manifest_sha256" to JsonPrimitive("changed")))) }
    }

}
