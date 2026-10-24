package de.youspeed.android.alpha

import android.database.sqlite.SQLiteDatabase
import android.os.Build
import android.os.Bundle
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Explicit, stationary replay against the full installed map; never injects system GPS. */
@RunWith(AndroidJUnit4::class)
class InstalledUpcomingSpeedLimitInstrumentedTest {
    @Test fun profileAndValidateFullInstalledLookaheadBundle() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val args = InstrumentationRegistry.getArguments()
        assumeTrue(args.getString("profile_installed_upcoming") == "true")
        val context = instrumentation.targetContext
        val stateFile = File(context.filesDir, "bundle/active_bundle.json")
        val stateText = stateFile.readText()
        val state = JSONObject(stateText)
        assertEquals("2026-10-23-v1.5-lookahead", state.getString("bundle_version"))
        assertEquals("34b31aac1dc5a6abacce959afb8ec44043146f5aa4f1ea488c07cb4a68efe09c", state.getString("db_sha256"))
        val database = File(state.getString("db_path"))
        assertEquals(3099021312L, database.length())
        val modified = database.lastModified()
        val preferences = context.getSharedPreferences("youspeed", 0).all.toMap()
        val cases = JSONObject(File(context.cacheDir, "upcoming-physical-cases.json").readText()).getJSONArray("cases")
        assertTrue(cases.length() >= 5)
        val attempts = JSONArray()
        val correctnessFailures = JSONArray()
        val lifecycle = JSONArray()
        fun membership(c: JSONObject): Set<Long> = c.getJSONArray("relationGroupIDs").let { a -> (0 until a.length()).map { a.getLong(it) }.toSet() }
        fun read(reader: UpcomingSpeedLimitReader, c: JSONObject) = reader.read(c.getDouble("lat"), c.getDouble("lon"),
            c.getString("wayID"), c.getInt("direction"), true, 1.0, c.getDouble("headingDeg"), 1.0, membership(c))
        fun attempt(mode: String, index: Int, round: Int, reader: UpcomingSpeedLimitReader): UpcomingSpeedLimitSnapshot? {
            val c = cases.getJSONObject(index)
            val started = System.nanoTime()
            val result = read(reader, c)
            val wall = (System.nanoTime() - started) / 1e6
            val target = result?.candidates?.firstOrNull { it.signID == c.getString("expectedSignID") }
            val correct = target != null && target.speedKmh == c.getInt("expectedSpeedKmh") &&
                target.originWayID == c.getString("expectedOriginWayID") &&
                kotlin.math.abs(target.distanceM - c.getDouble("expectedDistanceM")) <= 0.25
            val row = JSONObject().put("mode", mode).put("case", c.getString("id")).put("round", round)
                .put("wallMs", wall).put("completed", result != null).put("correct", correct)
                .put("queryTimeMs", result?.queryTimeMs ?: JSONObject.NULL).put("reason", result?.reason ?: "suppressed_or_budget")
                .put("pathSegments", result?.path?.size ?: 0).put("signID", target?.signID ?: JSONObject.NULL)
                .put("speedKmh", target?.speedKmh ?: JSONObject.NULL).put("distanceM", target?.distanceM ?: JSONObject.NULL)
            attempts.put(row)
            if (result != null && !correct) correctnessFailures.put(row)
            return result
        }
        // Every connection is freshly opened. OS page caches are deliberately uncontrolled.
        for (round in 0 until 2) for (index in 0 until cases.length()) {
            val openStarted = System.nanoTime()
            SQLiteDatabase.openDatabase(database.path, null, SQLiteDatabase.OPEN_READONLY).use { db ->
                val reader = UpcomingSpeedLimitReader(db)
                val openMs = (System.nanoTime() - openStarted) / 1e6
                attempt("connection_cold", index, round, reader)
                attempts.getJSONObject(attempts.length() - 1).put("connectionOpenMs", openMs)
            }
        }
        SQLiteDatabase.openDatabase(database.path, null, SQLiteDatabase.OPEN_READONLY).use { db ->
            val reader = UpcomingSpeedLimitReader(db)
            for (round in 0 until 25) for (index in 0 until cases.length()) attempt("warm", index, round, reader)
            for (index in 0 until cases.length()) {
                val c = cases.getJSONObject(index)
                val snapshot = requireNotNull(read(reader, c))
                val target = requireNotNull(snapshot.candidates.firstOrNull { it.signID == c.getString("expectedSignID") })
                val (primary, passedSnapshot) = primaryOfferAfterSign(db, database.path, reader, target)
                assertEquals(target.speedKmh, primary.getInt("speedKmh"))
                assertEquals(target.signID, primary.getString("signID"))
                val tracker = UpcomingSpeedLimitTracker()
                val identity = state.getString("db_sha256")
                tracker.consume(snapshot, identity, 1000, 1000)
                assertEquals(target.signID, tracker.presentation(target.speedKmh + 10, false, true, 1000)?.signID)
                assertFalse("An equal current limit suppresses this sign; a later lower sign may remain", tracker.presentation(target.speedKmh, false, true, 1000)?.signID == target.signID)
                assertNull(tracker.presentation(target.speedKmh + 10, false, false, 1000))
                assertNull(tracker.presentation(target.speedKmh + 10, false, true, 4000))
                tracker.consume(passedSnapshot, identity, 2000, 2000)
                assertFalse(tracker.presentation(target.speedKmh + 10, false, true, 2000)?.signID == target.signID)
                tracker.consume(snapshot, identity, 2100, 2100)
                assertFalse("Passage memory survives backward GPS jitter", tracker.presentation(target.speedKmh + 10, false, true, 2100)?.signID == target.signID)
                val departureTracker = UpcomingSpeedLimitTracker()
                departureTracker.consume(snapshot, identity, 1000, 1000)
                departureTracker.consume(snapshot.copy(wayID = "unrelated", relationGroupIDs = setOf(-1), path = emptyList(), candidates = emptyList()), identity, 1100, 1100)
                assertNull(departureTracker.presentation(target.speedKmh + 10, false, true, 1100))
                lifecycle.put(JSONObject().put("case", c.getString("id")).put("lowerOnly", true).put("reliableContextOnly", true)
                    .put("expiry", true).put("passageAndJitter", true).put("relationDeparture", true)
                    .put("primaryOfferAfterSign", primary)
                    .put("scope", "Production tracker driven by full-bundle approach snapshot and explicit stationary state replay"))
            }
        }
        val production = JSONArray()
        for (index in 0 until minOf(5, cases.length())) {
            val c = cases.getJSONObject(index)
            val openStarted = System.nanoTime()
            V3SpeedLimitLookup(database.path, "DEU", MatcherDebugProfile.M7.lookupModel).use { lookup ->
                val openMs = (System.nanoTime() - openStarted) / 1e6
                for (round in 0 until 26) {
                    val started = System.nanoTime()
                    val result = lookup.lookup(c.getDouble("lat"), c.getDouble("lon"), 120.0, 1200, c.getDouble("headingDeg"),
                        60.0, 1.0, 4, WayMatchContext(preferredWayId = c.getString("wayID"),
                            recentWayIds = listOf(c.getString("wayID")), matchedFixCount = 3), 1.0)
                    val wallMs = (System.nanoTime() - started) / 1e6
                    val target = result.upcomingSpeedLimits?.candidates?.firstOrNull { it.signID == c.getString("expectedSignID") }
                    production.put(JSONObject().put("case", c.getString("id")).put("round", round)
                        .put("mode", if(round == 0) "connection_cold" else "warm").put("connectionOpenMs", openMs)
                        .put("wallMs", wallMs).put("queryTimeMs", result.queryTimeMs).put("lookupStageMs", JSONObject(result.lookupStageMs))
                        .put("wayID", result.wayId).put("expectedWay", c.getString("wayID"))
                        .put("matchedWayStable", result.matchedWayStable).put("previewCompleted", result.upcomingSpeedLimits != null)
                        .put("previewQueryTimeMs", result.upcomingSpeedLimits?.queryTimeMs ?: JSONObject.NULL)
                        .put("correctTarget", target != null && target.speedKmh == c.getInt("expectedSpeedKmh") && kotlin.math.abs(target.distanceM-c.getDouble("expectedDistanceM"))<=0.25))
                }
            }
        }
        val report = JSONObject().put("format", "youspeed.upcoming.full-installed.android.v1")
            .put("scope", "Stationary read-only native-reader and production-matcher replay; no system GPS injection, no real-drive timing, OS caches uncontrolled")
            .put("device", Build.MODEL).put("api", Build.VERSION.SDK_INT).put("package", context.packageName)
            .put("versionCode", BuildConfig.VERSION_CODE).put("versionName", BuildConfig.VERSION_NAME)
            .put("databasePath", database.path).put("databaseBytes", database.length()).put("bundleSHA256", state.getString("db_sha256"))
            .put("attempts", attempts).put("correctnessFailures", correctnessFailures).put("lifecycle", lifecycle).put("productionMatcher", production)
        File(context.cacheDir, "upcoming-physical-results.json").writeText(report.toString(2))
        assertEquals("No completed preview may have an incorrect target", 0, correctnessFailures.length())
        for(index in 0 until cases.length()) assertTrue("Every source case must complete warm", (0 until attempts.length()).any {
            val row=attempts.getJSONObject(it); row.getString("mode")=="warm" && row.getString("case")==cases.getJSONObject(index).getString("id") && row.getBoolean("correct")
        })
        assertEquals(stateText, stateFile.readText())
        assertEquals(modified, database.lastModified())
        assertEquals(preferences, context.getSharedPreferences("youspeed", 0).all)
        instrumentation.sendStatus(0, Bundle().apply { putString("stream", "Full installed bundle: ${attempts.length()} reader attempts, ${production.length()} matcher attempts, ${lifecycle.length()} lifecycle cases; receipt in cache/upcoming-physical-results.json\n") })
    }

    private fun primaryOfferAfterSign(db: SQLiteDatabase, path: String, reader: UpcomingSpeedLimitReader, target: UpcomingSpeedLimitCandidate): Pair<JSONObject, UpcomingSpeedLimitSnapshot> {
        data class Rule(val way: String, val direction: Int, val start: Double, val end: Double)
        val rule = db.rawQuery("SELECT way_id,direction,start_chainage_m,end_chainage_m FROM traffic_sign_way_rule WHERE sign_id=? AND association_status='accepted' AND lane_scope='all' AND end_chainage_m>start_chainage_m ORDER BY (way_id=? ) DESC,way_id LIMIT 1", arrayOf(target.signID, target.originWayID)).use {
            check(it.moveToFirst()); Rule(it.getString(0), it.getInt(1), it.getDouble(2), it.getDouble(3))
        }
        val station = if(rule.direction>0) rule.start+minOf(1.0,(rule.end-rule.start)/2) else rule.end-minOf(1.0,(rule.end-rule.start)/2)
        val points = db.rawQuery("SELECT points_json FROM way_geom WHERE way_id=?", arrayOf(rule.way)).use { check(it.moveToFirst()); JSONArray(it.getString(0)) }
        var cumulative = 0.0
        var lat = Double.NaN
        var lon = Double.NaN
        var heading = Double.NaN
        for(i in 0 until points.length()-1) {
            val a=points.getJSONArray(i); val b=points.getJSONArray(i+1)
            val length=InventorySignRuntime.distance(a.getDouble(0),a.getDouble(1),b.getDouble(0),b.getDouble(1))*(6371000.0/6371008.8)
            if(station <= cumulative+length || i==points.length()-2) {
                val fraction=((station-cumulative)/length).coerceIn(0.0,1.0)
                lat=a.getDouble(0)+(b.getDouble(0)-a.getDouble(0))*fraction
                lon=a.getDouble(1)+(b.getDouble(1)-a.getDouble(1))*fraction
                val dx=(b.getDouble(1)-a.getDouble(1))*kotlin.math.cos(Math.toRadians(lat))
                val dy=b.getDouble(0)-a.getDouble(0)
                heading=(Math.toDegrees(kotlin.math.atan2(dx,dy))+360+(if(rule.direction<0)180 else 0))%360
                break
            }
            cumulative+=length
        }
        val now=java.time.Instant.now()
        val decision=InventorySignDatabase(path).use { source ->
            InventorySignRuntime { }.evaluate(source.read(lat,lon,rule.way,rule.direction),
                InventorySignFix(lat,lon,now,1.0,rule.way,rule.direction,true,"physical-readonly",heading,1.0),now,false,false)
        }
        val offer=requireNotNull(decision.speedRule)
        val groups=db.rawQuery("SELECT continuity_group_id FROM way_continuity_membership WHERE way_id=? AND continuity_kind='route_relation_connected'",arrayOf(rule.way)).use { c -> buildSet { while(c.moveToNext()) add(c.getLong(0)) } }
        val post=requireNotNull(reader.read(lat,lon,rule.way,rule.direction,true,1.0,heading,1.0,groups))
        assertFalse("The real full-bundle post-sign reader cannot advertise a passed sign",post.candidates.any { it.signID==target.signID })
        return JSONObject().put("wayID",rule.way).put("direction",rule.direction).put("stationM",station)
            .put("signID",offer.sign.id).put("speedKmh",offer.speedKmh)
            .put("postReaderCompleted",true).put("postReaderExcludedPassedSign",true)
            .put("scope","Existing production InventorySignDatabase and InventorySignRuntime at a source-derived post-sign point; camera disabled only in this isolated runtime object")
            .let { it to post }
    }
}
