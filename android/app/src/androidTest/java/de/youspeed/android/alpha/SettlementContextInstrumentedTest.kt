package de.youspeed.android.alpha

import android.database.sqlite.SQLiteDatabase
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.util.UUID
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class SettlementContextInstrumentedTest {
    private val geometry = "[[49.0,7.999],[49.0,8.001]]"

    private fun fixture(maxspeed: String? = null, type: String? = null, source: String? = null,
                        capability: String? = null, segments: List<Array<Any?>> = emptyList(),
                        residentialRing: String? = null, highway: String = "secondary"): File {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val file = File(context.cacheDir, "settlement-${UUID.randomUUID()}.sqlite")
        SQLiteDatabase.openOrCreateDatabase(file, null).use { db ->
            db.execSQL("CREATE TABLE metadata (key TEXT PRIMARY KEY,value TEXT)")
            db.execSQL("INSERT INTO metadata VALUES ('schema_version','1')")
            db.execSQL("CREATE TABLE ways (way_id INTEGER PRIMARY KEY,highway TEXT,street_name TEXT,ref TEXT,maxspeed TEXT,maxspeed_type TEXT,source_maxspeed TEXT,approx_heading_deg REAL,service TEXT,tunnel TEXT,min_lon REAL,min_lat REAL,max_lon REAL,max_lat REAL)")
            db.execSQL("INSERT INTO ways VALUES (1,?,'Test road',NULL,?,?,?,90,NULL,NULL,7.999,49,8.001,49)", arrayOf(highway,maxspeed,type,source))
            db.execSQL("CREATE TABLE ways_rtree (way_id INTEGER,min_lon REAL,max_lon REAL,min_lat REAL,max_lat REAL)")
            db.execSQL("INSERT INTO ways_rtree VALUES (1,7.999,8.001,49,49)")
            db.execSQL("CREATE TABLE way_geom (way_id INTEGER PRIMARY KEY,points_json TEXT)")
            db.execSQL("INSERT INTO way_geom VALUES (1,?)", arrayOf(geometry))
            db.execSQL("CREATE TABLE areas (area_id TEXT PRIMARY KEY,geometry_type TEXT,name TEXT,place TEXT,boundary TEXT,admin_level TEXT,residential TEXT,points_json TEXT,min_lon REAL,min_lat REAL,max_lon REAL,max_lat REAL)")
            db.execSQL("INSERT INTO areas VALUES ('admin','Polygon','Municipality',NULL,'administrative','8',NULL,'[[7.99,48.99],[8.01,48.99],[8.01,49.01],[7.99,49.01],[7.99,48.99]]',7.99,48.99,8.01,49.01)")
            if (residentialRing != null) db.execSQL("INSERT INTO areas VALUES ('residential','Polygon',NULL,NULL,NULL,NULL,'landuse',?,7.99,48.99,8.01,49.01)", arrayOf(residentialRing))
            if (capability != null) {
                db.execSQL("INSERT INTO metadata VALUES ('settlement_context_version',?)", arrayOf(capability))
                db.execSQL("CREATE TABLE settlement_segment (segment_id INTEGER PRIMARY KEY,way_id INTEGER,segment_index INTEGER,direction INTEGER,inside_city INTEGER,source TEXT,confidence TEXT,evidence_json TEXT,points_json TEXT)")
                segments.forEachIndexed { index, row ->
                    db.execSQL("INSERT INTO settlement_segment VALUES (?,1,?,?,?,?,?,'[]',?)", arrayOf(index + 1,index,row[0],row[1],row[2],row[3],row[4]))
                }
            }
        }
        return file
    }

    private fun row(inside: Int?, direction: Int = 0, geometry: String = this.geometry, confidence: String = "high") =
        arrayOf<Any?>(direction, inside, "zone_traffic", confidence, geometry)

    private fun lookup(file: File, heading: Double? = 90.0, accuracy: Double? = 5.0,
                       model: LookupMatchingModel = LookupMatchingModel.CORRIDOR_HMM): SpeedLookupResult =
        V3SpeedLimitLookup(file.path, countryCode = "DEU", matchingModel = model).use {
            it.lookup(49.0, 8.0, 100.0, 16, heading, speedKmh = 30.0, horizontalAccuracyM = 5.0,
                headingAccuracyDeg = accuracy)
        }

    @Test fun legacyRural30AndUrban70IgnoreAdministrativeContainmentAndNumericHeuristics() {
        val rural = lookup(fixture("30", source = "DE:rural"))
        assertEquals(30, rural.speedLimitKmh)
        assertEquals(false, rural.insideCity)
        assertEquals("settlement:source_maxspeed:high", rural.citySource)
        assertEquals("Municipality", rural.cityName)
        val urban = lookup(fixture("70", type = "DE:urban"))
        assertEquals(70, urban.speedLimitKmh)
        assertEquals(true, urban.insideCity)
        assertEquals("settlement:maxspeed_type:high", urban.citySource)
    }

    @Test fun missingContextAndAdministrativeNameDoNotProduceRuralDefault() {
        val result = lookup(fixture())
        assertNull(result.insideCity)
        assertNull(result.speedLimitKmh)
        assertEquals("Municipality", result.cityName)
        assertEquals("settlement:missing:unknown", result.citySource)
    }

    @Test fun nullableSegmentContextOverridesLegacyTagsAndDoesNotBecomeFalse() {
        val result = lookup(fixture(type = "DE:rural", capability = "1", segments = listOf(row(null, confidence = "unknown"))))
        assertNull(result.insideCity)
        assertNull(result.speedLimitKmh)
        assertEquals("settlement:missing:unknown", result.citySource)
        val missing = lookup(fixture(type = "DE:urban", capability = "1"))
        assertNull(missing.insideCity)
        assertNull(missing.speedLimitKmh)
    }

    @Test fun directionalSegmentsUseGpsHeadingAndUnknownHeadingConflicts() {
        val file = fixture(capability = "1", segments = listOf(row(1, 1), row(0, -1)))
        assertEquals(true, lookup(file).insideCity)
        assertEquals(50, lookup(file).speedLimitKmh)
        assertEquals(false, lookup(file, 270.0).insideCity)
        assertEquals(100, lookup(file, 270.0).speedLimitKmh)
        assertNull(lookup(file, null).insideCity)
        assertNull(lookup(file, accuracy = null).insideCity)
        assertEquals("settlement:conflict:unknown", lookup(file, null).citySource)
    }

    @Test fun sharedBoundaryTiePreservesUnknown() {
        val result = lookup(fixture(capability = "1", segments = listOf(
            row(0, geometry = "[[49.0,7.999],[49.0,8.0]]"),
            row(1, geometry = "[[49.0,8.0],[49.0,8.001]]"),
        )))
        assertNull(result.insideCity)
        assertNull(result.speedLimitKmh)
        assertEquals("settlement:conflict:unknown", result.citySource)
    }

    @Test fun repeatedPolygonVertexDoesNotMakeBoundingBoxInside() {
        val result = lookup(fixture(residentialRing = "[[7.999,48.999],[7.999,48.999],[8.001,48.999],[7.999,49.001],[7.999,48.999]]"))
        // Query lies on the triangle's diagonal: use a ring entirely south of it instead.
        val outside = lookup(fixture(residentialRing = "[[7.999,48.999],[7.999,48.999],[8.001,48.999],[8.001,48.9995],[7.999,48.999]]"))
        assertNull(outside.insideCity)
        assertNull(outside.speedLimitKmh)
        assertEquals("settlement:missing:unknown", outside.citySource)
        assertEquals(true, result.insideCity)
        assertEquals("settlement:landuse:low", result.citySource)
        assertNull(result.speedLimitKmh)
    }

    @Test fun malformedRowsAndNullCapabilityFailClosed() {
        for (value in listOf<Any?>(2, 4294967297L, "invalid", null)) {
            val file = fixture(type = "DE:urban", capability = "1", segments = listOf(row(1)))
            SQLiteDatabase.openDatabase(file.path, null, SQLiteDatabase.OPEN_READWRITE).use {
                it.execSQL("UPDATE settlement_segment SET inside_city=?", arrayOf(value))
            }
            assertNull(lookup(file).insideCity)
            assertNull(lookup(file).speedLimitKmh)
        }
        for (points in listOf("[[49,7.999],[49,8.001,0]]", "[[49,7.999],[99,8.001]]", "[[49,7.999],[49,\"8.001\"]]")) {
            assertNull(lookup(fixture(capability = "1", segments = listOf(row(1, geometry = points)))).insideCity)
        }
        val nullVersion = fixture(type = "DE:urban", capability = "1", segments = listOf(row(1)))
        SQLiteDatabase.openDatabase(nullVersion.path, null, SQLiteDatabase.OPEN_READWRITE).use {
            it.execSQL("UPDATE metadata SET value=NULL WHERE key='settlement_context_version'")
        }
        assertNull(lookup(nullVersion).insideCity)
        assertTrue(runCatching { AndroidBundleDeltaDatabase().validateSettlementCapability(nullVersion) }.isFailure)
    }

    private val matchingModels = listOf(
        LookupMatchingModel.CORRIDOR_HMM,
        LookupMatchingModel.SIMPLE_SPEED_REF_URBAN_RELEASE_NARROW_WINDOW_HEURISTIC,
    )

    @Test fun residentialAndServiceDefault50WithoutChangingUnknownOrWeakCityContext() {
        for (model in matchingModels) for (highway in listOf("residential", "service", " ReSiDeNtIaL ")) {
            for (capability in listOf(null, "1")) {
                val unknown = lookup(fixture(highway = highway, capability = capability,
                    segments = listOf(row(null, confidence = "unknown"))), model = model)
                assertEquals("$model $highway", 50, unknown.speedLimitKmh)
                assertEquals(DerivedSpeedSource.HIGHWAY_CLASS, unknown.speedSource)
                assertNull(unknown.insideCity)
                assertEquals("settlement:missing:unknown", unknown.citySource)
            }
            val weak = lookup(fixture(highway = highway, capability = "1",
                segments = listOf(row(1, confidence = "low"))), model = model)
            assertEquals(50, weak.speedLimitKmh)
            assertEquals(DerivedSpeedSource.HIGHWAY_CLASS, weak.speedSource)
            assertEquals(true, weak.insideCity)
            assertEquals("settlement:zone_traffic:low", weak.citySource)
        }
    }

    @Test fun residentialAndServicePreserveExplicitLimitsAndUnlimited() {
        for (model in matchingModels) for (highway in listOf("residential", "service")) {
            for (inside in listOf(null, 0, 1)) {
                val segment = row(inside, confidence = if (inside == null) "unknown" else "high")
                val explicit = lookup(fixture("30", highway = highway, capability = "1",
                    segments = listOf(segment)), model = model)
                assertEquals(30, explicit.speedLimitKmh)
                assertEquals(DerivedSpeedSource.EXPLICIT_TAG, explicit.speedSource)
                val unlimited = lookup(fixture("none", highway = highway, capability = "1",
                    segments = listOf(segment)), model = model)
                assertNull(unlimited.speedLimitKmh)
                assertTrue(unlimited.isUnlimitedSpeedLimit)
                assertEquals(DerivedSpeedSource.EXPLICIT_UNLIMITED_TAG, unlimited.speedSource)
            }
        }
    }

    @Test fun highConfidenceSettlementTakesPrecedenceOverResidentialAndServiceDefault() {
        for (model in matchingModels) for (highway in listOf("residential", "service")) {
            val outside = lookup(fixture(highway = highway, capability = "1",
                segments = listOf(row(0))), model = model)
            assertEquals(100, outside.speedLimitKmh)
            assertEquals(false, outside.insideCity)
            assertEquals("settlement:zone_traffic:high", outside.citySource)
            val inside = lookup(fixture(highway = highway, capability = "1",
                segments = listOf(row(1))), model = model)
            assertEquals(50, inside.speedLimitKmh)
            assertEquals(true, inside.insideCity)
        }
    }

    @Test fun missingSettlementDoesNotRestoreSuppressedInheritedSpeedTags() {
        for (model in matchingModels) for (highway in listOf("residential", "service")) {
            for (tag in listOf("DE:urban", "DE:rural")) {
                val unknown = lookup(fixture(type = tag, highway = highway, capability = "1",
                    segments = listOf(row(null, confidence = "unknown"))), model = model)
                assertNull(unknown.speedLimitKmh)
                assertNull(unknown.insideCity)
                assertEquals(DerivedSpeedSource.INHERITED_TAG, unknown.speedSource)
                val conflict = lookup(fixture(source = tag, highway = highway, capability = "1",
                    segments = listOf(row(0), row(1))), model = model)
                assertNull(conflict.speedLimitKmh)
                assertNull(conflict.insideCity)
                assertEquals("settlement:conflict:unknown", conflict.citySource)
            }
        }
    }

    @Test fun residentialAndServiceDefaultDoesNotChangeOtherRoadClasses() {
        for (model in matchingModels) {
            for (highway in listOf("primary", "secondary", "tertiary", "unclassified", "road")) {
                val result = lookup(fixture(highway = highway, capability = "1",
                    segments = listOf(row(null, confidence = "unknown"))), model = model)
                assertNull("$model $highway", result.speedLimitKmh)
                assertNull(result.insideCity)
            }
            assertEquals(10, lookup(fixture(highway = "living_street"), model = model).speedLimitKmh)
            val motorway = lookup(fixture(highway = "motorway"), model = model)
            assertNull(motorway.speedLimitKmh)
            assertFalse(motorway.isUnlimitedSpeedLimit)
        }
    }

    @Test fun installRejectsUnsupportedAndMalformedSettlementCapability() {
        val validator = AndroidBundleDeltaDatabase()
        val supported = fixture(capability = "1", segments = listOf(row(1)))
        validator.validateSettlementCapability(supported)
        assertTrue(runCatching { validator.validateSettlementCapability(fixture(capability = "2")) }.isFailure)
        assertTrue(runCatching { validator.validateSettlementCapability(fixture(capability = "1", segments = listOf(row(2)))) }.isFailure)
        assertNull(lookup(fixture(type = "DE:urban", capability = "2")).insideCity)
    }
}
