package de.youspeed.android.alpha

import java.io.BufferedInputStream
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.security.MessageDigest
import java.time.Clock
import java.time.Instant
import java.util.Locale
import java.util.zip.GZIPInputStream
import java.util.zip.InflaterInputStream
import kotlin.math.abs

enum class BundleSyncMode {
    BOOTSTRAP,
    UP_TO_DATE,
    FULL_DOWNLOAD,
}

data class ActiveBundleState(
    val region: String,
    val countryCode: String?,
    val bundleVersion: String,
    val dbFileName: String,
    val dbPath: String,
    val dbSha256: String,
    val dbBytes: Long,
    val manifestUrl: String,
    val activatedAtUTC: String,
)

data class BundleSyncResult(
    val mode: BundleSyncMode,
    val bundleVersion: String,
    val dbPath: String,
    val details: String,
)

data class DownloadedBundleInfo(
    val region: String,
    val bundleVersion: String,
    val countryCode: String?,
    val dbFileName: String,
    val dbPath: String,
)

data class LocalBundleRoute(
    val region: String,
    val bundleVersion: String,
    val countryCode: String?,
    val dbPath: String,
)

private data class MaterializedDatabaseArtifact(
    val bytes: Long,
    val sha256: String,
)

interface HttpFetcher {
    @Throws(IOException::class)
    fun fetch(url: String): ByteArray

    @Throws(IOException::class)
    fun fetchToFile(url: String, destination: File)
}

class BundleBootstrapper(
    private val rootDir: File,
    private val httpFetcher: HttpFetcher,
    private val clock: Clock = Clock.systemUTC(),
    private val assetReader: AppAssetReader? = null,
) {
    private data class CoverageRing(
        val isHole: Boolean,
        val points: List<Pair<Double, Double>>,
    )

    private data class CoverageEntry(
        val region: String,
        val bundleVersion: String,
        val countryCode: String?,
        val dbPath: String,
        val bbox: BundleCoverageBBox,
        val rings: List<CoverageRing>,
    )

    private val coverageCacheTtlMillis = 60_000L
    private var coverageCacheLoadedAtMillis = 0L
    private var cachedCoverageEntries: List<CoverageEntry> = emptyList()

    fun activeState(): ActiveBundleState? {
        val stateFile = File(rootDir, "active_bundle.json")
        if (!stateFile.exists()) {
            return null
        }
        return ContractJson.decodeActiveBundleState(stateFile.readText())
    }

    fun listDownloadedBundles(): List<DownloadedBundleInfo> {
        val bundlesRoot = File(rootDir, "bundles")
        if (!bundlesRoot.exists()) {
            return emptyList()
        }
        val regions = bundlesRoot.listFiles { file -> file.isDirectory } ?: return emptyList()
        return regions.flatMap { regionDir ->
            val versions = regionDir.listFiles { file -> file.isDirectory } ?: emptyArray()
            versions.mapNotNull { versionDir ->
                val manifestFile = File(versionDir, "bundle-manifest.v3.json")
                if (!manifestFile.exists()) {
                    return@mapNotNull null
                }
                val manifest = ContractJson.decodeBundleManifest(manifestFile.readText())
                val dbFile = File(versionDir, manifest.db.file)
                if (!dbFile.exists()) {
                    return@mapNotNull null
                }
                DownloadedBundleInfo(
                    region = manifest.region,
                    bundleVersion = manifest.bundleVersion,
                    countryCode = manifest.countryCode,
                    dbFileName = manifest.db.file,
                    dbPath = dbFile.absolutePath,
                )
            }
        }.sortedWith(compareBy<DownloadedBundleInfo> { it.region }.thenByDescending { it.bundleVersion }.thenBy { it.dbFileName })
    }

    fun removeDownloadedBundlesKeepingSeed(): Int {
        val bundlesRoot = File(rootDir, "bundles")
        if (!bundlesRoot.exists()) {
            return 0
        }
        var removed = 0
        (bundlesRoot.listFiles { file -> file.isDirectory } ?: emptyArray()).forEach { entry ->
            if (entry.name == "seed") {
                return@forEach
            }
            if (entry.deleteRecursively()) {
                removed += 1
            }
        }
        val state = activeState()
        if (state != null && state.bundleVersion != "seed") {
            clearActiveState()
        }
        invalidateCoverageCache()
        return removed
    }

    fun removeDownloadedBundles(region: String): Int {
        val token = tokenize(region)
        if (token.isEmpty()) {
            return 0
        }
        val bundlesRoot = File(rootDir, "bundles")
        if (!bundlesRoot.exists()) {
            return 0
        }
        var removed = 0
        (bundlesRoot.listFiles { file -> file.isDirectory } ?: emptyArray()).forEach { entry ->
            if (tokenize(entry.name) == token && entry.deleteRecursively()) {
                removed += 1
            }
        }
        val state = activeState()
        if (state != null && tokenize(state.region) == token) {
            clearActiveState()
        }
        invalidateCoverageCache()
        return removed
    }

    fun resolveLocalBundleRoute(
        lat: Double,
        lon: Double,
        fallbackDBPath: String?,
    ): LocalBundleRoute? {
        val entries = loadCoverageEntriesIfNeeded()
        if (entries.isEmpty()) {
            val fallback = fallbackDBPath?.trim().orEmpty()
            return if (fallback.isEmpty()) null else LocalBundleRoute("unknown", "unknown", null, fallback)
        }

        val matches = entries.filter { pointIsInsideCoverage(lon = lon, lat = lat, entry = it) }
        if (matches.isEmpty()) {
            val fallback = fallbackDBPath?.trim().orEmpty()
            return if (fallback.isEmpty()) null else LocalBundleRoute("unknown", "unknown", null, fallback)
        }

        val best = matches.sortedWith(
            compareBy<CoverageEntry> { bboxArea(it.bbox) }
                .thenByDescending { it.bundleVersion }
                .thenBy { it.region },
        ).first()
        return LocalBundleRoute(
            region = best.region,
            bundleVersion = best.bundleVersion,
            countryCode = best.countryCode,
            dbPath = best.dbPath,
        )
    }

    @Throws(IOException::class)
    fun fetchManifest(manifestUrl: String): V3BundleManifest {
        val raw = httpFetcher.fetch(manifestUrl).toString(Charsets.UTF_8)
        return decodeManifestOrThrow(manifestUrl, raw)
    }

    @Throws(IOException::class)
    fun syncFromManifestUrl(manifestUrl: String): BundleSyncResult {
        ensureRoot()
        val manifestBytes = httpFetcher.fetch(manifestUrl)
        val manifestRaw = manifestBytes.toString(Charsets.UTF_8)
        val manifest = decodeManifestOrThrow(manifestUrl, manifestRaw)

        val current = activeState()
        if (current != null &&
            current.region == manifest.region &&
            current.bundleVersion == manifest.bundleVersion &&
            File(current.dbPath).exists()
        ) {
            return BundleSyncResult(
                mode = BundleSyncMode.UP_TO_DATE,
                bundleVersion = current.bundleVersion,
                dbPath = current.dbPath,
                details = "already active",
            )
        }

        val bundleDir = File(File(rootDir, "bundles"), "${tokenize(manifest.region)}/${tokenize(manifest.bundleVersion)}")
        if (!bundleDir.exists() && !bundleDir.mkdirs()) {
            throw IOException("Unable to create bundle directory: ${bundleDir.absolutePath}")
        }

        val stagingDir = File(rootDir, "staging").also {
            if (!it.exists() && !it.mkdirs()) {
                throw IOException("Unable to create staging directory: ${it.absolutePath}")
            }
        }
        val stagingDb = File.createTempFile("bundle-", ".tmp", stagingDir)
        val compression = normalizedCompression(manifest.db)
        val downloadedArtifact = if (compression == null) {
            stagingDb
        } else {
            File.createTempFile("bundle-download-", ".tmp", stagingDir)
        }

        try {
            if (!manifest.dbParts.isNullOrEmpty()) {
                assembleMultipartArtifact(downloadedArtifact, manifest, manifestUrl)
            } else {
                httpFetcher.fetchToFile(
                    url = ContractJson.resolveArtifactUrl(manifest.db, manifestUrl),
                    destination = downloadedArtifact,
                )
                validateFile(
                    file = downloadedArtifact,
                    expectedBytes = manifest.db.bytes,
                    expectedSha256 = manifest.db.sha256,
                    label = manifest.db.file,
                )
            }

            val dbArtifact = if (compression == null) {
                MaterializedDatabaseArtifact(
                    bytes = stagingDb.length(),
                    sha256 = manifest.db.sha256.lowercase(Locale.US),
                )
            } else {
                materializeCompressedDatabaseArtifact(
                    artifactFile = downloadedArtifact,
                    artifact = manifest.db,
                    compression = compression,
                    destinationDb = stagingDb,
                )
            }

            val finalDb = File(bundleDir, manifest.db.file)
            if (finalDb.exists() && !finalDb.delete()) {
                throw IOException("Unable to replace existing DB: ${finalDb.absolutePath}")
            }
            if (!stagingDb.renameTo(finalDb)) {
                stagingDb.copyTo(finalDb, overwrite = true)
                if (!stagingDb.delete()) {
                    stagingDb.deleteOnExit()
                }
            }

            File(bundleDir, "bundle-manifest.v3.json").writeText(manifestRaw)

            val state = ActiveBundleState(
                region = manifest.region,
                countryCode = manifest.countryCode,
                bundleVersion = manifest.bundleVersion,
                dbFileName = manifest.db.file,
                dbPath = finalDb.absolutePath,
                dbSha256 = dbArtifact.sha256,
                dbBytes = dbArtifact.bytes,
                manifestUrl = manifestUrl,
                activatedAtUTC = Instant.now(clock).toString(),
            )
            File(rootDir, "active_bundle.json").writeText(ContractJson.encodeActiveBundleState(state))
            invalidateCoverageCache()

            return BundleSyncResult(
                mode = BundleSyncMode.FULL_DOWNLOAD,
                bundleVersion = manifest.bundleVersion,
                dbPath = finalDb.absolutePath,
                details = if (!manifest.dbParts.isNullOrEmpty()) {
                    "full multipart bundle activated"
                } else {
                    "full bundle activated"
                },
            )
        } finally {
            if (stagingDb.exists()) {
                stagingDb.delete()
            }
            if (downloadedArtifact != stagingDb && downloadedArtifact.exists()) {
                downloadedArtifact.delete()
            }
        }
    }

    private fun assembleMultipartArtifact(
        artifactFile: File,
        manifest: V3BundleManifest,
        manifestUrl: String,
    ) {
        val dbParts = manifest.dbParts ?: error("db_parts missing")
        require(dbParts.isNotEmpty()) { "db_parts is empty" }

        var totalBytes = 0L
        FileOutputStream(artifactFile).use { output ->
            for (part in dbParts) {
                val partFile = File.createTempFile("bundle-part-", ".tmp", artifactFile.parentFile)
                try {
                    httpFetcher.fetchToFile(
                        url = ContractJson.resolveArtifactUrl(part, manifestUrl),
                        destination = partFile,
                    )
                    validateFile(
                        file = partFile,
                        expectedBytes = part.bytes,
                        expectedSha256 = part.sha256,
                        label = part.file,
                    )
                    partFile.inputStream().use { input -> input.copyTo(output) }
                    totalBytes += partFile.length()
                } finally {
                    if (partFile.exists()) {
                        partFile.delete()
                    }
                }
            }
        }

        if (totalBytes != manifest.db.bytes) {
            throw IllegalArgumentException(
                "db_parts size mismatch: expected ${manifest.db.bytes}, got $totalBytes"
            )
        }
        validateFile(
            file = artifactFile,
            expectedBytes = manifest.db.bytes,
            expectedSha256 = manifest.db.sha256,
            label = manifest.db.file,
        )
    }

    private fun ensureRoot() {
        if (!rootDir.exists() && !rootDir.mkdirs()) {
            throw IOException("Unable to create root directory: ${rootDir.absolutePath}")
        }
    }

    private fun clearActiveState() {
        val stateFile = File(rootDir, "active_bundle.json")
        if (stateFile.exists()) {
            stateFile.delete()
        }
    }

    @Synchronized
    private fun invalidateCoverageCache() {
        cachedCoverageEntries = emptyList()
        coverageCacheLoadedAtMillis = 0L
    }

    @Synchronized
    private fun loadCoverageEntriesIfNeeded(forceReload: Boolean = false): List<CoverageEntry> {
        val now = clock.millis()
        if (!forceReload &&
            coverageCacheLoadedAtMillis > 0L &&
            now - coverageCacheLoadedAtMillis < coverageCacheTtlMillis
        ) {
            return cachedCoverageEntries
        }

        val bundlesRoot = File(rootDir, "bundles")
        if (!bundlesRoot.exists()) {
            cachedCoverageEntries = emptyList()
            coverageCacheLoadedAtMillis = now
            return cachedCoverageEntries
        }

        val bundleDirs = mutableListOf<File>()
        (bundlesRoot.listFiles { file -> file.isDirectory } ?: emptyArray())
            .sortedBy { it.name }
            .forEach { regionDir ->
                if (regionDir.name == "seed") {
                    return@forEach
                }
                if (File(regionDir, "bundle-manifest.v3.json").exists()) {
                    bundleDirs += regionDir
                    return@forEach
                }
                bundleDirs += (regionDir.listFiles { file -> file.isDirectory } ?: emptyArray())
            }

        val loaded = mutableListOf<CoverageEntry>()
        bundleDirs.forEach { bundleDir ->
            val manifestFile = File(bundleDir, "bundle-manifest.v3.json")
            if (!manifestFile.exists()) {
                return@forEach
            }
            val manifest = runCatching { ContractJson.decodeBundleManifest(manifestFile.readText()) }.getOrNull()
                ?: return@forEach
            val coverage = manifest.coverage ?: return@forEach
            val dbFile = File(bundleDir, manifest.db.file)
            if (!dbFile.exists()) {
                return@forEach
            }

            val rings = if (coverage.poly != null) {
                val polyText = loadCoveragePolyText(
                    polyFile = coverage.poly.file,
                    region = manifest.region,
                    bundleDir = bundleDir,
                )
                if (polyText == null) {
                    emptyList()
                } else {
                    runCatching { parsePolyRings(polyText) }.getOrElse { emptyList() }
                }
            } else {
                emptyList()
            }

            loaded += CoverageEntry(
                region = manifest.region,
                bundleVersion = manifest.bundleVersion,
                countryCode = manifest.countryCode,
                dbPath = dbFile.absolutePath,
                bbox = coverage.bbox,
                rings = rings,
            )
        }

        cachedCoverageEntries = loaded
        coverageCacheLoadedAtMillis = now
        return loaded
    }

    private fun loadCoveragePolyText(
        polyFile: String,
        region: String,
        bundleDir: File,
    ): String? {
        val requestedName = File(polyFile).name
        listOf(polyFile, requestedName).forEach { candidate ->
            if (candidate.isBlank()) {
                return@forEach
            }
            val file = File(bundleDir, candidate)
            if (file.exists()) {
                return file.readText()
            }
        }
        return readEmbeddedCoveragePolyText(polyFile = polyFile, region = region)
    }

    private fun readEmbeddedCoveragePolyText(
        polyFile: String,
        region: String,
    ): String? {
        val reader = assetReader ?: return null
        val requestedNames = mutableListOf<String>()

        fun appendRequestedName(raw: String) {
            val normalized = File(raw).name.trim()
            if (normalized.isBlank()) {
                return
            }
            if (requestedNames.none { it.equals(normalized, ignoreCase = true) }) {
                requestedNames += normalized
            }
        }

        appendRequestedName(polyFile)
        appendRequestedName(normalizedCoveragePolyName(region))

        requestedNames.forEach { requestedName ->
            reader.readTextOrNull("CoveragePolys/$requestedName")?.let { return it }
            reader.readTextOrNull(requestedName)?.let { return it }
        }

        val availableNames = reader.listOrNull("CoveragePolys").orEmpty()
        requestedNames.forEach { requestedName ->
            val normalizedRequested = requestedName.lowercase(Locale.US)
            val matchedName = availableNames.firstOrNull { normalizedRequested.endsWith(it.lowercase(Locale.US)) }
            if (matchedName != null) {
                reader.readTextOrNull("CoveragePolys/$matchedName")?.let { return it }
            }
        }
        return null
    }

    private fun normalizedCoveragePolyName(region: String): String {
        val trimmed = region.trim().lowercase(Locale.US)
        val lastComponent = trimmed.substringAfterLast('/')
        val normalized = lastComponent
            .replace(" ", "-")
            .replace("_", "-")
        return if (normalized.isBlank()) "" else "$normalized.poly"
    }

    private fun parsePolyRings(raw: String): List<CoverageRing> {
        val lines = raw.lineSequence()
            .map { it.trim() }
            .toList()
        if (lines.isEmpty()) {
            return emptyList()
        }

        val rings = mutableListOf<CoverageRing>()
        var index = 1
        while (index < lines.size) {
            val token = lines[index]
            index += 1
            if (token.isEmpty()) {
                continue
            }
            if (token.equals("END", ignoreCase = true)) {
                break
            }

            val isHole = token.startsWith("!")
            val points = mutableListOf<Pair<Double, Double>>()
            while (index < lines.size) {
                val pointLine = lines[index]
                index += 1
                if (pointLine.isEmpty()) {
                    continue
                }
                if (pointLine.equals("END", ignoreCase = true)) {
                    break
                }
                val components = pointLine.split(Regex("\\s+"))
                if (components.size < 2) {
                    continue
                }
                val lon = components[0].toDoubleOrNull() ?: continue
                val lat = components[1].toDoubleOrNull() ?: continue
                points += lon to lat
            }
            if (points.size >= 3) {
                val closedPoints = if (points.first() == points.last()) points else points + points.first()
                rings += CoverageRing(isHole = isHole, points = closedPoints)
            }
        }
        return rings
    }

    private fun bboxArea(bbox: BundleCoverageBBox): Double {
        val width = maxOf(0.0, bbox.maxLon - bbox.minLon)
        val height = maxOf(0.0, bbox.maxLat - bbox.minLat)
        return width * height
    }

    private fun pointIsInsideCoverage(
        lon: Double,
        lat: Double,
        entry: CoverageEntry,
    ): Boolean {
        if (lon < entry.bbox.minLon || lon > entry.bbox.maxLon || lat < entry.bbox.minLat || lat > entry.bbox.maxLat) {
            return false
        }
        if (entry.rings.isEmpty()) {
            return true
        }

        val insideOuter = entry.rings
            .filterNot { it.isHole }
            .any { pointInRing(lon = lon, lat = lat, ring = it.points) }
        if (!insideOuter) {
            return false
        }
        val insideHole = entry.rings
            .filter { it.isHole }
            .any { pointInRing(lon = lon, lat = lat, ring = it.points) }
        return !insideHole
    }

    private fun pointInRing(
        lon: Double,
        lat: Double,
        ring: List<Pair<Double, Double>>,
    ): Boolean {
        if (ring.size < 4) {
            return false
        }
        var inside = false
        for (index in 0 until ring.lastIndex) {
            val current = ring[index]
            val next = ring[index + 1]
            if (pointOnSegment(px = lon, py = lat, x1 = current.first, y1 = current.second, x2 = next.first, y2 = next.second)) {
                return true
            }
            val crossesLatitude = (current.second > lat) != (next.second > lat)
            val denominator = if ((next.second - current.second) == 0.0) 1e-30 else (next.second - current.second)
            val xAtLat = ((next.first - current.first) * (lat - current.second) / denominator) + current.first
            if (crossesLatitude && lon < xAtLat) {
                inside = !inside
            }
        }
        return inside
    }

    private fun pointOnSegment(
        px: Double,
        py: Double,
        x1: Double,
        y1: Double,
        x2: Double,
        y2: Double,
    ): Boolean {
        val epsilon = 1e-12
        val cross = ((px - x1) * (y2 - y1)) - ((py - y1) * (x2 - x1))
        if (abs(cross) > epsilon) {
            return false
        }
        val dot = ((px - x1) * (x2 - x1)) + ((py - y1) * (y2 - y1))
        if (dot < -epsilon) {
            return false
        }
        val squaredLength = ((x2 - x1) * (x2 - x1)) + ((y2 - y1) * (y2 - y1))
        return dot - squaredLength <= epsilon
    }

    private fun validateFile(
        file: File,
        expectedBytes: Long,
        expectedSha256: String,
        label: String,
    ) {
        val actualBytes = file.length()
        if (actualBytes != expectedBytes) {
            throw IllegalArgumentException("$label size mismatch: expected $expectedBytes, got $actualBytes")
        }
        val actualSha = sha256Hex(file)
        if (actualSha != expectedSha256.lowercase(Locale.US)) {
            throw IllegalArgumentException("$label sha256 mismatch")
        }
    }

    private fun sha256Hex(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
            while (true) {
                val read = input.read(buffer)
                if (read <= 0) {
                    break
                }
                digest.update(buffer, 0, read)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    private fun normalizedCompression(artifact: BundleArtifact): String? {
        val raw = artifact.compression?.trim()?.lowercase(Locale.US).orEmpty()
        return raw.takeIf { it.isNotEmpty() && it != "none" }
    }

    private fun materializeCompressedDatabaseArtifact(
        artifactFile: File,
        artifact: BundleArtifact,
        compression: String,
        destinationDb: File,
    ): MaterializedDatabaseArtifact {
        val expectedBytes = artifact.uncompressedBytes
            ?: throw IllegalArgumentException("Compressed bundle db is missing uncompressed_bytes")
        val expectedSha256 = artifact.uncompressedSha256
            ?.trim()
            ?.takeIf { it.isNotEmpty() }
            ?.lowercase(Locale.US)
            ?: throw IllegalArgumentException("Compressed bundle db is missing uncompressed_sha256")

        if (destinationDb.exists()) {
            destinationDb.delete()
        }
        val digest = MessageDigest.getInstance("SHA-256")
        var totalBytes = 0L
        val inflaterFactory: (BufferedInputStream) -> java.io.InputStream = when (compression) {
            "gzip" -> { input -> GZIPInputStream(input) }
            "zlib" -> { input -> InflaterInputStream(input) }
            else -> throw IllegalArgumentException("Unsupported bundle db compression '$compression' for ${artifact.file}")
        }

        artifactFile.inputStream().use { rawInput ->
            inflaterFactory(BufferedInputStream(rawInput)).use { inflated ->
                FileOutputStream(destinationDb).use { output ->
                    val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
                    while (true) {
                        val read = inflated.read(buffer)
                        if (read <= 0) {
                            break
                        }
                        output.write(buffer, 0, read)
                        digest.update(buffer, 0, read)
                        totalBytes += read.toLong()
                    }
                }
            }
        }

        if (totalBytes != expectedBytes) {
            destinationDb.delete()
            throw IllegalArgumentException(
                "bundle db size mismatch after decompression: expected $expectedBytes, got $totalBytes",
            )
        }
        val actualSha = digest.digest().joinToString("") { "%02x".format(it) }
        if (actualSha != expectedSha256) {
            destinationDb.delete()
            throw IllegalArgumentException("bundle db sha256 mismatch after decompression")
        }
        return MaterializedDatabaseArtifact(bytes = totalBytes, sha256 = actualSha)
    }

    private fun decodeManifestOrThrow(
        manifestUrl: String,
        raw: String,
    ): V3BundleManifest {
        return try {
            ContractJson.decodeBundleManifest(raw).also { it.validateLaunchContract() }
        } catch (error: Exception) {
            val excerpt = raw.replace(Regex("\\s+"), " ").take(220)
            throw IOException(
                "Invalid bundle manifest from $manifestUrl: ${error.message ?: error.javaClass.simpleName}; body=$excerpt",
                error,
            )
        }
    }

    private fun tokenize(raw: String): String {
        return raw.trim()
            .lowercase(Locale.US)
            .replace(" ", "-")
            .replace("_", "-")
            .replace("/", "-")
    }
}
