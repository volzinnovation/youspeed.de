package de.youspeed.android.alpha

import java.net.URI
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

data class BundleArtifact(
    val file: String,
    val bytes: Long,
    val sha256: String,
    val url: String?,
    val compression: String? = null,
    val uncompressedBytes: Long? = null,
    val uncompressedSha256: String? = null,
)

data class BundleCoverageBBox(
    val minLon: Double,
    val minLat: Double,
    val maxLon: Double,
    val maxLat: Double,
)

data class BundleCoverage(
    val bbox: BundleCoverageBBox,
    val poly: BundleArtifact?,
)

data class V3BundleManifest(
    val format: String,
    val schemaVersion: Int,
    val variant: String,
    val region: String,
    val countryCode: String?,
    val bundleVersion: String,
    val createdAtUTC: String,
    val minAppVersion: String,
    val db: BundleArtifact,
    val dbParts: List<BundleArtifact>?,
    val deltaIndex: BundleArtifact?,
    val penaltyRules: BundleArtifact?,
    val coverage: BundleCoverage?,
) {
    fun validateLaunchContract() {
        require(format == "youspeed.v3.bundle.manifest") { "Unexpected manifest format: $format" }
        require(variant == "v3") { "Unexpected manifest variant: $variant" }
    }
}

data class V3BundleTargetRegionConfig(
    val regionId: String,
    val regionName: String?,
)

data class V3BundleTargetCountryConfig(
    val rank: Int,
    val countryId: String,
    val countryCode: String,
    val iso2: String?,
    val mode: String,
    val regions: List<V3BundleTargetRegionConfig>,
)

data class V3ManifestEndpoint(
    val countryId: String,
    val countryCode: String,
    val regionId: String,
    val manifestRegion: String,
    val regionName: String?,
    val manifestUrl: String,
)

data class V3BundleTargetsConfig(
    val format: String,
    val schemaVersion: Int,
    val variant: String,
    val maxCountryPbfBytes: Long,
    val githubOwner: String?,
    val githubRepo: String?,
    val countries: List<V3BundleTargetCountryConfig>,
) {
    fun countryById(countryId: String): V3BundleTargetCountryConfig? {
        val key = countryId.trim().lowercase()
        if (key.isEmpty()) {
            return null
        }
        return countries.firstOrNull { it.countryId.lowercase() == key }
    }

    fun countryByCode(countryCode: String): V3BundleTargetCountryConfig? {
        val key = countryCode.trim().uppercase()
        if (key.isEmpty()) {
            return null
        }
        return countries.firstOrNull { it.countryCode.uppercase() == key }
    }

    fun manifestEndpoints(
        githubOwner: String? = null,
        githubRepo: String? = null,
        preferredCountryCode: String? = null,
    ): List<V3ManifestEndpoint> {
        val owner = (githubOwner ?: this.githubOwner)?.trim().orEmpty()
        val repo = (githubRepo ?: this.githubRepo)?.trim().orEmpty()
        if (owner.isEmpty() || repo.isEmpty()) {
            return emptyList()
        }

        val preferredCode = preferredCountryCode?.trim()?.uppercase()
        val orderedCountries = if (preferredCode == null) {
            countries
        } else {
            val preferred = countries.firstOrNull { it.countryCode.uppercase() == preferredCode }
            if (preferred == null) {
                countries
            } else {
                listOf(preferred) + countries.filterNot { it === preferred }
            }
        }

        val seen = linkedSetOf<String>()
        val out = ArrayList<V3ManifestEndpoint>()
        for (country in orderedCountries) {
            val countryToken = idToken(country.countryId)
            if (countryToken.isEmpty()) {
                continue
            }
            if (country.mode != "regional_shards") {
                val manifestUrl = "https://github.com/$owner/$repo/releases/download/$countryToken/${countryToken}_manifest.json"
                if (seen.add(manifestUrl)) {
                    out += V3ManifestEndpoint(
                        countryId = country.countryId,
                        countryCode = country.countryCode,
                        regionId = country.countryId,
                        manifestRegion = countryToken,
                        regionName = null,
                        manifestUrl = manifestUrl,
                    )
                }
                continue
            }

            for (region in country.regions) {
                val fullRegionId = expandedRegionId(country, region.regionId)
                val regionTail = fullRegionId.substringAfterLast('/')
                val regionToken = idToken(regionTail)
                if (regionToken.isEmpty()) {
                    continue
                }
                val manifestUrl = "https://github.com/$owner/$repo/releases/download/$regionToken/${regionToken}_manifest.json"
                if (seen.add(manifestUrl)) {
                    out += V3ManifestEndpoint(
                        countryId = country.countryId,
                        countryCode = country.countryCode,
                        regionId = fullRegionId,
                        manifestRegion = regionToken,
                        regionName = region.regionName,
                        manifestUrl = manifestUrl,
                    )
                }
            }
        }
        return out
    }

    private fun expandedRegionId(
        country: V3BundleTargetCountryConfig,
        regionId: String,
    ): String {
        val trimmedRegionId = regionId.trim().lowercase()
        val trimmedCountryId = country.countryId.trim().lowercase()
        if (trimmedRegionId.isEmpty()) {
            return trimmedCountryId
        }
        if ('/' in trimmedRegionId) {
            return trimmedRegionId
        }
        if (country.mode == "regional_shards" && trimmedRegionId != trimmedCountryId) {
            return "$trimmedCountryId/$trimmedRegionId"
        }
        return trimmedRegionId
    }

    private fun idToken(raw: String): String {
        return raw.trim()
            .lowercase()
            .replace(" ", "-")
            .replace("_", "-")
            .replace("/", "-")
    }
}

object ContractJson {
    private val json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
    }

    fun decodeBundleTargets(raw: String): V3BundleTargetsConfig {
        val root = json.parseToJsonElement(raw).jsonObject
        return V3BundleTargetsConfig(
            format = root.requiredString("format"),
            schemaVersion = root.requiredInt("schema_version"),
            variant = root.requiredString("variant"),
            maxCountryPbfBytes = root.requiredLong("max_country_pbf_bytes"),
            githubOwner = root.optionalString("github_owner"),
            githubRepo = root.optionalString("github_repo"),
            countries = root.requiredArray("countries").map { countryElement ->
                val country = countryElement.jsonObject
                V3BundleTargetCountryConfig(
                    rank = country.requiredInt("rank"),
                    countryId = country.requiredString("country_id"),
                    countryCode = country.requiredString("country_code"),
                    iso2 = country.optionalString("iso2"),
                    mode = country.requiredString("mode"),
                    regions = country.requiredArray("regions").map { regionElement ->
                        val region = regionElement.jsonObject
                        V3BundleTargetRegionConfig(
                            regionId = region.requiredString("region_id"),
                            regionName = region.optionalString("name"),
                        )
                    },
                )
            },
        )
    }

    fun decodeBundleManifest(raw: String): V3BundleManifest {
        val root = json.parseToJsonElement(raw).jsonObject
        return V3BundleManifest(
            format = root.requiredString("format"),
            schemaVersion = root.requiredInt("schema_version"),
            variant = root.requiredString("variant"),
            region = root.requiredString("region"),
            countryCode = root.optionalString("country_code"),
            bundleVersion = root.requiredString("bundle_version"),
            createdAtUTC = root.requiredString("created_at_utc"),
            minAppVersion = root.requiredString("min_app_version"),
            db = root.requiredObject("db").toBundleArtifact(),
            dbParts = root.optionalArray("db_parts")?.map { it.jsonObject.toBundleArtifact() },
            deltaIndex = root.optionalObject("delta_index")?.toBundleArtifact(),
            penaltyRules = root.optionalObject("penalty_rules")?.toBundleArtifact(),
            coverage = root.optionalObject("coverage")?.let { coverage ->
                BundleCoverage(
                    bbox = coverage.requiredObject("bbox").let { bbox ->
                        BundleCoverageBBox(
                            minLon = bbox.requiredDouble("min_lon"),
                            minLat = bbox.requiredDouble("min_lat"),
                            maxLon = bbox.requiredDouble("max_lon"),
                            maxLat = bbox.requiredDouble("max_lat"),
                        )
                    },
                    poly = coverage.optionalObject("poly")?.toBundleArtifact(),
                )
            },
        )
    }

    fun encodeActiveBundleState(state: ActiveBundleState): String {
        val escapedDbPath = state.dbPath.replace("\\", "\\\\").replace("\"", "\\\"")
        val escapedManifestUrl = state.manifestUrl.replace("\\", "\\\\").replace("\"", "\\\"")
        val escapedRegion = state.region.replace("\\", "\\\\").replace("\"", "\\\"")
        val escapedDbFile = state.dbFileName.replace("\\", "\\\\").replace("\"", "\\\"")
        val countryCodePart = state.countryCode?.let {
            "\"country_code\":\"${it.replace("\\", "\\\\").replace("\"", "\\\"")}\","
        }.orEmpty()
        return buildString {
            append("{")
            append("\"region\":\"").append(escapedRegion).append("\",")
            append(countryCodePart)
            append("\"bundle_version\":\"").append(state.bundleVersion).append("\",")
            append("\"db_file_name\":\"").append(escapedDbFile).append("\",")
            append("\"db_path\":\"").append(escapedDbPath).append("\",")
            append("\"db_sha256\":\"").append(state.dbSha256).append("\",")
            append("\"db_bytes\":").append(state.dbBytes).append(",")
            append("\"manifest_url\":\"").append(escapedManifestUrl).append("\",")
            append("\"activated_at_utc\":\"").append(state.activatedAtUTC).append("\"")
            append("}")
        }
    }

    fun decodeActiveBundleState(raw: String): ActiveBundleState {
        val root = json.parseToJsonElement(raw).jsonObject
        return ActiveBundleState(
            region = root.requiredString("region"),
            countryCode = root.optionalString("country_code"),
            bundleVersion = root.requiredString("bundle_version"),
            dbFileName = root.requiredString("db_file_name"),
            dbPath = root.requiredString("db_path"),
            dbSha256 = root.requiredString("db_sha256"),
            dbBytes = root.requiredLong("db_bytes"),
            manifestUrl = root.requiredString("manifest_url"),
            activatedAtUTC = root.requiredString("activated_at_utc"),
        )
    }

    fun resolveArtifactUrl(artifact: BundleArtifact, manifestUrl: String): String {
        val explicit = artifact.url?.trim().orEmpty()
        if (explicit.isNotEmpty()) {
            return URI(manifestUrl).resolve(explicit).toString()
        }
        return URI(manifestUrl).resolve(artifact.file).toString()
    }

    private fun JsonObject.toBundleArtifact(): BundleArtifact {
        return BundleArtifact(
            file = requiredString("file"),
            bytes = requiredLong("bytes"),
            sha256 = requiredString("sha256"),
            url = optionalString("url"),
            compression = optionalString("compression"),
            uncompressedBytes = optionalLong("uncompressed_bytes"),
            uncompressedSha256 = optionalString("uncompressed_sha256"),
        )
    }

    private fun JsonObject.requiredArray(key: String): JsonArray =
        this[key]?.jsonArray ?: error("Missing array field: $key")

    private fun JsonObject.requiredObject(key: String): JsonObject =
        this[key]?.jsonObject ?: error("Missing object field: $key")

    private fun JsonObject.optionalArray(key: String): JsonArray? =
        this[key]?.takeUnless { it is JsonPrimitive && it.content == "null" }?.jsonArray

    private fun JsonObject.optionalObject(key: String): JsonObject? =
        this[key]?.let { element ->
            if (element is JsonPrimitive && element.isString.not() && element.content == "null") {
                null
            } else if (element is JsonObject) {
                element
            } else {
                null
            }
        }

    private fun JsonObject.requiredString(key: String): String =
        this[key]?.jsonPrimitive?.content ?: error("Missing string field: $key")

    private fun JsonObject.optionalString(key: String): String? {
        val value = this[key] ?: return null
        if (value is JsonPrimitive && value.isString) {
            return value.content
        }
        if (value is JsonPrimitive && value.isString.not() && value.content == "null") {
            return null
        }
        return value.jsonPrimitive.content
    }

    private fun JsonObject.requiredInt(key: String): Int =
        this[key]?.jsonPrimitive?.intOrNull ?: error("Missing int field: $key")

    private fun JsonObject.requiredLong(key: String): Long =
        this[key]?.jsonPrimitive?.longOrNull ?: error("Missing long field: $key")

    private fun JsonObject.optionalLong(key: String): Long? =
        this[key]?.jsonPrimitive?.longOrNull

    private fun JsonObject.requiredDouble(key: String): Double =
        this[key]?.jsonPrimitive?.doubleOrNull ?: error("Missing double field: $key")
}

private val JsonPrimitive.intOrNull: Int?
    get() = content.toIntOrNull()

private val JsonPrimitive.longOrNull: Long?
    get() = content.toLongOrNull()

private val JsonPrimitive.doubleOrNull: Double?
    get() = content.toDoubleOrNull()
