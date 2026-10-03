package de.youspeed.android.alpha

import android.database.sqlite.SQLiteDatabase
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class RouteLookupEvidenceInstrumentedTest {
    @Test
    fun routeEvidenceRetainsFullStatelessMatchAndDistanceSemantics() = withFixture { file ->
        for (country in listOf("DEU", "FRA")) {
            for (model in LookupMatchingModel.entries) {
                V3SpeedLimitLookup(file.absolutePath, countryCode = country, matchingModel = model).use { lookup ->
                    // Includes accuracy-capped admission, empty-cap full fallback,
                    // walking/uncertain headings and a coverage gap.
                    for ((lat, lon, speed, headingAccuracy) in listOf(
                        listOf(0.0, 0.0, 60.0, 5.0),
                        listOf(0.0008, 0.0, 60.0, 5.0),
                        listOf(0.0, 0.0, 0.2, 80.0),
                        listOf(0.02, 0.02, 60.0, 5.0),
                    )) {
                        val probe = lookup.lookupRouteEvidence(lat, lon, 120.0, 32, 90.0,
                            speedKmh = speed, horizontalAccuracyM = 5.0, gpsSignalBars = 4,
                            headingAccuracyDeg = headingAccuracy)
                        val full = lookup.lookup(lat, lon, 120.0, 32, 90.0,
                            speedKmh = speed, horizontalAccuracyM = 5.0, gpsSignalBars = 4,
                            headingAccuracyDeg = headingAccuracy)
                        val label = "$country $model at $lat,$lon speed=$speed"
                        assertEquals("$label way evidence", full.wayId != null, probe.hasWayMatch)
                        assertEquals("$label speed evidence",
                            full.speedLimitKmh != null || full.isUnlimitedSpeedLimit, probe.hasSpeedMatch)
                        assertEquals("$label nearest road", full.nearestCandidateDistanceM, probe.nearestCandidateDistanceM)
                        assertEquals("$label nearest speed", full.nearestSpeedCandidateDistanceM, probe.nearestSpeedCandidateDistanceM)
                    }
                }
            }
        }
    }

    @Test
    fun densityUsesCommonRadiusIndependentOfAccuracyAndMatcherNarrowWindow() = withFixture { file ->
        for (model in listOf(LookupMatchingModel.CONNECTED_BASELINE,
            LookupMatchingModel.SIMPLE_SPEED_REF_URBAN_RELEASE_NARROW_WINDOW_HEURISTIC)) {
            V3SpeedLimitLookup(file.absolutePath, countryCode = "DEU", matchingModel = model).use { lookup ->
                for (accuracy in listOf(null, 1.0, 5.0, 50.0)) {
                    val probe = lookup.lookupRouteEvidence(0.0, 0.0, 120.0, 32, 90.0,
                        speedKmh = 60.0, horizontalAccuracyM = accuracy, gpsSignalBars = 4,
                        headingAccuracyDeg = 5.0)
                    // Six roads are geometrically nearby: numeric, inherited, default,
                    // unlimited, tunnel and unknown-speed roads all count as features.
                    // Way 2006 has an overlapping bbox but lies 178 m away and is excluded.
                    assertEquals("$model accuracy=$accuracy", 6, probe.candidateCount)
                    assertEquals("$model speed-bearing density accuracy=$accuracy", 5, probe.speedCandidateCount)
                }
                val narrow = lookup.lookupRouteEvidence(0.0, 0.0, 15.0, 32, 90.0,
                    speedKmh = 60.0, horizontalAccuracyM = 5.0, headingAccuracyDeg = 5.0)
                assertEquals(5, narrow.candidateCount)
                assertEquals(4, narrow.speedCandidateCount)
            }
        }
    }

    @Test
    fun densityExcludesMissingMalformedAndSinglePointGeometry() = withFixture(populate = { db ->
        SqliteFixtureSupport.execSql(db, """
            INSERT INTO ways VALUES (2008, 'primary', 'Missing geometry', NULL, '30', NULL, NULL, 90, NULL, NULL, -0.001, -0.001, 0.001, 0.001);
            INSERT INTO ways VALUES (2009, 'primary', 'Malformed geometry', NULL, '30', NULL, NULL, 90, NULL, NULL, -0.001, -0.001, 0.001, 0.001);
            INSERT INTO ways VALUES (2010, 'primary', 'Single point', NULL, '30', NULL, NULL, 90, NULL, NULL, -0.001, -0.001, 0.001, 0.001);
            INSERT INTO ways VALUES (2011, 'primary', 'Invalid coordinates', NULL, '30', NULL, NULL, 90, NULL, NULL, -0.001, -0.001, 0.001, 0.001);
            INSERT INTO ways_rtree SELECT way_id, min_lon, max_lon, min_lat, max_lat FROM ways WHERE way_id >= 2008;
            INSERT INTO way_geom VALUES (2009, '[[0,0],["invalid",0]]');
            INSERT INTO way_geom VALUES (2010, '[[0,0]]');
            INSERT INTO way_geom VALUES (2011, '[[91,0],[91,0.001]]');
        """.trimIndent())
    }) { file ->
        V3SpeedLimitLookup(file.absolutePath, countryCode = "DEU",
            matchingModel = LookupMatchingModel.CONNECTED_BASELINE).use { lookup ->
            val probe = lookup.lookupRouteEvidence(0.0, 0.0, 120.0, 32, 90.0,
                speedKmh = 60.0, horizontalAccuracyM = 5.0, headingAccuracyDeg = 5.0)
            assertEquals(6, probe.candidateCount)
            assertEquals(5, probe.speedCandidateCount)
            val full = lookup.lookup(0.0, 0.0, 120.0, 32, 90.0,
                speedKmh = 60.0, horizontalAccuracyM = 5.0, headingAccuracyDeg = 5.0)
            assertEquals(full.wayId != null, probe.hasWayMatch)
            assertEquals(full.nearestCandidateDistanceM, probe.nearestCandidateDistanceM)
        }
    }

    @Test
    fun probesSkipAdministrativeRingsAndMotorwayBranchOutput() = withFixture(populate = { db ->
        db.execSQL("DELETE FROM ways WHERE way_id != 2003")
        db.execSQL("DELETE FROM ways_rtree WHERE way_id != 2003")
        SqliteFixtureSupport.execSql(db, """
            CREATE TABLE areas (
              area_id TEXT, geometry_type TEXT, name TEXT, place TEXT, boundary TEXT, admin_level TEXT,
              min_lon REAL, min_lat REAL, max_lon REAL, max_lat REAL, residential TEXT, points_json TEXT
            );
            INSERT INTO areas VALUES ('residential', 'polygon', NULL, NULL, NULL, NULL,
              -0.01, -0.01, 0.01, 0.01, 'yes',
              '[[-0.01,-0.01],[0.01,-0.01],[0.01,0.01],[-0.01,0.01],[-0.01,-0.01]]');
            CREATE TABLE city_boundary (
              row_id INTEGER PRIMARY KEY, osm_type TEXT, osm_id INTEGER, admin_level INTEGER,
              name TEXT, min_lon REAL, min_lat REAL, max_lon REAL, max_lat REAL
            );
            CREATE TABLE city_ring (
              boundary_row_id INTEGER, ring_index INTEGER, outer_index INTEGER,
              is_hole INTEGER, points_json TEXT
            );
            INSERT INTO city_boundary VALUES (1, 'relation', 1, 8, 'Fixture Town', -0.01, -0.01, 0.01, 0.01);
            INSERT INTO city_ring VALUES (1, 0, 0, 0,
              '[[-0.01,-0.01],[0.01,-0.01],[0.01,0.01],[-0.01,0.01],[-0.01,-0.01]]');
        """.trimIndent())
    }) { file ->
        V3SpeedLimitLookup(file.absolutePath, countryCode = "DEU",
            matchingModel = LookupMatchingModel.CONNECTED_BASELINE).use { lookup ->
            val probe = lookup.lookupRouteEvidence(-0.00003, 0.0, 120.0, 32, 90.0,
                speedKmh = 100.0, horizontalAccuracyM = 5.0, headingAccuracyDeg = 5.0)
            val probeStats = lookup.cacheStats()
            assertTrue(probe.hasWayMatch)
            assertTrue(probe.hasSpeedMatch)
            assertEquals(0L, probeStats.rings.decodes)
            assertEquals(3, probeStats.queryShapes)

            val full = lookup.lookup(-0.00003, 0.0, 120.0, 32, 90.0,
                speedKmh = 100.0, horizontalAccuracyM = 5.0, headingAccuracyDeg = 5.0)
            assertEquals("2003", full.wayId)
            assertTrue(full.isUnlimitedSpeedLimit)
            assertEquals("Fixture Town", full.cityName)
            assertEquals(2L, lookup.cacheStats().rings.decodes)
            assertEquals(4, lookup.cacheStats().queryShapes)
            assertTrue(full.applicabilityGeometry != null)
        }
    }

    @Test
    fun probesKeepSettlementSuppressionForInheritedGermanSpeeds() = withFixture(populate = { db ->
        db.execSQL("DELETE FROM ways WHERE way_id != 2005")
        db.execSQL("DELETE FROM ways_rtree WHERE way_id != 2005")
        SqliteFixtureSupport.execSql(db, """
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO metadata VALUES ('settlement_context_version', '1');
            CREATE TABLE settlement_segment (
              segment_id INTEGER PRIMARY KEY, way_id INTEGER, segment_index INTEGER,
              direction INTEGER, inside_city INTEGER, source TEXT, confidence TEXT, points_json TEXT
            );
            INSERT INTO settlement_segment VALUES (1, 2005, 0, 0, NULL, 'conflict', 'unknown',
              '[[0.0003,-0.001],[0.0003,0.001]]');
        """.trimIndent())
    }) { file ->
        V3SpeedLimitLookup(file.absolutePath, countryCode = "DEU",
            matchingModel = LookupMatchingModel.CONNECTED_BASELINE).use { lookup ->
            val probe = lookup.lookupRouteEvidence(0.0003, 0.0, 120.0, 32, 90.0,
                speedKmh = 60.0, horizontalAccuracyM = 5.0, headingAccuracyDeg = 5.0)
            assertTrue(probe.hasWayMatch)
            assertFalse(probe.hasSpeedMatch)
            // A speed-bearing feature may exist while runtime settlement evidence
            // suppresses that selected way's displayed inherited speed.
            assertEquals(1, probe.candidateCount)
            assertEquals(1, probe.speedCandidateCount)
            val full = lookup.lookup(0.0003, 0.0, 120.0, 32, 90.0,
                speedKmh = 60.0, horizontalAccuracyM = 5.0, headingAccuracyDeg = 5.0)
            assertEquals(null, full.speedLimitKmh)
            assertEquals(full.nearestSpeedCandidateDistanceM, probe.nearestSpeedCandidateDistanceM)
        }
    }

    private fun withFixture(populate: (SQLiteDatabase) -> Unit = {}, block: (File) -> Unit) {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val file = File(context.cacheDir, "route-evidence-${UUID.randomUUID()}.sqlite")
        try {
            SQLiteDatabase.openOrCreateDatabase(file, null).use { db ->
                SqliteFixtureSupport.execSql(db, """
                    CREATE TABLE ways (
                      way_id INTEGER PRIMARY KEY, highway TEXT, street_name TEXT, ref TEXT, maxspeed TEXT,
                      maxspeed_type TEXT, source_maxspeed TEXT, approx_heading_deg REAL, service TEXT, tunnel TEXT,
                      min_lon REAL, min_lat REAL, max_lon REAL, max_lat REAL
                    );
                    CREATE TABLE ways_rtree (
                      way_id INTEGER, min_lon REAL, max_lon REAL, min_lat REAL, max_lat REAL
                    );
                    CREATE TABLE way_geom (way_id INTEGER PRIMARY KEY, points_json TEXT NOT NULL);
                    INSERT INTO ways VALUES (2001, 'secondary', 'Numeric', NULL, '30', NULL, NULL, 90, NULL, NULL, -0.001, 0, 0.001, 0);
                    INSERT INTO ways VALUES (2002, 'residential', 'Default', NULL, NULL, NULL, NULL, 90, NULL, NULL, -0.001, 0.00003, 0.001, 0.00003);
                    INSERT INTO ways VALUES (2003, 'motorway', 'Unlimited', NULL, 'none', NULL, NULL, 90, NULL, NULL, -0.001, -0.00003, 0.001, -0.00003);
                    INSERT INTO ways VALUES (2004, 'primary', 'Tunnel', NULL, '70', NULL, NULL, 90, NULL, 'yes', -0.001, 0.00004, 0.001, 0.00004);
                    INSERT INTO ways VALUES (2005, 'secondary', 'Inherited', NULL, NULL, 'DE:rural', NULL, 90, NULL, NULL, -0.001, 0.0003, 0.001, 0.0003);
                    INSERT INTO ways VALUES (2006, 'primary', 'Distant with overlapping bounds', NULL, '70', NULL, NULL, 90, NULL, NULL, -0.002, -0.002, 0.002, 0.002);
                    INSERT INTO ways VALUES (2007, NULL, 'Unknown speed', NULL, NULL, NULL, NULL, 90, NULL, NULL, -0.001, 0.00005, 0.001, 0.00005);
                    INSERT INTO ways_rtree SELECT way_id, min_lon, max_lon, min_lat, max_lat FROM ways;
                    INSERT INTO way_geom VALUES (2001, '[[0,-0.001],[0,0.001]]');
                    INSERT INTO way_geom VALUES (2002, '[[0.00003,-0.001],[0.00003,0.001]]');
                    INSERT INTO way_geom VALUES (2003, '[[-0.00003,-0.001],[-0.00003,0.001]]');
                    INSERT INTO way_geom VALUES (2004, '[[0.00004,-0.001],[0.00004,0.001]]');
                    INSERT INTO way_geom VALUES (2005, '[[0.0003,-0.001],[0.0003,0.001]]');
                    INSERT INTO way_geom VALUES (2006, '[[0.0016,-0.001],[0.0016,0.001]]');
                    INSERT INTO way_geom VALUES (2007, '[[0.00005,-0.001],[0.00005,0.001]]');
                """.trimIndent())
                populate(db)
            }
            block(file)
        } finally {
            file.delete()
        }
    }
}
