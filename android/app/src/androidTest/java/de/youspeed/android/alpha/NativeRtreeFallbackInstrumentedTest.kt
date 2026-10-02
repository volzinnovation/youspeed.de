package de.youspeed.android.alpha

import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteException
import android.util.Log
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.security.MessageDigest
import java.util.UUID
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class NativeRtreeFallbackInstrumentedTest {
    @Test fun unchangedRealRtreeBundleSupportsProductionLookupWithoutModule() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val file = File(instrumentation.targetContext.cacheDir, "native-rtree-${UUID.randomUUID()}.sqlite")
        try {
            instrumentation.context.assets.open("matcher/candidate-admission-native-rtree-v1.sqlite").use { input ->
                file.outputStream().use { output -> input.copyTo(output) }
            }
            val original = sha256(file)
            val nativeRtreeAvailable = SQLiteDatabase.openDatabase(file.path, null, SQLiteDatabase.OPEN_READONLY).use { db ->
                // Read sqlite_master without instantiating the unavailable virtual table.
                db.rawQuery("SELECT sql FROM sqlite_master WHERE name='ways_rtree'", null).use { cursor ->
                    assertTrue(cursor.moveToFirst())
                    assertTrue(cursor.getString(0).contains("USING rtree", ignoreCase = true))
                }
                try {
                    db.rawQuery("SELECT count(*) FROM ways_rtree", null).use { cursor ->
                        assertTrue(cursor.moveToFirst())
                        assertEquals(4, cursor.getInt(0))
                    }
                    true
                } catch (error: SQLiteException) {
                    if (!SqliteFixtureSupport.isRtreeUnavailable(error)) throw error
                    false
                }
            }
            V3SpeedLimitLookup(file.path, countryCode = "DEU").use { service ->
                repeat(3) {
                    assertEquals(listOf("9007199254740993", "10"),
                        service.admittedWayIdsForTesting(0.0, 0.0, 200.0, 2))
                    val result = service.lookup(0.0, 0.0, 200.0, 2, 90.0,
                        speedKmh = 40.0, horizontalAccuracyM = 5.0, gpsSignalBars = 4)
                    assertEquals("9007199254740993", result.wayId)
                    assertEquals(30, result.speedLimitKmh)
                }
            }
            assertEquals("Read-only fallback must not rewrite virtual tables", original, sha256(file))
            Log.i("NativeRtreeFallbackTest", "Unchanged native R-tree database: " +
                if (nativeRtreeAvailable) "native module available; normal lookup verified"
                else "module unavailable; production bounds fallback verified")
        } finally { file.delete() }
    }

    private fun sha256(file: File) = MessageDigest.getInstance("SHA-256").digest(file.readBytes()).toList()
}
