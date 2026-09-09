package de.youspeed.android.alpha

import java.security.MessageDigest
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long

/** Discovery only. Installation and reviewed runtime activation remain separate gates. */
data class TrafficSignCountryPackRegistry(
    val generation: Int, val environment: String, val expiresAt: Long, val packs: List<Pack>,
) {
    data class ArtifactReference(val url: String, val sha256: String, val sizeBytes: Int)
    data class Platform(val platform: String, val minimumRuntime: String)
    data class Compatibility(
        val minimumAppVersion: String, val maximumAppVersion: String,
        val taxonomyVersion: String, val preprocessingVersion: String, val platforms: List<Platform>,
    )
    data class Pack(
        val packId: String, val version: Int, val countries: List<String>, val rollout: String,
        val manifest: ArtifactReference?, val compatibility: Compatibility, val calibrated: Boolean,
        val reason: String, val supersedes: List<Int>, val rollbackVersion: Int?,
    )
    data class Decision(val state: String, val packId: String? = null, val version: Int? = null) {
        val overrideEligible: Boolean get() = false
    }

    fun decision(
        country: String?, platform: String, appVersion: String, runtimeVersion: String,
        taxonomy: String = "tsr-semantic-v1", preprocessing: String = "vision-scale-fit-rgb-v1", now: Long,
    ): Decision {
        fun result(state: String, pack: Pack? = null) = Decision(state, pack?.packId, pack?.version)
        if (now < 0 || now >= expiresAt) return result("registry_expired")
        if (country == null) return result("country_unresolved")
        val candidates = packs.filter { country in it.countries }
        if (candidates.map { it.packId }.toSet().size > 1) return result("ambiguous_pack")
        val pack = candidates.maxByOrNull { it.version } ?: return result("unavailable")
        if (pack.rollout == "withdrawn") return result("withdrawn", pack)
        val c = pack.compatibility
        val app = numericVersion(appVersion); val runtime = numericVersion(runtimeVersion)
        val minimum = numericVersion(c.minimumAppVersion); val maximum = numericVersion(c.maximumAppVersion)
        val target = c.platforms.firstOrNull { it.platform == platform }
        val minimumRuntime = target?.let { numericVersion(it.minimumRuntime) }
        if (app == null || runtime == null || minimum == null || maximum == null || minimumRuntime == null ||
            app !in minimum..maximum || runtime < minimumRuntime || c.taxonomyVersion != taxonomy ||
            c.preprocessingVersion != preprocessing) return result("incompatible", pack)
        if (pack.manifest == null) return result("unavailable", pack)
        if (environment == "fixture") return result("fixture_only", pack)
        if (!pack.calibrated || pack.rollout in setOf("evaluation", "shadow")) return result("shadow", pack)
        if (pack.rollout == "canary") return result("canary_not_enrolled", pack)
        return result("downloadable", pack)
    }

    companion object {
        fun sha256(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

        /** Only for bytes from the signed APK, never for a downloaded index. */
        fun decodeBundled(bytes: ByteArray): TrafficSignCountryPackRegistry = decodeTrusted(bytes, setOf(sha256(bytes)))

        fun decodeTrusted(bytes: ByteArray, trustedSHA256: Set<String>, minimumGeneration: Int = 1, allowFixtures: Boolean = false): TrafficSignCountryPackRegistry {
            require(bytes.size <= 1_048_576)
            require(sha256(bytes) in trustedSHA256) { "Untrusted registry" }
            val root = Json.parseToJsonElement(bytes.toString(Charsets.UTF_8)).jsonObject
            require(root.getValue("schema_version").jsonPrimitive.int == 1)
            val generation = root.getValue("generation").jsonPrimitive.int
            val environment = root.text("environment")
            val expiresAt = root.getValue("expires_at").jsonPrimitive.long
            require(generation >= maxOf(1, minimumGeneration) && expiresAt in 1..4_102_444_800L)
            require(environment in setOf("fixture", "production") && (allowFixtures || environment == "production"))
            val packs = root.getValue("packs").jsonArray.map { element ->
                val item = element.jsonObject
                val c = item.getValue("compatibility").jsonObject
                val compatibility = Compatibility(c.text("minimum_app_version"), c.text("maximum_app_version"),
                    c.text("taxonomy_version"), c.text("preprocessing_version"), c.getValue("platforms").jsonArray.map {
                        Platform(it.jsonObject.text("platform"), it.jsonObject.text("minimum_runtime"))
                    })
                val manifest = item.getValue("manifest").takeUnless { it == JsonNull }?.jsonObject?.let {
                    ArtifactReference(it.text("url"), it.text("sha256"), it.getValue("size_bytes").jsonPrimitive.int)
                }
                Pack(item.text("pack_id"), item.getValue("version").jsonPrimitive.int,
                    item.getValue("countries").jsonArray.map { it.jsonPrimitive.content }, item.text("rollout"),
                    manifest, compatibility, item.getValue("calibrated").jsonPrimitive.boolean, item.text("reason"),
                    item.getValue("supersedes").jsonArray.map { it.jsonPrimitive.int },
                    item.getValue("rollback_version").takeUnless { it == JsonNull }?.jsonPrimitive?.int,
                ).also { pack ->
                    require(Regex("[a-z0-9][a-z0-9._-]{0,95}").matches(pack.packId) && pack.version > 0)
                    require(pack.countries.size in 1..16 && pack.countries.toSet().size == pack.countries.size &&
                        pack.countries.all { Regex("[A-Z]{2}").matches(it) })
                    require(pack.rollout in setOf("evaluation", "shadow", "canary", "available", "withdrawn"))
                    val minimum = requireNotNull(numericVersion(compatibility.minimumAppVersion))
                    val maximum = requireNotNull(numericVersion(compatibility.maximumAppVersion))
                    require(minimum <= maximum && compatibility.taxonomyVersion.isNotEmpty() && compatibility.preprocessingVersion.isNotEmpty())
                    require(pack.reason.isNotEmpty() && compatibility.platforms.size in 1..2 &&
                        compatibility.platforms.map { it.platform }.toSet().size == compatibility.platforms.size)
                    require(compatibility.platforms.all { it.platform in setOf("ios", "android") && numericVersion(it.minimumRuntime) != null })
                    require(pack.supersedes.toSet().size == pack.supersedes.size && pack.supersedes.all { it in 1 until pack.version })
                    require(pack.rollbackVersion == null || pack.rollbackVersion in 1 until pack.version)
                    manifest?.let { ref ->
                        require(ref.sizeBytes in 1..1_048_576 && Regex("[a-f0-9]{64}").matches(ref.sha256))
                        require(ref.url.length <= 2048 && Regex("https://[a-z0-9.-]+/[A-Za-z0-9/_.-]+").matches(ref.url) &&
                            "/${ref.sha256}/" in ref.url && ".." !in ref.url.split('/'))
                    }
                }
            }
            require(packs.size <= 256 && packs.map { it.packId to it.version }.toSet().size == packs.size)
            return TrafficSignCountryPackRegistry(generation, environment, expiresAt, packs)
        }

        private fun JsonObject.text(key: String): String {
            val value = getValue(key).jsonPrimitive
            require(value.isString)
            return value.content
        }

        private fun numericVersion(raw: String): Long? {
            if (!Regex("[0-9]{1,6}(\\.[0-9]{1,6}){0,2}").matches(raw)) return null
            val parts = raw.split('.').map { it.toLong() } + listOf(0L, 0L)
            return parts[0] * 1_000_000_000_000L + parts[1] * 1_000_000L + parts[2]
        }
    }
}
