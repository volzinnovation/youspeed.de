package de.youspeed.android.alpha

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
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

        val githubToken = BuildConfig.YOUSPEED_RELEASE_READ_TOKEN.trim()
        assumeTrue("YOUSPEED_RELEASE_READ_TOKEN missing in app BuildConfig", githubToken.isNotBlank())

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
                httpFetcher = HttpUrlFetcher(githubToken),
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
            assertEquals(manifest.db.bytes, File(requireNotNull(active).dbPath).length())
        } finally {
            rootDir.deleteRecursively()
        }
    }
}
