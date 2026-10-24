package de.youspeed.android.alpha

import android.database.sqlite.SQLiteDatabase
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.time.Instant
import java.util.UUID
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class InventorySignDatabaseInstrumentedTest {
    @Test fun copiedBwInventoryCannotActivateInAnotherRegionButOsmFallbackRemains() {
        val file = fixture()
        try {
            SQLiteDatabase.openDatabase(file.path, null, SQLiteDatabase.OPEN_READWRITE).use { db ->
                db.execSQL("UPDATE traffic_sign_runtime SET source_id='mobidata-bw-vzk' WHERE sign_id='speed'")
                db.execSQL("UPDATE traffic_sign_runtime SET source_id='osm-settlement' WHERE sign_id='town'")
            }
            InventorySignDatabase(file.path).use { db ->
                val snapshot = db.read(48.0, 8.00001, "10", 1)
                assertEquals(listOf("town"), snapshot.signs.map { it.id })
                assertTrue(snapshot.rules.none { it.speedKmh != null })
                assertTrue(snapshot.rules.any { it.sign.id == "town" })
            }
        } finally { file.delete() }
    }
    private fun fixture(version: String? = "1"): File {
        val file=File(InstrumentationRegistry.getInstrumentation().targetContext.cacheDir,"inventory-${UUID.randomUUID()}.sqlite")
        SQLiteDatabase.openOrCreateDatabase(file,null).use { db ->
            db.execSQL("CREATE TABLE ways(way_id INTEGER PRIMARY KEY,maxspeed TEXT)")
            db.execSQL("INSERT INTO ways VALUES(10,'70')")
            if(version!=null) {
                db.execSQL("CREATE TABLE traffic_sign_capability(key TEXT PRIMARY KEY,value TEXT)")
                db.execSQL("INSERT INTO traffic_sign_capability VALUES('version',?)",arrayOf(version))
            }
            if(version=="1") {
                db.execSQL("CREATE TABLE traffic_sign_runtime(sign_id TEXT PRIMARY KEY,source_id TEXT,record_key TEXT,snapshot_sha256 TEXT,sign_code TEXT,normalized_code TEXT,kind TEXT,numeric_value REAL,unit TEXT,parameter_status TEXT,lon REAL,lat REAL,orientation_deg REAL,display_radius_m REAL,pictogram_code TEXT,pictogram_path TEXT,model_classes_json TEXT)")
                db.execSQL("INSERT INTO traffic_sign_runtime VALUES('town','source','record','snapshot','DE:310','DE:310','settlement_boundary',NULL,NULL,'not_applicable',8,48,90,30,'DE:310','tsr/sign-pictograms/png/de-310.png','[]')")
                db.execSQL("INSERT INTO traffic_sign_runtime VALUES('speed','source','record2','snapshot','DE:274-30','DE:274-30','speed_limit',30,'km/h','parsed_source_value',8,48,90,10,'DE:274-30',NULL,'[\"maxspeed:30\"]')")
                db.execSQL("CREATE TABLE traffic_sign_way_rule(rule_id TEXT PRIMARY KEY,sign_id TEXT,way_id INTEGER,direction INTEGER,start_chainage_m REAL,end_chainage_m REAL,station_chainage_m REAL,local_heading_deg REAL,speed_kmh REAL,inside_city INTEGER,association_status TEXT,lane_scope TEXT)")
                db.execSQL("INSERT INTO traffic_sign_way_rule VALUES('speed-rule','speed',10,1,74,150,74,90,30,1,'accepted','all')")
                db.execSQL("INSERT INTO traffic_sign_way_rule VALUES('unresolved-lane','speed',10,1,74,150,74,90,80,NULL,'accepted','unresolved')")
                db.execSQL("CREATE TABLE traffic_sign_association(sign_id TEXT PRIMARY KEY,status TEXT,way_id INTEGER,direction INTEGER,station_chainage_m REAL,local_heading_deg REAL)")
                db.execSQL("INSERT INTO traffic_sign_association VALUES('town','accepted',10,1,74,90)")
                db.execSQL("INSERT INTO traffic_sign_association VALUES('speed','accepted',10,1,74,90)")
                db.execSQL("CREATE TABLE way_geom(way_id INTEGER PRIMARY KEY,points_json TEXT)")
                db.execSQL("INSERT INTO way_geom VALUES(10,'[[48,7.999],[48,8.001]]')")
            }
        }
        return file
    }
    @Test fun legacyAndFutureCapabilitiesReturnNoOptionalDataAndNeverChangeRoads() {
        for(version in listOf(null,"2")) {
            val file=fixture(version)
            try {
                InventorySignDatabase(file.path).use { assertFalse(it.read(48.0,8.0,"10",1).supported) }
                SQLiteDatabase.openDatabase(file.path,null,SQLiteDatabase.OPEN_READONLY).use { db ->
                    db.rawQuery("SELECT maxspeed FROM ways WHERE way_id=10",null).use { assertTrue(it.moveToFirst()); assertEquals("70",it.getString(0)) }
                }
            } finally { file.delete() }
        }
    }
    @Test fun sourceGeometryChainageDoesNotChangeWithQueryLatitude() {
        val file=fixture()
        try { InventorySignDatabase(file.path).use { db ->
            val a=db.read(48.00005,8.001,"10",1)
            val b=db.read(48.0001,8.001,"10",1)
            assertEquals(a.chainage!!,b.chainage!!,1e-8)
            val expected=InventorySignRuntime.distance(48.0,7.999,48.0,8.001)*(6371000.0/6371008.8)
            assertEquals(expected,a.chainage!!,1e-8)
        } } finally { file.delete() }
    }
    @Test fun exactBundleContractProjectsDirectionAndExcludesUnresolvedLanes() {
        val file=fixture()
        try {
            InventorySignDatabase(file.path).use { db ->
                val snapshot=db.read(48.0,8.00001,"10",1)
                assertTrue(snapshot.supported); assertEquals(2,snapshot.signs.size)
                assertTrue(snapshot.signs.all { it.associatedHeadingDeg == 90.0 && it.sourceTravelHeading == 90.0 })
                assertEquals(1,snapshot.rules.count { it.speedKmh!=null })
                assertTrue(snapshot.chainage!! > 74)
                val time=Instant.parse("2026-10-21T12:00:00Z")
                val runtime=InventorySignRuntime { }
                val result=runtime.evaluate(snapshot,InventorySignFix(48.0,8.00001,time,5.0,"10",1,true,"snapshot",90.0,5.0),time,false,false)
                assertEquals(30,result.speedRule?.speedKmh)
                assertEquals("city_entry",result.boundary)
                val reverse=db.read(48.0,8.00001,"10",-1)
                assertTrue(reverse.rules.isEmpty())
                val withoutWay=db.read(48.0,8.00001,null,0)
                assertTrue(withoutWay.rules.isEmpty()); assertEquals(2,withoutWay.signs.size)
            }
        } finally { file.delete() }
    }
}
