package de.youspeed.android.alpha

import java.net.URI
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

internal object BundlePathSafety {
    fun validateFileName(value: String) {
        require(value.isNotEmpty() && value == value.trim() && value != "." && value != ".." &&
            '/' !in value && '\\' !in value && value.none { it.isISOControl() }) { "Bundle paths require a local file name" }
    }

    // Country/shard IDs retain their logical identity; never accept dot segments.
    fun validateRegion(value: String) = value.split('/').forEach(::validateFileName)

    fun descendant(child: java.io.File, directory: java.io.File): java.io.File {
        require(child.canonicalPath.startsWith(directory.canonicalPath + java.io.File.separator)) {
            "Bundle path escapes its storage directory"
        }
        return child
    }
}

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

data class PackedBundleBase(
    val version: Int,
    val roads: BundleArtifact,
    val nodes: BundleArtifact? = null,
)

/** The native v4 generation-one reader is already implemented in the 1.5 dev
 * app. Published packed manifests retain their immutable 1.6 capability gate;
 * marketing versions must neither disable this reader nor claim future support. */
internal object PackedBundleReaderCompatibility {
    const val VERSION = "1.6"
}

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
    val packedBase: PackedBundleBase? = null,
) {
    fun validateLocalPaths() {
        BundlePathSafety.validateRegion(region)
        BundlePathSafety.validateFileName(bundleVersion)
        val artifacts = listOfNotNull(db, deltaIndex, penaltyRules, coverage?.poly, packedBase?.roads, packedBase?.nodes) + dbParts.orEmpty()
        artifacts.forEach { BundlePathSafety.validateFileName(it.file) }
    }

    fun validateLaunchContract(currentAppVersion: String = BuildConfig.MAP_COMPATIBILITY_APP_VERSION) {
        validateLocalPaths()
        val packed = format == "youspeed.v4.bundle.manifest"
        require(packed || format == "youspeed.v3.bundle.manifest") { "Unexpected manifest format: $format" }
        require(variant == if (packed) "v4" else "v3") { "Unexpected manifest variant: $variant" }
        require(schemaVersion == 1) { "Unsupported manifest schema version: $schemaVersion" }
        require(BundleAppVersion.isAtLeast(currentAppVersion, currentAppVersion)) { "Invalid app version" }
        val compatibilityVersion = if (packed) PackedBundleReaderCompatibility.VERSION else currentAppVersion
        require(BundleAppVersion.isAtLeast(compatibilityVersion, minAppVersion)) {
            "Bundle requires ${if (packed) "packed reader compatibility" else "app"} $minAppVersion; current compatibility is $compatibilityVersion"
        }
        if (packed) {
            require(BundleAppVersion.isAtLeast(minAppVersion, "1.6")) { "Packed bundles require reader compatibility 1.6 or later" }
            val base = requireNotNull(packedBase) { "Packed base is missing" }
            require(base.version == 1) { "Unsupported packed base version" }
            require(deltaIndex == null) { "SQL deltas cannot mutate packed generations" }
            require(dbParts.isNullOrEmpty()) { "Packed contexts require a single independently compressed artifact" }
            val artifacts = listOfNotNull(db, base.roads, base.nodes)
            require(artifacts.map { it.file }.distinct().size == artifacts.size) { "Packed artifact file names must be distinct" }
            artifacts.forEach { artifact ->
                require(artifact.file.isNotBlank() && artifact.file != "." && artifact.file != ".." &&
                    '/' !in artifact.file && '\\' !in artifact.file) { "Packed artifacts require local file names" }
                require(artifact.bytes > 0 && artifact.sha256.matches(Regex("[0-9a-fA-F]{64}"))) { "Invalid packed artifact identity" }
                val compression=artifact.compression?.trim()?.lowercase().orEmpty()
                require(compression in setOf("","none","gzip","zlib")) {"Unsupported packed transport compression"}
                if(compression !in setOf("","none"))require((artifact.uncompressedBytes?:0)>0&&
                    artifact.uncompressedSha256?.matches(Regex("[0-9a-fA-F]{64}"))==true) {"Packed installed identity is missing"}
            }
        } else require(packedBase == null) { "Packed artifacts require a v4 manifest" }
    }
}

data class V3DeltaEntry(val fromBundleVersion: String, val toBundleVersion: String, val region: String?, val deltaManifestFile: String)
data class V3DeltaManifest(val region: String, val fromBundleVersion: String, val toBundleVersion: String, val patch: BundleArtifact)

data class V3BundleTargetRegionConfig(
    val regionId: String,
    val regionName: String?,
)

data class V3BundleTargetPenaltyRules(
    val file: String,
    val source: String?,
)

data class V3BundleTargetCountryConfig(
    val rank: Int,
    val countryId: String,
    val countryCode: String,
    val iso2: String?,
    val penaltyRules: V3BundleTargetPenaltyRules?,
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
                    penaltyRules = country.optionalObject("penalty_rules")?.let { rules ->
                        V3BundleTargetPenaltyRules(
                            file = rules.requiredString("file"),
                            source = rules.optionalString("source"),
                        )
                    },
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
            packedBase = root.optionalObject("packed_base")?.let { packed ->
                PackedBundleBase(packed.requiredInt("version"), packed.requiredObject("roads").toBundleArtifact(),
                    packed.optionalObject("nodes")?.toBundleArtifact())
            },
        ).also { it.validateLocalPaths() }
    }

    fun decodeDeltaIndex(raw: String): List<V3DeltaEntry> {
        val root = json.parseToJsonElement(raw).jsonObject
        require(root.requiredString("format") == "youspeed.v3.delta.index") { "Unexpected delta index format" }
        return root.requiredArray("entries").map { element ->
            val entry = element.jsonObject
            V3DeltaEntry(entry.requiredString("from_bundle_version"), entry.requiredString("to_bundle_version"),
                entry.optionalString("region"), entry.requiredString("delta_manifest_file"))
        }
    }

    fun decodeDeltaManifest(raw: String): V3DeltaManifest {
        val root = json.parseToJsonElement(raw).jsonObject
        require(root.requiredString("format") == "youspeed.v3.delta.manifest") { "Unexpected delta manifest format" }
        return V3DeltaManifest(root.requiredString("region"), root.requiredString("from_bundle_version"),
            root.requiredString("to_bundle_version"), root.requiredObject("patch").toBundleArtifact())
    }

    fun encodeActiveBundleState(state: ActiveBundleState): String = JsonObject(buildMap {
        put("region", JsonPrimitive(state.region))
        state.countryCode?.let { put("country_code", JsonPrimitive(it)) }
        put("bundle_version", JsonPrimitive(state.bundleVersion))
        put("db_file_name", JsonPrimitive(state.dbFileName))
        put("db_path", JsonPrimitive(state.dbPath))
        put("db_sha256", JsonPrimitive(state.dbSha256))
        put("db_bytes", JsonPrimitive(state.dbBytes))
        put("manifest_url", JsonPrimitive(state.manifestUrl))
        put("activated_at_utc", JsonPrimitive(state.activatedAtUTC))
    }).toString()

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
        ).also {
            BundlePathSafety.validateRegion(it.region)
            BundlePathSafety.validateFileName(it.bundleVersion)
            BundlePathSafety.validateFileName(it.dbFileName)
            require(it.dbPath.none { char -> char.isISOControl() }) { "Invalid active bundle database path" }
        }
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
        ).also { BundlePathSafety.validateFileName(it.file) }
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
