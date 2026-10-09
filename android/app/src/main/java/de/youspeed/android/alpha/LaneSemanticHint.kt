package de.youspeed.android.alpha

import kotlinx.serialization.json.*

/** Exact-exposure semantic evidence; Swift is the behavioral reference. This core is not
 * connected to detection, tracking, ranking or display. See shared/lanes/semantic-hint-v1. */
object LaneSemanticHint {
    const val MAX_SAFE_INTEGER = 9_007_199_254_740_991L
    const val OUTPUT_KIND = "lane-paint-probability-v1"
    private val scopeKeys = setOf("sessionId", "sessionGeneration", "cameraId", "cameraGeneration", "calibrationGeneration")
    private val modelKeys = setOf("modelId", "revision", "outputKind")
    class Invalid(val reason: String) : IllegalArgumentException(reason)

    class Policy(value: JsonObject) {
        private val pinnedModelIdentity: JsonObject
        val modelIdentity: JsonObject get() = snapshot(pinnedModelIdentity)
        val maskWidth: Int
        val maskHeight: Int
        val maxCaptureAgeNs: Long
        init {
            val model = value["modelIdentity"] as? JsonObject
            val width = integer(value["maskWidth"], 1, 512)
            val height = integer(value["maskHeight"], 1, 512)
            val age = integer(value["maxCaptureAgeNs"], 1)
            if (!keys(value, "schemaVersion", "modelIdentity", "maskWidth", "maskHeight", "maxCaptureAgeNs") ||
                integer(value["schemaVersion"]) != 1L || model == null || !validModel(model) ||
                string(model["outputKind"]) != OUTPUT_KIND || width == null || height == null || age == null) throw Invalid("invalid_policy")
            pinnedModelIdentity = snapshot(model); maskWidth = width.toInt(); maskHeight = height.toInt(); maxCaptureAgeNs = age
        }
    }
    class Evidence internal constructor(
        val frameId: String, val sourceTimeNs: Long, val sourceClockId: String,
        val capturedAtNs: Long, val clockId: String, val arrivedAtNs: Long,
        val scopeIdentity: String, val geometryIdentity: String, val modelIdentity: String, val provenanceIdentity: String,
        val width: Int, val height: Int, probabilities: DoubleArray, validity: BooleanArray,
        private val metadata: JsonObject,
    ) {
        private val scores = probabilities.copyOf()
        private val valid = validity.copyOf()
        val probabilities: DoubleArray get() = scores.copyOf()
        val validity: BooleanArray get() = valid.copyOf()
        fun probabilityAt(index: Int): Double? = if (index in valid.indices && valid[index]) scores[index] else null
        internal fun requalify(context: JsonObject, policy: Policy): Qualification {
            val checked = qualifyMetadata(metadata, context, policy, false)
            if (checked.reason != "metadata_qualified") return checked
            if (width != policy.maskWidth || height != policy.maskHeight) return Qualification("shape_mismatch", captureAgeNs = checked.captureAgeNs)
            return Qualification("qualified", this, checked.captureAgeNs)
        }
        internal fun invalidBufferReason(): String? = when {
            scores.any { !it.isFinite() || it !in 0.0..1.0 } -> "invalid_scores"
            !valid.any { it } -> "no_valid_pixels"
            else -> null
        }
    }
    data class Qualification(val reason: String, val hint: Evidence? = null, val captureAgeNs: Long? = null) {
        val accepted: Boolean get() = hint != null
    }
    data class GuidanceInput<T>(val baseline: T, val qualification: Qualification)
    fun <T> prepareGuidance(baseline: T, hint: JsonObject?, context: JsonObject, policy: Policy): GuidanceInput<T> =
        GuidanceInput(baseline, qualify(hint, context, policy))

    fun <T> prepareGuidanceTyped(baseline: T, metadata: JsonObject?, width: Int, height: Int,
                                probabilities: DoubleArray, validity: BooleanArray, context: JsonObject, policy: Policy): GuidanceInput<T> =
        GuidanceInput(baseline, qualifyTyped(metadata, width, height, probabilities, validity, context, policy))

    private fun qualifyMetadata(hint: JsonObject?, context: JsonObject, policy: Policy, containsMask: Boolean): Qualification {
        contextReason(context)?.let { return Qualification(it) }
        if (hint == null) return Qualification("missing_hint")
        if (hint.keys != setOf("schemaVersion", "modelIdentity", "provenance", "scope", "exposure", "arrival", "geometry", "alignment") + (if (containsMask) setOf("mask") else emptySet())) return Qualification("invalid_hint")
        if (integer(hint["schemaVersion"]) != 1L) return Qualification("schema_mismatch")
        val model = hint["modelIdentity"] as? JsonObject
        if (model == null || !validModel(model) || model != policy.modelIdentity) return Qualification("model_mismatch")
        val provenance = hint["provenance"] as? JsonObject
        if (provenance == null || !keys(provenance, "kind", "sourceId") || string(provenance["kind"]) !in setOf("model_inference", "synthetic_fixture") || !text(provenance["sourceId"])) return Qualification("invalid_provenance")
        val scope = hint["scope"] as? JsonObject
        if (scope == null || !validScope(scope)) return Qualification("invalid_scope")
        if (scope != context["scope"]) return Qualification("scope_mismatch")
        val exposure = hint["exposure"] as? JsonObject
        if (exposure == null || !validExposure(exposure)) return Qualification("invalid_exposure")
        if (boolean(exposure["clockKnown"]) != true) return Qualification("unknown_clock")
        val currentExposure = context.getValue("exposure").jsonObject
        if (listOf("clockId", "sourceClockId").any { exposure[it] != currentExposure[it] }) return Qualification("clock_mismatch")
        if (exposure != currentExposure) return Qualification("exposure_mismatch")
        val arrival = hint["arrival"] as? JsonObject
        if (arrival == null || !validReading(arrival)) return Qualification("invalid_arrival")
        if (boolean(arrival["clockKnown"]) != true) return Qualification("unknown_clock")
        if (arrival["clockId"] != exposure["clockId"]) return Qualification("clock_mismatch")
        val captured = integer(exposure["capturedAtNs"])!!; val arrived = integer(arrival["atNs"])!!
        val now = integer(context.getValue("now").jsonObject["atNs"])!!
        if (arrived < captured) return Qualification("arrival_before_capture")
        if (arrived > now) return Qualification("future_arrival")
        val age = now - captured
        if (age > policy.maxCaptureAgeNs) return Qualification("stale_hint", captureAgeNs = age)
        val geometry = hint["geometry"] as? JsonObject
        if (geometry == null || !validGeometry(geometry)) return Qualification("invalid_geometry", captureAgeNs = age)
        if (geometry != context["geometry"]) return Qualification("geometry_mismatch", captureAgeNs = age)
        if (hint["alignment"] != buildJsonObject { put("mode", "exact_exposure") }) return Qualification("alignment_unsupported", captureAgeNs = age)
        return Qualification("metadata_qualified", captureAgeNs = age)
    }

    /** JSON reference bridge. Typed producers bypass JSON mask decoding. */
    fun qualify(hint: JsonObject?, context: JsonObject, policy: Policy): Qualification {
        val checked = qualifyMetadata(hint, context, policy, true)
        if (checked.reason != "metadata_qualified" || hint == null) return checked
        val age = checked.captureAgeNs!!
        val mask = hint["mask"] as? JsonObject
        if (mask == null || !keys(mask, "width", "height", "probabilities", "validity")) return Qualification("invalid_mask", captureAgeNs = age)
        val scores = mask["probabilities"] as? JsonArray; val valid = mask["validity"] as? JsonArray
        if (integer(mask["width"], 1, 512) != policy.maskWidth.toLong() || integer(mask["height"], 1, 512) != policy.maskHeight.toLong() ||
            scores == null || valid == null || scores.size != policy.maskWidth * policy.maskHeight || valid.size != scores.size) return Qualification("shape_mismatch", captureAgeNs = age)
        val decoded = DoubleArray(scores.size)
        for (index in scores.indices) decoded[index] = probability(scores[index]) ?: return Qualification("invalid_scores", captureAgeNs = age)
        if (valid.any { boolean(it) == null }) return Qualification("invalid_validity", captureAgeNs = age)
        return ownAndQualify(JsonObject(hint.filterKeys { it != "mask" }), policy.maskWidth, policy.maskHeight,
            decoded, BooleanArray(valid.size) { boolean(valid[it])!! }, policy, age)
    }

    /** Metadata is the exact hint envelope WITHOUT mask. Buffers are copied before validation
     * so accepted evidence owns the checked bytes. Do not mutate while submitting a buffer. */
    fun qualifyTyped(metadata: JsonObject?, width: Int, height: Int, probabilities: DoubleArray, validity: BooleanArray,
                     context: JsonObject, policy: Policy): Qualification {
        val checked = qualifyMetadata(metadata, context, policy, false)
        if (checked.reason != "metadata_qualified" || metadata == null) return checked
        return ownAndQualify(metadata, width, height, probabilities, validity, policy, checked.captureAgeNs!!)
    }

    private fun ownAndQualify(metadata: JsonObject, width: Int, height: Int, probabilities: DoubleArray, validity: BooleanArray,
                              policy: Policy, age: Long): Qualification {
        if (width !in 1..512 || height !in 1..512 || width != policy.maskWidth || height != policy.maskHeight ||
            probabilities.size != width * height || validity.size != probabilities.size) return Qualification("shape_mismatch", captureAgeNs = age)
        val owned = snapshot(metadata); val exposure = owned.getValue("exposure").jsonObject
        val evidence = Evidence(string(exposure["frameId"])!!, integer(exposure["sourceTimeNs"])!!, string(exposure["sourceClockId"])!!,
            integer(exposure["capturedAtNs"])!!, string(exposure["clockId"])!!, integer(owned.getValue("arrival").jsonObject["atNs"])!!,
            canonical(owned.getValue("scope")), canonical(owned.getValue("geometry")), canonical(owned.getValue("modelIdentity")), canonical(owned.getValue("provenance")),
            width, height, probabilities, validity, owned)
        evidence.invalidBufferReason()?.let { return Qualification(it, captureAgeNs = age) }
        return Qualification("qualified", evidence, age)
    }

    /** Only accepted owned evidence enters Cache; context checks never rescan its mask. */
    private fun requalify(hint: Evidence?, context: JsonObject, policy: Policy): Qualification =
        hint?.requalify(context, policy) ?: qualifyMetadata(null, context, policy, false)

    /** Single-owner cache: use only on its owner's queue. No camera scheduling/thread-safety claim. */
    class Cache(val policy: Policy, context: JsonObject) {
        private lateinit var context: JsonObject
        private lateinit var key: String
        private var hint: Evidence? = null
        var latestSourceTimeNs: Long? = null; private set
        init { resetScope(context) }
        fun resetScope(next: JsonObject) {
            contextReason(next)?.let { throw Invalid(it) }
            context = snapshot(next); key = contextKey(next); hint = null; latestSourceTimeNs = null
        }
        fun advance(next: JsonObject): String {
            contextReason(next)?.let { return it }
            if (contextKey(next) != key) return "context_scope_mismatch"
            val old = context.getValue("exposure").jsonObject; val new = next.getValue("exposure").jsonObject
            if (integer(next.getValue("now").jsonObject["atNs"])!! < integer(context.getValue("now").jsonObject["atNs"])!!) return "context_clock_regression"
            val oldSource = integer(old["sourceTimeNs"])!!; val newSource = integer(new["sourceTimeNs"])!!
            val oldCapture = integer(old["capturedAtNs"])!!; val newCapture = integer(new["capturedAtNs"])!!
            if (newSource < oldSource || newCapture < oldCapture) return "context_exposure_regression"
            if (newSource == oldSource && new != old) return "context_exposure_conflict"
            if (newSource > oldSource && (new["frameId"] == old["frameId"] || newCapture == oldCapture)) return "context_exposure_conflict"
            context = snapshot(next)
            return "advanced"
        }
        fun offer(value: JsonObject?): Qualification {
            return accept(qualify(value, context, policy))
        }
        fun offerTyped(metadata: JsonObject?, width: Int, height: Int, probabilities: DoubleArray, validity: BooleanArray): Qualification =
            accept(qualifyTyped(metadata, width, height, probabilities, validity, context, policy))
        private fun accept(result: Qualification): Qualification {
            val accepted = result.hint ?: return result
            latestSourceTimeNs?.let { latest ->
                if (accepted.sourceTimeNs <= latest) return Qualification(if (accepted.sourceTimeNs == latest) "duplicate_exposure" else "out_of_order_exposure", captureAgeNs = result.captureAgeNs)
            }
            hint = accepted; latestSourceTimeNs = accepted.sourceTimeNs
            return result
        }
        // Uses the last accepted owner context, not a clock read. Advance fresh time/
        // exposure before consumption and withhold evidence after rejected advance/reset;
        // rejected owner updates deliberately preserve the prior state.
        fun current(): Qualification = requalify(hint, context, policy)
    }

    /** Rebase an already-trusted native clock. This does not measure synchronization.
     * Retain original exposure time: inference completion/arrival is not capture time. */
    class ClockEpoch(val clockId: String, val originNs: Long, val role: Role) {
        enum class Role { SOURCE_PRESENTATION, CAPTURE_MONOTONIC }
        init { if (!text(JsonPrimitive(clockId)) || originNs < 0) throw Invalid("invalid_clock_epoch") }
        fun relative(readingNs: Long, readingClock: String, known: Boolean): Long {
            if (!known) throw Invalid("unknown_clock")
            if (readingClock != clockId) throw Invalid("clock_mismatch")
            if (readingNs < 0) throw Invalid("invalid_clock_reading")
            val relative = try { Math.subtractExact(readingNs, originNs) } catch (_: ArithmeticException) { throw Invalid("clock_out_of_range") }
            if (relative !in 0..MAX_SAFE_INTEGER) throw Invalid("clock_out_of_range")
            return relative
        }
    }
    fun exposure(frameId: String, source: ClockEpoch, sourceNs: Long, sourceClockId: String,
                 capture: ClockEpoch, captureNs: Long, captureClockId: String, clocksKnown: Boolean): JsonObject {
        if (!text(JsonPrimitive(frameId)) || source.role != ClockEpoch.Role.SOURCE_PRESENTATION || capture.role != ClockEpoch.Role.CAPTURE_MONOTONIC) throw Invalid("invalid_clock_role")
        return buildJsonObject {
            put("frameId", frameId)
            put("sourceTimeNs", source.relative(sourceNs, sourceClockId, clocksKnown)); put("sourceClockId", source.clockId)
            put("capturedAtNs", capture.relative(captureNs, captureClockId, clocksKnown)); put("clockId", capture.clockId); put("clockKnown", true)
        }
    }
    fun contextReason(value: JsonObject): String? {
        val scope = value["scope"] as? JsonObject; val exposure = value["exposure"] as? JsonObject
        val geometry = value["geometry"] as? JsonObject; val now = value["now"] as? JsonObject
        if (!keys(value, "schemaVersion", "scope", "exposure", "geometry", "now") || integer(value["schemaVersion"]) != 1L ||
            scope == null || !validScope(scope) || exposure == null || !validExposure(exposure) || geometry == null || !validGeometry(geometry) ||
            now == null || !validReading(now)) return "invalid_context"
        if (boolean(now["clockKnown"]) != true || boolean(exposure["clockKnown"]) != true) return "unknown_clock"
        if (now["clockId"] != exposure["clockId"]) return "clock_mismatch"
        if (integer(now["atNs"])!! < integer(exposure["capturedAtNs"])!!) return "future_capture"
        val crop = geometry.getValue("crop").jsonObject
        if (boolean(geometry["fullScene"]) != true || integer(crop["x"]) != 0L || integer(crop["y"]) != 0L ||
            integer(crop["width"]) != integer(geometry["sourceWidth"]) || integer(crop["height"]) != integer(geometry["sourceHeight"])) return "partial_scene_unsupported"
        return null
    }
    private fun integer(value: JsonElement?, minimum: Long = 0, maximum: Long = MAX_SAFE_INTEGER): Long? {
        val primitive = value as? JsonPrimitive ?: return null
        if (primitive.isString) return null
        return primitive.content.toLongOrNull()?.takeIf { it in minimum..maximum }
    }
    private fun string(value: JsonElement?): String? = (value as? JsonPrimitive)?.takeIf { it.isString }?.content
    private fun text(value: JsonElement?): Boolean = string(value)?.let { text ->
        text.codePointCount(0, text.length) <= 512 && text.codePoints().anyMatch { !contractWhitespace(it) }
    } ?: false
    // Match the shared Python contract's Unicode whitespace and code-point length rules.
    private fun contractWhitespace(value: Int) = value in 9..13 || value in 28..32 || value in 8192..8202 ||
        value in setOf(133, 160, 5760, 8232, 8233, 8239, 8287, 12288)
    private fun boolean(value: JsonElement?): Boolean? = (value as? JsonPrimitive)?.takeIf { !it.isString }?.booleanOrNull
    private fun probability(value: JsonElement?): Double? = (value as? JsonPrimitive)?.takeIf { !it.isString }?.doubleOrNull?.takeIf { it.isFinite() && it in 0.0..1.0 }
    private fun keys(value: JsonObject, vararg expected: String) = value.keys == expected.toSet()
    private fun validModel(value: JsonObject) = value.keys == modelKeys && modelKeys.all { text(value[it]) }
    private fun validScope(value: JsonObject) = value.keys == scopeKeys && text(value["sessionId"]) && text(value["cameraId"]) && scopeKeys.filter { it.endsWith("Generation") }.all { integer(value[it]) != null }
    private fun validExposure(value: JsonObject) = keys(value, "frameId", "sourceTimeNs", "sourceClockId", "capturedAtNs", "clockId", "clockKnown") &&
        listOf("frameId", "sourceClockId", "clockId").all { text(value[it]) } && listOf("sourceTimeNs", "capturedAtNs").all { integer(value[it]) != null } && boolean(value["clockKnown"]) != null
    private fun validReading(value: JsonObject) = keys(value, "atNs", "clockId", "clockKnown") && integer(value["atNs"]) != null && text(value["clockId"]) && boolean(value["clockKnown"]) != null
    private fun validGeometry(value: JsonObject): Boolean {
        if (!keys(value, "sourceWidth", "sourceHeight", "crop", "rotationDegrees", "mirrored", "analysisWidth", "analysisHeight", "mappingId", "fullScene") ||
            listOf("sourceWidth", "sourceHeight", "analysisWidth", "analysisHeight").any { integer(value[it], 1, 32_768) == null } ||
            integer(value["rotationDegrees"]) !in setOf(0L, 90L, 180L, 270L) || boolean(value["mirrored"]) == null || boolean(value["fullScene"]) == null || !text(value["mappingId"])) return false
        val crop = value["crop"] as? JsonObject ?: return false
        if (!keys(crop, "x", "y", "width", "height")) return false
        val x = integer(crop["x"]) ?: return false; val y = integer(crop["y"]) ?: return false
        val width = integer(crop["width"], 1, 32_768) ?: return false; val height = integer(crop["height"], 1, 32_768) ?: return false
        return x + width <= integer(value["sourceWidth"])!! && y + height <= integer(value["sourceHeight"])!!
    }
    private fun canonical(value: JsonElement): String = when (value) {
        is JsonObject -> value.keys.sorted().joinToString(",", "{", "}") { JsonPrimitive(it).toString() + ":" + canonical(value.getValue(it)) }
        is JsonArray -> value.joinToString(",", "[", "]") { canonical(it) }
        else -> value.toString()
    }
    private fun snapshot(value: JsonObject): JsonObject = Json.parseToJsonElement(value.toString()).jsonObject
    private fun contextKey(value: JsonObject): String = canonical(buildJsonObject {
        put("scope", value.getValue("scope")); put("geometry", value.getValue("geometry"))
        put("sourceClockId", value.getValue("exposure").jsonObject.getValue("sourceClockId")); put("clockId", value.getValue("exposure").jsonObject.getValue("clockId"))
    })
}
