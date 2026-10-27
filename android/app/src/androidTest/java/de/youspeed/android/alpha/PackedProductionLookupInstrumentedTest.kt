package de.youspeed.android.alpha

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import org.json.JSONArray
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Explicitly staged real pilot/source data; no normal installed bundle is opened
 * or replaced. The test runner must supply the isolated app-owned directory. */
@RunWith(AndroidJUnit4::class)
class PackedProductionLookupInstrumentedTest {
    @Test fun completePilotSQLAndProductionMatcherMatchOriginalSQLite() {
        val argument=InstrumentationRegistry.getArguments().getString("packed_pilot_dir")
        assumeTrue("Requires explicitly staged verified pilot",argument!=null)
        val directory=File(requireNotNull(argument));val original=File(directory,"source.sqlite")
        val context=directory.listFiles()?.singleOrNull{it.name.endsWith(".context.yspc")}
        assertTrue(original.isFile);assertNotNull(context)
        val packed=requireNotNull(context)
        NativeRuntimeSqlDatabase(original.path,false).use { reference ->
            RuntimeMapDatabase.open(packed.path).use { runtime ->
                val tables=reference.rawQuery("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name",null)
                    .use {rows->buildList{while(rows.moveToNext())add(rows.getString(0))}}
                assertTrue(tables.size>=20)
                for(table in tables) {
                    require(table.matches(Regex("[A-Za-z0-9_]+")))
                    val filter=if(table=="metadata")" WHERE key NOT LIKE 'packed_%'" else ""
                    fun count(db:RuntimeSqlDatabase)=db.rawQuery("SELECT COUNT(*) FROM \"$table\""+filter,null).use{assertTrue(it.moveToFirst());it.getLong(0)}
                    assertEquals(table,count(reference),count(runtime.database))
                }
                reference.rawQuery("SELECT way_id,points_json FROM way_geom ORDER BY way_id",null).use { expected ->
                    runtime.database.rawQuery("SELECT way_id,points_json FROM way_geom ORDER BY way_id",null).use { actual ->
                        var count=0
                        while(expected.moveToNext()) {assertTrue(actual.moveToNext());assertEquals(expected.getLong(0),actual.getLong(0));assertEquals(expected.getString(1),actual.getString(1));count++}
                        assertFalse(actual.moveToNext());assertTrue(count>1000)
                    }
                }
            }
            val probes=reference.rawQuery("SELECT points_json FROM way_geom ORDER BY way_id",null).use {rows->buildList {
                var index=0;while(rows.moveToNext()){if(index++%47==0){val point=JSONArray(rows.getString(0)).getJSONArray(0);add(point.getDouble(0) to point.getDouble(1))}}
            }}
            fun semantic(result:SpeedLookupResult)=result.copy(queryTimeMs=0.0,lookupStageMs=emptyMap(),
                upcomingSpeedLimits=result.upcomingSpeedLimits?.copy(queryTimeMs=0.0))
            V3SpeedLimitLookup(original.path,"MC").use { legacy ->
                V3SpeedLimitLookup(packed.path,"MC").use { reader ->
                    for((lat,lon) in probes) {
                        val expected=legacy.lookup(lat,lon,60.0,1200,null,horizontalAccuracyM=5.0)
                        val actual=reader.lookup(lat,lon,60.0,1200,null,horizontalAccuracyM=5.0)
                        assertEquals("Production matcher at $lat,$lon",semantic(expected),semantic(actual))
                    }
                }
            }
        }
    }
}
