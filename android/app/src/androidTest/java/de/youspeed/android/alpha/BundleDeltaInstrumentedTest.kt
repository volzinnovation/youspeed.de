package de.youspeed.android.alpha

import android.database.sqlite.SQLiteDatabase
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.util.UUID
import org.junit.Assert.*
import org.junit.Test

class BundleDeltaInstrumentedTest {
    @Test fun nativeDeltaAppliesTransactionWithQuotedSemicolonsAndValidatesMaterializedDatabase() {
        val file = File(InstrumentationRegistry.getInstrumentation().targetContext.cacheDir, "delta-${UUID.randomUUID()}.sqlite")
        try {
            SQLiteDatabase.openOrCreateDatabase(file, null).use { db ->
                db.execSQL("CREATE TABLE ways (way_id INTEGER PRIMARY KEY, street_name TEXT, maxspeed TEXT)")
                db.execSQL("CREATE TABLE ways_rtree (way_id INTEGER PRIMARY KEY, min_lon REAL, max_lon REAL, min_lat REAL, max_lat REAL)")
                db.execSQL("CREATE TABLE way_geom (way_id INTEGER PRIMARY KEY, points_json TEXT)")
                db.execSQL("INSERT INTO ways VALUES (1, 'Before', '50')")
            }
            val backend = AndroidBundleDeltaDatabase()
            backend.applyPatch(file, "BEGIN IMMEDIATE; UPDATE ways SET street_name='Rue de l''Église; south', maxspeed='30' WHERE way_id=1; COMMIT;")
            backend.validate(file)
            SQLiteDatabase.openDatabase(file.path, null, SQLiteDatabase.OPEN_READONLY).use { db ->
                db.rawQuery("SELECT street_name,maxspeed FROM ways WHERE way_id=1", null).use { cursor ->
                    assertTrue(cursor.moveToFirst())
                    assertEquals("Rue de l'Église; south", cursor.getString(0))
                    assertEquals("30", cursor.getString(1))
                }
            }
            assertFalse(File(file.path + "-wal").exists() && File(file.path + "-wal").length() > 0)
        } finally { SQLiteDatabase.deleteDatabase(file) }
    }
}
