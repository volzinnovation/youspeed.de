package de.youspeed.android.alpha

import android.database.sqlite.SQLiteDatabase
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class UpcomingSpeedLimitReaderInstrumentedTest {
    @Test fun optionalRealBadenWuerttembergProbe() {
        val directory=InstrumentationRegistry.getArguments().getString("upcoming_probe_dir")
        org.junit.Assume.assumeTrue("Optional verified real bundle probe",directory!=null)
        val root=File(requireNotNull(directory))
        val cases=JSONObject(File(root,"cases.json").readText()).getJSONArray("cases")
        val measured=org.json.JSONArray()
        assertTrue(cases.length()>=5)
        SQLiteDatabase.openDatabase(File(root,"probe.sqlite").path,null,SQLiteDatabase.OPEN_READONLY).use { db ->
            val reader=UpcomingSpeedLimitReader(db)
            for(index in 0 until cases.length()) {
                val c=cases.getJSONObject(index)
                val memberships=c.getJSONArray("relationGroupIDs").let { a -> (0 until a.length()).map { a.getLong(it) }.toSet() }
                fun lookup()=reader.read(c.getDouble("lat"),c.getDouble("lon"),c.getString("wayID"),c.getInt("direction"),true,1.0,c.getDouble("headingDeg"),1.0,memberships, c.optDouble("drivingSpeedKmh", c.optDouble("speedKmh", Double.NaN)))
                lookup() // Warm the bounded connection caches as on successive real fixes.
                val attempts=org.json.JSONArray()
                var accepted: UpcomingSpeedLimitSnapshot? = null
                repeat(3) {
                    if (accepted == null) {
                        val began=System.nanoTime()
                        val result=lookup()
                        attempts.put(JSONObject().put("wallTimeMs",(System.nanoTime()-began)/1e6)
                            .put("returnedSnapshot",result!=null))
                        accepted=result
                    }
                }
                val result=requireNotNull(accepted) { "${c.getString("id")}: $attempts" }
                assertTrue(result.topologyAvailable)
                val target=result.candidates.firstOrNull { it.signID==c.getString("expectedSignID") }
                assertNotNull("Physical target from real BW data: ${c.getString("id")}",target)
                assertEquals(c.getInt("expectedSpeedKmh"),target!!.speedKmh)
                assertEquals(c.getString("expectedOriginWayID"),target.originWayID)
                assertEquals(c.getDouble("expectedDistanceM"),target.distanceM,0.25)
                measured.put(JSONObject().put("id",c.getString("id")).put("signID",target.signID)
                    .put("originWayID",target.originWayID).put("speedKmh",target.speedKmh).put("distanceM",target.distanceM).put("attempts",attempts)
                    .put("queryTimeMs",result.queryTimeMs).put("lookaheadDistanceM",result.lookaheadDistanceM).put("reason",result.reason).put("pathSegments",result.path.size))
            }
        }
        File(root,"android-results.json").writeText(JSONObject().put("format","youspeed.upcoming.bw-probe.android.v1")
            .put("device",android.os.Build.MODEL).put("versionName",BuildConfig.VERSION_NAME).put("versionCode",BuildConfig.VERSION_CODE)
            .put("cases",measured).toString(2))
    }
    private fun database(): SQLiteDatabase = SQLiteDatabase.create(null).apply {
        execSQL("CREATE TABLE traffic_sign_capability(key TEXT PRIMARY KEY,value TEXT)")
        execSQL("INSERT INTO traffic_sign_capability VALUES('version','1'),('road_snapshot_sha256','${"a".repeat(64)}')")
        execSQL("CREATE TABLE way_geom(way_id INTEGER PRIMARY KEY,points_json TEXT)")
        execSQL("INSERT INTO way_geom VALUES(1,'[[0,0],[0,0.01]]')")
        execSQL("CREATE TABLE traffic_sign_runtime(sign_id TEXT PRIMARY KEY,source_id TEXT,snapshot_sha256 TEXT,kind TEXT,parameter_status TEXT,numeric_value REAL,sign_code TEXT,unit TEXT)")
        execSQL("CREATE TABLE traffic_sign_association(sign_id TEXT PRIMARY KEY,status TEXT,way_id INTEGER,direction INTEGER,station_chainage_m REAL)")
        execSQL("CREATE INDEX station ON traffic_sign_association(way_id,direction,status)")
        execSQL("CREATE TABLE traffic_sign_way_rule(rule_id TEXT PRIMARY KEY,sign_id TEXT,way_id INTEGER,direction INTEGER,start_chainage_m REAL,end_chainage_m REAL,station_chainage_m REAL,speed_kmh REAL,association_status TEXT,lane_scope TEXT)")
        execSQL("CREATE INDEX rules ON traffic_sign_way_rule(way_id,direction,start_chainage_m)")
        execSQL("CREATE TABLE way_continuity_group(continuity_group_id INTEGER PRIMARY KEY,continuity_kind TEXT)")
        execSQL("CREATE TABLE way_continuity_membership(way_id INTEGER,continuity_group_id INTEGER,continuity_kind TEXT)")
        execSQL("INSERT INTO way_continuity_group VALUES(10,'route_relation_connected')")
        execSQL("INSERT INTO way_continuity_membership VALUES(1,10,'route_relation_connected'),(2,10,'route_relation_connected')")
    }
    private fun SQLiteDatabase.sign(id: String, station: Double, speed: Int = 70, way: Int = 1, direction: Int = 1) {
        execSQL("INSERT INTO traffic_sign_runtime VALUES(?,'source','snapshot','speed_limit','parsed_source_value',?,'numeric','km/h')",arrayOf(id,speed))
        execSQL("INSERT INTO traffic_sign_association VALUES(?,'accepted',?,?,?)",arrayOf(id,way,direction,station))
        execSQL("INSERT INTO traffic_sign_way_rule VALUES(?,?,?,?,?,?,?,?,'accepted','all')",arrayOf("rule-$id",id,way,direction,if(direction>0) station else 0,if(direction>0) 1100 else station,station,speed))
    }
    private fun read(db: SQLiteDatabase, direction: Int = 1) = UpcomingSpeedLimitReader(db).read(0.0,0.001,"1",direction,true,5.0,if(direction>0)90.0 else 270.0,5.0,setOf(10))

    @Test fun thirtySecondHorizonsReadBeyondThreeHundredMetresAndExcludeJustOutside() {
        for ((speed, distance) in listOf(50.0 to 400.0, 100.0 to 800.0, 130.0 to 1050.0)) {
            database().use { db ->
                db.execSQL("UPDATE way_geom SET points_json='[[0,0],[0,0.02]]'")
                db.sign("far", distance, 50)
                db.execSQL("UPDATE traffic_sign_way_rule SET end_chainage_m=2200")
                val reader = UpcomingSpeedLimitReader(db)
                fun lookup(observed: Double?) = reader.read(0.0,0.0,"1",1,true,1.0,90.0,1.0,setOf(10),observed)
                lookup(speed) // Warm Android's initial SQLite/JIT work before asserting the bounded read.
                assertTrue(requireNotNull(lookup(null)).candidates.isEmpty())
                val target = requireNotNull(lookup(speed))
                assertEquals(UpcomingSpeedLimitHorizon.distanceM(speed),target.lookaheadDistanceM,0.0)
                assertEquals(distance,target.candidates.single().distanceM,1e-9)
                val boundary = target.lookaheadDistanceM
                db.execSQL("UPDATE traffic_sign_association SET station_chainage_m=?",arrayOf(boundary))
                db.execSQL("UPDATE traffic_sign_way_rule SET station_chainage_m=?,start_chainage_m=?",arrayOf(boundary,boundary))
                assertEquals(boundary,requireNotNull(lookup(speed)).candidates.single().distanceM,0.0)
                db.execSQL("UPDATE traffic_sign_association SET station_chainage_m=?",arrayOf(boundary+0.01))
                db.execSQL("UPDATE traffic_sign_way_rule SET station_chainage_m=?,start_chainage_m=?",arrayOf(boundary+0.01,boundary+0.01))
                assertTrue(requireNotNull(lookup(speed)).candidates.isEmpty())
                fun reverse()=reader.read(0.0,0.02,"1",-1,true,1.0,270.0,1.0,setOf(10),speed)
                val reverseChainage=requireNotNull(reverse()).chainageM
                val reverseStation=reverseChainage-boundary
                db.execSQL("UPDATE traffic_sign_association SET direction=-1,station_chainage_m=?",arrayOf(reverseStation))
                db.execSQL("UPDATE traffic_sign_way_rule SET direction=-1,station_chainage_m=?,start_chainage_m=0,end_chainage_m=?",arrayOf(reverseStation,reverseStation))
                assertEquals(boundary,requireNotNull(reverse()).candidates.single().distanceM,1e-9)
                db.execSQL("UPDATE traffic_sign_association SET station_chainage_m=?",arrayOf(reverseStation-0.01))
                db.execSQL("UPDATE traffic_sign_way_rule SET station_chainage_m=?,end_chainage_m=?",arrayOf(reverseStation-0.01,reverseStation-0.01))
                assertTrue(requireNotNull(reverse()).candidates.isEmpty())
            }
        }
    }

    @Test fun longerCrossWayReverseApproachRemainsConsumedAfterPassageAndJitter() {
        database().use { db ->
            val length = 600.4526038806173 // 0.0054 degrees on the shared 6371000 m sphere.
            db.execSQL("UPDATE way_geom SET points_json='[[0,0],[0,0.0054]]' WHERE way_id=1")
            db.execSQL("INSERT INTO way_geom VALUES(2,'[[0,0.0108],[0,0.0054]]')")
            db.sign("far-reverse",length-400.0,50,way=2,direction=-1)
            topology(db)
            db.execSQL("INSERT INTO upcoming_path_segment VALUES(1,1,1,0,?,?, 'allowed',1,2),(2,2,-1,0,?,?,'allowed',2,3)",arrayOf(length,length,length,length))
            db.execSQL("INSERT INTO upcoming_path_successor VALUES(1,'certified',2,'source_node_unbranched_unmerged_v1',2)")
            val reader = UpcomingSpeedLimitReader(db)
            fun lookup(lon: Double, way: String, direction: Int, speed: Double?) = reader.read(0.0,lon,way,direction,true,1.0,90.0,1.0,setOf(10),speed)
            lookup(0.0,"1",1,130.0)
            assertTrue(requireNotNull(lookup(0.0,"1",1,null)).candidates.isEmpty())
            val approach = requireNotNull(lookup(0.0,"1",1,130.0))
            val target = approach.candidates.single()
            assertEquals(1000.4526038806173,target.distanceM,1e-6)
            assertEquals(-1,target.direction)
            val tracker = UpcomingSpeedLimitTracker()
            tracker.consume(approach,"bundle",1000,1000)
            assertEquals("far-reverse",tracker.presentation(100,false,true,1000)?.signID)
            tracker.consume(requireNotNull(lookup(0.00901,"2",-1,130.0)),"bundle",2000,2000)
            tracker.consume(requireNotNull(lookup(0.00899,"2",-1,130.0)),"bundle",3000,3000)
            assertNull(tracker.presentation(100,false,true,3000))
        }
    }

    @Test fun workCapRemainsBoundedAndCannotExposeATargetBeyondItsProof() {
        database().use { db ->
            db.execSQL("UPDATE way_geom SET points_json='[[0,0],[0,0.02]]'")
            topology(db)
            for (id in 1..34) {
                db.execSQL("INSERT INTO upcoming_path_segment VALUES(?,1,1,?,?,10,'allowed',?,?)",arrayOf(id,(id-1)*10,id*10,id,id+1))
                if (id<34) db.execSQL("INSERT INTO upcoming_path_successor VALUES(?,'certified',?,'source_node_unbranched_unmerged_v1',?)",arrayOf(id,id+1,id+1))
            }
            db.sign("proved",250.0,50)
            db.execSQL("UPDATE traffic_sign_way_rule SET end_chainage_m=2200")
            val reader=UpcomingSpeedLimitReader(db)
            fun lookup()=reader.read(0.0,0.0,"1",1,true,1.0,90.0,1.0,setOf(10),100.0)
            repeat(2) { lookup() }
            val result=requireNotNull(lookup())
            assertEquals(32,result.path.size)
            assertEquals("work_cap",result.reason)
            assertEquals(listOf("proved"),result.candidates.map { it.signID }.distinct())
            db.execSQL("UPDATE traffic_sign_association SET station_chainage_m=325")
            db.execSQL("UPDATE traffic_sign_way_rule SET station_chainage_m=325,start_chainage_m=325")
            assertTrue(requireNotNull(lookup()).candidates.isEmpty())
        }
    }

    private fun topology(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE upcoming_path_capability(key TEXT PRIMARY KEY,value TEXT)")
        for ((key,value) in mapOf("version" to "1","completeness" to "complete","road_snapshot_sha256" to "a".repeat(64),"geometry_convention" to "source_vertices_spherical_6371000m_v1","source_node_incidence" to "complete_pbf_highway_v1","restrictions" to "all_involved_ways_stop_v1","motorcar_profile" to "existing_runtime_direction_v1")) db.execSQL("INSERT INTO upcoming_path_capability VALUES(?,?)",arrayOf(key,value))
        db.execSQL("CREATE TABLE upcoming_path_segment(segment_id INTEGER PRIMARY KEY,way_id INTEGER,direction INTEGER,start_chainage_m REAL,end_chainage_m REAL,length_m REAL,permission_status TEXT,start_node_id INTEGER,end_node_id INTEGER)")
        db.execSQL("CREATE INDEX upcoming_path_way ON upcoming_path_segment(way_id,direction,start_chainage_m)")
        db.execSQL("CREATE TABLE upcoming_path_successor(from_segment_id INTEGER PRIMARY KEY,status TEXT,to_segment_id INTEGER,proof TEXT,via_node_id INTEGER)")
    }

    @Test fun physicalStationProvidesAlongWayDistanceAndLegacyCapabilityIsOptional() {
        database().use { db ->
            db.sign("speed",250.0)
            val result = requireNotNull(read(db))
            assertFalse(result.topologyAvailable)
            assertEquals(250.0 - 111.1949266, result.candidates.single().distanceM,0.001)
            db.execSQL("UPDATE traffic_sign_capability SET value='2' WHERE key='version'")
            assertNull(read(db))
        }
    }
    @Test fun conditionalStationCannotBecomeAnUnconditionalPreview() {
        database().use { db ->
            db.sign("speed",250.0)
            assertEquals("speed",requireNotNull(read(db)).candidates.single().signID)
            // A conditional limit is never flattened to a numeric lookahead
            // target: active hours still need separate verified applicability.
            db.execSQL("UPDATE traffic_sign_way_rule SET lane_scope='conditional'")
            assertTrue(requireNotNull(read(db)).candidates.isEmpty())
        }
    }
    private fun SQLiteDatabase.townEntry() {
        execSQL("ALTER TABLE traffic_sign_way_rule ADD COLUMN inside_city INTEGER")
        execSQL("INSERT INTO traffic_sign_runtime VALUES('town','osm-settlement','snapshot','settlement_boundary','not_applicable',NULL,'DE:310',NULL)")
        execSQL("INSERT INTO traffic_sign_association VALUES('town','accepted',1,1,250)")
        execSQL("INSERT INTO traffic_sign_way_rule VALUES('town-rule','town',1,1,250,1100,250,NULL,'accepted','all',1)")
    }
    @Test fun directedTownEntryPreviewsFiftyAndExitOrUnresolvedLocalityDoesNot() {
        for (direction in listOf(1,-1)) database().use { db ->
            db.townEntry()
            db.execSQL("UPDATE traffic_sign_association SET direction=?",arrayOf(direction))
            db.execSQL("UPDATE traffic_sign_way_rule SET direction=?,start_chainage_m=?,end_chainage_m=?",arrayOf(direction,if(direction>0)250 else 0,if(direction>0)1100 else 250))
            val lon=if(direction>0)0.001 else 0.003
            val reader=UpcomingSpeedLimitReader(db)
            fun lookup(d: Int)=reader.read(0.0,lon,"1",d,true,1.0,if(d>0)90.0 else 270.0,1.0,setOf(10))
            lookup(direction)
            val result=requireNotNull(lookup(direction))
            assertEquals(50,result.candidates.single().speedKmh)
            assertEquals("osm-settlement",result.candidates.single().sourceID)
            assertEquals(direction*(250-result.chainageM),result.candidates.single().distanceM,1e-6)
            assertTrue(requireNotNull(lookup(-direction)).candidates.isEmpty())
        }
        for (invalid in listOf("UPDATE traffic_sign_runtime SET sign_code='DE:311'","UPDATE traffic_sign_way_rule SET inside_city=NULL","UPDATE traffic_sign_way_rule SET lane_scope='unresolved'","UPDATE traffic_sign_association SET status='ambiguous'")) database().use { db ->
            db.townEntry(); db.execSQL(invalid)
            assertTrue(invalid,requireNotNull(read(db)).candidates.isEmpty())
        }
    }
    @Test fun townEntryKeepsFreshExplicitLimitAndCannotHideItsConditionalScope() {
        for (scope in listOf("all","conditional","unresolved")) database().use { db ->
            db.townEntry()
            db.execSQL("UPDATE traffic_sign_way_rule SET end_chainage_m=250 WHERE sign_id='town'")
            db.execSQL("INSERT INTO traffic_sign_runtime VALUES('posted','source','snapshot','speed_limit','parsed_source_value',30,'DE:274-30','km/h')")
            db.execSQL("INSERT INTO traffic_sign_association VALUES('posted','accepted',1,1,250)")
            db.execSQL("INSERT INTO traffic_sign_way_rule VALUES('posted-rule','posted',1,1,250,1100,250,30,'accepted',?,1)",arrayOf(scope))
            val candidates=requireNotNull(read(db)).candidates
            if(scope=="all") { assertEquals("posted",candidates.single().signID); assertEquals(30,candidates.single().speedKmh) }
            else assertTrue(scope,candidates.isEmpty())
        }
    }
    @Test fun conditionalOsmContextBlocksImpliedTownFiftyWithoutSuppressingGovernmentBoundary() {
        database().use { db ->
            db.townEntry()
            db.execSQL("CREATE TABLE road_speed_rule_set(way_id INTEGER PRIMARY KEY,rules_json TEXT)")
            db.execSQL("INSERT INTO road_speed_rule_set VALUES(1,'{}')")
            assertTrue(requireNotNull(read(db)).candidates.isEmpty())
            db.execSQL("UPDATE traffic_sign_runtime SET source_id='mobidata-bw-vzk'")
            assertEquals(50,requireNotNull(read(db)).candidates.single().speedKmh)
            assertTrue(requireNotNull(UpcomingSpeedLimitReader(db,false).read(0.0,0.001,"1",1,true,1.0,90.0,1.0,setOf(10))).candidates.isEmpty())
        }
    }
    @Test fun townEntryAtCertifiedSplitUsesPhysicalOriginAndReverseChildLocality() {
        database().use { db ->
            val length=222.3898532891175
            db.execSQL("UPDATE way_geom SET points_json='[[0,0],[0,0.002]]' WHERE way_id=1")
            db.execSQL("INSERT INTO way_geom VALUES(2,'[[0,0.004],[0,0.002]]')")
            db.townEntry(); topology(db)
            db.execSQL("INSERT INTO upcoming_path_segment VALUES(1,1,1,0,?,?, 'allowed',1,2),(2,2,-1,0,?,?,'allowed',2,3)",arrayOf(length,length,length,length))
            db.execSQL("INSERT INTO upcoming_path_successor VALUES(1,'certified',2,'source_node_unbranched_unmerged_v1',2)")
            db.execSQL("UPDATE traffic_sign_association SET station_chainage_m=?",arrayOf(length))
            db.execSQL("UPDATE traffic_sign_way_rule SET station_chainage_m=?,start_chainage_m=?,end_chainage_m=?",arrayOf(length,length,length))
            db.execSQL("INSERT INTO traffic_sign_way_rule VALUES('town-child','town',2,-1,0,?,?,NULL,'accepted','all',1)",arrayOf(length,length))
            val reader=UpcomingSpeedLimitReader(db)
            fun lookup(lon: Double,way: String,direction: Int)=reader.read(0.0,lon,way,direction,true,1.0,90.0,1.0,setOf(10))
            lookup(0.001,"1",1)
            val result=requireNotNull(lookup(0.001,"1",1))
            assertEquals("town",result.candidates.single().signID)
            assertEquals(50,result.candidates.single().speedKmh)
            assertEquals("1",result.candidates.single().originWayID)
            assertEquals(length-result.chainageM,result.candidates.single().distanceM,1e-6)
            assertTrue(requireNotNull(lookup(0.0021,"2",-1)).candidates.isEmpty())
        }
    }
    @Test fun originAssociationNotChildEntryAndAllStatusEventsBlockBeyond() {
        database().use { db ->
            db.sign("speed",250.0)
            db.execSQL("INSERT INTO traffic_sign_runtime VALUES('barrier','source','snapshot','speed_limit','dynamic_unverified',50,'dynamic','km/h')")
            db.execSQL("INSERT INTO traffic_sign_association VALUES('barrier','ambiguous',1,1,200)")
            assertTrue(requireNotNull(read(db)).candidates.isEmpty())
            db.execSQL("DELETE FROM traffic_sign_association WHERE sign_id='barrier'")
            db.execSQL("UPDATE traffic_sign_association SET way_id=2 WHERE sign_id='speed'")
            assertTrue(requireNotNull(read(db)).candidates.isEmpty())
        }
    }
    @Test fun ambiguousPostStationAndZeroLengthRulesCannotPromiseHandoff() {
        database().use { db ->
            db.sign("speed",250.0)
            db.execSQL("INSERT INTO traffic_sign_way_rule SELECT 'overlap',sign_id,way_id,direction,start_chainage_m,end_chainage_m,station_chainage_m,30,association_status,lane_scope FROM traffic_sign_way_rule")
            assertTrue(requireNotNull(read(db)).candidates.isEmpty())
            db.execSQL("DELETE FROM traffic_sign_way_rule WHERE rule_id='overlap'")
            db.execSQL("UPDATE traffic_sign_way_rule SET end_chainage_m=start_chainage_m")
            assertTrue(requireNotNull(read(db)).candidates.isEmpty())
        }
    }
    @Test fun certifiedSourceTopologyCrossesReversedWayAndStopHidesOnlyBeyondJunction() {
        database().use { db ->
            val length = 222.3898532891175
            db.execSQL("UPDATE way_geom SET points_json='[[0,0],[0,0.002]]' WHERE way_id=1")
            db.execSQL("INSERT INTO way_geom VALUES(2,'[[0,0.004],[0,0.002]]')")
            db.sign("next",length-100,way=2,direction=-1)
            db.execSQL("CREATE TABLE upcoming_path_capability(key TEXT PRIMARY KEY,value TEXT)")
            for ((key,value) in mapOf("version" to "1","completeness" to "complete","road_snapshot_sha256" to "a".repeat(64),"geometry_convention" to "source_vertices_spherical_6371000m_v1","source_node_incidence" to "complete_pbf_highway_v1","restrictions" to "all_involved_ways_stop_v1","motorcar_profile" to "existing_runtime_direction_v1")) db.execSQL("INSERT INTO upcoming_path_capability VALUES(?,?)",arrayOf(key,value))
            db.execSQL("CREATE TABLE upcoming_path_segment(segment_id INTEGER PRIMARY KEY,way_id INTEGER,direction INTEGER,start_chainage_m REAL,end_chainage_m REAL,length_m REAL,permission_status TEXT,start_node_id INTEGER,end_node_id INTEGER)")
            db.execSQL("INSERT INTO upcoming_path_segment VALUES(1,1,1,0,?,?, 'allowed',1,2),(2,2,-1,0,?,?,'allowed',2,3)",arrayOf(length,length,length,length))
            db.execSQL("CREATE TABLE upcoming_path_successor(from_segment_id INTEGER PRIMARY KEY,status TEXT,to_segment_id INTEGER,proof TEXT,via_node_id INTEGER)")
            db.execSQL("INSERT INTO upcoming_path_successor VALUES(1,'certified',2,'source_node_unbranched_unmerged_v1',2)")
            val result = requireNotNull(read(db))
            assertTrue(result.topologyAvailable)
            assertEquals(-1,result.candidates.single().direction)
            assertEquals(211.1949266,result.candidates.single().distanceM,0.001)
            db.execSQL("UPDATE upcoming_path_successor SET status='stop'")
            assertTrue(requireNotNull(read(db)).candidates.isEmpty())
            db.execSQL("UPDATE upcoming_path_successor SET status='certified'")
            db.sign("endpoint",length,30)
            db.execSQL("UPDATE traffic_sign_way_rule SET start_chainage_m=?,end_chainage_m=? WHERE sign_id='endpoint'",arrayOf(length,length))
            assertTrue("A zero-length origin needs an actual continuing offer",requireNotNull(read(db)).candidates.none { it.signID=="endpoint" })
            db.execSQL("INSERT INTO traffic_sign_way_rule VALUES('child','endpoint',2,-1,?,?,?,30,'accepted','all')",arrayOf(length-100,length,length))
            val atEndpoint=requireNotNull(read(db))
            assertEquals("endpoint",atEndpoint.candidates.first().signID)
            val tracker=UpcomingSpeedLimitTracker()
            tracker.consume(atEndpoint,"bundle",1000,1000)
            val child=requireNotNull(UpcomingSpeedLimitReader(db).read(0.0,0.00201,"2",-1,true,1.0,90.0,1.0,setOf(10)))
            tracker.consume(child,"bundle",2000,2000)
            val jitter=requireNotNull(UpcomingSpeedLimitReader(db).read(0.0,0.00199,"1",1,true,1.0,90.0,1.0,setOf(10)))
            tracker.consume(jitter,"bundle",3000,3000)
            assertNotEquals("Endpoint passage cannot reappear after split jitter","endpoint",tracker.presentation(100,false,true,3000)?.signID)
        }
    }
}
