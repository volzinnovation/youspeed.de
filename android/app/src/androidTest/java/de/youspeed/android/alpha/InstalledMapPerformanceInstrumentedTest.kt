package de.youspeed.android.alpha

import android.database.sqlite.SQLiteDatabase
import android.util.Log
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test

/** Read-only acceptance against the attached phone's installed legacy pack. */
class InstalledMapPerformanceInstrumentedTest {
    @Test fun indexedLegacyMapKeepsExactCandidatesAndFreshResults() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val relative = InstrumentationRegistry.getArguments().getString("bundle_db") ?: ""
        assumeTrue("Only run when an installed map is supplied", relative.isNotEmpty())
        val file = File(context.filesDir, relative)
        assertTrue(file.isFile)
        val db = SQLiteDatabase.openDatabase(file.path, null, SQLiteDatabase.OPEN_READONLY)
        try {
            val options = db.rawQuery("PRAGMA compile_options", null).use { c -> buildList { while(c.moveToNext()) add(c.getString(0)) } }
            Log.i("YouSpeedMapBenchmark", "rtreeModule=${options.any { it == "ENABLE_RTREE" }}")
            val index = ReadOnlyRtreeIndex { id -> db.rawQuery("SELECT data FROM ways_rtree_node WHERE nodeno=?", arrayOf(id.toString())).use { if(it.moveToFirst()) it.getBlob(0) else null } }
            // Compare the reader's overlap candidates to real way bounds, then
            // time the production matcher at the position that stalled.
            val lat = 47.577285; val lon = 7.5988983333333335
            val minLon = lon - .002; val maxLon = lon + .002; val minLat = lat - .002; val maxLat = lat + .002
            val ids = index.intersect(minLon,maxLon,minLat,maxLat)!!
            val where = "min_lon<=? AND max_lon>=? AND min_lat<=? AND max_lat>=?"
            val args = arrayOf(maxLon.toString(),minLon.toString(),maxLat.toString(),minLat.toString())
            fun actual(sql: String) = db.rawQuery(sql,args).use { c -> buildSet { while(c.moveToNext()) add(c.getLong(0)) } }
            assertEquals(actual("SELECT way_id FROM ways WHERE $where"), actual("SELECT way_id FROM ways WHERE way_id IN (${ids.joinToString(",")}) AND $where"))
            V3SpeedLimitLookup(file.path,countryCode="DEU",matchingModel=LookupMatchingModel.SIMPLE_SPEED_REF_URBAN_RELEASE_NARROW_WINDOW_HEURISTIC).use { lookup ->
                repeat(3) { i ->
                    val start = System.nanoTime()
                    val probe = lookup.lookupRouteEvidence(lat,lon,120.0,1200,null,speedKmh=0.0,horizontalAccuracyM=10.0,gpsSignalBars=4)
                    val probeMs = (System.nanoTime()-start)/1e6
                    val result = lookup.lookup(lat,lon,120.0,1200,null,speedKmh=0.0,horizontalAccuracyM=10.0,gpsSignalBars=4)
                    assertEquals(result.wayId != null,probe.hasWayMatch)
                    assertTrue("Lookup must fit the existing six-second freshness limit",probeMs+result.queryTimeMs < 6000)
                    assertTrue("Production lookup must use the existing index", lookup.cacheStats().spatialIndexNodeReads > 0)
                    Log.i("YouSpeedMapBenchmark","run=$i probeMs=$probeMs selectedMs=${result.queryTimeMs} ways=${probe.candidateCount} way=${result.wayId} indexNodes=${lookup.cacheStats().spatialIndexNodeReads}")
                }
            }
        } finally { db.close() }
    }
}
