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
    @Test fun fullPackedPforzheimAndNeuenbuergLookupsStayWithinTheGpsInterval() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        org.junit.Assume.assumeTrue("Requires a staged full regional map in the isolated test host",
            InstrumentationRegistry.getArguments().getString("run_full_packed_city_acceptance") == "1")
        val context = instrumentation.targetContext
        assertEquals("de.youspeed.android.testhost", context.packageName)
        val directory = File(context.cacheDir, "city-full-packed")
        val map = File(directory, "baden-wuerttemberg_2026-10-27-packed-v1.context.yspc")
        assertTrue("The complete packed regional fixture must be staged explicitly", map.isFile)
        val digest = java.security.MessageDigest.getInstance("SHA-256")
        map.inputStream().buffered().use { input ->
            val buffer = ByteArray(1024 * 1024)
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                digest.update(buffer, 0, count)
            }
        }
        assertEquals("66bff716fa57500f482f7a8707fb1fcfa059beadcecab260b34934b7576666e5",
            digest.digest().joinToString("") { "%02x".format(it.toInt() and 255) })
        val results = org.json.JSONArray()
        V3SpeedLimitLookup(map.path, countryCode = "DEU").use { lookup ->
            for ((latitude, longitude, expectedCity) in listOf(
                Triple(48.878, 8.715, "Pforzheim"),
                Triple(48.8762966, 8.6453480, "Birkenfeld (Enzkreis)"),
                Triple(48.847, 8.589, "Neuenbürg (Enzkreis)"),
            )) repeat(3) { iteration ->
                val result = lookup.lookup(latitude, longitude, 120.0, 1200, null,
                    speedKmh = 0.0, horizontalAccuracyM = 5.0, gpsSignalBars = 4)
                results.put(org.json.JSONObject().apply {
                    put("city", result.cityName); put("latitude", latitude); put("longitude", longitude)
                    put("iteration", iteration); put("query_ms", result.queryTimeMs)
                    put("stages", org.json.JSONObject(result.lookupStageMs))
                })
                File(context.cacheDir, "city-full-packed-results.json").writeText(results.toString(2))
                assertEquals(expectedCity, result.cityName)
                assertTrue("A packed city-entry lookup must finish before the next 1 Hz GPS fix: ${result.queryTimeMs} ms",
                    result.queryTimeMs < 1000.0)
            }
        }
    }

    @Test fun zeroPaddedAdministrativeLevelStillUsesItsClosedRing() {
        val file = createLookupDb("city-spatial-zero-padded-level.sqlite")
        populateCoreSchema(file)
        addSpatialAreaSchema(file)
        SQLiteDatabase.openDatabase(file.path, null, SQLiteDatabase.OPEN_READWRITE).use { db ->
            db.execSQL("""INSERT INTO areas(row_id,area_id,geometry_type,name,boundary,admin_level,
                min_lon,min_lat,max_lon,max_lat,points_json) VALUES(1,'outside-ring','Polygon','Wrong district',
                'administrative','06',7.9,48.9,8.1,49.1,?)""",
                arrayOf(rectangleRing(8.05, 49.05, 8.1, 49.1)))
            db.execSQL("""INSERT INTO areas(row_id,area_id,geometry_type,name,place,min_lon,min_lat,max_lon,max_lat)
                VALUES(2,'nearby-town','Point','Neuenbürg','town',8.01,49.0,8.01,49.0)""")
        }
        spatialLookup(file).use { lookup ->
            assertEquals("Neuenbürg", lookup.lookupCityContext(49.0, 8.0).cityName)
            assertEquals("Neuenbürg", lookup.lookup(49.0, 8.0, 120.0, 32, null).cityName)
        }
    }

    @Test fun districtOnlyPforzheimPolygonRetainsItsNameWithoutDecodingUnrelatedAreas() {
        val file = createLookupDb("city-pforzheim-district-only-spatial.sqlite")
        populateCoreSchema(file)
        addSpatialAreaSchema(file)
        seedCityBoundary(file, 2001, 6, "Pforzheim", 8.68, 48.85, 8.75, 48.91,
            rectangleRing(8.68, 48.85, 8.75, 48.91))
        SQLiteDatabase.openDatabase(file.path, null, SQLiteDatabase.OPEN_READWRITE).use { db ->
            // These nearby landuse polygons must never enter the area-body
            // fetch; one containing park still enters but needs no geometry.
            repeat(600) { index ->
                db.execSQL("""INSERT INTO areas(row_id,area_id,geometry_type,name,min_lon,min_lat,max_lon,max_lat,points_json)
                    VALUES(?,?,'Polygon','Unrelated park',8.72,48.88,8.73,48.89,?)""",
                    arrayOf(index + 1, "park-$index", rectangleRing(8.72, 48.88, 8.73, 48.89)))
            }
            db.execSQL("""INSERT INTO areas(row_id,area_id,geometry_type,name,min_lon,min_lat,max_lon,max_lat,points_json)
                VALUES(1000,'containing-park','Polygon','Containing park',8.70,48.87,8.72,48.88,?)""",
                arrayOf(rectangleRing(8.70, 48.87, 8.72, 48.88)))
        }
        spatialLookup(file).use { lookup ->
            val result = lookup.lookup(48.878, 8.715, 120.0, 32, null)
            assertEquals("Pforzheim", result.cityName)
            assertNull(result.cityDistrictName)
            val decodes = lookup.cacheStats().rings.decodes
            assertEquals("Only the administrative city ring requires decoding", 1L, decodes)
            assertEquals(listOf("containing-park"), lookup.areaCandidateIdsForTesting(48.878, 8.715))
            assertEquals("Unrelated landuse geometry is not consumed by city or residential selection",
                decodes, lookup.cacheStats().rings.decodes)
            assertEquals("Pforzheim", lookup.lookupCityContext(48.878, 8.715).cityName)
        }
    }

    @Test fun spatialAreaCandidatesDeduplicateAndApplyTheCapInRowIdOrder() {
        val file = createLookupDb("city-spatial-cap.sqlite")
        populateCoreSchema(file)
        addSpatialAreaSchema(file)
        SQLiteDatabase.openDatabase(file.path, null, SQLiteDatabase.OPEN_READWRITE).use { db ->
            for (rowId in (1..520).reversed()) {
                db.execSQL("""INSERT INTO areas(row_id,area_id,geometry_type,name,place,min_lon,min_lat,max_lon,max_lat)
                    VALUES(?,?,'Point',?,'town',8.0,49.0,8.0,49.0)""",
                    arrayOf(rowId, "town-${521 - rowId}", "Town $rowId"))
            }
        }
        spatialLookup(file).use { lookup ->
            // Every row occurs in both the containing and nearby-place branch.
            assertEquals((1..512).map { "town-${521 - it}" }, lookup.areaCandidateIdsForTesting(49.0, 8.0))
        }
    }

    @Test fun containingAdministrativeAreaSurvivesMoreThan512NearbyPlaces() {
        val file = createLookupDb("city-spatial-containing-priority.sqlite")
        populateCoreSchema(file)
        addSpatialAreaSchema(file)
        SQLiteDatabase.openDatabase(file.path, null, SQLiteDatabase.OPEN_READWRITE).use { db ->
            repeat(520) { index ->
                db.execSQL("""INSERT INTO areas(row_id,area_id,geometry_type,name,place,min_lon,min_lat,max_lon,max_lat)
                    VALUES(?,?,'Point',?,'hamlet',8.01,49.0,8.01,49.0)""",
                    arrayOf(index + 1, "hamlet-$index", "Hamlet $index"))
            }
            db.execSQL("""INSERT INTO areas(row_id,area_id,geometry_type,name,boundary,admin_level,
                min_lon,min_lat,max_lon,max_lat,points_json) VALUES(1000,'containing-admin','Polygon','Neuenbürg',
                'administrative','8',7.99,48.99,8.01,49.01,?)""",
                arrayOf(rectangleRing(7.99, 48.99, 8.01, 49.01)))
        }
        spatialLookup(file).use { lookup ->
            val ids = lookup.areaCandidateIdsForTesting(49.0, 8.0)
            assertEquals(512, ids.size)
            assertEquals("containing-admin", ids.last())
            assertEquals("Neuenbürg", lookup.lookupCityContext(49.0, 8.0).cityName)
            assertEquals("Neuenbürg", lookup.lookup(49.0, 8.0, 120.0, 32, null).cityName)
        }
    }

    @Test fun spatialAreaFallbackPreservesPolygonBboxContainingPlaceAndNearestPrecedence() {
        val file = createLookupDb("city-spatial-precedence.sqlite")
        populateCoreSchema(file)
        addSpatialAreaSchema(file)
        SQLiteDatabase.openDatabase(file.path, null, SQLiteDatabase.OPEN_READWRITE).use { db ->
            db.execSQL("DROP TABLE IF EXISTS city_place_rtree")
            db.execSQL("DROP TABLE city_place")
            fun area(id: Int, name: String, place: String?, level: String?, ring: String?, min: Double = 7.99, max: Double = 8.01) {
                db.execSQL("""INSERT INTO areas(row_id,area_id,geometry_type,name,place,boundary,admin_level,
                    min_lon,min_lat,max_lon,max_lat,points_json) VALUES(?,?,'Polygon',?,?,?,?,?,48.99,?,49.01,?)""",
                    arrayOf(id, "area-$id", name, place, if (level == null) null else "administrative", level, min, max, ring))
            }
            area(1, "Neuenbürg", null, "8", rectangleRing(7.99, 48.99, 8.01, 49.01))
            area(2, "Enzkreis", null, "6", rectangleRing(7.99, 48.99, 8.01, 49.01))
            area(3, "Birkenfeld", null, "8", null)
            area(4, "Containing village", "village", null, rectangleRing(7.99, 48.99, 8.01, 49.01))
            area(5, "Nearby town", "town", null, null, 8.02, 8.02)
            area(6, "Closer hamlet", "hamlet", null, null, 8.001, 8.001)
        }
        fun check(expected: String, source: String) {
            spatialLookup(file).use { lookup ->
                val named = lookup.lookupCityContext(49.0, 8.0)
                assertEquals(expected, named.cityName)
                assertEquals(source, named.citySource)
                assertEquals(expected, lookup.lookup(49.0, 8.0, 120.0, 32, null).cityName)
            }
        }
        check("Neuenbürg (Enzkreis)", "admin_polygon")
        spatialLookup(file).use { lookup ->
            assertEquals("Neuenbürg (Enzkreis)", lookup.lookupCityContext(49.0, 7.99).cityName)
        }
        SQLiteDatabase.openDatabase(file.path, null, SQLiteDatabase.OPEN_READWRITE).use { it.execSQL("DELETE FROM areas WHERE row_id IN (1,2)") }
        check("Birkenfeld", "admin_bbox")
        SQLiteDatabase.openDatabase(file.path, null, SQLiteDatabase.OPEN_READWRITE).use { it.execSQL("DELETE FROM areas WHERE row_id=3") }
        check("Containing village", "place_bbox")
        SQLiteDatabase.openDatabase(file.path, null, SQLiteDatabase.OPEN_READWRITE).use { it.execSQL("DELETE FROM areas WHERE row_id=4") }
        check("Nearby town", "place_nearest")
    }

    @Test fun completeAdministrativePolygonAvoidsUnneededAreaGeometryInBothLookupPaths() {
        fun exercise(extraArea: Boolean, model: LookupMatchingModel): Long {
            val file = createLookupDb("city-complete-${extraArea}-${model.name}.sqlite")
            populateCoreSchema(file)
            SQLiteDatabase.openDatabase(file.path, null, SQLiteDatabase.OPEN_READWRITE).use { db ->
                db.execSQL("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT)")
                db.execSQL("INSERT INTO metadata VALUES('settlement_context_version','1')")
                db.execSQL("CREATE TABLE settlement_segment(segment_id INTEGER,way_id INTEGER,segment_index INTEGER,direction INTEGER,inside_city INTEGER,source TEXT,confidence TEXT,evidence_json TEXT,points_json TEXT)")
                if (extraArea) db.execSQL("""INSERT INTO areas VALUES('park','Polygon','Unrelated park',NULL,NULL,NULL,
                    7.995,48.995,8.005,49.005,'landuse','[[7.995,48.995],[8.005,48.995],[8.005,49.005],[7.995,49.005],[7.995,48.995]]')""")
            }
            for ((level, name, extent) in listOf(Triple(6, "District", 0.03), Triple(8, "Town", 0.02))) {
                seedCityBoundary(file, level.toLong(), level, name, 8 - extent, 49 - extent, 8 + extent, 49 + extent,
                    rectangleRing(8 - extent, 49 - extent, 8 + extent, 49 + extent))
            }
            return V3SpeedLimitLookup(file.path, countryCode = "DEU", matchingModel = model).use { lookup ->
                val result = lookup.lookup(49.0, 8.0, 120.0, 32, null)
                assertEquals("Town (District)", result.cityName)
                assertEquals("District", result.cityDistrictName)
                assertEquals(result.cityName, lookup.lookupCityContext(49.0, 8.0).cityName)
                lookup.cacheStats().rings.decodes
            }
        }
        for (model in listOf(LookupMatchingModel.CORRIDOR_HMM,
            LookupMatchingModel.SIMPLE_SPEED_REF_URBAN_RELEASE_NARROW_WINDOW_HEURISTIC)) {
            assertEquals("An irrelevant area must not add decoding after complete polygon resolution",
                exercise(false, model), exercise(true, model))
        }
    }

    @Test fun incompleteAdministrativePolygonStillGetsDistrictFromAreas() {
        val file = createLookupDb("city-incomplete-district-fallback.sqlite")
        populateCoreSchema(file)
        seedCityBoundary(file, 8, 8, "Town", 7.98, 48.98, 8.02, 49.02,
            rectangleRing(7.98, 48.98, 8.02, 49.02))
        SQLiteDatabase.openDatabase(file.path, null, SQLiteDatabase.OPEN_READWRITE).use { db ->
            for ((level, name, extent) in listOf(Triple(6, "District", 0.03), Triple(8, "Town", 0.02))) {
                db.execSQL("INSERT INTO areas VALUES(?,'Polygon',?,NULL,'administrative',?,?,?,?,?,NULL,?)",
                    arrayOf("admin-$level", name, level.toString(), 8 - extent, 49 - extent, 8 + extent, 49 + extent,
                        rectangleRing(8 - extent, 49 - extent, 8 + extent, 49 + extent)))
            }
        }
        V3SpeedLimitLookup(file.path).use { lookup ->
            val result = lookup.lookup(49.0, 8.0, 120.0, 32, null)
            assertEquals("Town (District)", result.cityName)
            assertEquals("Town", result.cityPlaceName)
            assertEquals("District", result.cityDistrictName)
            assertEquals(result.cityName, lookup.lookupCityContext(49.0, 8.0).cityName)
        }
    }

    @Test
    fun adminPolygon_formatsAdminLevel9WithAdminLevel6Qualifier() {
        val dbFile = createLookupDb("city-admin-polygon-prefers-level8.sqlite")
        populateCoreSchema(dbFile)
        seedCityBoundary(
            dbFile = dbFile,
            rowId = 3L,
            adminLevel = 6,
            name = "Enzkreis",
            minLon = 8.6625509,
            minLat = 48.850934,
            maxLon = 8.7425509,
            maxLat = 48.930934,
            ring = rectangleRing(
                minLon = 8.6625509,
                minLat = 48.850934,
                maxLon = 8.7425509,
                maxLat = 48.930934,
            ),
        )
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

            assertEquals("Pforzheim - Buechenbronn (Enzkreis)", result.cityName)
            assertEquals("Pforzheim - Buechenbronn", result.cityPlaceName)
            assertEquals("Enzkreis", result.cityDistrictName)
            assertNull(result.insideCity)
            assertEquals("settlement:missing:unknown", result.citySource)
        }
    }

    @Test
    fun adminPolygon_usesAdminLevel9WhenNoAdminLevel8Exists() {
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

            assertEquals("Kullenmühle", result.cityName)
            assertEquals("Kullenmühle", result.cityPlaceName)
            assertNull(result.cityDistrictName)
            assertNull(result.insideCity)
            assertEquals("settlement:missing:unknown", result.citySource)
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
            assertEquals("Pforzheim", result.cityPlaceName)
            assertNull(result.cityDistrictName)
            assertNull(result.insideCity)
            assertEquals("settlement:missing:unknown", result.citySource)
        }
    }

    @Test
    fun adminPolygon_formatsAdminLevel8WithAdminLevel6Qualifier() {
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

            assertEquals("Ispringen (Enzkreis)", result.cityName)
            assertEquals("Ispringen", result.cityPlaceName)
            assertEquals("Enzkreis", result.cityDistrictName)
            assertNull(result.insideCity)
            assertEquals("settlement:missing:unknown", result.citySource)
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
            assertNull(result.insideCity)
            assertEquals("settlement:missing:unknown", result.citySource)
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
            assertNull(result.insideCity)
            assertEquals("settlement:missing:unknown", result.citySource)
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
            assertNull(result.insideCity)
            assertEquals("settlement:missing:unknown", result.citySource)
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
            assertEquals("settlement:missing:unknown", result.citySource)
        }
    }

    private fun createLookupDb(fileName: String): File {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val dir = File(context.cacheDir, "city-context-tests").also { it.mkdirs() }
        return File(dir, fileName).also { if (it.exists()) it.delete() }
    }

    private fun spatialLookup(file: File) = V3SpeedLimitLookup(file.path,
        databaseOverride = NativeRuntimeSqlDatabase(file.path, false))

    private fun addSpatialAreaSchema(file: File) {
        SQLiteDatabase.openDatabase(file.path, null, SQLiteDatabase.OPEN_READWRITE).use { db ->
            db.execSQL("DROP TABLE areas")
            db.execSQL("""CREATE TABLE areas(row_id INTEGER PRIMARY KEY,area_id TEXT UNIQUE,geometry_type TEXT,
                name TEXT,place TEXT,boundary TEXT,admin_level TEXT,min_lon REAL,min_lat REAL,max_lon REAL,max_lat REAL,
                residential TEXT,points_json TEXT)""")
            db.execSQL("CREATE INDEX idx_areas_place_admin ON areas(place,admin_level,boundary)")
            tryCreateRtreeTable(db, "CREATE VIRTUAL TABLE areas_rtree USING rtree(row_id,min_lon,max_lon,min_lat,max_lat)")
            if (!tableExists(db, "areas_rtree")) {
                // Framework SQLite omits Rtree on some Android versions. The
                // native adapter still executes the exact production SQL over
                // this equivalent bounds fixture; the full packed acceptance
                // test additionally covers the real native Rtree and VFS.
                db.execSQL("CREATE TABLE areas_rtree(row_id INTEGER PRIMARY KEY,min_lon REAL,max_lon REAL,min_lat REAL,max_lat REAL)")
            }
            db.execSQL("""CREATE TRIGGER area_insert AFTER INSERT ON areas BEGIN
                INSERT INTO areas_rtree VALUES(new.row_id,new.min_lon,new.max_lon,new.min_lat,new.max_lat); END""")
            db.execSQL("""CREATE TRIGGER area_delete AFTER DELETE ON areas BEGIN
                DELETE FROM areas_rtree WHERE row_id=old.row_id; END""")
        }
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
