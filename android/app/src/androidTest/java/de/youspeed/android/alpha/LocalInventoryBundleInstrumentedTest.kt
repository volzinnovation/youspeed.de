package de.youspeed.android.alpha

import android.database.sqlite.SQLiteDatabase
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.time.Instant
import org.json.JSONArray
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Explicit, offline verification of the full bundle installed by the local test installer. */
@RunWith(AndroidJUnit4::class)
class LocalInventoryBundleInstrumentedTest {
    @Test fun installedBwBundleRoutesAndSuppliesDirectedRuntimeRules() {
        assumeTrue("Run explicitly with -e localInventoryBundle true after the local installer",
            InstrumentationRegistry.getArguments().getString("localInventoryBundle") == "true")
        val context=InstrumentationRegistry.getInstrumentation().targetContext
        val bootstrapper=BundleBootstrapper(File(context.filesDir,"bundle"),object: HttpFetcher {
            override fun fetch(url: String): ByteArray = error("Local test must not fetch $url")
            override fun fetchToFile(url: String,destination: File,onProgress: ((Long,Long?) -> Unit)?) {
                error("Local test must not fetch $url")
            }
        })
        val active=requireNotNull(bootstrapper.activeState())
        assertEquals("baden-wuerttemberg",active.region)
        assertTrue(active.bundleVersion.contains("v1.5"))
        val file=File(active.dbPath)
        AndroidBundleDeltaDatabase().validate(file)
        AndroidBundleDeltaDatabase().validateSettlementCapability(file)
        val row=SQLiteDatabase.openDatabase(file.path,null,SQLiteDatabase.OPEN_READONLY).use { db ->
            db.rawQuery("SELECT count(*) FROM traffic_sign_runtime",null).use {
                assertTrue(it.moveToFirst()); assertTrue(it.getInt(0)>160000)
            }
            db.rawQuery("SELECT r.way_id,r.direction,r.start_chainage_m,r.end_chainage_m,r.speed_kmh,g.points_json " +
                "FROM traffic_sign_way_rule r JOIN way_geom g USING(way_id) " +
                "WHERE r.association_status='accepted' AND r.lane_scope='all' AND r.speed_kmh IS NOT NULL " +
                "AND r.end_chainage_m-r.start_chainage_m>10 ORDER BY r.rule_id LIMIT 1",null).use {
                assertTrue(it.moveToFirst())
                RuleProbe(it.getString(0),it.getInt(1),(it.getDouble(2)+it.getDouble(3))/2,it.getInt(4),JSONArray(it.getString(5)))
            }
        }
        val point=pointAt(row.points,row.chainage)
        val route=requireNotNull(bootstrapper.resolveLocalBundleRoute(48.7758,9.1829,null))
        assertEquals(active.dbPath,route.dbPath)
        assertEquals(active.dbSha256,route.dbSha256)
        InventorySignDatabase(active.dbPath).use { db ->
            val snapshot=db.read(point.first,point.second,row.wayId,row.direction)
            assertTrue(snapshot.supported)
            assertEquals(row.chainage,snapshot.chainage!!,.1)
            val now=Instant.now()
            val heading=(requireNotNull(snapshot.localHeading)+if(row.direction<0) 180 else 0)%360
            val runtime=InventorySignRuntime { }
            val decision=runtime.evaluate(snapshot,InventorySignFix(point.first,point.second,now,5.0,row.wayId,row.direction,true,
                active.dbSha256,heading,5.0,active.dbSha256,active.bundleVersion),now,false,false)
            assertEquals(row.speedKmh,decision.speedRule?.speedKmh)
            assertEquals(row.wayId,decision.speedRule?.wayId)
            assertEquals(row.direction,decision.speedRule?.direction)
            assertNotNull(decision.speedRule?.sign?.associatedHeadingDeg)
        }
    }
    private data class RuleProbe(val wayId: String,val direction: Int,val chainage: Double,val speedKmh: Int,val points: JSONArray)
    private fun pointAt(points: JSONArray, target: Double): Pair<Double,Double> {
        var traversed=0.0
        for(i in 0 until points.length()-1) {
            val a=points.getJSONArray(i);val b=points.getJSONArray(i+1)
            val length=InventorySignRuntime.distance(a.getDouble(0),a.getDouble(1),b.getDouble(0),b.getDouble(1))*6371000/6371008.8
            if(target<=traversed+length) {
                val fraction=((target-traversed)/length).coerceIn(0.0,1.0)
                return (a.getDouble(0)+(b.getDouble(0)-a.getDouble(0))*fraction) to
                    (a.getDouble(1)+(b.getDouble(1)-a.getDouble(1))*fraction)
            }
            traversed+=length
        }
        error("Rule chainage outside source geometry")
    }
}
