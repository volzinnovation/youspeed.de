package de.youspeed.android.alpha

import java.time.Instant
import java.util.Locale
import kotlinx.serialization.json.*

/** A complete OCR attempt is one JSON line, including raw multiline text rather than display text. */
internal object TrafficSignSupplementaryOCRDiagnostics {
    fun encode(annotation: TrafficSignSupplementaryTextAnnotation, timestamp: Instant): String = buildJsonObject {
        put("timestampUTC", timestamp.toString()); put("event", "supplementary_ocr_attempt")
        put("frameId", annotation.frameId); put("physicalSignId", annotation.physicalSignId)
        put("primaryClassId", annotation.primaryClassId)
        put("primarySpeedKmh", annotation.primarySpeedKmh?.let(::JsonPrimitive) ?: JsonNull)
        put("sourceObservedAt", annotation.sourceObservedAt.toString())
        put("status", annotation.status.name.lowercase(Locale.ROOT))
        put("rawText", annotation.rawText?.let(::JsonPrimitive) ?: JsonNull)
        put("rawTextLength", annotation.rawText?.length ?: 0)
        put("engine", annotation.engine); put("modelVersion", annotation.modelVersion)
        put("generation", annotation.generation)
        put("decision", annotation.qualityDecision)
        put("passes", JsonArray(annotation.ocrPasses.map { pass -> buildJsonObject {
            put("text", pass.text); put("confidence", pass.confidence); put("scale", pass.scale); put("uncovered_ink", pass.uncoveredInk)
        } }))
        put("ocrBox", annotation.ocrBoundingBox?.let { box ->
            JsonArray(listOf(box.x, box.y, box.width, box.height).map(::JsonPrimitive))
        } ?: JsonNull)
    }.toString()
}
