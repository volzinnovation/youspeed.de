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
) {
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
        return removed
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
