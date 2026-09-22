package de.youspeed.android.alpha

import java.io.File
import java.security.MessageDigest
import java.time.Clock
import java.time.Instant
import java.time.ZoneId
import java.time.ZoneOffset
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class BundleOfflineAccessTests {
    @get:Rule
    val temporaryFolder = TemporaryFolder()

    @Test
    fun restartOpensInstalledMapOfflineWithoutCheckingItsContentsAgain() {
        val fixture = Fixture(temporaryFolder.newFolder())
        val installed = fixture.install()
        val recordedState = requireNotNull(fixture.bootstrapper.activeState())
        // Deliberately differ from the install metadata: reopening must not hash or size-validate the map.
        File(installed.dbPath).writeText("changed local database contents with a different size")
        fixture.responses.clear()

        val restarted = BundleBootstrapper(fixture.root, fixture.fetcher)

        assertEquals(recordedState, restarted.activeState())
        val route = requireNotNull(restarted.resolveLocalBundleRoute(48.5, 8.5, fallbackDBPath = null))
        assertEquals(installed.dbPath, route.dbPath)
        assertEquals(recordedState.dbSha256, route.dbSha256)
        assertTrue("Local access must never fetch a manifest or database", fixture.requests.isEmpty())
    }

    @Test
    fun activeDatabaseFallbackDoesNotClaimCoverageOutsideInstalledRegion() {
        val fixture = Fixture(temporaryFolder.newFolder())
        val installed = fixture.install()
        fixture.responses.clear()
        assertTrue(fixture.bootstrapper.resolveLocalBundleRoutes(43.3, 5.4, null).isEmpty())
        val fallback = fixture.bootstrapper.resolveLocalBundleRoutes(43.3, 5.4, installed.dbPath)
        // A fallback carries database identity but is not proof of coverage.
        assertEquals(listOf("installed-region"), fallback.map { it.region })
        assertEquals(installed.dbPath, fallback.single().dbPath)
        assertTrue(fixture.requests.isEmpty())
    }

    @Test
    fun coverageCacheRefreshKeepsUsingInstalledMapWithoutRecheckingContents() {
        val fixture = Fixture(temporaryFolder.newFolder())
        fixture.install()
        val initialRoute = requireNotNull(fixture.bootstrapper.resolveLocalBundleRoute(48.5, 8.5, null))
        File(initialRoute.dbPath).writeText("changed contents")
        fixture.responses.clear()

        assertEquals(initialRoute, fixture.bootstrapper.resolveLocalBundleRoute(48.5, 8.5, null))
        fixture.clock.now = fixture.clock.now.plusSeconds(61)
        assertEquals(initialRoute, fixture.bootstrapper.resolveLocalBundleRoute(48.5, 8.5, null))
        assertTrue(fixture.requests.isEmpty())
    }

    @Test
    fun upToDateSyncComparesRecordedMetadataWithoutRecheckingOrDownloadingDatabase() {
        val fixture = Fixture(temporaryFolder.newFolder())
        val installed = fixture.install()
        val changedContents = "changed local database"
        File(installed.dbPath).writeText(changedContents)
        fixture.responses.remove(fixture.databaseUrl)

        val result = fixture.bootstrapper.syncFromManifestUrl(fixture.manifestUrl)

        assertEquals(BundleSyncMode.UP_TO_DATE, result.mode)
        assertEquals(installed.dbPath, result.dbPath)
        assertEquals(changedContents, File(result.dbPath).readText())
        assertEquals(listOf(fixture.manifestUrl), fixture.requests)
    }

    @Test
    fun missingEmptyAndNonFileDatabasePathsAreNotAvailableOffline() {
        val fixture = Fixture(temporaryFolder.newFolder())
        val database = File(fixture.install().dbPath)
        fixture.responses.clear()

        database.writeBytes(byteArrayOf())
        assertNull(fixture.bootstrapper.activeState())
        assertNull(fixture.bootstrapper.resolveLocalBundleRoute(48.5, 8.5, null))
        assertTrue(database.delete())
        assertNull(fixture.bootstrapper.activeState())
        assertNull(BundleBootstrapper(fixture.root, fixture.fetcher).resolveLocalBundleRoute(48.5, 8.5, null))
        assertTrue(database.mkdir())
        assertNull(fixture.bootstrapper.activeState())
        assertNull(BundleBootstrapper(fixture.root, fixture.fetcher).resolveLocalBundleRoute(48.5, 8.5, null))
        assertTrue(fixture.requests.isEmpty())
    }

    @Test
    fun downloadedDatabaseStillRequiresValidChecksumBeforeInstallation() {
        val fixture = Fixture(temporaryFolder.newFolder())
        fixture.responses[fixture.databaseUrl] = ByteArray(fixture.databaseContents.size) { 0x5a }

        assertThrows(IllegalArgumentException::class.java) { fixture.install() }

        assertNull(fixture.bootstrapper.activeState())
        assertNull(fixture.bootstrapper.resolveLocalBundleRoute(48.5, 8.5, null))
    }

    private class Fixture(val root: File) {
        val clock = MutableClock()
        val databaseContents = "downloaded map fixture".toByteArray()
        val manifestUrl = "https://bundle.test/manifest.json"
        val databaseUrl = "https://bundle.test/map.sqlite"
        val requests = mutableListOf<String>()
        val responses = mutableMapOf(
            databaseUrl to databaseContents,
            manifestUrl to """
                {
                  "format": "youspeed.v3.bundle.manifest", "schema_version": 1, "variant": "v3",
                  "region": "installed-region", "country_code": "DEU", "bundle_version": "2026-09-12",
                  "created_at_utc": "2026-09-12T00:00:00Z", "min_app_version": "1.0.0",
                  "db": {
                    "file": "map.sqlite", "url": "$databaseUrl", "bytes": ${databaseContents.size},
                    "sha256": "${MessageDigest.getInstance("SHA-256").digest(databaseContents).joinToString("") { "%02x".format(it) }}"
                  },
                  "coverage": { "bbox": { "min_lon": 8.0, "min_lat": 48.0, "max_lon": 9.0, "max_lat": 49.0 } }
                }
            """.trimIndent().toByteArray(),
        )
        val fetcher = object : HttpFetcher {
            override fun fetch(url: String): ByteArray {
                requests += url
                return responses[url] ?: error("Network unavailable for $url")
            }

            override fun fetchToFile(url: String, destination: File, onProgress: ((Long, Long?) -> Unit)?) {
                destination.writeBytes(fetch(url))
            }
        }
        val bootstrapper = BundleBootstrapper(root, fetcher, clock, deltaDatabase = ContractTestDatabase)

        fun install(): BundleSyncResult = bootstrapper.syncFromManifestUrl(manifestUrl).also { requests.clear() }
    }

    private class MutableClock : Clock() {
        var now = Instant.parse("2026-09-12T12:00:00Z")
        override fun getZone(): ZoneId = ZoneOffset.UTC
        override fun withZone(zone: ZoneId): Clock = Clock.fixed(now, zone)
        override fun instant(): Instant = now
    }
}
