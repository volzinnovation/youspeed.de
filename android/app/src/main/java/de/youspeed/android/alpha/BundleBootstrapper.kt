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
    DELTA_PATCH,
}

enum class BundleSyncStage {
    PREPARING,
    DOWNLOADING,
    ASSEMBLING,
    APPLYING_DELTA,
    COMPLETED,
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

data class BundleSyncProgress(
    val stage: BundleSyncStage,
    val detail: String,
    val completedBytes: Long,
    val totalBytes: Long,
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
    val dbSha256: String? = null,
)

private data class MaterializedDatabaseArtifact(
    val bytes: Long,
    val sha256: String,
)

interface HttpFetcher {
    @Throws(IOException::class)
    fun fetch(url: String): ByteArray

    @Throws(IOException::class)
    fun fetchToFile(
        url: String,
        destination: File,
        onProgress: ((completedBytes: Long, totalBytes: Long?) -> Unit)? = null,
    )
}

class BundleBootstrapper(
    private val rootDir: File,
    private val httpFetcher: HttpFetcher,
    private val clock: Clock = Clock.systemUTC(),
    private val assetReader: AppAssetReader? = null,
    private val deltaDatabase: BundleDeltaDatabase = AndroidBundleDeltaDatabase(),
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
        val dbSha256: String?,
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
        val state = runCatching { ContractJson.decodeActiveBundleState(stateFile.readText()) }.getOrNull()
            ?: return null
        // Content integrity is checked before installation; local access only needs the file to remain available.
        return state.takeIf { File(it.dbPath).isAvailableDatabase() }
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

    fun resolveLocalBundleRoutes(
        lat: Double,
        lon: Double,
        fallbackDBPath: String?,
    ): List<LocalBundleRoute> {
        val entries = loadCoverageEntriesIfNeeded()
        if (entries.isEmpty()) {
            val fallback = fallbackDBPath?.trim().orEmpty()
            return fallbackRoute(fallback)?.let(::listOf).orEmpty()
        }

        val matches = entries.filter { pointIsInsideCoverage(lon = lon, lat = lat, entry = it) }
        if (matches.isEmpty()) {
            val fallback = fallbackDBPath?.trim().orEmpty()
            return fallbackRoute(fallback)?.let(::listOf).orEmpty()
        }

        val sortedMatches = matches.sortedWith(
            compareBy<CoverageEntry> { bboxArea(it.bbox) }
                .thenByDescending { it.bundleVersion }
                .thenBy { it.region },
        )
        var availableMatches = sortedMatches.filter { File(it.dbPath).isAvailableDatabase() }
        if (availableMatches.isEmpty()) {
            availableMatches = loadCoverageEntriesIfNeeded(forceReload = true)
                .filter { pointIsInsideCoverage(lon = lon, lat = lat, entry = it) }
                .sortedWith(
                    compareBy<CoverageEntry> { bboxArea(it.bbox) }
                        .thenByDescending { it.bundleVersion }
                        .thenBy { it.region },
                )
                .filter { File(it.dbPath).isAvailableDatabase() }
        }
        if (availableMatches.isEmpty()) {
            return fallbackRoute(fallbackDBPath?.trim().orEmpty())?.let(::listOf).orEmpty()
        }
        return availableMatches.map { entry ->
            LocalBundleRoute(
                region = entry.region,
                bundleVersion = entry.bundleVersion,
                countryCode = entry.countryCode,
                dbPath = entry.dbPath,
                dbSha256 = entry.dbSha256,
            )
        }
    }

    fun resolveLocalBundleRoute(
        lat: Double,
        lon: Double,
        fallbackDBPath: String?,
    ): LocalBundleRoute? = resolveLocalBundleRoutes(lat, lon, fallbackDBPath).firstOrNull()

    private fun fallbackRoute(dbPath: String): LocalBundleRoute? {
        if (dbPath.isEmpty()) return null
        val active = activeState()?.takeIf { it.dbPath == dbPath }
        return LocalBundleRoute(
            region = active?.region ?: "unknown",
            bundleVersion = active?.bundleVersion ?: "unknown",
            countryCode = active?.countryCode,
            dbPath = dbPath,
            dbSha256 = active?.dbSha256,
        )
    }

    @Throws(IOException::class)
    fun fetchManifest(manifestUrl: String): V3BundleManifest {
        val raw = httpFetcher.fetch(manifestUrl).toString(Charsets.UTF_8)
        return decodeManifestOrThrow(manifestUrl, raw)
    }

    /** Like iPhone, synchronizes every preferred-country shard and returns the last successful activation. */
    fun syncFromManifestEndpoints(
        endpoints: List<V3ManifestEndpoint>,
        preferredCountryCode: String? = null,
        onProgress: ((BundleSyncProgress) -> Unit)? = null,
    ): BundleSyncResult {
        require(endpoints.isNotEmpty()) { "No embedded manifest endpoints available" }
        val preferred = preferredCountryCode?.trim()?.uppercase(Locale.ROOT)
        val matching = endpoints.filter { preferred == null || it.countryCode.uppercase(Locale.ROOT) == preferred }
        val sequence = matching.ifEmpty { endpoints }
        var lastSuccess: BundleSyncResult? = null
        var firstFailure: Exception? = null
        sequence.forEachIndexed { index, endpoint ->
            val prefix = "[${index + 1}/${sequence.size}] ${endpoint.countryCode} ${endpoint.regionId}"
            try {
                lastSuccess = syncFromManifestUrl(endpoint.manifestUrl) { progress ->
                    onProgress?.invoke(progress.copy(detail = "$prefix: ${progress.detail}"))
                }
            } catch (failure: Exception) {
                if (firstFailure == null) firstFailure = failure
            }
        }
        return lastSuccess ?: throw (firstFailure ?: IOException("No manifest endpoint could be synchronized"))
    }

    @Throws(IOException::class)
    fun syncFromManifestUrl(
        manifestUrl: String,
        onProgress: ((BundleSyncProgress) -> Unit)? = null,
    ): BundleSyncResult {
        ensureRoot()
        val manifestBytes = httpFetcher.fetch(manifestUrl)
        val manifestRaw = manifestBytes.toString(Charsets.UTF_8)
        val manifest = decodeManifestOrThrow(manifestUrl, manifestRaw)
        val totalDownloadBytes = totalDownloadBytes(manifest)
        emitProgress(
            onProgress = onProgress,
            stage = BundleSyncStage.PREPARING,
            detail = "Manifest geladen: ${manifest.region} ${manifest.bundleVersion}",
            completedBytes = 0L,
            totalBytes = totalDownloadBytes,
        )

        val current = activeState()
        if (current != null &&
            current.region == manifest.region &&
            current.bundleVersion == manifest.bundleVersion &&
            materializedDatabaseExpectation(manifest)?.let { (bytes, sha) ->
                current.dbBytes == bytes && current.dbSha256.equals(sha, ignoreCase = true)
            } == true
        ) {
            emitProgress(
                onProgress = onProgress,
                stage = BundleSyncStage.COMPLETED,
                detail = "Bundle bereits aktuell",
                completedBytes = totalDownloadBytes,
                totalBytes = totalDownloadBytes,
            )
            return BundleSyncResult(
                mode = BundleSyncMode.UP_TO_DATE,
                bundleVersion = current.bundleVersion,
                dbPath = current.dbPath,
                details = "already active",
            )
        }

        if (current != null && current.region == manifest.region && current.bundleVersion != manifest.bundleVersion &&
            !DeltaUpdatePolicy.forceFullReload(current.bundleVersion, manifest.bundleVersion) && manifest.deltaIndex != null) {
            tryApplyDelta(current, manifest, manifestUrl, manifestRaw, onProgress)?.let { return it }
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
                assembleMultipartArtifact(
                    artifactFile = downloadedArtifact,
                    manifest = manifest,
                    manifestUrl = manifestUrl,
                    onProgress = onProgress,
                )
            } else {
                httpFetcher.fetchToFile(
                    url = ContractJson.resolveArtifactUrl(manifest.db, manifestUrl),
                    destination = downloadedArtifact,
                    onProgress = { completedBytes, reportedTotalBytes ->
                        emitProgress(
                            onProgress = onProgress,
                            stage = BundleSyncStage.DOWNLOADING,
                            detail = "Lade ${manifest.region}",
                            completedBytes = completedBytes,
                            totalBytes = resolveProgressTotalBytes(
                                expectedTotalBytes = totalDownloadBytes,
                                reportedTotalBytes = reportedTotalBytes,
                            ),
                        )
                    },
                )
                emitProgress(
                    onProgress = onProgress,
                    stage = BundleSyncStage.DOWNLOADING,
                    detail = "Lade ${manifest.region}",
                    completedBytes = downloadedArtifact.length(),
                    totalBytes = resolveProgressTotalBytes(
                        expectedTotalBytes = totalDownloadBytes,
                        reportedTotalBytes = downloadedArtifact.length().takeIf { it > 0L },
                    ),
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
                emitProgress(
                    onProgress = onProgress,
                    stage = BundleSyncStage.ASSEMBLING,
                    detail = "Entpacke ${manifest.region}",
                    completedBytes = totalDownloadBytes,
                    totalBytes = totalDownloadBytes,
                )
                materializeCompressedDatabaseArtifact(
                    artifactFile = downloadedArtifact,
                    artifact = manifest.db,
                    compression = compression,
                    destinationDb = stagingDb,
                )
            }

            installPenaltyRules(
                manifest = manifest,
                manifestUrl = manifestUrl,
                bundleDir = bundleDir,
                onProgress = onProgress,
            )
            val finalDb = activatePreparedDatabase(stagingDb, bundleDir, manifest, manifestRaw, manifestUrl, dbArtifact)
            emitProgress(
                onProgress = onProgress,
                stage = BundleSyncStage.COMPLETED,
                detail = "Bundle aktiviert: ${manifest.region} ${manifest.bundleVersion}",
                completedBytes = totalDownloadBytes,
                totalBytes = totalDownloadBytes,
            )

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

    private fun tryApplyDelta(current: ActiveBundleState, manifest: V3BundleManifest, manifestUrl: String,
        manifestRaw: String, onProgress: ((BundleSyncProgress) -> Unit)?): BundleSyncResult? {
        val ref = manifest.deltaIndex ?: return null
        val indexUrl = ContractJson.resolveArtifactUrl(ref, manifestUrl)
        emitProgress(onProgress, BundleSyncStage.PREPARING, "Loading delta index", 0, 0)
        val entries = ContractJson.decodeDeltaIndex(httpFetcher.fetch(indexUrl).toString(Charsets.UTF_8))
        val path = DeltaUpdatePolicy.path(entries, current.bundleVersion, manifest.bundleVersion, manifest.region) ?: return null
        var expected = current.bundleVersion
        val steps = path.map { entry ->
            val url = java.net.URI(indexUrl).resolve(entry.deltaManifestFile).toString()
            val delta = ContractJson.decodeDeltaManifest(httpFetcher.fetch(url).toString(Charsets.UTF_8))
            require(delta.region == manifest.region && delta.fromBundleVersion == expected &&
                delta.toBundleVersion == entry.toBundleVersion && delta.toBundleVersion != delta.fromBundleVersion) {
                "Delta manifest version or region mismatch in update chain"
            }
            expected = delta.toBundleVersion
            url to delta
        }
        require(expected == manifest.bundleVersion) { "Delta path does not terminate at target bundle version" }
        val expectedDatabase = materializedDatabaseExpectation(manifest)
            ?: throw IOException("Delta target is missing materialized database identity")
        val total = steps.fold(0L) { count, (_, delta) ->
            val bytes = delta.patch.bytes.coerceAtLeast(0)
            if (Long.MAX_VALUE - count < bytes) Long.MAX_VALUE else count + bytes
        }
        val stagingDir = File(rootDir, "staging").also { if (!it.exists() && !it.mkdirs()) throw IOException("Cannot create staging directory") }
        val available = stagingDir.usableSpace
        val required = current.dbBytes.toDouble() + total.toDouble() + 256.0 * 1024 * 1024
        if (available > 0L && available.toDouble() < required) throw IOException("Insufficient disk space for delta update")
        val staging = File.createTempFile("delta-", ".sqlite", stagingDir)
        try {
            File(current.dbPath).copyTo(staging, overwrite = true)
            var downloaded = 0L
            for ((index, step) in steps.withIndex()) {
                val patch = step.second.patch
                emitProgress(onProgress, BundleSyncStage.DOWNLOADING, "Downloading delta patch ${index + 1}/${steps.size}", downloaded, total)
                val bytes = httpFetcher.fetch(ContractJson.resolveArtifactUrl(patch, step.first))
                val digest = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
                require(digest.equals(patch.sha256, ignoreCase = true)) { "Delta patch sha256 mismatch" }
                val compression = patch.compression?.trim()?.lowercase(Locale.ROOT)?.takeIf { it.isNotEmpty() }
                    ?: if (patch.file.endsWith(".zlib", true) || patch.file.endsWith(".sqlz", true)) "zlib" else "none"
                val sqlBytes = when (compression) {
                    "none", "identity" -> bytes
                    "zlib" -> InflaterInputStream(bytes.inputStream()).use { it.readBytes() }
                    else -> throw IOException("Unsupported delta patch compression: $compression")
                }
                val sql = Charsets.UTF_8.newDecoder().onMalformedInput(java.nio.charset.CodingErrorAction.REPORT)
                    .onUnmappableCharacter(java.nio.charset.CodingErrorAction.REPORT).decode(java.nio.ByteBuffer.wrap(sqlBytes)).toString()
                downloaded = (downloaded.toDouble() + patch.bytes.coerceAtLeast(0).toDouble()).coerceAtMost(total.toDouble()).toLong()
                emitProgress(onProgress, BundleSyncStage.APPLYING_DELTA, "Applying delta patch ${index + 1}/${steps.size}", downloaded, total)
                deltaDatabase.applyPatch(staging, sql)
            }
            deltaDatabase.validate(staging)
            validateFile(staging, expectedDatabase.first, expectedDatabase.second, "materialized delta database")
            val bundleDir = File(File(rootDir, "bundles"), "${tokenize(manifest.region)}/${tokenize(manifest.bundleVersion)}")
            installPenaltyRules(
                manifest = manifest,
                manifestUrl = manifestUrl,
                bundleDir = bundleDir,
                onProgress = onProgress,
            )
            val finalDb = activatePreparedDatabase(staging, bundleDir, manifest, manifestRaw, manifestUrl,
                MaterializedDatabaseArtifact(expectedDatabase.first, expectedDatabase.second.lowercase(Locale.ROOT)))
            emitProgress(onProgress, BundleSyncStage.COMPLETED, "Delta update applied", total, total)
            return BundleSyncResult(BundleSyncMode.DELTA_PATCH, manifest.bundleVersion, finalDb.absolutePath, "delta chain applied")
        } finally {
            staging.delete()
            File(staging.path + "-wal").delete()
            File(staging.path + "-shm").delete()
            File(staging.path + "-journal").delete()
        }
    }

    private fun installPenaltyRules(
        manifest: V3BundleManifest,
        manifestUrl: String,
        bundleDir: File,
        onProgress: ((BundleSyncProgress) -> Unit)?,
    ) {
        val artifact = manifest.penaltyRules ?: return
        val fileName = artifact.file.trim()
        require(fileName.isNotEmpty() && !fileName.contains('/') && !fileName.contains('\\') && fileName != "." && fileName != "..") {
            "Invalid penalty rules artifact path"
        }
        if (!bundleDir.exists() && !bundleDir.mkdirs()) {
            throw IOException("Unable to create bundle directory for penalty rules")
        }
        val temporary = File(bundleDir, ".${fileName}.tmp")
        val final = File(bundleDir, fileName)
        if (temporary.exists()) temporary.delete()
        try {
            onProgress?.invoke(BundleSyncProgress(BundleSyncStage.DOWNLOADING, "Lade $fileName", 0L, artifact.bytes))
            httpFetcher.fetchToFile(
                url = ContractJson.resolveArtifactUrl(artifact, manifestUrl),
                destination = temporary,
                onProgress = { completedBytes, reportedTotalBytes ->
                    onProgress?.invoke(
                        BundleSyncProgress(
                            stage = BundleSyncStage.DOWNLOADING,
                            detail = "Lade $fileName",
                            completedBytes = completedBytes.coerceAtLeast(0L),
                            totalBytes = maxOf(artifact.bytes, reportedTotalBytes ?: artifact.bytes),
                        ),
                    )
                },
            )
            validateFile(temporary, artifact.bytes, artifact.sha256, "penalty rules $fileName")
            if (final.exists() && !final.delete()) {
                throw IOException("Unable to replace penalty rules file: ${final.absolutePath}")
            }
            if (!temporary.renameTo(final)) {
                throw IOException("Unable to activate penalty rules file: ${final.absolutePath}")
            }
        } finally {
            if (temporary.exists()) temporary.delete()
        }
    }

    private fun activatePreparedDatabase(stagingDb: File, bundleDir: File, manifest: V3BundleManifest,
        manifestRaw: String, manifestUrl: String, dbArtifact: MaterializedDatabaseArtifact): File {
        deltaDatabase.validateSettlementCapability(stagingDb)
        if (!bundleDir.exists() && !bundleDir.mkdirs()) throw IOException("Cannot create bundle directory")
        val finalDb = File(bundleDir, manifest.db.file)
        val prepared = File(bundleDir, manifest.db.file + ".tmp")
        java.nio.file.Files.move(stagingDb.toPath(), prepared.toPath(), java.nio.file.StandardCopyOption.REPLACE_EXISTING)
        java.nio.file.Files.move(prepared.toPath(), finalDb.toPath(), java.nio.file.StandardCopyOption.REPLACE_EXISTING,
            java.nio.file.StandardCopyOption.ATOMIC_MOVE)
        File(bundleDir, "bundle-manifest.v3.json").writeText(manifestRaw)
        val state = ActiveBundleState(manifest.region, manifest.countryCode, manifest.bundleVersion, manifest.db.file,
            finalDb.absolutePath, dbArtifact.sha256, dbArtifact.bytes, manifestUrl, Instant.now(clock).toString())
        val stateFile = File(rootDir, "active_bundle.json")
        val temporaryState = File(rootDir, "active_bundle.json.tmp")
        temporaryState.writeText(ContractJson.encodeActiveBundleState(state))
        java.nio.file.Files.move(temporaryState.toPath(), stateFile.toPath(), java.nio.file.StandardCopyOption.REPLACE_EXISTING,
            java.nio.file.StandardCopyOption.ATOMIC_MOVE)
        invalidateCoverageCache()
        return finalDb
    }

    private fun assembleMultipartArtifact(
        artifactFile: File,
        manifest: V3BundleManifest,
        manifestUrl: String,
        onProgress: ((BundleSyncProgress) -> Unit)?,
    ) {
        val dbParts = manifest.dbParts ?: error("db_parts missing")
        require(dbParts.isNotEmpty()) { "db_parts is empty" }

        val totalProgressBytes = dbParts.sumOf { it.bytes.coerceAtLeast(0L) }
            .takeIf { it > 0L }
            ?: manifest.db.bytes.coerceAtLeast(0L)
        var totalBytes = 0L
        FileOutputStream(artifactFile).use { output ->
            for ((index, part) in dbParts.withIndex()) {
                val partFile = File.createTempFile("bundle-part-", ".tmp", artifactFile.parentFile)
                try {
                    httpFetcher.fetchToFile(
                        url = ContractJson.resolveArtifactUrl(part, manifestUrl),
                        destination = partFile,
                        onProgress = { completedBytes, _ ->
                            val normalizedPartBytes = part.bytes.coerceAtLeast(0L)
                            val normalizedCompletedBytes = if (normalizedPartBytes > 0L) {
                                completedBytes.coerceIn(0L, normalizedPartBytes)
                            } else {
                                completedBytes.coerceAtLeast(0L)
                            }
                            emitProgress(
                                onProgress = onProgress,
                                stage = BundleSyncStage.DOWNLOADING,
                                detail = "Lade ${part.file} (${index + 1}/${dbParts.size})",
                                completedBytes = totalBytes + normalizedCompletedBytes,
                                totalBytes = totalProgressBytes,
                            )
                        },
                    )
                    validateFile(
                        file = partFile,
                        expectedBytes = part.bytes,
                        expectedSha256 = part.sha256,
                        label = part.file,
                    )
                    partFile.inputStream().use { input -> input.copyTo(output) }
                    totalBytes += partFile.length()
                    emitProgress(
                        onProgress = onProgress,
                        stage = BundleSyncStage.DOWNLOADING,
                        detail = "Lade ${part.file} (${index + 1}/${dbParts.size})",
                        completedBytes = totalBytes,
                        totalBytes = totalProgressBytes,
                    )
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
            if (!dbFile.isAvailableDatabase()) {
                return@forEach
            }
            // Keep the installed digest as metadata without reading the database again during GPS routing.
            val installedSha = materializedDatabaseExpectation(manifest)?.second
                ?.trim()?.lowercase(Locale.US)
                ?.takeIf { Regex("^[0-9a-f]{64}$").matches(it) }

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
                dbSha256 = installedSha,
                bbox = coverage.bbox,
                rings = rings,
            )
        }

        // Retain previous downloads for rollback without routing through them.
        val latest = loaded.groupBy { it.region.lowercase(Locale.US) }.values.map { entries ->
            entries.maxBy { if (it.bundleVersion == "seed") "" else it.bundleVersion }
        }
        cachedCoverageEntries = latest
        coverageCacheLoadedAtMillis = now
        return latest
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
        if (x1 == x2 && y1 == y2) return abs(px - x1) <= epsilon && abs(py - y1) <= epsilon
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

    private fun materializedDatabaseExpectation(manifest: V3BundleManifest): Pair<Long, String>? {
        return if (normalizedCompression(manifest.db) == null) {
            manifest.db.bytes to manifest.db.sha256
        } else {
            val bytes = manifest.db.uncompressedBytes ?: return null
            val sha256 = manifest.db.uncompressedSha256?.trim()?.takeIf(String::isNotEmpty) ?: return null
            bytes to sha256
        }
    }

    private fun File.isAvailableDatabase(): Boolean = isFile && length() > 0L

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

    private fun totalDownloadBytes(manifest: V3BundleManifest): Long {
        val multipartTotal = manifest.dbParts
            ?.sumOf { it.bytes.coerceAtLeast(0L) }
            ?.takeIf { it > 0L }
        return multipartTotal ?: manifest.db.bytes.coerceAtLeast(0L)
    }

    private fun resolveProgressTotalBytes(
        expectedTotalBytes: Long,
        reportedTotalBytes: Long?,
    ): Long {
        val normalizedReportedTotalBytes = reportedTotalBytes?.takeIf { it > 0L } ?: 0L
        return if (expectedTotalBytes > 0L) expectedTotalBytes else normalizedReportedTotalBytes
    }

    private fun emitProgress(
        onProgress: ((BundleSyncProgress) -> Unit)?,
        stage: BundleSyncStage,
        detail: String,
        completedBytes: Long,
        totalBytes: Long,
    ) {
        val normalizedTotalBytes = totalBytes.coerceAtLeast(0L)
        val normalizedCompletedBytes = completedBytes.coerceAtLeast(0L).let { bytes ->
            if (normalizedTotalBytes > 0L) bytes.coerceAtMost(normalizedTotalBytes) else bytes
        }
        onProgress?.invoke(
            BundleSyncProgress(
                stage = stage,
                detail = detail,
                completedBytes = normalizedCompletedBytes,
                totalBytes = normalizedTotalBytes,
            )
        )
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
