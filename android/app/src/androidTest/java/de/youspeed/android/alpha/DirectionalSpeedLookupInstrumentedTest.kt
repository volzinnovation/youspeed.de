package de.youspeed.android.alpha

import android.content.Context
import android.content.ContextWrapper
import android.database.sqlite.SQLiteDatabase
import android.location.Location
import android.location.LocationManager
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.security.MessageDigest
import java.time.Clock
import java.util.UUID
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class DirectionalSpeedLookupInstrumentedTest {
    private val context: Context get() = InstrumentationRegistry.getInstrumentation().targetContext.also {
        assertTrue("Requires the isolated test host", it.packageName.endsWith(".testhost"))
    }
    private fun field(name: String) = ConsumerSessionController::class.java.getDeclaredField(name).apply { isAccessible = true }
    private fun method(name: String) = ConsumerSessionController::class.java.declaredMethods.single { it.name == name }.apply { isAccessible = true }
    private fun sha(file: File) = MessageDigest.getInstance("SHA-256").digest(file.readBytes()).joinToString("") { "%02x".format(it) }

    @Test fun generatedHistoricalSourceFixtureResolvesBothDirectionsAndControllerAuthority() {
        val database = File(context.filesDir, "directional-speeds.sqlite")
        val casesFile = File(context.filesDir, "directional-speeds.json")
        assertTrue("Stage the source-generated shared fixture before running this test", database.isFile && casesFile.isFile)
        val cases = JSONObject(casesFile.readText())
        val originalHash = sha(database)
        assertEquals(cases.getString("databaseSHA256"), originalHash)
        val originalModified = database.lastModified()
        val originalBytes = database.length()
        val results = (0 until cases.getJSONArray("cases").length()).map { index ->
            val row = cases.getJSONArray("cases").getJSONObject(index)
            val lat = row.getDouble("lat")
            val lon = row.getDouble("lon")
            val heading = row.getDouble("forwardHeadingDeg")
            val expectedWay = row.getString("wayId")
            val expectedForward = row.getInt("expectedForwardKmh")
            val expectedBackward = row.getInt("expectedBackwardKmh")
            val backward = (heading + 180) % 360
            val sets = listOf(LookupMatchingModel.CONNECTED_BASELINE,
                LookupMatchingModel.SIMPLE_SPEED_REF_URBAN_RELEASE_NARROW_WINDOW_HEURISTIC).map { model ->
                V3SpeedLimitLookup(database.path, "DEU", model).use { reader ->
                    fun query(course: Double?, accuracy: Double? = 5.0) = reader.lookup(lat, lon, 120.0, 64,
                        course, speedKmh = 30.0, horizontalAccuracyM = 5.0, gpsSignalBars = 4, headingAccuracyDeg = accuracy)
                    val forward = query(heading)
                    val reverse = query(backward)
                    val unknown = query(null)
                    for (result in listOf(forward, reverse, unknown, query(heading, null))) {
                        assertEquals("$model selected source way", expectedWay, result.wayId)
                        assertNull("Directional numeric evidence does not fabricate settlement state", result.insideCity)
                        assertEquals("settlement:missing:unknown", result.citySource)
                    }
                    assertEquals(expectedForward, forward.speedLimitKmh)
                    assertEquals(expectedBackward, reverse.speedLimitKmh)
                    assertEquals(DerivedSpeedSource.EXPLICIT_TAG, forward.speedSource)
                    assertEquals(DerivedSpeedSource.EXPLICIT_TAG, reverse.speedSource)
                    assertNull(unknown.speedLimitKmh)
                    assertEquals(DerivedSpeedSource.DIRECTIONAL_UNRESOLVED, unknown.speedSource)
                    assertNull(query(heading, null).speedLimitKmh)
                    val probe = reader.lookupRouteEvidence(lat, lon, 120.0, 64, null,
                        speedKmh = 30.0, horizontalAccuracyM = 5.0, gpsSignalBars = 4, headingAccuracyDeg = null)
                    assertTrue("Headingless routing retains road evidence", probe.hasWayMatch)
                    assertFalse("Feature density does not grant current speed authority", probe.hasSpeedMatch)
                    assertTrue("Directional source data still counts for overlapping-bundle density", probe.speedCandidateCount > 0)
                    assertEquals(unknown.speedCandidateCount, probe.speedCandidateCount)
                    assertNotNull(probe.nearestSpeedCandidateDistanceM)
                    assertTrue(requireNotNull(probe.nearestSpeedCandidateDistanceM) < 5.0)
                    Triple(forward, reverse, unknown)
                }
            }
            SharedCase(lat, lon, heading, backward, expectedForward, expectedBackward, sets.last())
        }
        withController { controller ->
            var now = 0.0
            var sequence = 0L
            val model = SpeedLimitReferenceModel.load { context.assets.open("speed-limit-reference/$it").use { stream -> stream.readBytes() } }
            val runtime = SpeedReferenceRuntime(model) { now }
            field("speedReference").set(controller, runtime)
            val gate = field("lookupToken").get(controller) as TrafficSignLookupMutationGate
            val generation = field("trafficSignGeneration").get(controller) as TrafficSignWriteGate
            assertEquals("1.1.0:497e157de2d04ed067897ecc9abde29ecf304a4147c9897b26e71d5c5fc0fcd9", runtime.policyIdentity)
            for (case in results) {
                now = 0.0
                runtime.reset()
                fun publish(result: SpeedLookupResult, heading: Double?) {
                    val location = Location(LocationManager.GPS_PROVIDER).apply {
                        latitude = case.lat; longitude = case.lon; accuracy = 5f; speed = 30f / 3.6f
                        if (heading != null) { bearing = heading.toFloat(); bearingAccuracyDegrees = 5f }
                        time = System.currentTimeMillis(); elapsedRealtimeNanos = SystemClock.elapsedRealtimeNanos()
                    }
                    val position = TrafficSignPositionSample(location.time, case.lat, case.lon, heading, 30.0 / 3.6)
                    field("latestTrafficSignPosition").set(controller, position)
                    method("applyActiveLocalSpeedCorrectionIfNeeded").invoke(controller, result, location)
                    val base = method("trafficSignBaseLimit").invoke(controller, null, null, result, "DEU", null, false) as TrafficSignBaseLimit
                    assertNotNull(method("evaluateTrafficSignSources").invoke(controller, gate.snapshot(), ++sequence, generation.get(),
                        position, result, location, base, "source-fixture", originalHash, database.path, "DEU", null, heading, 10))
                    controller.setAudioAlertThresholdKmh(10)
                }
                publish(case.lookup.first, case.heading)
                assertEquals(case.forward, controller.uiState.speedLimitKmh)
                assertEquals(EffectiveSpeedLimitSource.BUNDLE, controller.uiState.effectiveSpeedLimitSource)
                assertTrue(requireNotNull(runtime.output()).current)
                now = 1.0
                publish(case.lookup.second, case.backwardHeading)
                assertEquals(case.forward, controller.uiState.speedLimitKmh)
                assertEquals(EffectiveSpeedLimitSource.LAST_KNOWN, controller.uiState.effectiveSpeedLimitSource)
                now = 8.999
                publish(case.lookup.second, case.backwardHeading)
                assertEquals(EffectiveSpeedLimitSource.LAST_KNOWN, controller.uiState.effectiveSpeedLimitSource)
                now = 9.0
                publish(case.lookup.second, case.backwardHeading)
                assertEquals(case.backward, controller.uiState.speedLimitKmh)
                assertEquals(EffectiveSpeedLimitSource.BUNDLE, controller.uiState.effectiveSpeedLimitSource)
                assertTrue(requireNotNull(runtime.output()).current)
                now = 10.0
                publish(case.lookup.third, null)
                assertEquals(case.backward, controller.uiState.speedLimitKmh)
                assertEquals(EffectiveSpeedLimitSource.LAST_KNOWN, controller.uiState.effectiveSpeedLimitSource)
                assertFalse(requireNotNull(runtime.output()).current)
            }
        }
        assertEquals(originalBytes, database.length())
        assertEquals(originalModified, database.lastModified())
        assertEquals(originalHash, sha(database))
    }

    @Test fun nativeSqliteLookupCoversBendsLegacyAndAmbiguousDirectionalInputs() {
        fun check(forward: String?, backward: String?, base: String? = null, hasColumns: Boolean = true,
            points: String = "[[49,7.999],[49,8.001]]", body: (V3SpeedLimitLookup) -> Unit) {
            val database = fixture(forward, backward, base, hasColumns, points)
            try { V3SpeedLimitLookup(database.path, "DEU", LookupMatchingModel.CONNECTED_BASELINE).use(body) }
            finally { SQLiteDatabase.deleteDatabase(database) }
        }
        fun V3SpeedLimitLookup.query(course: Double?, lat: Double = 49.0, lon: Double = 8.0,
            speed: Double? = 30.0, accuracy: Double? = 5.0) = lookup(lat, lon, 120.0, 32, course,
                speedKmh = speed, horizontalAccuracyM = 5.0, gpsSignalBars = 4, headingAccuracyDeg = accuracy)
        check("30", "70") { reader ->
            assertEquals(30, reader.query(90.0).speedLimitKmh)
            assertEquals(70, reader.query(270.0).speedLimitKmh)
            val ambiguous = reader.query(null)
            assertEquals(true, ambiguous.insideCity)
            assertNull("Known urban context cannot replace conflicting explicit directional limits with 50", ambiguous.speedLimitKmh)
            assertEquals(DerivedSpeedSource.DIRECTIONAL_UNRESOLVED, ambiguous.speedSource)
            assertNull(reader.query(0.0).speedLimitKmh)
            assertNull(reader.query(90.0, accuracy = null).speedLimitKmh)
            assertNull(reader.query(90.0, speed = 0.0).speedLimitKmh)
        }
        check("30", "30") { assertEquals(30, it.query(null).speedLimitKmh) }
        check("30", null, base = "50") {
            assertEquals(30, it.query(90.0).speedLimitKmh)
            assertEquals(50, it.query(270.0).speedLimitKmh)
            assertNull(it.query(null).speedLimitKmh)
        }
        check(null, null, base = "50", hasColumns = false) { assertEquals(50, it.query(null).speedLimitKmh) }
        check("30 @ (wet)", "70", base = "50") {
            assertNull(it.query(90.0).speedLimitKmh)
            assertEquals(70, it.query(270.0).speedLimitKmh)
        }
        check("signals", "30 @ (wet)") {
            assertNull(it.query(null).speedLimitKmh)
            assertEquals(0, it.query(null).speedCandidateCount)
        }
        check("DE:urban", "de:urban") {
            assertEquals(50, it.query(null).speedLimitKmh)
            assertEquals(DerivedSpeedSource.INHERITED_TAG, it.query(null).speedSource)
            assertEquals(1, it.query(null).speedCandidateCount)
        }
        check("none", "70") {
            assertTrue(it.query(90.0).isUnlimitedSpeedLimit)
            assertEquals(DerivedSpeedSource.EXPLICIT_UNLIMITED_TAG, it.query(90.0).speedSource)
            assertEquals(70, it.query(270.0).speedLimitKmh)
            assertFalse(it.query(null).isUnlimitedSpeedLimit)
            assertNull(it.query(null).speedLimitKmh)
        }
        check("30", "50", points = "[[49,8.001],[49,7.999]]") {
            assertEquals(50, it.query(90.0).speedLimitKmh)
            assertEquals(30, it.query(270.0).speedLimitKmh)
        }
        check("100", "70", points = "[[49,7.999],[49,8],[49.001,8]]") {
            assertEquals(100, it.query(0.0, lat = 49.0008).speedLimitKmh)
            assertEquals(70, it.query(180.0, lat = 49.0008).speedLimitKmh)
            assertNull(it.query(90.0, lat = 49.0008).speedLimitKmh)
        }
    }

    private data class SharedCase(val lat: Double, val lon: Double, val heading: Double, val backwardHeading: Double,
        val forward: Int, val backward: Int, val lookup: Triple<SpeedLookupResult, SpeedLookupResult, SpeedLookupResult>)

    private fun fixture(forward: String?, backward: String?, base: String?, hasColumns: Boolean, points: String): File {
        val file = File(context.cacheDir, "directional-" + UUID.randomUUID() + ".sqlite")
        SQLiteDatabase.openOrCreateDatabase(file, null).use { db ->
            db.execSQL("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT)")
            db.execSQL("INSERT INTO metadata VALUES('schema_version','1')")
            db.execSQL("INSERT INTO metadata VALUES('settlement_context_version','1')")
            db.execSQL("CREATE TABLE ways(way_id INTEGER PRIMARY KEY,highway TEXT,street_name TEXT,ref TEXT,maxspeed TEXT,maxspeed_type TEXT,source_maxspeed TEXT,approx_heading_deg REAL,service TEXT,tunnel TEXT,min_lon REAL,min_lat REAL,max_lon REAL,max_lat REAL)")
            db.execSQL("INSERT INTO ways VALUES(1,'secondary','Fixture Road',NULL,?,NULL,NULL,90,NULL,NULL,7.999,49,8.001,49.001)", arrayOf(base))
            if (hasColumns) {
                db.execSQL("ALTER TABLE ways ADD COLUMN maxspeed_forward TEXT")
                db.execSQL("ALTER TABLE ways ADD COLUMN maxspeed_backward TEXT")
                db.execSQL("UPDATE ways SET maxspeed_forward=?,maxspeed_backward=?", arrayOf(forward, backward))
            }
            SqliteFixtureSupport.createRtree(db, "ways_rtree")
            db.execSQL("INSERT INTO ways_rtree VALUES(1,7.999,8.001,49,49.001)")
            db.execSQL("CREATE TABLE way_geom(way_id INTEGER PRIMARY KEY,points_json TEXT)")
            db.execSQL("INSERT INTO way_geom VALUES(1,?)", arrayOf(points))
            db.execSQL("CREATE TABLE settlement_segment(segment_id INTEGER PRIMARY KEY,way_id INTEGER,segment_index INTEGER,direction INTEGER,inside_city INTEGER,source TEXT,confidence TEXT,points_json TEXT)")
            db.execSQL("INSERT INTO settlement_segment VALUES(1,1,0,0,1,'zone_traffic','high',?)", arrayOf(points))
        }
        return file
    }

    private fun withController(body: (ConsumerSessionController) -> Unit) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val base = context
        val id = "directional-controller-" + UUID.randomUUID()
        val root = File(base.cacheDir, id).apply { mkdirs() }
        val isolated = object : ContextWrapper(base) {
            override fun getApplicationContext(): Context = this
            override fun getFilesDir() = File(root, "files").apply { mkdirs() }
            override fun getCacheDir() = File(root, "cache").apply { mkdirs() }
            override fun getNoBackupFilesDir() = File(root, "no-backup").apply { mkdirs() }
            override fun getSharedPreferences(name: String, mode: Int) = base.getSharedPreferences("$id-$name", mode)
        }
        lateinit var controller: ConsumerSessionController
        instrumentation.runOnMainSync {
            controller = ConsumerSessionController(isolated, File(root, "bundle"),
                isolated.getSharedPreferences("youspeed", Context.MODE_PRIVATE), Clock.systemUTC(), null)
        }
        try {
            val deadline = SystemClock.uptimeMillis() + 30_000
            while (controller.uiState.startupDataState == StartupDataState.LOADING && SystemClock.uptimeMillis() < deadline) SystemClock.sleep(100)
            instrumentation.runOnMainSync { field("isDriving").setBoolean(controller, true); body(controller) }
        } finally {
            instrumentation.runOnMainSync { controller.dispose() }
            base.deleteSharedPreferences("$id-youspeed"); root.deleteRecursively()
        }
    }
}
