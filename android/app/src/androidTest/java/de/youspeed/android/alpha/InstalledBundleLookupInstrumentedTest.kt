package de.youspeed.android.alpha

import android.util.Log
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Opt-in, read-only verification of the map installed by the normal app download flow. */
@RunWith(AndroidJUnit4::class)
class InstalledBundleLookupInstrumentedTest {
    @Test
    fun activeBadenWuerttembergBundleSupportsProductionRoadAndSpeedLookup() {
        assumeTrue(
            "Installed map check requires run_installed_bundle_check=1",
            InstrumentationRegistry.getArguments().getString("run_installed_bundle_check") == "1",
        )

        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val bundleRoot = File(context.filesDir, "bundle")
        val stateFile = File(bundleRoot, "active_bundle.json")
        assertTrue("Download and activate Baden-Württemberg in the app first", stateFile.isFile)
        val originalState = stateFile.readText()
        val bootstrapper = BundleBootstrapper(bundleRoot, ReadOnlyFetcher)
        // The production accessor verifies the materialized database's size and SHA-256.
        val active = bootstrapper.activeState()
        assertNotNull("Installed active state must reference a verified database", active)
        val installed = requireNotNull(active)
        assertEquals("baden-wuerttemberg", installed.region)
        assertEquals("DEU", installed.countryCode)
        assertTrue("A downloaded map is required", installed.bundleVersion !in setOf("", "none", "seed"))
        val database = File(installed.dbPath)
        val originalBytes = database.length()
        val originalModified = database.lastModified()

        V3SpeedLimitLookup(database.absolutePath, countryCode = installed.countryCode).use { lookup ->
            // Existing Loffenau replay coordinate, on a public road inside the regional map.
            // Assert readable road/speed data without pinning mutable OSM way IDs or limits.
            val result = lookup.lookup(
                lat = 48.7739967,
                lon = 8.3807646,
                radiusM = 120.0,
                maxCandidates = 64,
                headingDeg = null,
            )
            Log.i(
                "InstalledBundleLookup",
                "version=${installed.bundleVersion} way=${result.wayId} street=${result.streetName} " +
                    "speed=${result.speedLimitKmh} unlimited=${result.isUnlimitedSpeedLimit} " +
                    "candidates=${result.candidateCount} speedCandidates=${result.speedCandidateCount} " +
                    "nearestM=${result.nearestCandidateDistanceM} queryMs=${result.queryTimeMs}",
            )
            assertTrue("Production lookup must find nearby roads", result.candidateCount > 0)
            assertTrue("Production lookup must select a road", !result.wayId.isNullOrBlank())
            assertTrue(
                "The Loffenau road must be near the requested coordinate",
                result.nearestCandidateDistanceM?.let { it.isFinite() && it <= 120.0 } == true,
            )
            assertTrue("Nearby roads must provide speed data", result.speedCandidateCount > 0)
            assertTrue(
                "Production lookup must resolve a speed limit",
                result.isUnlimitedSpeedLimit || (result.speedLimitKmh?.let { it > 0 } == true),
            )
            assertTrue("Query timing must be valid", result.queryTimeMs.isFinite() && result.queryTimeMs >= 0.0)
        }

        assertEquals("Lookup must preserve activation state", originalState, stateFile.readText())
        assertEquals("Lookup must preserve database size", originalBytes, database.length())
        assertEquals("Lookup must not write the downloaded database", originalModified, database.lastModified())
    }

    private object ReadOnlyFetcher : HttpFetcher {
        override fun fetch(url: String): ByteArray = error("Installed map check must not download: $url")

        override fun fetchToFile(
            url: String,
            destination: File,
            onProgress: ((completedBytes: Long, totalBytes: Long?) -> Unit)?,
        ): Unit = error("Installed map check must not download: $url")
    }
}
