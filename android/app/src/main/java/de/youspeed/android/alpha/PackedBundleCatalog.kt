package de.youspeed.android.alpha

import java.io.IOException
import java.time.Clock
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

internal data class PackedCatalogManifest(
    val region: String, val bundleVersion: String, val artifact: BundleArtifact,
)

/** Called only from an already authorized bundle check/download. The mutable
 * catalog selects a verified immutable manifest; legacy endpoints remain valid
 * when that catalog has no published packed generation for the region. */
internal class PackedBundleCatalogResolver(
    private val fetcher: HttpFetcher,
    private val clock: Clock,
    private val catalogUrl: String = DEFAULT_URL,
) {
    private var loadedAt: Long? = null
    private var entries: Map<String, PackedCatalogManifest> = emptyMap()

    @Synchronized fun resolve(requested: String): PackedCatalogManifest? {
        val legacy = HttpUrlFetcher.parseGitHubReleaseAssetUrl(requested) ?: return null
        if (legacy.owner != "volzinnovation" || legacy.repo != "youspeed.de" ||
            "-packed-v1-" in legacy.tag || !legacy.assetName.endsWith("_manifest.json")) return null
        if (loadedAt?.let { clock.millis() - it in 0 until 300_000 } != true) {
            entries = try { decode(fetcher.fetch(catalogUrl).toString(Charsets.UTF_8)) }
                catch (failure: HttpStatusException) { if (failure.statusCode == 404) emptyMap() else throw failure }
            loadedAt = clock.millis()
        }
        return entries[legacy.assetName.removeSuffix("_manifest.json")]
    }

    private fun decode(raw: String): Map<String, PackedCatalogManifest> {
        val root = Json.parseToJsonElement(raw).jsonObject
        fun value(key: String) = root[key]?.jsonPrimitive?.content
        if (value("format") != "youspeed.v4.bundle.catalog" || value("schema_version") != "1" || value("variant") != "v4")
            throw IOException("Unsupported packed bundle catalog")
        val out = linkedMapOf<String, PackedCatalogManifest>()
        for (item in root["bundles"]?.jsonArray ?: throw IOException("Packed catalog bundles are missing")) {
            val row = item.jsonObject
            val region = row["region"]?.jsonPrimitive?.content ?: throw IOException("Catalog region is missing")
            val version = row["bundle_version"]?.jsonPrimitive?.content ?: throw IOException("Catalog bundle version is missing")
            val ref = row["manifest"]?.jsonObject ?: throw IOException("Catalog manifest is missing")
            val artifact = BundleArtifact(
                ref["file"]?.jsonPrimitive?.content ?: throw IOException("Catalog manifest file is missing"),
                ref["bytes"]?.jsonPrimitive?.content?.toLongOrNull() ?: throw IOException("Catalog manifest size is missing"),
                ref["sha256"]?.jsonPrimitive?.content ?: throw IOException("Catalog manifest checksum is missing"),
                ref["url"]?.jsonPrimitive?.content ?: throw IOException("Catalog manifest URL is missing"),
            )
            if (region.isBlank() || version.isBlank() || artifact.bytes <= 0 ||
                !artifact.sha256.matches(Regex("[0-9a-fA-F]{64}")) || out.containsKey(region))
                throw IOException("Invalid or duplicate packed catalog entry")
            out[region] = PackedCatalogManifest(region, version, artifact)
        }
        return out
    }

    companion object {
        const val DEFAULT_URL = "https://github.com/volzinnovation/youspeed.de/releases/download/packed-runtime-v1-latest/catalog.json"
    }
}
