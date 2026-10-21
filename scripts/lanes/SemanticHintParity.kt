package de.youspeed.android.alpha

import java.io.File
import java.nio.ByteBuffer
import java.security.MessageDigest
import kotlinx.serialization.json.*

private class SemanticBaseline {
    val confidence = 0.6; val supportRows = 5; val confirmations = 2; val trackId = 17
    fun signature() = buildJsonObject { put("confidence", confidence); put("supportRows", supportRows); put("confirmations", confirmations); put("trackId", trackId) }
}
private fun record(result: LaneSemanticHint.Qualification): JsonObject = buildJsonObject {
    put("reason", result.reason); put("accepted", result.accepted); put("captureAgeNs", result.captureAgeNs?.let { JsonPrimitive(it) } ?: JsonNull)
    val hint = result.hint
    if (hint == null) put("hint", JsonNull) else {
        val scores = hint.probabilities; val valid = hint.validity
        val bytes = ByteBuffer.allocate(scores.size * 8 + valid.size)
        scores.forEach { bytes.putDouble(it) }; valid.forEach { bytes.put(if (it) 1.toByte() else 0.toByte()) }
        val digest = MessageDigest.getInstance("SHA-256").digest(bytes.array()).joinToString("") { "%02x".format(it) }
        put("hint", buildJsonObject {
            put("frameId", hint.frameId); put("sourceTimeNs", hint.sourceTimeNs); put("sourceClockId", hint.sourceClockId)
            put("capturedAtNs", hint.capturedAtNs); put("clockId", hint.clockId); put("arrivedAtNs", hint.arrivedAtNs)
            put("scope", Json.parseToJsonElement(hint.scopeIdentity)); put("geometry", Json.parseToJsonElement(hint.geometryIdentity))
            put("modelIdentity", Json.parseToJsonElement(hint.modelIdentity)); put("provenance", Json.parseToJsonElement(hint.provenanceIdentity))
            put("width", hint.width); put("height", hint.height); put("maskSha256", digest); put("validCells", valid.count { it })
            put("unknownCellsStayUnknown", valid.indices.filter { !valid[it] }.all { hint.probabilityAt(it) == null })
            put("outsideCellsStayUnknown", hint.probabilityAt(-1) == null && hint.probabilityAt(valid.size) == null)
        })
    }
}
private fun nonfinite(hint: JsonObject?, name: String?): JsonObject? {
    if (hint == null || name == null) return hint
    val mask = hint.getValue("mask").jsonObject; val scores = mask.getValue("probabilities").jsonArray.toMutableList()
    scores[0] = JsonPrimitive(when (name) { "nan" -> Double.NaN; "positive_infinity" -> Double.POSITIVE_INFINITY; else -> Double.NEGATIVE_INFINITY })
    return JsonObject(hint + ("mask" to JsonObject(mask + ("probabilities" to JsonArray(scores)))))
}
private fun epoch(value: JsonObject): LaneSemanticHint.ClockEpoch {
    val role = when (value.getValue("role").jsonPrimitive.content) {
        "source_presentation" -> LaneSemanticHint.ClockEpoch.Role.SOURCE_PRESENTATION
        "capture_monotonic" -> LaneSemanticHint.ClockEpoch.Role.CAPTURE_MONOTONIC
        else -> throw LaneSemanticHint.Invalid("invalid_clock_role")
    }
    return LaneSemanticHint.ClockEpoch(value.getValue("clockId").jsonPrimitive.content, value.getValue("originNs").jsonPrimitive.long, role)
}
private class TypedInput(hint: JsonObject?) {
    private val scope = (hint?.get("scope") as? JsonObject)?.toMutableMap()
    val metadata: JsonObject? = hint?.let { JsonObject(it.filterKeys { key -> key != "mask" }.toMutableMap().apply {
        if (scope != null) put("scope", JsonObject(scope))
    }) }
    private val mask = hint?.get("mask") as? JsonObject
    val width = mask?.getValue("width")?.jsonPrimitive?.int ?: 0
    val height = mask?.getValue("height")?.jsonPrimitive?.int ?: 0
    val probabilities = mask?.getValue("probabilities")?.jsonArray?.map { it.jsonPrimitive.double }?.toDoubleArray() ?: doubleArrayOf()
    val validity = mask?.getValue("validity")?.jsonArray?.map { it.jsonPrimitive.boolean }?.toBooleanArray() ?: booleanArrayOf()
    fun mutateCaller() {
        if (probabilities.isNotEmpty()) probabilities[0] = Double.NaN
        if (validity.isNotEmpty()) validity[0] = false
        scope?.set("sessionId", JsonPrimitive("mutated-caller"))
    }
}
fun main(args: Array<String>) {
    require(args.size in 1..2) { "Expected prepared vector JSON path" }
    val document = Json.parseToJsonElement(File(args[0]).readText()).jsonObject
    val typed = args.last() == "--typed"
    val policy = LaneSemanticHint.Policy(document.getValue("policy").jsonObject)
    val cases = (document["qualificationCases"] as? JsonArray ?: JsonArray(emptyList())).map { raw ->
        val item = raw.jsonObject; val baseline = SemanticBaseline(); val before = baseline.signature()
        val hint = nonfinite(item["hint"] as? JsonObject, item["nonfiniteScore"]?.jsonPrimitive?.content)
        val buffers = if (typed) TypedInput(hint) else null
        val input = if (buffers != null) LaneSemanticHint.prepareGuidanceTyped(baseline, buffers.metadata, buffers.width, buffers.height,
            buffers.probabilities, buffers.validity, item.getValue("context").jsonObject, policy)
            else LaneSemanticHint.prepareGuidance(baseline, hint, item.getValue("context").jsonObject, policy)
        if (item["mutateCallerBuffers"]?.jsonPrimitive?.boolean == true) {
            buffers?.mutateCaller()
            input.qualification.hint?.let { evidence ->
                val exposedScores = evidence.probabilities; val exposedValidity = evidence.validity
                if (exposedScores.isNotEmpty()) { exposedScores[0] = Double.NaN; exposedValidity[0] = false }
            }
        }
        JsonObject(record(input.qualification) + mapOf("id" to item.getValue("id"), "baselinePreserved" to JsonPrimitive(input.baseline === baseline && before == baseline.signature()), "baseline" to baseline.signature()))
    }
    val sequences = (document["cacheSequences"] as? JsonArray ?: JsonArray(emptyList())).map { raw ->
        val item = raw.jsonObject; val cache = LaneSemanticHint.Cache(policy, item.getValue("context").jsonObject)
        val steps = item.getValue("operations").jsonArray.map { rawOp ->
            val operation = rawOp.jsonObject
            val row = when (operation.getValue("op").jsonPrimitive.content) {
                "offer" -> {
                    val hint = nonfinite(operation["hint"] as? JsonObject, operation["nonfiniteScore"]?.jsonPrimitive?.content)
                    if (typed) {
                        val buffers = TypedInput(hint)
                        val offered = cache.offerTyped(buffers.metadata, buffers.width, buffers.height, buffers.probabilities, buffers.validity)
                        if (operation["mutateCallerBuffers"]?.jsonPrimitive?.boolean == true) buffers.mutateCaller()
                        record(offered)
                    } else record(cache.offer(hint))
                }
                "advance" -> buildJsonObject { put("reason", cache.advance(operation.getValue("context").jsonObject)) }
                "reset" -> {
                    val reason = try { cache.resetScope(operation.getValue("context").jsonObject); "reset" } catch (error: LaneSemanticHint.Invalid) { error.reason }
                    buildJsonObject { put("reason", reason) }
                }
                "current" -> record(cache.current())
                else -> error("Unknown operation")
            }
            JsonObject(row + mapOf("current" to record(cache.current()), "latestSourceTimeNs" to (cache.latestSourceTimeNs?.let { JsonPrimitive(it) } ?: JsonNull)))
        }
        buildJsonObject { put("id", item.getValue("id")); put("steps", JsonArray(steps)) }
    }
    val clocks = (document["clockCases"] as? JsonArray ?: JsonArray(emptyList())).map { raw ->
        val item = raw.jsonObject
        buildJsonObject {
            put("id", item.getValue("id"))
            try {
                if (item["kind"]?.jsonPrimitive?.content == "exposure") {
                    put("exposure", LaneSemanticHint.exposure(item.getValue("frameId").jsonPrimitive.content,
                        epoch(item.getValue("source").jsonObject), item.getValue("sourceNs").jsonPrimitive.long, item.getValue("sourceClockId").jsonPrimitive.content,
                        epoch(item.getValue("capture").jsonObject), item.getValue("captureNs").jsonPrimitive.long, item.getValue("captureClockId").jsonPrimitive.content,
                        item.getValue("known").jsonPrimitive.boolean))
                } else put("relativeNs", epoch(item.getValue("epoch").jsonObject).relative(item.getValue("readingNs").jsonPrimitive.long, item.getValue("readingClockId").jsonPrimitive.content, item.getValue("known").jsonPrimitive.boolean))
                put("reason", "mapped")
            } catch (error: LaneSemanticHint.Invalid) { put("reason", error.reason) }
        }
    }
    val policies = (document["policyCases"] as? JsonArray ?: JsonArray(emptyList())).map { raw ->
        val item = raw.jsonObject
        val reason = try { LaneSemanticHint.Policy(item.getValue("policy").jsonObject); "valid_policy" } catch (error: LaneSemanticHint.Invalid) { error.reason }
        buildJsonObject { put("id", item.getValue("id")); put("reason", reason) }
    }
    println(buildJsonObject { put("qualificationCases", JsonArray(cases)); put("cacheSequences", JsonArray(sequences)); put("clockCases", JsonArray(clocks)); put("policyCases", JsonArray(policies)) })
}
