package de.youspeed.android.alpha

import java.io.File
import java.time.Instant
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class SignCollectionPhoneRoadMatchTests {
    @Test fun cropContractValidatesOptionalMatchConsistencyAndInt64Range() {
        val root = File("../../shared/tsr/collection-contract-v1")
        val gate = SignCollectionContractGate { File(root, it).readBytes() }
        val original = Json.parseToJsonElement(File(root, "fixtures/crop-v1.json").readText()).jsonObject
        val fix = Instant.parse("2026-10-02T09:55:00Z")
        val match = SignCollectionPhoneRoadMatch.capture("9007199254740993", "fixture", "a".repeat(64), fix, "unknown", false)!!.metadata(fix.plusMillis(500)).jsonObject
        val crop = JsonObject(original + mapOf("phone_road_match" to match, "source_frame_at" to JsonPrimitive(fix.plusMillis(500).toString())))
        gate.validate(crop, "crop")
        gate.validate(JsonObject(crop + ("phone_road_match" to JsonNull)), "crop")
        gate.validate(JsonObject(crop - "phone_road_match"), "crop")
        for (bad in listOf(JsonObject(match + ("frame_match_delta_ms" to JsonPrimitive(0))),
                           JsonObject(match + ("osm_way_id" to JsonPrimitive("9223372036854775808"))))) {
            assertThrows(Exception::class.java) { gate.validate(JsonObject(crop + ("phone_road_match" to bad)), "crop") }
        }
        File(signCollectionTestOutputDirectory(), "kotlin-phone-road-match-crop.json").writeText(SignCollectionJson.canonical(crop))
    }

    @Test fun sharedOriginalMatchVectorsPreserveSignedAgeAndExactStringIdentity() {
        val vectors = Json.parseToJsonElement(File("../../tests/tsr/collection/phone-road-match-vectors.json").readText()).jsonObject["cases"]!!.jsonArray
        for (scenario in vectors) {
            val row = scenario.jsonObject; val v = row["input"]!!.jsonObject
            fun text(key: String) = v[key]?.jsonPrimitive?.contentOrNull
            val fix = v["matched_fix_ms"]?.jsonPrimitive?.longOrNull?.let(Instant::ofEpochMilli)
            val frame = Instant.ofEpochMilli(v["frame_ms"]!!.jsonPrimitive.long)
            val match = SignCollectionPhoneRoadMatch.capture(text("osm_way_id"), text("bundle_version"), text("bundle_db_sha256"), fix,
                text("travel_direction")!!, v["matched_way_stable"]!!.jsonPrimitive.boolean)
            val value = match?.metadata(frame) ?: JsonNull
            assertEquals(row["id"].toString(), row["accepted"]!!.jsonPrimitive.boolean, value != JsonNull)
            if (value != JsonNull) {
                assertEquals(text("osm_way_id"), value.jsonObject["osm_way_id"]!!.jsonPrimitive.content)
                assertEquals(frame.toEpochMilli() - fix!!.toEpochMilli(), value.jsonObject["frame_match_delta_ms"]!!.jsonPrimitive.long)
            }
        }
        assertNull(SignCollectionPhoneRoadMatch.capture("1", "b", "a".repeat(64), Instant.MAX, "unknown", false))
    }
}
