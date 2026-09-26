package de.youspeed.android.alpha

import java.security.MessageDigest
import kotlinx.serialization.json.*

/** Immutable, packaged runtime policy; downloaded map/model packs cannot override it. */
internal data class SpeedLimitReferenceModel(val policy: Map<String, Any?>, val sha256: String) {
    val version: String get() = policy["version"] as String
    companion object {
        const val APPROVAL_LOCK_SHA256 = "d501f8fdcc6b4a0bddd7d6827f2c58753c7c15efb8d341d8b47d6e9992023b3a"
        const val DIRECTORY = "speed-limit-reference"
        fun decode(bytes: ByteArray): Map<String, Any?> = toValue(Json.parseToJsonElement(bytes.toString(Charsets.UTF_8))) as Map<String, Any?>
        private fun toValue(e: JsonElement): Any? = when(e) {
            JsonNull -> null
            is JsonObject -> e.mapValues { toValue(it.value) }
            is JsonArray -> e.map(::toValue)
            is JsonPrimitive -> when { e.isString -> e.content; e.booleanOrNull != null -> e.boolean; e.longOrNull != null -> e.long; else -> e.double }
        }
        fun load(read: (String) -> ByteArray): SpeedLimitReferenceModel {
            val bytes = read("approval-lock.json")
            require(hash(bytes) == APPROVAL_LOCK_SHA256) { "Approval lock mismatch" }
            val lock = decode(bytes)
            require((lock["schema_version"] as Number).toInt() == 1 && lock["runtime_active"] == true)
            var target: SpeedLimitReferenceModel? = null
            for (entry in lock["artifacts"] as List<Map<String, String>>) {
                val file = entry.getValue("file")
                require(file.isNotBlank() && !file.contains('/') && !file.contains('\\') && file != "." && file != "..")
                val content = read(file)
                require(hash(content) == entry["sha256"]) { "Artifact mismatch: $file" }
                if (entry["role"] == "target") {
                    val policy = decode(content)
                    require((policy["schema_version"] as Number).toInt() == 1 && policy["version"] == lock["target_version"])
                    target = SpeedLimitReferenceModel(policy, entry.getValue("sha256"))
                }
            }
            return requireNotNull(target)
        }
        private fun hash(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
    }
}
