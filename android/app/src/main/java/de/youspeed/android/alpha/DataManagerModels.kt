package de.youspeed.android.alpha

import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.io.File
import java.security.MessageDigest
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.time.Instant
import java.util.Locale
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.long
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.atan
import kotlin.math.exp
import kotlin.math.ln
import kotlin.math.max
import kotlin.math.min
import kotlin.math.tan

/** Administrative artwork for manual selection only. Never use this for bundle routing or TSR. */
data class DataManagerRegion(
    val id: String,
    val bounds: List<Double>,
    val polygons: List<List<List<List<Double>>>>,
) {
    val area: Double get() = (bounds[2] - bounds[0]) * (bounds[3] - bounds[1])

    fun contains(longitude: Double, latitude: Double): Boolean {
        if (!longitude.isFinite() || !latitude.isFinite() ||
            longitude !in bounds[0]..bounds[2] || latitude !in bounds[1]..bounds[3]) return false
        fun inRing(ring: List<List<Double>>): Boolean {
            var inside = false
            for (i in 0 until ring.size - 1) {
                val a = ring[i]; val b = ring[i + 1]
                val dx = b[0] - a[0]; val dy = b[1] - a[1]
                if (dx == 0.0 && dy == 0.0) continue
                val cross = (longitude - a[0]) * dy - (latitude - a[1]) * dx
                if (abs(cross) <= 1e-12 && longitude in min(a[0], b[0])..max(a[0], b[0]) &&
                    latitude in min(a[1], b[1])..max(a[1], b[1])) return true
                if ((a[1] > latitude) != (b[1] > latitude) &&
                    longitude < dx * (latitude - a[1]) / dy + a[0]) inside = !inside
            }
            return inside
        }
        return polygons.any { polygon -> inRing(polygon.first()) && polygon.drop(1).none(::inRing) }
    }
}

data class DataManagerMapCatalog(val regions: List<DataManagerRegion>, val attribution: String) {
    fun hit(longitude: Double, latitude: Double, availableIds: Set<String>): String? = regions.asSequence()
        .filter { it.id in availableIds && it.contains(longitude, latitude) }
        .sortedWith(compareBy<DataManagerRegion> { it.area }.thenBy { it.id }).firstOrNull()?.id

    companion object {
        const val ASSET_PATH = "RegionalCoverage/official-regions-v1.json"

        fun decode(bytes: ByteArray): DataManagerMapCatalog {
            require(bytes.size <= 2_000_000) { "Administrative geometry is too large" }
            val root = Json.parseToJsonElement(bytes.toString(Charsets.UTF_8)).jsonObject
            require(root.getValue("schema_version").jsonPrimitive.int == 1)
            require(root.getValue("boundary_kind").jsonPrimitive.content == "official_administrative_and_statistical_boundaries")
            val regions = root.getValue("regions").jsonArray.map { value ->
                val region = value.jsonObject
                val bounds = region.getValue("bbox").jsonArray.map { it.jsonPrimitive.double }
                require(bounds.size == 4 && bounds.all(Double::isFinite) && bounds[0] < bounds[2] && bounds[1] < bounds[3])
                val polygons = region.getValue("polygons").jsonArray.map { polygon -> polygon.jsonArray.map { ring ->
                    ring.jsonArray.map { point -> point.jsonArray.map { it.jsonPrimitive.double } }.also { points ->
                        require(points.size >= 4 && points.first() == points.last())
                        points.forEach { p -> require(p.size == 2 && p.all(Double::isFinite) &&
                            p[0] in -180.0..180.0 && p[1] in -90.0..90.0 &&
                            p[0] in bounds[0]..bounds[2] && p[1] in bounds[1]..bounds[3]) }
                    }
                }.also { require(it.isNotEmpty()) } }.also { require(it.isNotEmpty()) }
                DataManagerRegion(region.getValue("id").jsonPrimitive.content, bounds, polygons)
            }
            require(regions.size in 1..1000 && regions.map { it.id }.toSet().size == regions.size)
            return DataManagerMapCatalog(regions, root.getValue("attribution").jsonPrimitive.content)
        }
    }
}

/** A normalized Web Mercator viewport independent of pixel size and device rotation. */
data class DataManagerViewport(val centerX: Double, val centerY: Double, val span: Double) {
    fun safe() = DataManagerViewport(
        centerX.takeIf(Double::isFinite)?.coerceIn(0.0, 1.0) ?: GERMANY.centerX,
        centerY.takeIf(Double::isFinite)?.coerceIn(0.0, 1.0) ?: GERMANY.centerY,
        span.takeIf(Double::isFinite)?.coerceIn(0.00002, 1.2) ?: GERMANY.span,
    )

    fun transformed(panX: Double, panY: Double, zoom: Double, anchorX: Double, anchorY: Double,
        width: Double, height: Double): DataManagerViewport {
        if (width <= 0 || height <= 0 || !zoom.isFinite() || zoom <= 0) return this
        val side = min(width, height)
        val nextSpan = (span / zoom).coerceIn(0.00002, 1.2)
        return DataManagerViewport(
            centerX + (anchorX - width / 2) * (span - nextSpan) / side - panX * span / side,
            centerY + (anchorY - height / 2) * (span - nextSpan) / side - panY * span / side,
            nextSpan,
        ).safe()
    }

    fun coordinateAt(x: Double, y: Double, width: Double, height: Double): Pair<Double, Double> {
        val scale = min(width, height).coerceAtLeast(1.0) / span
        return longitude(centerX + (x - width / 2) / scale) to latitude(centerY + (y - height / 2) / scale)
    }

    companion object {
        fun projectX(longitude: Double) = (longitude + 180.0) / 360.0
        fun projectY(latitude: Double) = (1.0 - ln(tan(PI / 4 + latitude.coerceIn(-85.0, 85.0) * PI / 360)) / PI) / 2
        fun longitude(x: Double) = x * 360.0 - 180.0
        fun latitude(y: Double) = (2 * atan(exp((1 - 2 * y) * PI)) - PI / 2) * 180 / PI
        fun fit(bounds: List<Double>): DataManagerViewport {
            val minX = projectX(bounds[0]); val maxX = projectX(bounds[2])
            val minY = projectY(bounds[3]); val maxY = projectY(bounds[1])
            return DataManagerViewport((minX + maxX) / 2, (minY + maxY) / 2,
                max(maxX - minX, maxY - minY) * 1.2).safe()
        }
        // Includes Iceland, all of Sweden, Romania, and continental France.
        val EUROPE = DataManagerViewport(projectX(3.5), (projectY(72.0) + projectY(34.0)) / 2, 0.235)
        // Germany is the initial focus; Europe and per-region jumps remain available.
        val GERMANY = fit(listOf(5.5, 47.0, 15.8, 55.6))
    }
}

data class DataManagerPackageMetadata(
    val bundleVersion: String,
    val createdAtUTC: String?,
    val bytes: Long?,
) {
    companion object {
        fun fromManifest(manifest: V3BundleManifest): DataManagerPackageMetadata {
            val parts = manifest.dbParts.orEmpty()
            val bytes = if (parts.isNotEmpty()) {
                if (parts.any { it.bytes <= 0 }) null else runCatching {
                    parts.fold(0L) { total, part -> Math.addExact(total, part.bytes) }
                }.getOrNull()
            } else manifest.db.bytes.takeIf { it > 0 }
            return DataManagerPackageMetadata(manifest.bundleVersion,
                manifest.createdAtUTC.takeIf { runCatching { Instant.parse(it) }.isSuccess }, bytes)
        }
    }
}

data class DataManagerMetadataIndexEntry(val manifestUrl: String, val metadata: DataManagerPackageMetadata)

object DataManagerMetadataIndex {
    const val MAX_BYTES = 512 * 1024

    fun releaseUrl(owner: String, repo: String) =
        "https://github.com/$owner/$repo/releases/download/bundle-metadata/bundle-metadata.v3.json"

    fun matching(entries: Map<String, DataManagerMetadataIndexEntry>, manifestUrls: Map<String, String>) =
        entries.filter { (id, entry) -> manifestUrls[id] == entry.manifestUrl }

    fun decode(bytes: ByteArray): Map<String, DataManagerMetadataIndexEntry> {
        require(bytes.size <= MAX_BYTES) { "Bundle metadata index exceeds size limit" }
        val root = Json.parseToJsonElement(bytes.toString(Charsets.UTF_8)).jsonObject
        require(root.getValue("format").jsonPrimitive.content == "youspeed.v3.bundle.metadata")
        require(root.getValue("schema_version").jsonPrimitive.int == 1)
        val result = mutableMapOf<String, DataManagerMetadataIndexEntry>()
        for (element in root.getValue("bundles").jsonArray) {
            val entry = element.jsonObject
            val id = entry.getValue("id").jsonPrimitive.content
            val version = entry.getValue("bundle_version").jsonPrimitive.content
            val date = entry.getValue("created_at_utc").jsonPrimitive.content
            val size = entry.getValue("download_bytes").jsonPrimitive.long
            require(id !in result && version.isNotEmpty() && size > 0)
            Instant.parse(date)
            result[id] = DataManagerMetadataIndexEntry(entry.getValue("manifest_url").jsonPrimitive.content,
                DataManagerPackageMetadata(version, date, size))
        }
        return result
    }
}

/** Validated snapshots are isolated by source URL and survive app restarts. */
internal class DataManagerMetadataIndexCache(directory: File, sourceUrl: String) {
    private val key = MessageDigest.getInstance("SHA-256").digest(sourceUrl.toByteArray(Charsets.UTF_8))
        .joinToString("") { "%02x".format(it) }
    val file = File(File(directory, "bundle-metadata"), "$key.json")

    fun load(): Map<String, DataManagerMetadataIndexEntry>? = runCatching {
        require(file.length() <= DataManagerMetadataIndex.MAX_BYTES)
        DataManagerMetadataIndex.decode(file.readBytes())
    }.getOrNull()

    fun save(bytes: ByteArray): Map<String, DataManagerMetadataIndexEntry> {
        val index = DataManagerMetadataIndex.decode(bytes)
        file.parentFile?.mkdirs()
        val temporary = File.createTempFile("metadata-", ".tmp", file.parentFile)
        try {
            temporary.writeBytes(bytes)
            check(temporary.renameTo(file)) { "Could not save bundle metadata snapshot" }
        } finally {
            temporary.delete()
        }
        return index
    }
}

enum class DataManagerMetadataStatus { UNKNOWN, LOADING, READY, UNAVAILABLE, ERROR }
data class DataManagerMetadataState(
    val status: DataManagerMetadataStatus = DataManagerMetadataStatus.UNKNOWN,
    val metadata: DataManagerPackageMetadata? = null,
    val checkedAtMillis: Long = 0L,
)

enum class DataManagerDisplayState { INSTALLED, AVAILABLE, UNAVAILABLE, UNKNOWN }

/** Presentation of one independently requested entry in the existing serial transfer queue. */
data class DataManagerTransferState(val active: Boolean, val queued: Boolean, val error: String?) {
    fun canRequest(metadata: DataManagerMetadataState?): Boolean = !active && !queued &&
        metadata?.status != DataManagerMetadataStatus.UNAVAILABLE

    companion object {
        fun resolve(id: String, activeId: String?, queuedIds: List<String>, errors: Map<String, String>): DataManagerTransferState =
            DataManagerTransferState(activeId == id, activeId != id && id in queuedIds,
                errors[id].takeIf { activeId != id && id !in queuedIds })
    }
}

fun dataManagerDisplayState(installed: Boolean, metadata: DataManagerMetadataState?): DataManagerDisplayState = when {
    installed -> DataManagerDisplayState.INSTALLED
    metadata?.status == DataManagerMetadataStatus.UNAVAILABLE -> DataManagerDisplayState.UNAVAILABLE
    metadata?.metadata != null && metadata.status in setOf(DataManagerMetadataStatus.READY, DataManagerMetadataStatus.UNKNOWN) -> DataManagerDisplayState.AVAILABLE
    else -> DataManagerDisplayState.UNKNOWN
}

internal class DataManagerPackageUnavailable : IOException("Package is not published")

data class DataManagerInstalledRegion(
    val versionCount: Int,
    val totalDatabaseBytes: Long,
    val newestPackage: DataManagerPackageMetadata,
)

data class DataManagerPackageScope(val regionKey: String, val isCountryPackage: Boolean)

object DataManagerScopeResolver {
    fun key(value: String): String = value.trim().lowercase(Locale.US).replace(" ", "-").replace("_", "-").replace("/", "-")

    fun resolve(region: String, country: String, installedKeys: Set<String>): DataManagerPackageScope? {
        val exact = key(region)
        val wholeCountry = key(country)
        return when {
            exact in installedKeys -> DataManagerPackageScope(exact, false)
            wholeCountry in installedKeys -> DataManagerPackageScope(wholeCountry, exact != wholeCountry)
            else -> null
        }
    }
}

/** Metadata only: no database URLs are followed. Byte, request, and elapsed-time limits are independent. */
internal class DataManagerManifestReader(
    private val connectionFactory: (URL) -> HttpURLConnection = { it.openConnection() as HttpURLConnection },
) {
    fun read(endpoint: V3ManifestEndpoint): DataManagerPackageMetadata {
        val manifest = ContractJson.decodeBundleManifest(readBytes(endpoint.manifestUrl).toString(Charsets.UTF_8))
        manifest.validateLaunchContract()
        check(manifest.region.substringAfterLast('/') == endpoint.manifestRegion) { "Region metadata mismatch" }
        return DataManagerPackageMetadata.fromManifest(manifest)
    }

    fun readIndex(url: String): Map<String, DataManagerMetadataIndexEntry> = DataManagerMetadataIndex.decode(readIndexBytes(url))

    fun readIndexBytes(url: String): ByteArray = readBytes(url)

    private fun readBytes(url: String): ByteArray {
        val connection = connectionFactory(URL(url))
        connection.connectTimeout = 10_000
        connection.readTimeout = 10_000
        connection.instanceFollowRedirects = true
        connection.setRequestProperty("User-Agent", "YouSpeedAndroid/1.0")
        connection.setRequestProperty("Accept", "application/json")
        val deadline = System.nanoTime() + 20_000_000_000L
        try {
            val status = connection.responseCode
            if (status == 404 || status == 410) throw DataManagerPackageUnavailable()
            check(status in 200..299) { "Package metadata could not be checked" }
            check(connection.contentLengthLong <= MAX_BYTES) { "Package metadata exceeds size limit" }
            return connection.inputStream.use { readBounded(it) {
                check(!Thread.currentThread().isInterrupted && System.nanoTime() < deadline) { "Metadata request timed out" }
            } }
        } finally {
            connection.disconnect()
        }
    }

    companion object {
        const val MAX_BYTES = 512 * 1024
        internal fun readBounded(input: InputStream, checkDeadline: () -> Unit = {}): ByteArray {
            val output = ByteArrayOutputStream()
            val buffer = ByteArray(4096)
            while (true) {
                checkDeadline()
                val read = input.read(buffer)
                if (read < 0) break
                check(output.size() <= MAX_BYTES - read) { "Package metadata exceeds size limit" }
                output.write(buffer, 0, read)
            }
            return output.toByteArray()
        }
    }
}
