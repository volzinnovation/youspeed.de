package de.youspeed.android.alpha

import java.io.File
import kotlinx.serialization.json.*

// Camera-independent value needed by the existing visual calibration source; no camera mock.
data class NormalizedTrafficSignBoundingBox(val x: Double, val y: Double, val width: Double, val height: Double)
private fun encode(value: Any?): JsonElement = when (value) {
    null -> JsonNull
    is JsonElement -> value
    is Boolean -> JsonPrimitive(value)
    is Number -> JsonPrimitive(value)
    is String -> JsonPrimitive(value)
    is Map<*, *> -> JsonObject(value.entries.associate { it.key as String to encode(it.value) })
    is Iterable<*> -> JsonArray(value.map { encode(it) })
    else -> error("Unsupported output value")
}
private fun record(value: RoadBoundaryPresentationSnapshot) = encode(mapOf(
    "accepted" to value.accepted, "reason" to value.reason, "rawCount" to value.rawCount,
    "visibleCount" to value.visibleBoundaryIndices.size, "confirmedCount" to value.confirmedCount,
    "tentativeCount" to value.tentativeCount, "missingCount" to value.missingCount, "operationCount" to value.operationCount,
    "visibleBoundaryIndices" to value.visibleBoundaryIndices, "selectionDecisions" to value.selectionDecisions.map { it.diagnosticFields },
    "expiredTrackIds" to value.expiredTrackIds, "items" to value.items.map { mapOf("trackId" to it.trackId, "boundaryIndex" to it.boundaryIndex,
        "state" to it.state, "observationCount" to it.observationCount, "firstObservedSeconds" to it.firstObservedSeconds,
        "lastObservedSeconds" to it.lastObservedSeconds, "missedExposures" to it.missedExposures) }))
fun main(args: Array<String>) {
    val document = Json.parseToJsonElement(File(args[0]).readText()).jsonObject
    val output = document.getValue("cases").jsonArray.map { raw ->
        val scenario = raw.jsonObject; val baseline = RoadBoundaryEgoSelector(); val guided = RoadBoundaryEgoSelector()
        val frames = scenario.getValue("frames").jsonArray.map { rawFrame ->
            val frame = rawFrame.jsonObject; val time = frame.getValue("time").jsonPrimitive.double
            val boundaries = frame.getValue("boundaries").jsonArray.map { rawBoundary ->
                val value = rawBoundary.jsonObject
                RoadBoundaryEvidence(value.getValue("points").jsonArray.map { p -> LanePoint(p.jsonArray[0].jsonPrimitive.double, p.jsonArray[1].jsonPrimitive.double) },
                    value.getValue("confidence").jsonPrimitive.double, RoadBoundaryCue.valueOf(value.getValue("cue").jsonPrimitive.content.uppercase()),
                    value.getValue("supportRows").jsonPrimitive.int, RoadBoundaryProvenance.valueOf(value.getValue("provenance").jsonPrimitive.content.uppercase()))
            }
            val snapshot = RoadBoundaryPresentationSnapshot(true, null, frame.getValue("visible").jsonArray.map { it.jsonPrimitive.int },
                boundaries.indices.map { RoadBoundaryPresentationItem(it.toLong() + 1, it, "confirmed", 4, 0.0, time, 0) }, boundaries.size)
            val adjustments = (frame["adjustments"] as? JsonArray)?.map { value ->
                val number = value.jsonPrimitive
                if (number.isString) { if (number.content == "nan") Double.NaN else Double.POSITIVE_INFINITY } else number.double
            }
            val fragment = frame["fragmentAware"]?.jsonPrimitive?.boolean ?: false
            val before = boundaries.toList()
            val left = baseline.select(snapshot, boundaries, null, time, "fixture", fragmentAware = fragment)
            val right = guided.select(snapshot, boundaries, null, time, "fixture", fragmentAware = fragment, semanticScoreAdjustments = adjustments)
            encode(mapOf("baseline" to record(left), "guided" to record(right), "rawEvidenceUnchanged" to (before == boundaries),
                "confirmationCountsUnchanged" to (right.items.map { it.observationCount } == snapshot.items.map { it.observationCount }),
                "rawConfidence" to boundaries.map { it.confidence }, "rawSupportRows" to boundaries.map { it.supportRows }))
        }
        buildJsonObject { put("id", scenario.getValue("id")); put("frames", JsonArray(frames)) }
    }
    println(JsonArray(output))
}
