package de.youspeed.android.alpha

import android.database.sqlite.SQLiteDatabase
import android.util.Log
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.util.UUID
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class LookupResourcesInstrumentedTest {
    @Test fun repeatedRealSqliteQueriesReuseSchemaAndDecodedGeometry() {
        val file = fixture(30)
        try {
            V3SpeedLimitLookup(file.path, countryCode = "DE").use { lookup ->
                val first = query(lookup)
                val cold = lookup.cacheStats()
                repeat(100) {
                    val result = query(lookup)
                    assertEquals(first.wayId, result.wayId)
                    assertEquals(first.speedLimitKmh, result.speedLimitKmh)
                    assertEquals(first.cityName, result.cityName)
                    assertEquals(first.nearestCandidateDistanceM, result.nearestCandidateDistanceM)
                    lookup.lookupCityContext(0.0, 0.0)
                }
                val warm = lookup.cacheStats()
                assertEquals(1, cold.ways.decodes)
                assertEquals(cold.ways.decodes, warm.ways.decodes)
                assertTrue(warm.ways.hits >= 100)
                assertEquals(cold.rings.decodes, warm.rings.decodes)
                assertTrue(warm.rings.hits >= 100)
                assertEquals(cold.schemaQueries, warm.schemaQueries)
                assertEquals(cold.queryShapes, warm.queryShapes)
                assertEquals("1", first.wayId)
                assertEquals(30, first.speedLimitKmh)
                Log.i("LookupResourcesTest", "100 repeated fixes plus city probes: cold=$cold warm=$warm")
            }
        } finally { file.delete() }
    }

    @Test fun replacingSqliteAtSamePathReopensReaderAndDropsGeometry() {
        val file = fixture(30)
        val replacement = fixture(50)
        val pool = LookupSessionResources { key -> V3SpeedLimitLookup(key.dbPath, key.countryCode) }
        try {
            fun key() = LookupConnectionKey(file.path, "DE", MatcherDebugProfile.M5)
            assertEquals(30, pool.withReader(key()) { query(it).speedLimitKmh })
            assertEquals(30, pool.withReader(key()) { query(it).speedLimitKmh })
            Files.setLastModifiedTime(replacement.toPath(), Files.getLastModifiedTime(file.toPath()))
            Files.move(replacement.toPath(), file.toPath(), StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE)
            assertEquals(50, pool.withReader(key()) { query(it).speedLimitKmh })
            assertEquals(LookupPoolStats(2, 1, 0, 1, 1), pool.stats())
            pool.withReader(key()) { assertEquals(1, it.cacheStats().ways.decodes) }
            Log.i("LookupResourcesTest", "Same-path replacement: ${pool.stats()}")
        } finally {
            pool.close()
            file.delete()
            replacement.delete()
        }
    }

    private fun query(lookup: V3SpeedLimitLookup) = lookup.lookup(0.0, 0.0, 100.0, 16, 90.0,
        speedKmh = 30.0, horizontalAccuracyM = 5.0, gpsSignalBars = 4)

    private fun fixture(speed: Int): File {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val file = File(context.cacheDir, "lookup-resources-${UUID.randomUUID()}.sqlite")
        SQLiteDatabase.openOrCreateDatabase(file, null).use { db ->
            db.execSQL("CREATE TABLE ways (way_id INTEGER PRIMARY KEY, highway TEXT, street_name TEXT, ref TEXT, maxspeed TEXT, maxspeed_type TEXT, source_maxspeed TEXT, approx_heading_deg REAL, service TEXT, tunnel TEXT, min_lon REAL, min_lat REAL, max_lon REAL, max_lat REAL)")
            db.execSQL("CREATE TABLE way_geom (way_id INTEGER PRIMARY KEY, points_json TEXT)")
            db.execSQL("INSERT INTO ways VALUES (1, 'residential', 'Cache Street', NULL, '$speed', NULL, NULL, 90.0, NULL, NULL, -0.001, 0.0, 0.001, 0.0)")
            db.execSQL("INSERT INTO way_geom VALUES (1, '[[0.0,-0.001],[0.0,0.001]]')")
            db.execSQL("CREATE TABLE areas (area_id TEXT PRIMARY KEY, geometry_type TEXT, name TEXT, place TEXT, boundary TEXT, admin_level TEXT, min_lon REAL, min_lat REAL, max_lon REAL, max_lat REAL, residential TEXT, points_json TEXT)")
            db.execSQL("INSERT INTO areas VALUES ('city', 'Polygon', 'Cache City', 'city', NULL, NULL, -0.01, -0.01, 0.01, 0.01, NULL, '[[-0.01,-0.01],[0.01,-0.01],[0.01,0.01],[-0.01,0.01],[-0.01,-0.01]]')")
        }
        return file
    }
}
