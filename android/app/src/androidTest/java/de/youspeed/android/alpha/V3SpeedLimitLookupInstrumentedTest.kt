package de.youspeed.android.alpha

import android.database.sqlite.SQLiteDatabase
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class V3SpeedLimitLookupInstrumentedTest {
    @Test
    fun prefersSameRefContinuationWhenPreviousWayDropsOutOfRange() {
        val dbFile = createFixtureDb("continuity-${UUID.randomUUID()}.sqlite") { db ->
            execSql(
                db,
                """
                CREATE TABLE ways (
                  way_id INTEGER PRIMARY KEY,
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
                );
                CREATE TABLE ways_rtree (
                  way_id INTEGER NOT NULL,
                  min_lon REAL NOT NULL,
                  max_lon REAL NOT NULL,
                  min_lat REAL NOT NULL,
                  max_lat REAL NOT NULL
                );
                CREATE TABLE way_geom (
                  way_id INTEGER PRIMARY KEY,
                  points_json TEXT NOT NULL
                );
                CREATE TABLE way_links (
                  way_id INTEGER NOT NULL,
                  linked_way_id INTEGER NOT NULL,
                  shared_ref INTEGER NOT NULL DEFAULT 0,
                  shared_node_key TEXT NOT NULL,
                  PRIMARY KEY(way_id, linked_way_id, shared_node_key)
                );

                INSERT INTO ways VALUES (5001, 'primary', 'B10 West', 'B10', '70', NULL, NULL, 90.0, 'main', NULL, 13.0000, 52.0000, 13.0030, 52.0000);
                INSERT INTO ways_rtree VALUES (5001, 13.0000, 13.0030, 52.0000, 52.0000);
                INSERT INTO way_geom VALUES (5001, '[[52.0000,13.0000],[52.0000,13.0030]]');

                INSERT INTO ways VALUES (5002, 'primary', 'B10 East', 'B10', '70', NULL, NULL, 90.0, 'main', NULL, 13.0030, 52.0000, 13.0060, 52.0000);
                INSERT INTO ways_rtree VALUES (5002, 13.0030, 13.0060, 52.0000, 52.0000);
                INSERT INTO way_geom VALUES (5002, '[[52.0000,13.0030],[52.0000,13.0060]]');

                INSERT INTO ways VALUES (5003, 'residential', 'Side Road', NULL, '30', NULL, NULL, 90.0, 'main', NULL, 13.0040, 52.00012, 13.0056, 52.00012);
                INSERT INTO ways_rtree VALUES (5003, 13.0040, 13.0056, 52.00012, 52.00012);
                INSERT INTO way_geom VALUES (5003, '[[52.00012,13.0040],[52.00012,13.0056]]');

                INSERT INTO way_links VALUES (5001, 5002, 1, 'b10-east');
                INSERT INTO way_links VALUES (5002, 5001, 1, 'b10-east');
                """.trimIndent(),
            )
        }

        V3SpeedLimitLookup(dbFile.absolutePath).use { lookup ->
            val result = lookup.lookup(
                lat = 52.0000,
                lon = 13.0048,
                radiusM = 40.0,
                maxCandidates = 32,
                headingDeg = 90.0,
                speedKmh = 45.0,
                horizontalAccuracyM = 5.0,
                gpsSignalBars = 4,
                matchContext = WayMatchContext(
                    preferredWayId = "5001",
                    recentWayIds = listOf("5001"),
                    recentStreetRefs = listOf("B10"),
                ),
            )

            assertEquals("5002", result.wayId)
            assertEquals("B10", result.streetRef)
            assertEquals(70, result.speedLimitKmh)
        }
    }

    @Test
    fun keepsTunnelContinuityWhileTunnelModeIsActive() {
        val dbFile = createFixtureDb("tunnel-${UUID.randomUUID()}.sqlite") { db ->
            execSql(
                db,
                """
                CREATE TABLE ways (
                  way_id INTEGER PRIMARY KEY,
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
                );
                CREATE TABLE ways_rtree (
                  way_id INTEGER NOT NULL,
                  min_lon REAL NOT NULL,
                  max_lon REAL NOT NULL,
                  min_lat REAL NOT NULL,
                  max_lat REAL NOT NULL
                );
                CREATE TABLE way_geom (
                  way_id INTEGER PRIMARY KEY,
                  points_json TEXT NOT NULL
                );
                CREATE TABLE way_links (
                  way_id INTEGER NOT NULL,
                  linked_way_id INTEGER NOT NULL,
                  shared_ref INTEGER NOT NULL DEFAULT 0,
                  shared_node_key TEXT NOT NULL,
                  PRIMARY KEY(way_id, linked_way_id, shared_node_key)
                );
                CREATE TABLE corridor_progress (
                  corridor_kind TEXT NOT NULL,
                  corridor_id INTEGER NOT NULL,
                  side_node_key TEXT NOT NULL,
                  way_id INTEGER NOT NULL,
                  start_depth_m REAL NOT NULL,
                  end_depth_m REAL NOT NULL,
                  start_depth_nodes INTEGER NOT NULL,
                  end_depth_nodes INTEGER NOT NULL,
                  corridor_span_m REAL NOT NULL,
                  corridor_span_nodes INTEGER NOT NULL,
                  PRIMARY KEY(corridor_kind, corridor_id, side_node_key, way_id)
                );

                INSERT INTO ways VALUES (8101, 'primary', 'Surface Approach', 'B 10', '70', NULL, NULL, 90.0, 'main', NULL, 13.0000, 52.02000, 13.0010, 52.02000);
                INSERT INTO ways_rtree VALUES (8101, 13.0000, 13.0010, 52.02000, 52.02000);
                INSERT INTO way_geom VALUES (8101, '[[52.02000,13.0000],[52.02000,13.0010]]');

                INSERT INTO ways VALUES (8102, 'primary', 'Tunnel Mainline', 'B 10', '70', NULL, NULL, 90.0, 'main', 'yes', 13.0010, 52.02000, 13.0040, 52.02000);
                INSERT INTO ways_rtree VALUES (8102, 13.0010, 13.0040, 52.02000, 52.02000);
                INSERT INTO way_geom VALUES (8102, '[[52.02000,13.0010],[52.02000,13.0040]]');

                INSERT INTO ways VALUES (8103, 'primary', 'Surface Bypass', 'B 10', '70', NULL, NULL, 90.0, 'main', NULL, 13.0010, 52.02008, 13.0040, 52.02008);
                INSERT INTO ways_rtree VALUES (8103, 13.0010, 13.0040, 52.02008, 52.02008);
                INSERT INTO way_geom VALUES (8103, '[[52.02008,13.0010],[52.02008,13.0040]]');

                INSERT INTO way_links VALUES (8101, 8102, 1, 'tunnel-west');
                INSERT INTO way_links VALUES (8102, 8101, 1, 'tunnel-west');
                INSERT INTO way_links VALUES (8101, 8103, 1, 'surface-branch');
                INSERT INTO way_links VALUES (8103, 8101, 1, 'surface-branch');

                INSERT INTO corridor_progress VALUES ('tunnel', 1, 'tunnel-west', 8102, 0.0, 205.5, 1, 5, 205.5, 5);
                INSERT INTO corridor_progress VALUES ('tunnel', 1, 'tunnel-east', 8102, 205.5, 0.0, 5, 1, 205.5, 5);
                """.trimIndent(),
            )
        }

        V3SpeedLimitLookup(dbFile.absolutePath).use { lookup ->
            val result = lookup.lookup(
                lat = 52.02007,
                lon = 13.00260,
                radiusM = 80.0,
                maxCandidates = 32,
                headingDeg = 90.0,
                speedKmh = 32.0,
                horizontalAccuracyM = 10.0,
                gpsSignalBars = 1,
                matchContext = WayMatchContext(
                    preferredWayId = "8102",
                    preferredHighway = "primary",
                    preferredEndpointProximityM = 80.0,
                    recentWayIds = listOf("8102", "8101"),
                    recentFixes = listOf(WayMatchRecentFix(lat = 52.02007, lon = 13.00220)),
                    recentStreetRefs = listOf("B", "10"),
                    recentTunnelCandidateWayIds = setOf("8102"),
                    recentTunnelCandidateRefs = setOf("B", "10"),
                    recentTunnelApproachWayIds = setOf("8102"),
                    recentTunnelApproachRefs = setOf("B", "10"),
                    tunnelApproachFixCount = 3,
                    tunnelApproachBaselineAccuracyM = 5.0,
                    tunnelApproachBaselineSignalBars = 4,
                    matchedFixCount = 5,
                    hadRecentGpsSignalLoss = true,
                    isInTunnelMode = true,
                    activeCorridorState = CorridorMatchState(
                        kind = "tunnel",
                        corridorId = 1,
                        sideNodeKey = "tunnel-west",
                        depthM = 90.0,
                        spanM = 205.5,
                        depthNodes = 2,
                        spanNodes = 5,
                    ),
                ),
            )

            assertEquals("8102", result.wayId)
            assertTrue(result.isTunnelSegment)
            assertEquals("tunnel", result.activeCorridorState?.kind)
        }
    }

    private fun createFixtureDb(
        name: String,
        populate: (SQLiteDatabase) -> Unit,
    ): File {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val file = File(context.cacheDir, name)
        if (file.exists()) {
            file.delete()
        }
        val db = SQLiteDatabase.openOrCreateDatabase(file, null)
        try {
            populate(db)
        } finally {
            db.close()
        }
        return file
    }

    private fun execSql(
        db: SQLiteDatabase,
        sql: String,
    ) {
        sql.split(";")
            .map(String::trim)
            .filter(String::isNotEmpty)
            .forEach(db::execSQL)
    }
}
