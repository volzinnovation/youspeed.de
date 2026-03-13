package de.youspeed.android.alpha

import android.database.sqlite.SQLiteDatabase
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class CityContextInstrumentedTest {
    @Test
    fun adminPolygon_prefersAdminLevel8Boundary() {
        val dbFile = createLookupDb("city-admin-polygon-prefers-level8.sqlite")
        populateCoreSchema(dbFile)
        seedCityBoundary(
            dbFile = dbFile,
            rowId = 1L,
            adminLevel = 8,
            name = "Pforzheim",
            minLon = 8.6825509,
            minLat = 48.870934,
            maxLon = 8.7225509,
            maxLat = 48.910934,
            ring = rectangleRing(
                minLon = 8.6825509,
                minLat = 48.870934,
                maxLon = 8.7225509,
                maxLat = 48.910934,
            ),
        )
        seedCityBoundary(
            dbFile = dbFile,
            rowId = 2L,
            adminLevel = 9,
            name = "Buechenbronn",
            minLon = 8.6995509,
            minLat = 48.887934,
            maxLon = 8.7055509,
            maxLat = 48.893934,
            ring = rectangleRing(
                minLon = 8.6995509,
                minLat = 48.887934,
                maxLon = 8.7055509,
                maxLat = 48.893934,
            ),
        )

        V3SpeedLimitLookup(dbFile.absolutePath).use { lookup ->
            val result = lookup.lookup(
                lat = 48.890934,
                lon = 8.7025509,
                radiusM = 120.0,
                maxCandidates = 32,
                headingDeg = null,
            )

            assertEquals("Pforzheim", result.cityName)
            assertTrue(result.insideCity == true)
            assertEquals("admin_polygon", result.citySource)
        }
    }

    @Test
    fun adminPolygon_ignoresAdminLevel9AndFallsBackToPlace() {
        val dbFile = createLookupDb("city-admin-polygon-ignores-level9.sqlite")
        populateCoreSchema(dbFile)
        seedCityBoundary(
            dbFile = dbFile,
            rowId = 2L,
            adminLevel = 9,
            name = "Kullenmühle",
            minLon = 8.4396,
            minLat = 48.8071,
            maxLon = 8.4456,
            maxLat = 48.8131,
            ring = rectangleRing(
                minLon = 8.4396,
                minLat = 48.8071,
                maxLon = 8.4456,
                maxLat = 48.8131,
            ),
        )
        seedCityPlace(
            dbFile = dbFile,
            rowId = 1L,
            name = "Bad Herrenalb",
            place = "town",
            lon = 8.4382557,
            lat = 48.7990507,
        )

        V3SpeedLimitLookup(dbFile.absolutePath).use { lookup ->
            val result = lookup.lookup(
                lat = 48.8101,
                lon = 8.4426,
                radiusM = 120.0,
                maxCandidates = 32,
                headingDeg = null,
            )

            assertEquals("Bad Herrenalb", result.cityName)
            assertEquals(false, result.insideCity)
            assertEquals("place_fallback", result.citySource)
        }
    }

    @Test
    fun adminPolygon_usesAdminLevel6BoundaryWhenNoLevel8Exists() {
        val dbFile = createLookupDb("city-admin-polygon-uses-level6.sqlite")
        populateCoreSchema(dbFile)
        seedCityBoundary(
            dbFile = dbFile,
            rowId = 1L,
            adminLevel = 6,
            name = "Pforzheim",
            minLon = 8.6725509,
            minLat = 48.860934,
            maxLon = 8.7325509,
            maxLat = 48.920934,
            ring = rectangleRing(
                minLon = 8.6725509,
                minLat = 48.860934,
                maxLon = 8.7325509,
                maxLat = 48.920934,
            ),
        )

        V3SpeedLimitLookup(dbFile.absolutePath).use { lookup ->
            val result = lookup.lookup(
                lat = 48.890934,
                lon = 8.7025509,
                radiusM = 120.0,
                maxCandidates = 32,
                headingDeg = null,
            )

            assertEquals("Pforzheim", result.cityName)
            assertTrue(result.insideCity == true)
            assertEquals("admin_polygon", result.citySource)
        }
    }

    @Test
    fun adminPolygon_prefersAdminLevel8BoundaryOverLevel6() {
        val dbFile = createLookupDb("city-admin-polygon-prefers-level8-over-level6.sqlite")
        populateCoreSchema(dbFile)
        seedCityBoundary(
            dbFile = dbFile,
            rowId = 1L,
            adminLevel = 6,
            name = "Enzkreis",
            minLon = 8.6435,
            minLat = 48.8933,
            maxLon = 8.7035,
            maxLat = 48.9533,
            ring = rectangleRing(
                minLon = 8.6435,
                minLat = 48.8933,
                maxLon = 8.7035,
                maxLat = 48.9533,
            ),
        )
        seedCityBoundary(
            dbFile = dbFile,
            rowId = 2L,
            adminLevel = 8,
            name = "Ispringen",
            minLon = 8.6535,
            minLat = 48.9033,
            maxLon = 8.6935,
            maxLat = 48.9433,
            ring = rectangleRing(
                minLon = 8.6535,
                minLat = 48.9033,
                maxLon = 8.6935,
                maxLat = 48.9433,
            ),
        )

        V3SpeedLimitLookup(dbFile.absolutePath).use { lookup ->
            val result = lookup.lookup(
                lat = 48.9233,
                lon = 8.6735,
                radiusM = 120.0,
                maxCandidates = 32,
                headingDeg = null,
            )

            assertEquals("Ispringen", result.cityName)
            assertTrue(result.insideCity == true)
            assertEquals("admin_polygon", result.citySource)
        }
    }

    @Test
    fun nearestPlaceFallback_prefersNearbyCityOverCloserVillage() {
        val dbFile = createLookupDb("city-nearest-prefers-city-over-village.sqlite")
        populateCoreSchema(dbFile)
        seedPlace(
            dbFile = dbFile,
            areaId = "ispringen",
            name = "Ispringen",
            place = "village",
            lon = 8.6690154,
            lat = 48.9205599,
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
                lat = 48.9205,
                lon = 8.6692,
                radiusM = 120.0,
                maxCandidates = 32,
                headingDeg = null,
            )

            assertEquals("Pforzheim", result.cityName)
            assertEquals(false, result.insideCity)
            assertEquals("place_fallback", result.citySource)
        }
    }

    @Test
    fun nearestPlaceFallback_prefersNearbyTownOverCloserHamlet() {
        val dbFile = createLookupDb("city-nearest-prefers-town-over-hamlet.sqlite")
        populateCoreSchema(dbFile)
        seedPlace(
            dbFile = dbFile,
            areaId = "kullenmuehle",
            name = "Kullenmühle",
            place = "hamlet",
            lon = 8.442564,
            lat = 48.8101385,
        )
        seedPlace(
            dbFile = dbFile,
            areaId = "bad-herrenalb",
            name = "Bad Herrenalb",
            place = "town",
            lon = 8.4382557,
            lat = 48.7990507,
        )

        V3SpeedLimitLookup(dbFile.absolutePath).use { lookup ->
            val result = lookup.lookup(
                lat = 48.8101,
                lon = 8.4426,
                radiusM = 120.0,
                maxCandidates = 32,
                headingDeg = null,
            )

            assertEquals("Bad Herrenalb", result.cityName)
            assertEquals(false, result.insideCity)
            assertEquals("place_fallback", result.citySource)
        }
    }

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
            assertEquals(false, result.insideCity)
            assertEquals("place_fallback", result.citySource)
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
            assertEquals(false, result.insideCity)
            assertEquals("admin_polygons_plus_places", result.citySource)
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
            db.execSQL(
                """
                CREATE TABLE city_boundary (
                    row_id INTEGER PRIMARY KEY,
                    osm_type TEXT NOT NULL,
                    osm_id INTEGER NOT NULL,
                    admin_level INTEGER NOT NULL,
                    name TEXT,
                    min_lon REAL NOT NULL,
                    min_lat REAL NOT NULL,
                    max_lon REAL NOT NULL,
                    max_lat REAL NOT NULL
                )
                """.trimIndent()
            )
            tryCreateRtreeTable(
                db,
                """
                CREATE VIRTUAL TABLE city_boundary_rtree USING rtree(
                    row_id,
                    min_lon, max_lon,
                    min_lat, max_lat
                )
                """.trimIndent()
            )
            db.execSQL(
                """
                CREATE TABLE city_ring (
                    boundary_row_id INTEGER NOT NULL,
                    ring_index INTEGER NOT NULL,
                    outer_index INTEGER NOT NULL,
                    is_hole INTEGER NOT NULL,
                    points_json TEXT NOT NULL
                )
                """.trimIndent()
            )
            db.execSQL(
                """
                CREATE TABLE city_place (
                    row_id INTEGER PRIMARY KEY,
                    place TEXT NOT NULL,
                    name TEXT NOT NULL,
                    lon REAL NOT NULL,
                    lat REAL NOT NULL
                )
                """.trimIndent()
            )
            tryCreateRtreeTable(
                db,
                """
                CREATE VIRTUAL TABLE city_place_rtree USING rtree(
                    row_id,
                    min_lon, max_lon,
                    min_lat, max_lat
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
            if (tableExists(db, "city_place")) {
                val rowId = name.hashCode().toLong()
                db.execSQL(
                    """
                    INSERT INTO city_place (
                        row_id, place, name, lon, lat
                    ) VALUES (?, ?, ?, ?, ?)
                    """.trimIndent(),
                    arrayOf(rowId, place, name, lon, lat),
                )
                if (tableExists(db, "city_place_rtree")) {
                    db.execSQL(
                        """
                        INSERT INTO city_place_rtree (
                            row_id, min_lon, max_lon, min_lat, max_lat
                        ) VALUES (?, ?, ?, ?, ?)
                        """.trimIndent(),
                        arrayOf(rowId, lon, lon, lat, lat),
                    )
                }
            }
        }
    }

    private fun seedCityBoundary(
        dbFile: File,
        rowId: Long,
        adminLevel: Int,
        name: String,
        minLon: Double,
        minLat: Double,
        maxLon: Double,
        maxLat: Double,
        ring: String,
    ) {
        SQLiteDatabase.openDatabase(dbFile.absolutePath, null, SQLiteDatabase.OPEN_READWRITE).use { db ->
            db.execSQL(
                """
                INSERT INTO city_boundary (
                    row_id, osm_type, osm_id, admin_level, name,
                    min_lon, min_lat, max_lon, max_lat
                ) VALUES (?, 'relation', ?, ?, ?, ?, ?, ?, ?)
                """.trimIndent(),
                arrayOf(rowId, rowId + 1000L, adminLevel, name, minLon, minLat, maxLon, maxLat),
            )
            if (tableExists(db, "city_boundary_rtree")) {
                db.execSQL(
                    """
                    INSERT INTO city_boundary_rtree (
                        row_id, min_lon, max_lon, min_lat, max_lat
                    ) VALUES (?, ?, ?, ?, ?)
                    """.trimIndent(),
                    arrayOf(rowId, minLon, maxLon, minLat, maxLat),
                )
            }
            db.execSQL(
                """
                INSERT INTO city_ring (
                    boundary_row_id, ring_index, outer_index, is_hole, points_json
                ) VALUES (?, 0, 0, 0, ?)
                """.trimIndent(),
                arrayOf(rowId, ring),
            )
        }
    }

    private fun seedCityPlace(
        dbFile: File,
        rowId: Long,
        name: String,
        place: String,
        lon: Double,
        lat: Double,
    ) {
        SQLiteDatabase.openDatabase(dbFile.absolutePath, null, SQLiteDatabase.OPEN_READWRITE).use { db ->
            db.execSQL(
                """
                INSERT INTO city_place (
                    row_id, place, name, lon, lat
                ) VALUES (?, ?, ?, ?, ?)
                """.trimIndent(),
                arrayOf(rowId, place, name, lon, lat),
            )
            if (tableExists(db, "city_place_rtree")) {
                db.execSQL(
                    """
                    INSERT INTO city_place_rtree (
                        row_id, min_lon, max_lon, min_lat, max_lat
                    ) VALUES (?, ?, ?, ?, ?)
                    """.trimIndent(),
                    arrayOf(rowId, lon, lon, lat, lat),
                )
            }
        }
    }

    private fun tryCreateRtreeTable(
        db: SQLiteDatabase,
        sql: String,
    ) {
        try {
            db.execSQL(sql)
        } catch (error: Exception) {
            if (!error.message.orEmpty().contains("no such module: rtree", ignoreCase = true)) {
                throw error
            }
        }
    }

    private fun tableExists(
        db: SQLiteDatabase,
        name: String,
    ): Boolean {
        db.rawQuery(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            arrayOf(name),
        ).use { cursor ->
            return cursor.moveToFirst()
        }
    }

    private fun rectangleRing(
        minLon: Double,
        minLat: Double,
        maxLon: Double,
        maxLat: Double,
    ): String {
        return "[[$minLon,$minLat],[$maxLon,$minLat],[$maxLon,$maxLat],[$minLon,$maxLat],[$minLon,$minLat]]"
    }
}
