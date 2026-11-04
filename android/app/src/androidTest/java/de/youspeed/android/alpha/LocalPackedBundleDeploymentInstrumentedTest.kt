package de.youspeed.android.alpha

import android.content.Intent
import android.database.sqlite.SQLiteDatabase
import android.os.Bundle
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.net.URI
import java.security.MessageDigest
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Explicitly authorized packed-map installation and native replay; existing app data stays in place. */
@RunWith(AndroidJUnit4::class)
class LocalPackedBundleDeploymentInstrumentedTest {
    /** Exercises the normal activity/controller with real OS location callbacks; no location is injected. */
    @Test fun verifyPackedRegionWithLiveGpsWithoutChangingSettings() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        assumeTrue("Requires explicit live packed-map device test authorization",
            InstrumentationRegistry.getArguments().getString("run_live_packed_check") == "1")
        val context = instrumentation.targetContext
        val expected = JSONObject(File(context.cacheDir, "packed-region-device-test.json").readText())
        val samples = expected.getJSONArray("packed_samples")
        val expectedSample = samples.getJSONObject(samples.length() - 1)
        val activity = instrumentation.startActivitySync(Intent(context, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as MainActivity
        val preferences = context.getSharedPreferences("youspeed", 0).all.toMap()
        val observed = JSONArray()
        var previousQueryMs: Double? = null
        val deadline = SystemClock.elapsedRealtime() + 90_000
        while (SystemClock.elapsedRealtime() < deadline && observed.length() < 6) {
            instrumentation.runOnMainSync {
                val controller = activity.sessionController
                if (controller.uiState.startupLogReviewState == StartupLogReviewState.CHOICE) controller.keepStartupLogs()
                val state = controller.uiState
                if (state.activeBundleVersion == expected.getString("bundle_version") && state.gpsFixCount > 0 &&
                    !state.limitCityName.isNullOrBlank() && state.lastLookupQueryMs != previousQueryMs) {
                    previousQueryMs = state.lastLookupQueryMs
                    observed.put(JSONObject().apply {
                        put("fix_id", state.gpsFixCount); put("city", state.limitCityName)
                        put("street", state.limitStreetName); put("speed_kmh", state.speedLimitKmh)
                        put("query_ms", state.lastLookupQueryMs); put("bundle_version", state.activeBundleVersion)
                        put("recorded_at_ms", System.currentTimeMillis())
                    })
                }
            }
            Thread.sleep(250)
        }
        File(context.cacheDir, "packed-region-live-gps-test.json").writeText(observed.toString(2))
        instrumentation.sendStatus(0, Bundle().apply { putString("stream", observed.toString() + "\n") })
        assertTrue("The normal controller must publish at least three packed-map results from real GPS", observed.length() >= 3)
        for (index in 0 until observed.length()) {
            val row = observed.getJSONObject(index)
            assertEquals(expectedSample.getString("city"), row.getString("city"))
            // Real GPS may select an adjacent road as its position changes.
            // Exact street/speed parity is checked separately at a fixed
            // coordinate against the preserved legacy map.
            assertTrue(row.getString("street").isNotBlank())
            assertTrue(row.optInt("speed_kmh", 0) > 0)
            assertTrue(row.getDouble("query_ms") < TrafficSignRoadContextFreshness.MAXIMUM_AGE_MS)
        }
        assertEquals(preferences, context.getSharedPreferences("youspeed", 0).all)
        val journal = File(context.filesDir, "trip-journal/trips.sqlite")
        if (journal.isFile) SQLiteDatabase.openDatabase(journal.path, null, SQLiteDatabase.OPEN_READONLY).use { db ->
            val trips = JSONArray()
            db.rawQuery("SELECT id,start,end,state,distance FROM trips ORDER BY start", null).use { rows ->
                while (rows.moveToNext()) {
                    val id = rows.getString(0)
                    val events = db.rawQuery("SELECT COUNT(*) FROM events WHERE trip=?", arrayOf(id)).use {
                        assertTrue(it.moveToFirst()); it.getLong(0)
                    }
                    trips.put(JSONObject().apply {
                        put("id", id); put("start", rows.getDouble(1)); put("end", rows.getDouble(2))
                        put("state", rows.getString(3)); put("distance_m", rows.getDouble(4)); put("event_count", events)
                    })
                }
            }
            File(context.cacheDir, "packed-region-journal-after-test.json").writeText(trips.toString(2))
        }
    }

    @Test fun installVerifiedPackedRegionAndCompareProductionLookup() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val args = InstrumentationRegistry.getArguments()
        assumeTrue("Requires explicit packed-map device deployment authorization",
            args.getString("run_local_packed_install") == "1")
        val context = instrumentation.targetContext
        require(context.packageName in setOf("de.youspeed.android.debug", "de.youspeed.android.testhost"))
        val latitude = requireNotNull(args.getString("packed_test_lat")).toDouble()
        val longitude = requireNotNull(args.getString("packed_test_lon")).toDouble()
        require(latitude.isFinite() && latitude in -90.0..90.0 && longitude.isFinite() && longitude in -180.0..180.0)
        val staged = File(context.cacheDir, "packed-region-deployment").canonicalFile
        val manifestFile = File(staged, "manifest.json")
        val manifestRaw = manifestFile.readText()
        val manifest = ContractJson.decodeBundleManifest(manifestRaw)
        assertEquals("youspeed.v4.bundle.manifest", manifest.format)
        val packed = requireNotNull(manifest.packedBase)
        val root = File(context.filesDir, "bundle")
        val stateFile = File(root, "active_bundle.json")
        val backup = File(root, "active_bundle.before-packed-device-test.json")
        if (!backup.exists()) backup.writeText(stateFile.readText())
        val previousState = backup.readText()
        val previous = ContractJson.decodeActiveBundleState(previousState)
        val previousFile = File(previous.dbPath)
        val previousBytes = previousFile.length()
        val previousModified = previousFile.lastModified()
        val preferences = context.getSharedPreferences("youspeed", 0).all.toMap()

        fun sample(path: String, repeats: Int): Pair<SpeedLookupResult, JSONArray> {
            val rows = JSONArray()
            var last: SpeedLookupResult? = null
            V3SpeedLimitLookup(path, manifest.countryCode, MatcherDebugProfile.M7.lookupModel).use { lookup ->
                repeat(repeats) { index ->
                    val result = lookup.lookup(latitude, longitude, 120.0, 1200, null,
                        speedKmh = 0.0, horizontalAccuracyM = 5.0, gpsSignalBars = 4)
                    assertFalse(result.wayId.isNullOrBlank())
                    rows.put(JSONObject().apply {
                        put("iteration", index); put("way_id", result.wayId)
                        put("street", result.streetName); put("city", result.cityName)
                        put("place", result.cityPlaceName); put("district", result.cityDistrictName)
                        put("speed_kmh", result.speedLimitKmh); put("inside_city", result.insideCity)
                        put("query_ms", result.queryTimeMs); put("stages", JSONObject(result.lookupStageMs))
                    })
                    last = result
                }
            }
            return requireNotNull(last) to rows
        }
        val (legacyResult, legacySamples) = sample(previousFile.path, 1)
        val allowedFiles = buildSet {
            add("manifest.json")
            listOfNotNull(manifest.db, packed.roads, packed.nodes, manifest.penaltyRules,
                manifest.coverage?.poly).forEach { artifact ->
                add(URI(requireNotNull(artifact.url)).path.substringAfterLast('/'))
            }
        }
        val fetcher = object : HttpFetcher {
            private fun source(url: String): File {
                val name = URI(url).path.substringAfterLast('/')
                require(name in allowedFiles) { "Unexpected local test artifact: $name" }
                return File(staged, name).canonicalFile.also { require(it.parentFile == staged && it.isFile) }
            }
            override fun fetch(url: String) = source(url).readBytes()
            override fun fetchToFile(url: String, destination: File,
                onProgress: ((completedBytes: Long, totalBytes: Long?) -> Unit)?) {
                val file = source(url)
                file.inputStream().buffered().use { input -> destination.outputStream().use { input.copyTo(it) } }
                onProgress?.invoke(file.length(), file.length())
            }
        }
        val bootstrapper = BundleBootstrapper(root, fetcher)
        val started = System.nanoTime()
        val installed = bootstrapper.syncFromManifestUrl(manifestFile.toURI().toString()) { progress ->
            if (progress.stage != BundleSyncStage.DOWNLOADING) instrumentation.sendStatus(0,
                Bundle().apply { putString("stream", "Packed install ${progress.stage}: ${progress.detail}\n") })
        }
        val installMs = (System.nanoTime() - started) / 1e6
        val active = requireNotNull(bootstrapper.activeState())
        assertEquals(manifest.bundleVersion, active.bundleVersion)
        assertEquals(manifest.db.sha256, active.dbSha256)
        manifest.coverage?.poly?.let { poly ->
            val source = File(staged, URI(requireNotNull(poly.url)).path.substringAfterLast('/'))
            assertEquals(poly.bytes, source.length())
            assertEquals(poly.sha256, sha256(source))
            source.copyTo(File(File(active.dbPath).parentFile, poly.file), overwrite = true)
        }
        val (packedResult, packedSamples) = sample(active.dbPath, 5)
        assertEquals(legacyResult.wayId, packedResult.wayId)
        assertEquals(legacyResult.streetName, packedResult.streetName)
        assertEquals(legacyResult.cityName, packedResult.cityName)
        assertEquals(legacyResult.cityPlaceName, packedResult.cityPlaceName)
        assertEquals(legacyResult.cityDistrictName, packedResult.cityDistrictName)
        assertEquals(legacyResult.speedLimitKmh, packedResult.speedLimitKmh)
        assertEquals(legacyResult.insideCity, packedResult.insideCity)
        assertEquals(preferences, context.getSharedPreferences("youspeed", 0).all)
        assertEquals(previousBytes, previousFile.length())
        assertEquals(previousModified, previousFile.lastModified())
        assertTrue(previousFile.isFile)
        val receipt = JSONObject().apply {
            put("bundle_version", active.bundleVersion); put("db_path", active.dbPath)
            put("context_sha256", active.dbSha256); put("install_ms", installMs)
            put("install_mode", installed.mode.name); put("legacy_samples", legacySamples)
            put("packed_samples", packedSamples); put("previous_map_preserved", true)
            put("preferences_preserved", true); put("location_injected", false)
        }
        File(context.cacheDir, "packed-region-device-test.json").writeText(receipt.toString(2))
        instrumentation.sendStatus(0, Bundle().apply { putString("stream", receipt.toString() + "\n") })
    }

    private fun sha256(file: File): String {
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().buffered().use { input ->
            val buffer = ByteArray(64 * 1024)
            while (true) { val count = input.read(buffer); if (count < 0) break; digest.update(buffer, 0, count) }
        }
        return digest.digest().joinToString("") { "%02x".format(it.toInt() and 255) }
    }
}
