package de.youspeed.android.alpha

import java.time.Instant
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class TrafficSignSupplementaryOCRDiagnosticsTests {
    private val at = Instant.parse("2026-10-16T10:00:00Z")
    private fun annotation(raw: String?) = TrafficSignSupplementaryTextAnnotation("hazard:school", null, "physical", "frame",
        at, at, raw, null, if (raw == null) TrafficSignSupplementaryOCRStatus.NO_TEXT else TrafficSignSupplementaryOCRStatus.READ,
        NormalizedTrafficSignBoundingBox(.1, .1, .2, .2))

    @Test fun rawTextCannotForgeAnotherTripLogRecordAndUnknownClausesRemainUnchanged() {
        val raw = "Mo-Fr\n6:30-17:30h\naußer \\\"Anlieger\\\"\r\ntimestamp=forged\u0000\tbei Nässe"
        val line = TrafficSignSupplementaryOCRDiagnostics.encode(annotation(raw), at)
        assertFalse(line.contains('\n')); assertFalse(line.contains('\r')); assertFalse(line.contains('\u0000'))
        val decoded = Json.parseToJsonElement(line).jsonObject
        assertEquals(raw, decoded.getValue("rawText").jsonPrimitive.content)
        assertEquals("supplementary_ocr_attempt", decoded.getValue("event").jsonPrimitive.content)
        assertEquals(raw.length, decoded.getValue("rawTextLength").jsonPrimitive.int)
    }

    @Test fun fullContractLengthIsLoggedAndConsentedAnnotationKeepsTheSameRawText() {
        val tail = "\nbei Nässe; außer Anlieger \\\"A\\\""
        val raw = "x".repeat(4096 - tail.length) + tail
        val source = annotation(raw)
        assertEquals(4096, raw.length)
        val logged = Json.parseToJsonElement(TrafficSignSupplementaryOCRDiagnostics.encode(source, at)).jsonObject
        assertEquals(raw, logged.getValue("rawText").jsonPrimitive.content)
        val collected = SupplementaryOCRAnnotation(source.primaryClassId, null, source.physicalSignId, source.frameId, at, at,
            source.rawText, SupplementaryOCRAnnotation.Status.READ, SupplementaryOCRAnnotation.Box(.1, .1, .2, .2), null,
            source.engine, source.modelVersion, null)
        val roundTrip = Json.parseToJsonElement(collected.wire.toString()).jsonObject
        assertEquals(raw, roundTrip.getValue("raw_text").jsonPrimitive.content)
    }

    @Test fun noTextRemainsExplicitlyNull() {
        val decoded = Json.parseToJsonElement(TrafficSignSupplementaryOCRDiagnostics.encode(annotation(null), at)).jsonObject
        assertEquals(JsonNull, decoded["rawText"])
        assertEquals("no_text", decoded.getValue("status").jsonPrimitive.content)
    }
}
