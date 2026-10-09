package de.youspeed.android.alpha

import kotlinx.serialization.json.*
import java.math.BigDecimal
import java.math.MathContext
import java.math.RoundingMode
import java.security.MessageDigest
import java.time.Instant
import java.util.UUID

/** Backend semantic-json-v1, not RFC8785. Never hash JsonElement.toString(). */
internal object SignCollectionJson {
    fun uuid() = UUID.randomUUID().toString()
    fun isUuid(s: String) = runCatching { UUID.fromString(s).let { it.version() == 4 && it.variant() == 2 && it.toString() == s } }.getOrDefault(false)
    fun sha256(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
    fun digest(value: JsonElement) = sha256(canonical(value).toByteArray(Charsets.UTF_8))
    fun canonical(value: JsonElement, depth: Int = 0): String {
        require(depth <= 16) { "nesting" }
        return when (value) {
            is JsonObject -> {
                require(value.size <= 128)
                val order = Comparator<String> { a, b ->
                    val aa = a.codePoints().toArray(); val bb = b.codePoints().toArray()
                    var comparison = 0
                    for (i in 0 until minOf(aa.size, bb.size)) { comparison = aa[i].compareTo(bb[i]); if (comparison != 0) break }
                    if (comparison != 0) comparison else aa.size.compareTo(bb.size)
                }
                value.keys.sortedWith(order).joinToString(",", "{", "}") { canonical(JsonPrimitive(it)) + ":" + canonical(value.getValue(it), depth + 1) }
            }
            is JsonArray -> { require(value.size <= 128); value.joinToString(",", "[", "]") { canonical(it, depth + 1) } }
            is JsonPrimitive -> when {
                value === JsonNull -> "null"
                value.isString -> {
                    require(value.content.codePointCount(0, value.content.length) <= 4096 && value.content.codePoints().noneMatch { it in 0xD800..0xDFFF })
                    buildString {
                        append('"')
                        value.content.forEach { c -> when(c) {
                            '"' -> append("\\\""); '\\' -> append("\\\\"); '\b' -> append("\\b"); '\t' -> append("\\t")
                            '\n' -> append("\\n"); '\u000c' -> append("\\f"); '\r' -> append("\\r")
                            else -> if (c.code < 32) append("\\u%04x".format(c.code)) else append(c)
                        } }
                        append('"')
                    }
                }
                value.booleanOrNull != null -> value.content
                else -> {
                    val literal = value.content
                    if (!literal.contains('.') && !literal.contains('e', true)) require(BigDecimal(literal).abs() <= BigDecimal("9007199254740991")) { "unsafe_integer" }
                    val number = literal.toDouble(); require(number.isFinite())
                    if (number == 0.0) "0" else {
                        // Java 17 Double.toString differs from Python repr at e.g. 1e23.
                        // Round the exact binary64 to the shortest nearest decimal.
                        val exact = BigDecimal(number)
                        val shortest = (1..17).map { exact.round(MathContext(it, RoundingMode.HALF_EVEN)) }
                            .first { it.toDouble() == number }.stripTrailingZeros()
                        if (kotlin.math.abs(number) >= 1e-6 && kotlin.math.abs(number) < 1e21) shortest.toPlainString()
                        else {
                            val sign = if (number < 0) "-" else ""
                            val digits = shortest.unscaledValue().abs().toString()
                            val exponent = digits.length - shortest.scale() - 1
                            sign + digits.take(1) + (if (digits.length > 1) "." + digits.drop(1) else "") + "e" + (if (exponent >= 0) "+" else "-") + kotlin.math.abs(exponent)
                        }
                    }
                }
            }
        }
    }

    /** Reject duplicate keys before the JSON library could overwrite them. */
    fun parse(text: String): JsonElement {
        class Parser {
            var i = 0
            fun space() { while (i < text.length && text[i] in " \t\n\r") i++ }
            fun take(c: Char): Boolean { space(); if (i < text.length && text[i] == c) { i++; return true }; return false }
            fun value(depth: Int): JsonElement {
                space(); require(depth <= 16 && i < text.length)
                if (take('{')) {
                    val result = linkedMapOf<String, JsonElement>()
                    if (take('}')) return JsonObject(result)
                    do {
                        val key = value(depth + 1) as? JsonPrimitive ?: error("key")
                        require(key.isString && !result.containsKey(key.content) && take(':'))
                        result[key.content] = value(depth + 1); require(result.size <= 128)
                    } while (take(','))
                    require(take('}')); return JsonObject(result)
                }
                if (take('[')) {
                    val result = mutableListOf<JsonElement>()
                    if (take(']')) return JsonArray(result)
                    do { result += value(depth + 1); require(result.size <= 128) } while (take(','))
                    require(take(']')); return JsonArray(result)
                }
                val start = i
                if (text[i] == '"') {
                    i++; var escaped = false
                    while (i < text.length) {
                        val c = text[i++]
                        if (c == '"' && !escaped) break
                        escaped = c == '\\' && !escaped
                    }
                } else while (i < text.length && text[i] !in " \t\n\r,]}") i++
                val token = text.substring(start, i)
                // kotlinx accepts bare unquoted text; permit only JSON literals.
                require(token.startsWith('"') || token in listOf("true", "false", "null") || token.matches(Regex("-?(0|[1-9][0-9]*)(\\.[0-9]+)?([eE][+-]?[0-9]+)?")))
                return Json.parseToJsonElement(token).also { canonical(it, depth) }
            }
        }
        val parser = Parser(); val result = parser.value(0); parser.space(); require(parser.i == text.length)
        return result
    }
}

internal data class SignCollectionClaim(val scope: String, val disclosureVersion: String, val decidedAt: String, val generation: Int, val state: String) {
    val wire get() = buildJsonObject {
        put("scope", scope); put("disclosure_version", disclosureVersion); put("decided_at", decidedAt)
        put("consent_generation", generation); put("state", state); put("origin", "client_claim")
    }
    companion object {
        fun decode(o: JsonObject) = SignCollectionClaim(o.getValue("scope").jsonPrimitive.content, o.getValue("disclosure_version").jsonPrimitive.content,
            o.getValue("decided_at").jsonPrimitive.content, o.getValue("consent_generation").jsonPrimitive.int, o.getValue("state").jsonPrimitive.content)
    }
}

internal class SignCollectionContractGate private constructor(val verified: Boolean) {
    // Delivery additionally verifies deployed capabilities and explicit claims.
    val liveTransportAllowed get() = verified
    private val schemas = mutableMapOf<String, JsonObject>()
    fun validate(value: JsonElement, model: String) {
        require(verified); val schema = schemas.getValue(model)
        SignCollectionSchema.validate(value, schema, schema); signCollectionSemantics(value, model); SignCollectionJson.canonical(value)
    }
    constructor(read: (String) -> ByteArray) : this(true) {
        val bytes = read("manifest.json")
        require(SignCollectionJson.sha256(bytes) == MANIFEST_SHA256)
        val manifest = SignCollectionJson.parse(bytes.toString(Charsets.UTF_8)).jsonObject
        require(manifest.getValue("canonicalization").jsonPrimitive.content == "semantic-json-v1")
        manifest.getValue("files").jsonArray.forEach { entry ->
            val path = entry.jsonObject.getValue("path").jsonPrimitive.content
            require(!path.contains(".."))
            require(SignCollectionJson.sha256(read(path)) == entry.jsonObject.getValue("sha256").jsonPrimitive.content)
        }
        SignCollectionJson.parse(read("fixtures/semantic-json-v1.json").toString(Charsets.UTF_8)).jsonArray.forEach { vector ->
            val o = vector.jsonObject; val input = o.getValue("input")
            require(SignCollectionJson.canonical(input) == o.getValue("canonical").jsonPrimitive.content)
            require(SignCollectionJson.digest(input) == o.getValue("sha256").jsonPrimitive.content)
        }
        listOf("batch", "sighting", "correction", "media-status", "consent", "deletion", "crop").forEach { name ->
            schemas[name] = SignCollectionJson.parse(read("$name-v1.schema.json").toString(Charsets.UTF_8)).jsonObject
        }
    }
    companion object {
        const val MANIFEST_SHA256 = "2aca3371266166637d5a2d8528b774e7fbbfb9981f638538c672d126f3a836dd"
        val blocked get() = SignCollectionContractGate(false)
    }
}

internal data class SignCollectionCropGeometry(val supplied: Map<String, Double>, val original: List<Int>, val requested: List<Int>, val actual: List<Int>) {
    val wire get() = buildJsonObject {
        put("supplied_box", buildJsonObject { supplied.forEach { (k, v) -> put(k, v) } })
        put("original_box", JsonArray(original.map(::JsonPrimitive))); put("requested_box", JsonArray(requested.map(::JsonPrimitive))); put("actual_box", JsonArray(actual.map(::JsonPrimitive)))
        put("requested_extra_height", original[3] - original[1]); put("actual_extra_height", actual[3] - original[3]); put("bottom_clipped", actual != requested)
    }
    companion object {
        fun resolve(width: Int, height: Int, box: Map<String, Double>): SignCollectionCropGeometry {
            require(width in 1..32768 && height in 1..32768 && box.keys == setOf("x", "y", "width", "height"))
            val x = box.getValue("x"); val y = box.getValue("y"); val w = box.getValue("width"); val h = box.getValue("height")
            require(box.values.all { it.isFinite() } && x >= 0 && y >= 0 && w > 0 && h > 0 && x + w <= 1 && y + h <= 1)
            val original = listOf(kotlin.math.floor(x * width).toInt(), kotlin.math.floor(y * height).toInt(), minOf(width, kotlin.math.ceil((x + w) * width).toInt()), minOf(height, kotlin.math.ceil((y + h) * height).toInt()))
            require(original[2] > original[0] && original[3] > original[1])
            val requested = original.take(3) + (original[3] + original[3] - original[1])
            val actual = original.take(3) + minOf(height, requested[3])
            require((actual[2] - actual[0]).toLong() * (actual[3] - actual[1]) <= 16_000_000)
            return SignCollectionCropGeometry(box, original, requested, actual)
        }
    }
}
