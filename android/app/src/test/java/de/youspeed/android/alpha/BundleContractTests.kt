package de.youspeed.android.alpha

import java.io.File
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.security.MessageDigest
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset
import java.util.zip.GZIPOutputStream
import kotlin.io.path.createTempDirectory
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

class BundleContractTests {
    @Test
    fun loadsBundledTargetsAndBuildsGermanyShardEndpoints() {
        val raw = bundledTargetsAsset().readText()
        val config = ContractJson.decodeBundleTargets(raw)

        assertEquals("youspeed.v3.bundle.targets", config.format)
        assertEquals(1, config.schemaVersion)
        assertEquals("v3", config.variant)

        val germany = requireNotNull(config.countryById("germany"))
        assertEquals("DEU", germany.countryCode)
        assertEquals("regional_shards", germany.mode)
        assertTrue(germany.regions.any { it.regionId == "bayern" })
        assertTrue(germany.regions.any { it.regionId == "berlin" })

        val france = requireNotNull(config.countryById("france"))
        assertEquals("FRA", france.countryCode)
        assertEquals("regional_shards", france.mode)
        assertEquals(27, france.regions.size)
        assertTrue(france.regions.any { it.regionId == "ile-de-france" })
        assertTrue(france.regions.any { it.regionId == "rhone-alpes" })

        val switzerland = requireNotNull(config.countryById("switzerland"))
        assertEquals("CHE", switzerland.countryCode)
        assertEquals("single_country", switzerland.mode)

        val endpoints = config.manifestEndpoints(preferredCountryCode = "DEU")
        assertFalse(endpoints.isEmpty())
        assertEquals("DEU", endpoints.first().countryCode)
        assertTrue(endpoints.any { it.manifestRegion == "baden-wuerttemberg" })
        assertTrue(endpoints.any { it.regionId == "germany/bayern" })
        assertTrue(
            endpoints.any {
                it.manifestUrl == "https://github.com/volzinnovation/youspeed.de/releases/download/netherlands/netherlands_manifest.json"
            }
        )
        assertEquals(27, endpoints.count { it.countryCode.uppercase() == "FRA" })
        assertTrue(endpoints.any { it.regionId == "france/ile-de-france" })
        assertTrue(
            endpoints.any {
                it.manifestUrl == "https://github.com/volzinnovation/youspeed.de/releases/download/ile-de-france/ile-de-france_manifest.json"
            }
        )
        assertTrue(
            endpoints.any {
                it.manifestUrl == "https://github.com/volzinnovation/youspeed.de/releases/download/switzerland/switzerland_manifest.json"
            }
        )
    }

    @Test
    fun decodesBundleManifestCoverage() {
        val raw = """
            {
              "format": "youspeed.v3.bundle.manifest",
              "schema_version": 1,
              "variant": "v3",
              "region": "germany-baden-wuerttemberg",
              "bundle_version": "2026-03-02",
              "created_at_utc": "2026-03-02T00:00:00Z",
              "min_app_version": "1.0.0",
              "db": {
                "file": "DEU-latest.speeds_v3.sqlite",
                "bytes": 123,
                "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
                "url": null
              },
              "coverage": {
                "bbox": {
                  "min_lon": 8.0,
                  "min_lat": 47.0,
                  "max_lon": 10.0,
                  "max_lat": 49.0
                },
                "poly": {
                  "file": "germany-baden-wuerttemberg.poly",
                  "bytes": 512,
                  "sha256": "abcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcdefabcd",
                  "url": null
                }
              }
            }
        """.trimIndent()

        val manifest = ContractJson.decodeBundleManifest(raw)
        val coverage = requireNotNull(manifest.coverage)

        assertEquals("germany-baden-wuerttemberg", manifest.region)
        assertEquals(8.0, coverage.bbox.minLon, 0.0)
        assertEquals(49.0, coverage.bbox.maxLat, 0.0)
        assertEquals("germany-baden-wuerttemberg.poly", coverage.poly?.file)
    }

    @Test
    fun bootstrapsFullBundleAndPersistsActiveState() {
        val tempRoot = createTempDirectory("android-alpha-bootstrap").toFile()
        tempRoot.deleteOnExit()

        val dbBytes = "fixture-db".toByteArray()
        val manifestUrl = "https://speedconsumer.test/baden-wuerttemberg_manifest.json"
        val dbUrl = "https://speedconsumer.test/baden-wuerttemberg.sqlite"

        val fetcher = FakeHttpFetcher(
            mapOf(
                manifestUrl to """
                    {
                      "format": "youspeed.v3.bundle.manifest",
                      "schema_version": 1,
                      "variant": "v3",
                      "region": "germany/baden-wuerttemberg",
                      "country_code": "DEU",
                      "bundle_version": "2026-03-12-alpha",
                      "created_at_utc": "2026-03-12T00:00:00Z",
                      "min_app_version": "1.0.0",
                      "db": {
                        "file": "baden-wuerttemberg.sqlite",
                        "bytes": ${dbBytes.size},
                        "sha256": "${sha256Hex(dbBytes)}",
                        "url": "$dbUrl"
                      },
                      "delta_index": null
                    }
                """.trimIndent().toByteArray(),
                dbUrl to dbBytes,
            )
        )

        val bootstrapper = BundleBootstrapper(
            rootDir = tempRoot,
            httpFetcher = fetcher,
            clock = Clock.fixed(Instant.parse("2026-03-12T08:00:00Z"), ZoneOffset.UTC),
        )

        val result = bootstrapper.syncFromManifestUrl(manifestUrl)

        assertEquals(BundleSyncMode.FULL_DOWNLOAD, result.mode)
        assertTrue(File(result.dbPath).exists())
        assertEquals(sha256Hex(dbBytes), sha256Hex(File(result.dbPath).readBytes()))

        val state = bootstrapper.activeState()
        assertNotNull(state)
        assertEquals("germany/baden-wuerttemberg", state?.region)
        assertEquals("2026-03-12-alpha", state?.bundleVersion)
        assertEquals(manifestUrl, state?.manifestUrl)
    }

    @Test
    fun emitsDownloadProgressForSingleBundleSync() {
        val tempRoot = createTempDirectory("android-alpha-progress").toFile()
        tempRoot.deleteOnExit()

        val dbBytes = "fixture-db-progress".repeat(32).toByteArray()
        val manifestUrl = "https://speedconsumer.test/berlin_manifest.json"
        val dbUrl = "https://speedconsumer.test/berlin.sqlite"

        val fetcher = FakeHttpFetcher(
            mapOf(
                manifestUrl to """
                    {
                      "format": "youspeed.v3.bundle.manifest",
                      "schema_version": 1,
                      "variant": "v3",
                      "region": "germany/berlin",
                      "country_code": "DEU",
                      "bundle_version": "2026-03-17-progress",
                      "created_at_utc": "2026-03-17T00:00:00Z",
                      "min_app_version": "1.0.0",
                      "db": {
                        "file": "berlin.sqlite",
                        "bytes": ${dbBytes.size},
                        "sha256": "${sha256Hex(dbBytes)}",
                        "url": "$dbUrl"
                      },
                      "delta_index": null
                    }
                """.trimIndent().toByteArray(),
                dbUrl to dbBytes,
            )
        )

        val bootstrapper = BundleBootstrapper(rootDir = tempRoot, httpFetcher = fetcher)
        val progressEvents = mutableListOf<BundleSyncProgress>()

        bootstrapper.syncFromManifestUrl(manifestUrl) { progress ->
            progressEvents += progress
        }

        assertFalse(progressEvents.isEmpty())
        assertEquals(BundleSyncStage.PREPARING, progressEvents.first().stage)
        assertTrue(progressEvents.any { it.stage == BundleSyncStage.DOWNLOADING })
        assertEquals(BundleSyncStage.COMPLETED, progressEvents.last().stage)
        assertEquals(dbBytes.size.toLong(), progressEvents.last().completedBytes)
        assertEquals(dbBytes.size.toLong(), progressEvents.last().totalBytes)
    }

    @Test
    fun bootstrapsCompressedFullBundleAndPersistsInflatedState() {
        val tempRoot = createTempDirectory("android-alpha-bootstrap-gzip").toFile()
        tempRoot.deleteOnExit()

        val dbBytes = "fixture-db".repeat(128).toByteArray()
        val gzipBytes = gzip(dbBytes)
        val manifestUrl = "https://speedconsumer.test/baden-wuerttemberg_manifest.json"
        val dbUrl = "https://speedconsumer.test/baden-wuerttemberg.sqlite.gz"

        val fetcher = FakeHttpFetcher(
            mapOf(
                manifestUrl to """
                    {
                      "format": "youspeed.v3.bundle.manifest",
                      "schema_version": 1,
                      "variant": "v3",
                      "region": "germany/baden-wuerttemberg",
                      "country_code": "DEU",
                      "bundle_version": "2026-03-17-gzip",
                      "created_at_utc": "2026-03-17T00:00:00Z",
                      "min_app_version": "1.0.0",
                      "db": {
                        "file": "baden-wuerttemberg.sqlite",
                        "bytes": ${gzipBytes.size},
                        "sha256": "${sha256Hex(gzipBytes)}",
                        "url": "$dbUrl",
                        "compression": "gzip",
                        "uncompressed_bytes": ${dbBytes.size},
                        "uncompressed_sha256": "${sha256Hex(dbBytes)}"
                      },
                      "delta_index": null
                    }
                """.trimIndent().toByteArray(),
                dbUrl to gzipBytes,
            )
        )

        val bootstrapper = BundleBootstrapper(rootDir = tempRoot, httpFetcher = fetcher)
        val result = bootstrapper.syncFromManifestUrl(manifestUrl)

        assertEquals(BundleSyncMode.FULL_DOWNLOAD, result.mode)
        assertEquals(sha256Hex(dbBytes), sha256Hex(File(result.dbPath).readBytes()))

        val state = bootstrapper.activeState()
        assertNotNull(state)
        assertEquals(sha256Hex(dbBytes), state?.dbSha256)
        assertEquals(dbBytes.size.toLong(), state?.dbBytes)
    }

    @Test
    fun assemblesMultipartBundle() {
        val tempRoot = createTempDirectory("android-alpha-multipart").toFile()
        tempRoot.deleteOnExit()

        val partOne = "part-one-".toByteArray()
        val partTwo = "part-two".toByteArray()
        val fullDb = partOne + partTwo
        val manifestUrl = "https://speedconsumer.test/bayern_manifest.json"
        val partOneUrl = "https://speedconsumer.test/bayern.sqlite.part001"
        val partTwoUrl = "https://speedconsumer.test/bayern.sqlite.part002"

        val fetcher = FakeHttpFetcher(
            mapOf(
                manifestUrl to """
                    {
                      "format": "youspeed.v3.bundle.manifest",
                      "schema_version": 1,
                      "variant": "v3",
                      "region": "germany/bayern",
                      "country_code": "DEU",
                      "bundle_version": "2026-03-12-multipart",
                      "created_at_utc": "2026-03-12T00:00:00Z",
                      "min_app_version": "1.0.0",
                      "db": {
                        "file": "bayern.sqlite",
                        "bytes": ${fullDb.size},
                        "sha256": "${sha256Hex(fullDb)}",
                        "url": null
                      },
                      "db_parts": [
                        {
                          "file": "bayern.sqlite.part001",
                          "bytes": ${partOne.size},
                          "sha256": "${sha256Hex(partOne)}",
                          "url": "$partOneUrl"
                        },
                        {
                          "file": "bayern.sqlite.part002",
                          "bytes": ${partTwo.size},
                          "sha256": "${sha256Hex(partTwo)}",
                          "url": "$partTwoUrl"
                        }
                      ]
                    }
                """.trimIndent().toByteArray(),
                partOneUrl to partOne,
                partTwoUrl to partTwo,
            )
        )

        val bootstrapper = BundleBootstrapper(rootDir = tempRoot, httpFetcher = fetcher)

        val result = bootstrapper.syncFromManifestUrl(manifestUrl)

        assertEquals(BundleSyncMode.FULL_DOWNLOAD, result.mode)
        assertEquals(sha256Hex(fullDb), sha256Hex(File(result.dbPath).readBytes()))
    }

    @Test
    fun assemblesCompressedMultipartBundle() {
        val tempRoot = createTempDirectory("android-alpha-multipart-gzip").toFile()
        tempRoot.deleteOnExit()

        val fullDb = ("part-one-" + "part-two").repeat(128).toByteArray()
        val gzipDb = gzip(fullDb)
        val splitAt = gzipDb.size / 2
        val partOne = gzipDb.copyOfRange(0, splitAt)
        val partTwo = gzipDb.copyOfRange(splitAt, gzipDb.size)
        val manifestUrl = "https://speedconsumer.test/bayern_manifest.json"
        val partOneUrl = "https://speedconsumer.test/bayern.sqlite.gz.part001"
        val partTwoUrl = "https://speedconsumer.test/bayern.sqlite.gz.part002"

        val fetcher = FakeHttpFetcher(
            mapOf(
                manifestUrl to """
                    {
                      "format": "youspeed.v3.bundle.manifest",
                      "schema_version": 1,
                      "variant": "v3",
                      "region": "germany/bayern",
                      "country_code": "DEU",
                      "bundle_version": "2026-03-17-multipart-gzip",
                      "created_at_utc": "2026-03-17T00:00:00Z",
                      "min_app_version": "1.0.0",
                      "db": {
                        "file": "bayern.sqlite",
                        "bytes": ${gzipDb.size},
                        "sha256": "${sha256Hex(gzipDb)}",
                        "url": null,
                        "compression": "gzip",
                        "uncompressed_bytes": ${fullDb.size},
                        "uncompressed_sha256": "${sha256Hex(fullDb)}"
                      },
                      "db_parts": [
                        {
                          "file": "bayern.sqlite.gz.part001",
                          "bytes": ${partOne.size},
                          "sha256": "${sha256Hex(partOne)}",
                          "url": "$partOneUrl"
                        },
                        {
                          "file": "bayern.sqlite.gz.part002",
                          "bytes": ${partTwo.size},
                          "sha256": "${sha256Hex(partTwo)}",
                          "url": "$partTwoUrl"
                        }
                      ]
                    }
                """.trimIndent().toByteArray(),
                partOneUrl to partOne,
                partTwoUrl to partTwo,
            )
        )

        val bootstrapper = BundleBootstrapper(rootDir = tempRoot, httpFetcher = fetcher)
        val result = bootstrapper.syncFromManifestUrl(manifestUrl)

        assertEquals(BundleSyncMode.FULL_DOWNLOAD, result.mode)
        assertEquals(sha256Hex(fullDb), sha256Hex(File(result.dbPath).readBytes()))
    }

    @Test
    fun resolveLocalBundleRouteUsesEmbeddedCoveragePolysWhenDownloadedPolyMissing() {
        val tempRoot = createTempDirectory("android-alpha-route-poly").toFile()
        tempRoot.deleteOnExit()

        val sharedBBox = BundleCoverageBBox(minLon = 7.0, minLat = 47.0, maxLon = 10.5, maxLat = 50.0)
        val bwDb = writeCoverageBundle(
            rootDir = tempRoot,
            regionDirName = "z-bw",
            bundleVersion = "2026-03-17",
            manifestRegion = "z-bw",
            dbFileName = "baden-wuerttemberg.sqlite",
            bbox = sharedBBox,
            polyFileName = "baden-wuerttemberg.poly",
        )
        val rpDb = writeCoverageBundle(
            rootDir = tempRoot,
            regionDirName = "a-rp",
            bundleVersion = "2026-03-17",
            manifestRegion = "a-rp",
            dbFileName = "rheinland-pfalz.sqlite",
            bbox = sharedBBox,
            polyFileName = "rheinland-pfalz.poly",
        )

        val bootstrapper = BundleBootstrapper(
            rootDir = tempRoot,
            httpFetcher = FakeHttpFetcher(emptyMap()),
            assetReader = FileAppAssetReader(bundledSharedAssetsRoot()),
        )

        val route = bootstrapper.resolveLocalBundleRoute(
            lat = 48.80117,
            lon = 8.44278,
            fallbackDBPath = rpDb.absolutePath,
        )

        assertEquals("z-bw", route?.region)
        assertEquals(bwDb.absolutePath, route?.dbPath)
    }

    @Test
    fun resolveLocalBundleRouteFallsBackToBBoxWhenCoveragePolyIsUnavailable() {
        val tempRoot = createTempDirectory("android-alpha-route-bbox").toFile()
        tempRoot.deleteOnExit()

        val dbFile = writeCoverageBundle(
            rootDir = tempRoot,
            regionDirName = "bbox-only",
            bundleVersion = "2026-03-17",
            manifestRegion = "bbox-only",
            dbFileName = "bbox-only.sqlite",
            bbox = BundleCoverageBBox(minLon = 8.0, minLat = 48.0, maxLon = 9.0, maxLat = 49.0),
            polyFileName = "missing.poly",
        )
        val bootstrapper = BundleBootstrapper(rootDir = tempRoot, httpFetcher = FakeHttpFetcher(emptyMap()))

        val route = bootstrapper.resolveLocalBundleRoute(lat = 48.5, lon = 8.5, fallbackDBPath = null)

        assertEquals("bbox-only", route?.region)
        assertEquals(dbFile.absolutePath, route?.dbPath)
    }

    @Test
    fun resolveLocalBundleRoutePrefersMoreSpecificCoverageOverFallbackDb() {
        val tempRoot = createTempDirectory("android-alpha-route-specific").toFile()
        tempRoot.deleteOnExit()

        val broadDb = writeCoverageBundle(
            rootDir = tempRoot,
            regionDirName = "broad",
            bundleVersion = "2026-03-17",
            manifestRegion = "broad",
            dbFileName = "broad.sqlite",
            bbox = BundleCoverageBBox(minLon = 7.0, minLat = 47.0, maxLon = 10.0, maxLat = 50.0),
            polyFileName = null,
        )
        val narrowDb = writeCoverageBundle(
            rootDir = tempRoot,
            regionDirName = "narrow",
            bundleVersion = "2026-03-17",
            manifestRegion = "narrow",
            dbFileName = "narrow.sqlite",
            bbox = BundleCoverageBBox(minLon = 8.2, minLat = 48.6, maxLon = 8.7, maxLat = 49.0),
            polyFileName = null,
        )
        val bootstrapper = BundleBootstrapper(rootDir = tempRoot, httpFetcher = FakeHttpFetcher(emptyMap()))

        val route = bootstrapper.resolveLocalBundleRoute(
            lat = 48.80117,
            lon = 8.44278,
            fallbackDBPath = broadDb.absolutePath,
        )

        assertEquals("narrow", route?.region)
        assertEquals(narrowDb.absolutePath, route?.dbPath)
    }

    private class FakeHttpFetcher(
        private val responses: Map<String, ByteArray>,
    ) : HttpFetcher {
        override fun fetch(url: String): ByteArray {
            return responses[url] ?: error("No fixture for $url")
        }

        override fun fetchToFile(
            url: String,
            destination: File,
            onProgress: ((completedBytes: Long, totalBytes: Long?) -> Unit)?,
        ) {
            val bytes = fetch(url)
            destination.writeBytes(bytes)
            onProgress?.invoke(bytes.size.toLong(), bytes.size.toLong())
        }
    }
}

private fun bundledTargetsAsset(): File {
    val candidates = listOf(
        File("app/src/main/assets/BundleTargets.top10.json"),
        File("src/main/assets/BundleTargets.top10.json"),
        File("../app/src/main/assets/BundleTargets.top10.json"),
    )
    return candidates.firstOrNull { it.exists() }
        ?: error("Unable to locate BundleTargets.top10.json from ${System.getProperty("user.dir")}")
}

private fun bundledSharedAssetsRoot(): File {
    val candidates = listOf(
        File("shared"),
        File("../shared"),
        File("../../shared"),
    )
    return candidates.firstOrNull { File(it, "CoveragePolys").exists() }
        ?: error("Unable to locate shared coverage assets from ${System.getProperty("user.dir")}")
}

private fun writeCoverageBundle(
    rootDir: File,
    regionDirName: String,
    bundleVersion: String,
    manifestRegion: String,
    dbFileName: String,
    bbox: BundleCoverageBBox,
    polyFileName: String?,
): File {
    val bundleDir = File(File(File(rootDir, "bundles"), regionDirName), bundleVersion)
    check(bundleDir.mkdirs() || bundleDir.exists()) { "Unable to create ${bundleDir.absolutePath}" }

    val dbBytes = "$manifestRegion:$dbFileName".toByteArray()
    val dbFile = File(bundleDir, dbFileName)
    dbFile.writeBytes(dbBytes)
    val coverageJson = if (polyFileName == null) {
        """
          "coverage": {
            "bbox": {
              "min_lon": ${bbox.minLon},
              "min_lat": ${bbox.minLat},
              "max_lon": ${bbox.maxLon},
              "max_lat": ${bbox.maxLat}
            }
          }
        """.trimIndent()
    } else {
        """
          "coverage": {
            "bbox": {
              "min_lon": ${bbox.minLon},
              "min_lat": ${bbox.minLat},
              "max_lon": ${bbox.maxLon},
              "max_lat": ${bbox.maxLat}
            },
            "poly": {
              "file": "$polyFileName",
              "bytes": 1,
              "sha256": "${"0".repeat(64)}",
              "url": null
            }
          }
        """.trimIndent()
    }
    File(bundleDir, "bundle-manifest.v3.json").writeText(
        """
            {
              "format": "youspeed.v3.bundle.manifest",
              "schema_version": 1,
              "variant": "v3",
              "region": "$manifestRegion",
              "country_code": "DEU",
              "bundle_version": "$bundleVersion",
              "created_at_utc": "2026-03-17T00:00:00Z",
              "min_app_version": "1.0.0",
              "db": {
                "file": "$dbFileName",
                "bytes": ${dbBytes.size},
                "sha256": "${sha256Hex(dbBytes)}",
                "url": null
              },
              $coverageJson
            }
        """.trimIndent(),
    )
    return dbFile
}

private class FileAppAssetReader(
    private val rootDir: File,
) : AppAssetReader {
    override fun readText(name: String): String {
        return File(rootDir, name).readText()
    }

    override fun readTextOrNull(name: String): String? {
        return runCatching { readText(name) }.getOrNull()
    }

    override fun openOrNull(name: String): InputStream? {
        return runCatching { File(rootDir, name).inputStream() }.getOrNull()
    }

    override fun listOrNull(path: String): List<String>? {
        val dir = if (path.isBlank()) rootDir else File(rootDir, path)
        return dir.list()?.toList()
    }
}

private fun sha256Hex(bytes: ByteArray): String {
    val digest = MessageDigest.getInstance("SHA-256").digest(bytes)
    return digest.joinToString("") { "%02x".format(it) }
}

private fun gzip(bytes: ByteArray): ByteArray {
    val out = ByteArrayOutputStream()
    GZIPOutputStream(out).use { gzip ->
        gzip.write(bytes)
    }
    return out.toByteArray()
}
