package de.youspeed.android.alpha

import android.database.sqlite.SQLiteDatabase
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class CityContextInstrumentedTest {
    @Test
    fun nearestPlaceFallback_prefersCloserBadHerrenalbOverDistantHigherRankPforzheim() {
        val dbFile = createLookupDb("city-nearest-prefers-distance.sqlite")
        populateCoreSchema(dbFile)
        seedPlace(
            dbFile = dbFile,
            areaId = "bad-herrenalb",
            name = "Bad Herrenalb",
            place = "town",
            lon = 8.4382557,
            lat = 48.7990507,
        )
        seedPlace(
            dbFile = dbFile,
            areaId = "pforzheim",
            name = "Pforzheim",
            place = "city",
            lon = 8.7025509,
            lat = 48.890934,
        )

        V3SpeedLimitLookup(dbFile.absolutePath).use { lookup ->
            val result = lookup.lookup(
                lat = 48.7990,
                lon = 8.4392,
                radiusM = 120.0,
                maxCandidates = 32,
                headingDeg = null,
            )

            assertEquals("Bad Herrenalb", result.cityName)
            assertNull(result.insideCity)
            assertEquals("place_nearest", result.citySource)
        }
    }

    @Test
    fun nearestPlaceFallback_ignoresFarAwayPlacesOutsideThreshold() {
        val dbFile = createLookupDb("city-nearest-threshold.sqlite")
        populateCoreSchema(dbFile)
        seedPlace(
            dbFile = dbFile,
            areaId = "pforzheim",
            name = "Pforzheim",
            place = "city",
            lon = 8.7025509,
            lat = 48.890934,
        )

        V3SpeedLimitLookup(dbFile.absolutePath).use { lookup ->
            val result = lookup.lookup(
                lat = 48.7990,
                lon = 8.4392,
                radiusM = 120.0,
                maxCandidates = 32,
                headingDeg = null,
            )

            assertNull(result.cityName)
            assertNull(result.insideCity)
            assertEquals("bbox_no_match", result.citySource)
        }
    }

    private fun createLookupDb(fileName: String): File {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val dir = File(context.cacheDir, "city-context-tests").also { it.mkdirs() }
        return File(dir, fileName).also { if (it.exists()) it.delete() }
    }

    private fun populateCoreSchema(dbFile: File) {
        SQLiteDatabase.openOrCreateDatabase(dbFile, null).use { db ->
            db.execSQL(
                """
                CREATE TABLE ways (
                    way_id TEXT PRIMARY KEY,
                    highway TEXT,
                    street_name TEXT,
                    ref TEXT,
                    maxspeed TEXT,
                    maxspeed_type TEXT,
                    source_maxspeed TEXT,
                    approx_heading_deg REAL,
                    service TEXT,
                    tunnel TEXT,
                    min_lon REAL NOT NULL,
                    min_lat REAL NOT NULL,
                    max_lon REAL NOT NULL,
                    max_lat REAL NOT NULL
                )
                """.trimIndent()
            )
            db.execSQL(
                """
                CREATE TABLE areas (
                    area_id TEXT PRIMARY KEY,
                    geometry_type TEXT,
                    name TEXT,
                    place TEXT,
                    boundary TEXT,
                    admin_level TEXT,
                    min_lon REAL NOT NULL,
                    min_lat REAL NOT NULL,
                    max_lon REAL NOT NULL,
                    max_lat REAL NOT NULL,
                    residential TEXT,
                    points_json TEXT
                )
                """.trimIndent()
            )
        }
    }

    private fun seedPlace(
        dbFile: File,
        areaId: String,
        name: String,
        place: String,
        lon: Double,
        lat: Double,
    ) {
        SQLiteDatabase.openDatabase(dbFile.absolutePath, null, SQLiteDatabase.OPEN_READWRITE).use { db ->
            db.execSQL(
                """
                INSERT INTO areas (
                    area_id, geometry_type, name, place, boundary, admin_level,
                    min_lon, min_lat, max_lon, max_lat, residential, points_json
                ) VALUES (?, 'Point', ?, ?, NULL, NULL, ?, ?, ?, ?, NULL, NULL)
                """.trimIndent(),
                arrayOf(areaId, name, place, lon, lat, lon, lat),
            )
        }
    }
}
