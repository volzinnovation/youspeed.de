package de.youspeed.android.alpha

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.security.MessageDigest
import java.util.Locale
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class LiveBundleBootstrapInstrumentedTest {
    @Test
    fun bootstrapBadenWuerttembergShardFromLiveRelease() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val args = InstrumentationRegistry.getArguments()
        assumeTrue(
            "Live bootstrap test only runs when run_live_bootstrap=1 is provided",
            args.getString("run_live_bootstrap") == "1",
        )

        val appContext = instrumentation.targetContext
        val targetsRaw = appContext.assets.open("BundleTargets.top10.json").bufferedReader().use { it.readText() }
        val manifestEndpoints = ContractJson.decodeBundleTargets(targetsRaw).manifestEndpoints(preferredCountryCode = "DEU")
        val endpoint = manifestEndpoints.firstOrNull { it.manifestRegion == "baden-wuerttemberg" }
        assumeTrue("Baden-Wuerttemberg endpoint missing from BundleTargets.top10.json", endpoint != null)

        val rootDir = File(appContext.filesDir, "bundle-alpha-live-bootstrap-test")
        if (rootDir.exists()) {
            rootDir.deleteRecursively()
        }
        assertTrue(rootDir.mkdirs())

        try {
            val bootstrapper = BundleBootstrapper(
                rootDir = rootDir,
                httpFetcher = HttpUrlFetcher(),
            )

            val manifest = bootstrapper.fetchManifest(requireNotNull(endpoint).manifestUrl)
            assertEquals("baden-wuerttemberg", manifest.region)
            assertEquals("DEU", manifest.countryCode)

            val result = bootstrapper.syncFromManifestUrl(endpoint.manifestUrl)
            val active = bootstrapper.activeState()

            assertEquals(BundleSyncMode.FULL_DOWNLOAD, result.mode)
            assertEquals(manifest.bundleVersion, result.bundleVersion)
            assertNotNull(active)
            assertEquals(manifest.bundleVersion, active?.bundleVersion)
            assertEquals("baden-wuerttemberg", active?.region)
            val installed = requireNotNull(active)
            val compression = manifest.db.compression?.trim()?.lowercase(Locale.US).orEmpty()
            val isCompressed = compression.isNotEmpty() && compression != "none"
            val expectedBytes = if (isCompressed) {
                requireNotNull(manifest.db.uncompressedBytes) { "Compressed manifest must specify uncompressed_bytes" }
            } else {
                manifest.db.bytes
            }
            val expectedSha256 = (if (isCompressed) {
                requireNotNull(manifest.db.uncompressedSha256) { "Compressed manifest must specify uncompressed_sha256" }
            } else {
                manifest.db.sha256
            }).trim().lowercase(Locale.US)
            val installedFile = File(installed.dbPath)
            assertEquals(expectedBytes, installedFile.length())
            assertEquals(expectedBytes, installed.dbBytes)
            assertEquals(expectedSha256, installed.dbSha256)

            // Check the installed bytes independently of the persisted activation state.
            val digest = MessageDigest.getInstance("SHA-256")
            installedFile.inputStream().buffered().use { input ->
                val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
                while (true) {
                    val count = input.read(buffer)
                    if (count < 0) break
                    digest.update(buffer, 0, count)
                }
            }
            val installedSha256 = digest.digest().joinToString("") { "%02x".format(it) }
            assertEquals(expectedSha256, installedSha256)
        } finally {
            rootDir.deleteRecursively()
        }
    }
}
