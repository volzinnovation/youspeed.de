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
    fun below50GermanLimitMarksLookupInsideCity() {
        val dbFile = createFixtureDb("low-speed-city-${UUID.randomUUID()}.sqlite") { db ->
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

                INSERT INTO ways VALUES (4101, 'secondary', 'Low Speed Test Way', NULL, '30', NULL, NULL, 90.0, 'main', NULL, 13.0000, 52.0000, 13.0040, 52.0000);
                INSERT INTO ways_rtree VALUES (4101, 13.0000, 13.0040, 52.0000, 52.0000);
                INSERT INTO way_geom VALUES (4101, '[[52.0000,13.0000],[52.0000,13.0040]]');
                """.trimIndent(),
            )
        }

        V3SpeedLimitLookup(dbFile.absolutePath, countryCode = "DEU").use { lookup ->
            val result = lookup.lookup(
                lat = 52.0000,
                lon = 13.0020,
                radiusM = 120.0,
                maxCandidates = 32,
                headingDeg = 90.0,
                speedKmh = 30.0,
                horizontalAccuracyM = 5.0,
                gpsSignalBars = 4,
            )

            assertEquals("4101", result.wayId)
            assertEquals(30, result.speedLimitKmh)
            assertEquals(true, result.insideCity)
            assertEquals("de_speed_limit_lt_50", result.citySource)
        }
    }

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

    @Test
    fun blocksDirectMotorwayEntryUntilRampTransition() {
        val dbFile = createFixtureDb("motorway-${UUID.randomUUID()}.sqlite") { db ->
            createMotorwayCorridorFixtureDb(db)
        }

        V3SpeedLimitLookup(dbFile.absolutePath).use { lookup ->
            val result = lookup.lookup(
                lat = 52.06003,
                lon = 13.00430,
                radiusM = 80.0,
                maxCandidates = 32,
                headingDeg = 45.0,
                speedKmh = 35.0,
                horizontalAccuracyM = 5.0,
                gpsSignalBars = 4,
                matchContext = WayMatchContext(
                    preferredWayId = "9301",
                    preferredHighway = "primary",
                    preferredEndpointProximityM = 0.0,
                    recentWayIds = listOf("9301"),
                    recentStreetRefs = listOf("B", "462"),
                ),
            )

            assertEquals("9302", result.wayId)
            val directMotorway = result.candidateTraces.first { it.wayId == "9303" }
            assertEquals(false, directMotorway.corridorSelectable)
        }
    }

    @Test
    fun activatesMotorwayModeAfterRepeatedEntryProgress() {
        val dbFile = createFixtureDb("motorway-mode-${UUID.randomUUID()}.sqlite") { db ->
            createMotorwayCorridorFixtureDb(db)
        }

        V3SpeedLimitLookup(dbFile.absolutePath).use { lookup ->
            val result = lookup.lookup(
                lat = 52.06010,
                lon = 13.00595,
                radiusM = 80.0,
                maxCandidates = 32,
                headingDeg = 90.0,
                speedKmh = 70.0,
                horizontalAccuracyM = 5.0,
                gpsSignalBars = 4,
                matchContext = WayMatchContext(
                    preferredWayId = "9302",
                    preferredHighway = "motorway_link",
                    preferredEndpointProximityM = 0.0,
                    recentWayIds = listOf("9302", "9301"),
                    recentStreetRefs = listOf("A", "5", "B", "462"),
                    approachCorridorState = CorridorMatchState(
                        kind = "motorway",
                        corridorId = 1,
                        sideNodeKey = "motorway-west",
                        depthM = 24.0,
                        spanM = 411.0,
                        depthNodes = 1,
                        spanNodes = 3,
                    ),
                    approachCorridorFixCount = 2,
                    approachCorridorStartDepthM = 12.0,
                    approachCorridorStartDepthNodes = 0,
                ),
            )

            assertEquals("9303", result.wayId)
            assertEquals("motorway", result.activeCorridorState?.kind)
        }
    }

    @Test
    fun exposesVerifiedRouteRelationContinuityForSelectedWay() {
        val dbFile = createFixtureDb("relation-continuity-${UUID.randomUUID()}.sqlite") { db ->
            execSql(
                db,
                """
                CREATE TABLE ways (
                  way_id INTEGER PRIMARY KEY, highway TEXT, street_name TEXT, ref TEXT, maxspeed TEXT,
                  maxspeed_type TEXT, source_maxspeed TEXT, approx_heading_deg REAL, service TEXT, tunnel TEXT,
                  min_lon REAL NOT NULL, min_lat REAL NOT NULL, max_lon REAL NOT NULL, max_lat REAL NOT NULL
                );
                CREATE TABLE ways_rtree (
                  way_id INTEGER NOT NULL, min_lon REAL NOT NULL, max_lon REAL NOT NULL,
                  min_lat REAL NOT NULL, max_lat REAL NOT NULL
                );
                CREATE TABLE way_geom (way_id INTEGER PRIMARY KEY, points_json TEXT NOT NULL);
                CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE way_continuity_group (
                  continuity_group_id INTEGER PRIMARY KEY, continuity_kind TEXT NOT NULL, source_relation_id INTEGER
                );
                CREATE TABLE way_continuity_membership (
                  way_id INTEGER NOT NULL, continuity_group_id INTEGER NOT NULL, continuity_kind TEXT NOT NULL,
                  PRIMARY KEY (way_id, continuity_group_id)
                );

                INSERT INTO metadata VALUES ('way_continuity_mode', 'route_relation_connected');
                INSERT INTO ways VALUES (4401, 'primary', 'Relation Way', 'B 10', '70', NULL, NULL, 90.0, 'main', NULL, 13.0, 52.0, 13.004, 52.0);
                INSERT INTO ways_rtree VALUES (4401, 13.0, 13.004, 52.0, 52.0);
                INSERT INTO way_geom VALUES (4401, '[[52.0,13.0],[52.0,13.004]]');
                INSERT INTO way_continuity_group VALUES (77, 'route_relation_connected', 123456);
                INSERT INTO way_continuity_membership VALUES (4401, 77, 'route_relation_connected');
                """.trimIndent(),
            )
        }

        V3SpeedLimitLookup(dbFile.absolutePath).use { lookup ->
            val result = lookup.lookup(
                lat = 52.0,
                lon = 13.002,
                radiusM = 100.0,
                maxCandidates = 16,
                headingDeg = 90.0,
                speedKmh = 50.0,
                horizontalAccuracyM = 5.0,
                gpsSignalBars = 4,
            )

            assertEquals("4401", result.wayId)
            assertEquals(setOf(77L), result.routeRelationGroupIds)
            assertEquals(setOf(123456L), result.sourceRelationIds)
            assertTrue(result.routeRelationContinuityAvailable)
            assertEquals(TrafficSignTravelDirection.FORWARD, result.travelDirection)
            assertEquals(false, result.matchedWayStable)

            val stabilized = lookup.lookup(
                lat = 52.0,
                lon = 13.0021,
                radiusM = 100.0,
                maxCandidates = 16,
                headingDeg = 90.0,
                speedKmh = 50.0,
                horizontalAccuracyM = 5.0,
                gpsSignalBars = 4,
                matchContext = WayMatchContext(preferredWayId = "4401", matchedFixCount = 1),
            )
            assertTrue(stabilized.matchedWayStable)
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

    private fun createMotorwayCorridorFixtureDb(db: SQLiteDatabase) {
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

            INSERT INTO ways VALUES (9301, 'primary', 'Surface Approach', 'B 462', '70', NULL, NULL, 90.0, 'main', NULL, 13.0000, 52.06000, 13.0040, 52.06000);
            INSERT INTO ways_rtree VALUES (9301, 13.0000, 13.0040, 52.06000, 52.06000);
            INSERT INTO way_geom VALUES (9301, '[[52.06000,13.0000],[52.06000,13.0040]]');

            INSERT INTO ways VALUES (9302, 'motorway_link', 'Entry Ramp', 'A 5', '80', NULL, NULL, 45.0, 'main', NULL, 13.0040, 52.06000, 13.0050, 52.06010);
            INSERT INTO ways_rtree VALUES (9302, 13.0040, 13.0050, 52.06000, 52.06010);
            INSERT INTO way_geom VALUES (9302, '[[52.06000,13.0040],[52.06010,13.0050]]');

            INSERT INTO ways VALUES (9303, 'motorway', 'Autobahn Mainline', 'A 5', '130', NULL, NULL, 90.0, 'main', NULL, 13.0040, 52.06010, 13.0100, 52.06010);
            INSERT INTO ways_rtree VALUES (9303, 13.0040, 13.0100, 52.06010, 52.06010);
            INSERT INTO way_geom VALUES (9303, '[[52.06010,13.0040],[52.06010,13.0100]]');

            INSERT INTO ways VALUES (9304, 'motorway_link', 'Exit Ramp', 'A 5', '80', NULL, NULL, 135.0, 'main', NULL, 13.0064, 52.06000, 13.0074, 52.06010);
            INSERT INTO ways_rtree VALUES (9304, 13.0064, 13.0074, 52.06000, 52.06010);
            INSERT INTO way_geom VALUES (9304, '[[52.06010,13.0064],[52.06000,13.0074]]');

            INSERT INTO ways VALUES (9305, 'secondary', 'Exit Surface Road', 'K 5', '70', NULL, NULL, 90.0, 'main', NULL, 13.0074, 52.06000, 13.0110, 52.06000);
            INSERT INTO ways_rtree VALUES (9305, 13.0074, 13.0110, 52.06000, 52.06000);
            INSERT INTO way_geom VALUES (9305, '[[52.06000,13.0074],[52.06000,13.0110]]');

            INSERT INTO corridor_progress VALUES ('motorway', 1, 'motorway-west', 9303, 0.0, 411.0, 1, 3, 411.0, 3);
            INSERT INTO corridor_progress VALUES ('motorway', 1, 'motorway-east', 9303, 411.0, 0.0, 3, 1, 411.0, 3);

            INSERT INTO way_links VALUES (9301, 9302, 0, 'surface-entry');
            INSERT INTO way_links VALUES (9302, 9301, 0, 'surface-entry');
            INSERT INTO way_links VALUES (9301, 9303, 0, 'motorway-west');
            INSERT INTO way_links VALUES (9303, 9301, 0, 'motorway-west');
            INSERT INTO way_links VALUES (9302, 9303, 1, 'motorway-west');
            INSERT INTO way_links VALUES (9303, 9302, 1, 'motorway-west');
            INSERT INTO way_links VALUES (9303, 9304, 1, 'motorway-east');
            INSERT INTO way_links VALUES (9304, 9303, 1, 'motorway-east');
            INSERT INTO way_links VALUES (9303, 9305, 0, 'motorway-east');
            INSERT INTO way_links VALUES (9305, 9303, 0, 'motorway-east');
            INSERT INTO way_links VALUES (9304, 9305, 0, 'surface-exit');
            INSERT INTO way_links VALUES (9305, 9304, 0, 'surface-exit');
            """.trimIndent(),
        )
    }
}
