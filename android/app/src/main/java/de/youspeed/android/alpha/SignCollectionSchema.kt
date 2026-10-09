package de.youspeed.android.alpha

import kotlinx.serialization.json.*
import java.time.OffsetDateTime
import java.time.ZoneOffset

/** JSON Schema subset emitted by the pinned Pydantic models. */
internal object SignCollectionSchema {
    fun validate(value: JsonElement, schema: JsonObject, root: JsonObject) {
        schema["\$ref"]?.let {
            val ref = it.jsonPrimitive.content; require(ref.startsWith("#/\$defs/"))
            validate(value, root.getValue("\$defs").jsonObject.getValue(ref.removePrefix("#/\$defs/")).jsonObject, root); return
        }
        schema["anyOf"]?.let { branches ->
            require(branches.jsonArray.any { runCatching { validate(value, it.jsonObject, root) }.isSuccess }); return
        }
        schema["const"]?.let { require(SignCollectionJson.canonical(value) == SignCollectionJson.canonical(it)) }
        schema["enum"]?.let { choices -> require(choices.jsonArray.any { SignCollectionJson.canonical(value) == SignCollectionJson.canonical(it) }) }
        when (schema["type"]?.jsonPrimitive?.content) {
            "null" -> require(value === JsonNull)
            "boolean" -> require(value is JsonPrimitive && !value.isString && value.booleanOrNull != null)
            "integer", "number" -> {
                require(value is JsonPrimitive && !value.isString && value.booleanOrNull == null && value !== JsonNull)
                val d = value.double; require(d.isFinite())
                if (schema["type"]!!.jsonPrimitive.content == "integer") require(value.content.matches(Regex("-?(0|[1-9][0-9]*)")))
                schema["minimum"]?.let { require(d >= it.jsonPrimitive.double) }; schema["maximum"]?.let { require(d <= it.jsonPrimitive.double) }
                schema["exclusiveMinimum"]?.let { require(d > it.jsonPrimitive.double) }; schema["exclusiveMaximum"]?.let { require(d < it.jsonPrimitive.double) }
            }
            "string" -> {
                require(value is JsonPrimitive && value.isString)
                val s = value.content; val length = s.codePointCount(0, s.length)
                schema["minLength"]?.let { require(length >= it.jsonPrimitive.int) }; schema["maxLength"]?.let { require(length <= it.jsonPrimitive.int) }
                schema["pattern"]?.let { require(Regex(it.jsonPrimitive.content).containsMatchIn(s)) }
                if (schema["format"]?.jsonPrimitive?.content == "date-time") require(OffsetDateTime.parse(s).offset == ZoneOffset.UTC)
            }
            "array" -> {
                require(value is JsonArray)
                schema["minItems"]?.let { require(value.size >= it.jsonPrimitive.int) }; schema["maxItems"]?.let { require(value.size <= it.jsonPrimitive.int) }
                schema["items"]?.let { item -> value.forEach { validate(it, item.jsonObject, root) } }
            }
            "object" -> {
                require(value is JsonObject)
                val properties = schema["properties"]?.jsonObject ?: JsonObject(emptyMap())
                require(schema["required"]?.jsonArray?.all { it.jsonPrimitive.content in value } != false)
                value.forEach { (key, child) ->
                    val property = properties[key]
                    if (property != null) validate(child, property.jsonObject, root)
                    else require(schema["additionalProperties"] != JsonPrimitive(false))
                }
            }
            null -> Unit
            else -> error("unsupported_schema")
        }
    }
}

internal fun signCollectionSemantics(value: JsonElement, model: String) {
    val o = value.jsonObject
    listOf("event_id", "installation_id", "batch_id", "collection_session_id", "crop_id", "observation_id", "deletion_request_id", "target_id", "superseded_by").forEach { key ->
        o[key]?.takeIf { it !== JsonNull }?.let { require(SignCollectionJson.isUuid(it.jsonPrimitive.content)) }
    }
    o["media_refs"]?.jsonArray?.forEach { require(SignCollectionJson.isUuid(it.jsonPrimitive.content)) }
    if (model == "sighting") {
        fun date(key: String) = OffsetDateTime.parse(o.getValue(key).jsonPrimitive.content).toInstant()
        require(date("first_seen_at") <= date("representative_frame_at") && date("representative_frame_at") <= date("last_seen_at"))
        val scores = o.getValue("scores").jsonObject
        if (o.getValue("source_kind").jsonPrimitive.content == "manual_capture") require(o.getValue("model") === JsonNull && listOf("detector_raw", "classifier_raw", "calibrated_confidence").all { scores[it] === JsonNull })
        else require(o.getValue("model") !== JsonNull)
        if (scores.getValue("calibrated_confidence") !== JsonNull) require(scores["calibration_id"] is JsonPrimitive && scores["calibration_id"] !== JsonNull && scores["calibration_sha256"] is JsonPrimitive && scores["calibration_sha256"] !== JsonNull)
    }
    if (model == "correction" && o.getValue("intent").jsonPrimitive.content == "retract_correction") require(o.getValue("target_kind").jsonPrimitive.content == "correction")
    if (model == "crop") o["phone_road_match"]?.takeIf { it != JsonNull }?.jsonObject?.let { match ->
        val way = match.getValue("osm_way_id").jsonPrimitive.content
        require(way.toLongOrNull()?.let { it > 0 && it.toString() == way } == true)
        val frame = OffsetDateTime.parse(o.getValue("source_frame_at").jsonPrimitive.content).toInstant()
        val fix = OffsetDateTime.parse(match.getValue("matched_fix_at").jsonPrimitive.content).toInstant()
        val elapsed = java.time.Duration.between(fix, frame)
        val actual = elapsed.seconds * 1000.0 + elapsed.nano / 1_000_000.0
        require(kotlin.math.abs(actual - match.getValue("frame_match_delta_ms").jsonPrimitive.double) <= 1.0)
    }
    if (model == "crop") {
        val geometry = SignCollectionCropGeometry.resolve(o.getValue("source_width").jsonPrimitive.int, o.getValue("source_height").jsonPrimitive.int, o.getValue("supplied_box").jsonObject.mapValues { it.value.jsonPrimitive.double })
        geometry.wire.forEach { (key, expected) -> require(SignCollectionJson.canonical(expected) == SignCollectionJson.canonical(o.getValue(key))) }
        require(o.getValue("decoded_width").jsonPrimitive.int == geometry.actual[2]-geometry.actual[0] && o.getValue("decoded_height").jsonPrimitive.int == geometry.actual[3]-geometry.actual[1])
        require(o.getValue("source_upright_sha256") !== JsonNull || !o.getValue("local_frame_token").jsonPrimitive.contentOrNull.isNullOrEmpty())
    }
    if (model == "batch") {
        val ids = o.getValue("events").jsonArray.map { it.jsonObject.getValue("event_id").jsonPrimitive.content }
        require(ids.size == ids.toSet().size && ids.all(SignCollectionJson::isUuid))
    }
}
