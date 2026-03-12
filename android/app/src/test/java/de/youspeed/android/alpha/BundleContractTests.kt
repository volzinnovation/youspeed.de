package de.youspeed.android.alpha

import java.io.File
import java.security.MessageDigest
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset
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

    private class FakeHttpFetcher(
        private val responses: Map<String, ByteArray>,
    ) : HttpFetcher {
        override fun fetch(url: String): ByteArray {
            return responses[url] ?: error("No fixture for $url")
        }

        override fun fetchToFile(
            url: String,
            destination: File,
        ) {
            destination.writeBytes(fetch(url))
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

private fun sha256Hex(bytes: ByteArray): String {
    val digest = MessageDigest.getInstance("SHA-256").digest(bytes)
    return digest.joinToString("") { "%02x".format(it) }
}
