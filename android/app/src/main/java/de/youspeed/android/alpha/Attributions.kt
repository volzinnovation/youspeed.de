package de.youspeed.android.alpha

import java.net.URI
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

internal data class AttributionEntry(
    val id: String,
    val title: String,
    val attribution: String,
    val license: String,
    val sourceUrl: String,
    val licenseUrl: String,
    val changes: String,
    val category: String,
)

internal data class AttributionCatalog(val reviewedAt: String, val entries: List<AttributionEntry>) {
    companion object {
        const val ASSET_PATH = "attributions/sources.json"
        const val SHARED_NOTICES = "attributions/THIRD_PARTY_NOTICES.txt"
        const val MODEL_NOTICES = "tsr/DE.panoramax-bootstrap.tsrmodelpack/THIRD_PARTY_NOTICES.txt"
        const val CH_MODEL_NOTICES = "tsr/CH.panoramax-bootstrap.tsrmodelpack/THIRD_PARTY_NOTICES.txt"
        const val SPEECH_NOTICES = "vosk-model-small-de-0.15/COPYING"
        const val SPEECH_NOTICES_FR = "vosk-model-small-fr-0.22/COPYING"
        const val SPEECH_NOTICES_NL = "vosk-model-small-nl-0.22/COPYING"
        const val SPEECH_NOTICES_EN = "vosk-model-small-en-us-0.15/COPYING"
        val CATEGORIES = listOf("data", "sign", "model", "software", "reference")
        val NOTICE_PATHS = listOf(SHARED_NOTICES, MODEL_NOTICES, CH_MODEL_NOTICES, SPEECH_NOTICES, SPEECH_NOTICES_FR, SPEECH_NOTICES_NL, SPEECH_NOTICES_EN)

        fun decode(raw: String): AttributionCatalog {
            val root = Json.parseToJsonElement(raw).jsonObject
            require(root.getValue("schema_version").jsonPrimitive.int == 1)
            val reviewedAt = root.string("reviewed_at")
            val entries = root.getValue("entries").jsonArray.map { value ->
                val entry = value.jsonObject
                AttributionEntry(
                    id = entry.string("id"), title = entry.string("title"),
                    attribution = entry.string("attribution"), license = entry.string("license"),
                    sourceUrl = entry.link("source_url"), licenseUrl = entry.link("license_url"),
                    changes = entry.string("changes"), category = entry.string("category"),
                ).also { require(it.category in CATEGORIES) }
            }
            require(entries.isNotEmpty() && entries.map { it.id }.distinct().size == entries.size)
            return AttributionCatalog(reviewedAt, entries)
        }

        private fun JsonObject.string(key: String): String = getValue(key).jsonPrimitive.let {
            require(it.isString && it.content.isNotBlank()) { "Missing attribution field: $key" }
            it.content
        }

        private fun JsonObject.link(key: String): String = string(key).also {
            val uri = URI(it)
            require(uri.scheme in setOf("https", "http") && !uri.host.isNullOrBlank())
        }
    }
}
