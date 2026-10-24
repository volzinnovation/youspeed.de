package de.youspeed.android.alpha

import java.time.Instant
import kotlinx.serialization.json.*

/** Immutable collection provenance. It never replaces a model label or evaluates a road rule. */
internal data class SupplementaryOCRAnnotation(
    val primaryClassId: String,
    val primarySpeedKmh: Int?,
    val physicalSignId: String,
    val frameId: String,
    val observedAt: Instant,
    val firstSeenAt: Instant,
    val rawText: String?,
    val status: Status,
    val primaryBox: Box,
    val ocrBox: Box?,
    val engine: String,
    val modelVersion: String,
    val parsedTimeWindow: ParsedTimeWindow?,
) {
    /** Parsed candidates still require explicit complete-assembly verification and two frames. */
    val conditionalInterpretationCandidate: ConditionalOCRInterpretation.Parsed? get() =
        rawText?.takeIf { status == Status.READ && primarySpeedKmh != null && primaryClassId == "maxspeed:$primarySpeedKmh" }
            ?.let(ConditionalOCRInterpretation::parse)
    enum class Status(val wireValue: String) { READ("read"), NO_TEXT("no_text"), FAILED("failed") }
    data class Box(val x: Double, val y: Double, val width: Double, val height: Double) {
        val valid get() = listOf(x, y, width, height).all { it.isFinite() } && x >= 0 && y >= 0 &&
            width > 0 && height > 0 && x + width <= 1 && y + height <= 1
        val wire get() = buildJsonObject { put("x", x); put("y", y); put("width", width); put("height", height) }
    }
    data class ParsedTimeWindow(val startMinutes: Int, val endMinutes: Int) {
        val wire get() = buildJsonObject { put("start_minutes", startMinutes); put("end_minutes", endMinutes) }
    }
    init {
        require(listOf(primaryClassId, physicalSignId, frameId, engine, modelVersion).all {
            it.isNotEmpty() && it.codePointCount(0, it.length) <= 160
        })
        require((primarySpeedKmh == null || primarySpeedKmh in 1..1000) && primaryBox.valid && ocrBox?.valid != false)
        require(firstSeenAt <= observedAt)
        require(rawText == null || rawText.isNotEmpty() && rawText.codePointCount(0, rawText.length) <= 4096)
        require(status != Status.READ || rawText != null)
        require(parsedTimeWindow == null || parsedTimeWindow.startMinutes in 0..1439 && parsedTimeWindow.endMinutes in 0..1439)
    }
    val wire get() = buildJsonObject {
        put("schema_version", 1); put("primary_class_id", primaryClassId); put("primary_speed_kmh", primarySpeedKmh?.let(::JsonPrimitive) ?: JsonNull)
        put("physical_sign_id", physicalSignId); put("frame_id", frameId)
        put("observed_at", observedAt.toString()); put("first_seen_at", firstSeenAt.toString())
        put("raw_text", rawText?.let(::JsonPrimitive) ?: JsonNull); put("status", status.wireValue)
        put("normalized_primary_box", primaryBox.wire); put("normalized_ocr_box", ocrBox?.wire ?: JsonNull)
        put("engine", engine); put("model_version", modelVersion)
        put("parsed_time_window", parsedTimeWindow?.wire ?: JsonNull)
    }
    fun matches(modelLabel: String, speedKmh: Int?, box: List<Double>): Boolean {
        if (primaryClassId != modelLabel || (primarySpeedKmh != null && primarySpeedKmh != speedKmh) || box.size != 4 ||
            box.any { !it.isFinite() } || box[2] <= 0 || box[3] <= 0) return false
        val intersection = maxOf(0.0, minOf(primaryBox.x + primaryBox.width, box[0] + box[2]) - maxOf(primaryBox.x, box[0])) *
            maxOf(0.0, minOf(primaryBox.y + primaryBox.height, box[1] + box[3]) - maxOf(primaryBox.y, box[1]))
        return intersection / maxOf(1e-12, primaryBox.width * primaryBox.height + box[2] * box[3] - intersection) >= .2
    }
}
