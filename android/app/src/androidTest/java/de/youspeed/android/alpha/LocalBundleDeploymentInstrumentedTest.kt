package de.youspeed.android.alpha

import android.database.sqlite.SQLiteDatabase
import android.os.Bundle
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.net.URI
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.MessageDigest
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Explicit opt-in device deployment through the production installer, preserving existing maps and settings. */
@RunWith(AndroidJUnit4::class)
class LocalBundleDeploymentInstrumentedTest {
    @Test fun installAndVerifyBadenWuerttembergSettlementPilot() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        assumeTrue("Requires explicit run_local_bundle_install=1 deployment opt-in",
            InstrumentationRegistry.getArguments().getString("run_local_bundle_install") == "1")
        val context = instrumentation.targetContext
        val staged = File(context.cacheDir, "bw-settlement-pilot-deployment")
        val manifestFile = File(staged, "baden-wuerttemberg_manifest.json")
        val manifest = ContractJson.decodeBundleManifest(manifestFile.readText())
        assertEquals("baden-wuerttemberg", manifest.region)
        assertEquals("2026-09-14-settlement-pilot", manifest.bundleVersion)
        assertEquals("1938df90ffa6b9ff0f5dfb2b4f09c622f4208cb03102fc5fb2c2f5ebc531a183", manifest.db.uncompressedSha256)
        val root = File(context.filesDir, "bundle")
        val bootstrapper = BundleBootstrapper(root, object : HttpFetcher {
            private fun source(url: String): File {
                val uri = URI(url)
                check(uri.scheme == "file") { "Device-local deployment must not access the network" }
                return File(uri).canonicalFile.also { check(it.parentFile == staged.canonicalFile) }
            }
            override fun fetch(url: String): ByteArray = source(url).readBytes()
            override fun fetchToFile(url: String, destination: File,
                onProgress: ((completedBytes: Long, totalBytes: Long?) -> Unit)?) {
                val input = source(url)
                input.inputStream().buffered().use { stream -> destination.outputStream().use { stream.copyTo(it) } }
                onProgress?.invoke(input.length(), input.length())
            }
        })
        val previous = bootstrapper.activeState()
        val previousFile = previous?.let { File(it.dbPath) }
        val previousBytes = previousFile?.length()
        val previousModified = previousFile?.lastModified()
        val previousPreferences = context.getSharedPreferences("youspeed", 0).all.toMap()
        val poly = requireNotNull(manifest.coverage?.poly)
        val stagedPoly = File(staged, poly.file)
        assertEquals(poly.bytes, stagedPoly.length())
        assertEquals(poly.sha256, sha256(stagedPoly))
        val destination = File(root, "bundles/${manifest.region}/${manifest.bundleVersion}")
        assertTrue(destination.isDirectory || destination.mkdirs())
        val preparedPoly = File(destination, poly.file + ".tmp")
        stagedPoly.copyTo(preparedPoly, overwrite = true)
        Files.move(preparedPoly.toPath(), File(destination, poly.file).toPath(),
            StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE)
        val result = bootstrapper.syncFromManifestUrl(manifestFile.toURI().toString()) { progress ->
            if (progress.stage != BundleSyncStage.DOWNLOADING) instrumentation.sendStatus(0,
                Bundle().apply { putString("stream", "${progress.stage}: ${progress.detail}\n") })
        }
        val installed = requireNotNull(bootstrapper.activeState())
        assertEquals(manifest.bundleVersion, installed.bundleVersion)
        assertEquals(manifest.db.uncompressedSha256, installed.dbSha256)
        assertEquals(manifest.db.uncompressedBytes, installed.dbBytes)
        assertEquals(installed.dbBytes, File(installed.dbPath).length())
        assertEquals(manifestFile.readText(), File(destination, "bundle-manifest.v3.json").readText())
        assertEquals(previousPreferences, context.getSharedPreferences("youspeed", 0).all)
        if (previousFile != null && previousFile.path != installed.dbPath) {
            assertTrue("Previous map must remain installed", previousFile.isFile)
            assertEquals(previousBytes, previousFile.length())
            assertEquals(previousModified, previousFile.lastModified())
        }
        SQLiteDatabase.openDatabase(installed.dbPath, null, SQLiteDatabase.OPEN_READONLY).use { db ->
            db.rawQuery("SELECT value FROM metadata WHERE key='settlement_context_version'", null).use {
                assertTrue(it.moveToFirst()); assertEquals("1", it.getString(0))
            }
            db.rawQuery("SELECT count(*) FROM settlement_segment", null).use {
                assertTrue(it.moveToFirst()); assertEquals(1294198L, it.getLong(0))
            }
        }
        val samples = listOf(
            Triple("251051581", 48.79660110525675, 8.437240933320787), // Im Kloster, service
            Triple("368645193", 48.80192816202721, 8.438886642937886), // Bahnhofsplatz, residential
        )
        for (model in listOf(LookupMatchingModel.CORRIDOR_HMM,
            LookupMatchingModel.SIMPLE_SPEED_REF_URBAN_RELEASE_NARROW_WINDOW_HEURISTIC)) {
            for ((way, lat, lon) in samples) {
                V3SpeedLimitLookup(installed.dbPath, countryCode = "DEU", matchingModel = model).use {
                    val lookup = it.lookup(lat, lon, 30.0, 64, null, speedKmh = 30.0, horizontalAccuracyM = 1.0)
                    instrumentation.sendStatus(0, Bundle().apply { putString("stream",
                        "$model sample=$way matched=${lookup.wayId} street=${lookup.streetName} " +
                            "speed=${lookup.speedLimitKmh} insideCity=${lookup.insideCity} " +
                            "source=${lookup.citySource} queryMs=${lookup.queryTimeMs}\n") })
                    assertEquals(way, lookup.wayId)
                    assertEquals(50, lookup.speedLimitKmh)
                    assertNull(lookup.insideCity)
                    assertEquals("settlement:missing:unknown", lookup.citySource)
                    assertEquals(DerivedSpeedSource.HIGHWAY_CLASS, lookup.speedSource)
                }
            }
        }
        val routed = bootstrapper.resolveLocalBundleRoute(samples.first().second, samples.first().third, installed.dbPath)
        assertEquals(installed.dbPath, routed?.dbPath)
        instrumentation.sendStatus(0, Bundle().apply { putString("stream",
            "Installed ${installed.bundleVersion} mode=${result.mode} bytes=${installed.dbBytes} " +
                "sha256=${installed.dbSha256}; previous map and preferences preserved\n") })
    }

    private fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().buffered().use { input ->
            val buffer = ByteArray(65536)
            while (true) {
                val n = input.read(buffer)
                if (n < 0) break
                digest.update(buffer, 0, n)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }
}
