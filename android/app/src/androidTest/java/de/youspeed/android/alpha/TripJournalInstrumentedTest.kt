package de.youspeed.android.alpha

import android.content.Context
import android.content.ContextWrapper
import android.content.SharedPreferences
import android.database.sqlite.SQLiteDatabase
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.util.UUID
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class TripJournalInstrumentedTest {
    private fun withJournalRoot(test: (Context,File) -> Unit) {
        val base=InstrumentationRegistry.getInstrumentation().targetContext
        val root=File(base.cacheDir,"trip-regression-${UUID.randomUUID()}").apply { mkdirs() }
        val preferences="trip-regression-${UUID.randomUUID()}"
        val isolated=object : ContextWrapper(base) {
            override fun getFilesDir()=File(root,"files").apply { mkdirs() }
            override fun getCacheDir()=File(root,"cache").apply { mkdirs() }
            override fun getSharedPreferences(name:String,mode:Int):SharedPreferences=base.getSharedPreferences(preferences,mode)
        }
        try { test(isolated,root) } finally { base.deleteSharedPreferences(preferences); root.deleteRecursively() }
    }

    @Test fun freshInstallCanReadCreateRecordAndReopenTripWithoutSetupError() = withJournalRoot { context,_ ->
        var tripID=""
        TripJournal(context,heartbeat=false).use { journal ->
            val initial=journal.snapshot()
            assertTrue(initial.first.isEmpty())
            assertEquals(0.0,initial.second.getDouble("distance"),0.0)
            journal.setEnabled(true)
            journal.start()
            journal.tsr("recognition",mapOf("raw_class" to "DE:274-50"))
            val recorded=journal.snapshot()
            assertEquals(1,recorded.first.size)
            tripID=recorded.first.single().getString("id")
            assertEquals("active",recorded.first.single().getString("state"))
            assertEquals("tsr",journal.events(tripID).single {it.optString("kind")=="tsr"}.getString("kind"))
            assertNull(journal.error)
        }
        TripJournal(context,heartbeat=false).use { reopened ->
            val saved=reopened.snapshot().first.single()
            assertEquals(tripID,saved.getString("id"))
            assertEquals("interrupted",saved.getString("state"))
            assertEquals(2,reopened.events(tripID).size)
            assertNull(reopened.error)
        }
    }

    @Test fun unsetAndExplicitOffNeverCreateTripsAndExplicitEnableStartsRequestedDriveWithLogs() = withJournalRoot {context,_ ->
        val wall=1792836000.0
        TripJournal(context,heartbeat=false,wallClock={wall},elapsedClock={1000}).use {journal ->
            assertFalse(journal.configured);assertFalse(journal.enabled)
            journal.start()
            journal.location(android.location.Location("gps").apply {latitude=48.0;longitude=8.0;accuracy=3f;time=(wall*1000).toLong()})
            journal.tsr("recognition",mapOf("raw_class" to "maxspeed:30"))
            assertTrue(journal.snapshot().first.isEmpty())
            journal.setEnabled(false)
            assertTrue(journal.configured);assertFalse(journal.enabled)
            journal.start();assertTrue(journal.snapshot().first.isEmpty())
            journal.setEnabled(true)
            journal.location(android.location.Location("gps").apply {latitude=48.0;longitude=8.0;accuracy=3f;time=(wall*1000).toLong()})
            journal.tsr("recognition",mapOf("raw_class" to "maxspeed:30"))
            val trip=journal.snapshot().first.single()
            assertEquals("active",trip.getString("state"))
            val kinds=journal.events(trip.getString("id")).map {it.getString("kind")}
            assertTrue(kinds.containsAll(listOf("gps","tsr")))
        }
    }

    @Test fun failedDirectorySetupCanRetryWithoutPublishingAPartialDatabase() = withJournalRoot { context,_ ->
        val blocked=File(context.filesDir,"trip-journal").apply { writeText("temporary blocker") }
        TripJournal(context,heartbeat=false).use { journal ->
            assertTrue(runCatching { journal.snapshot() }.isFailure)
            assertTrue(requireNotNull(journal.error).contains("directory"))
            assertEquals("temporary blocker",blocked.readText())
            assertTrue(blocked.delete())
            journal.setEnabled(true); journal.start()
            assertEquals(1,journal.snapshot().first.size)
            assertNull(journal.error)
        }
    }

    @Test fun incompleteSetupIsRepairedWithoutResettingCounterValues() = withJournalRoot { context,_ ->
        val root=File(context.filesDir,"trip-journal").apply { mkdirs() }
        SQLiteDatabase.openOrCreateDatabase(File(root,"trips.sqlite"),null).use { db ->
            db.execSQL("CREATE TABLE counters(id INTEGER PRIMARY KEY CHECK(id=1),origin REAL,distance REAL,usage REAL)")
            db.execSQL("INSERT INTO counters VALUES(1,1234,9876,5432)")
        }
        TripJournal(context,heartbeat=false).use { journal ->
            val result=journal.snapshot()
            assertTrue(result.first.isEmpty())
            assertEquals(1234.0,result.second.getDouble("origin"),0.0)
            assertEquals(9876.0,result.second.getDouble("distance"),0.0)
            assertTrue(result.second.getDouble("usage") in 5432.0..5433.0)
            journal.setEnabled(true); journal.start()
            assertEquals(1,journal.snapshot().first.size)
            assertNull(journal.error)
        }
    }
    @Test fun standstillSaveRemembersOdometerAndResumesOnMovement() = withJournalRoot {context,_ ->
        var tick=0L
        val wall=System.currentTimeMillis()/1000.0
        TripJournal(context,heartbeat=false,wallClock={wall+tick},elapsedClock={tick*1000}).use {journal ->
            journal.setEnabled(true);journal.start();journal.snapshot()
            fun feed(speed:Float,at:Long) {
                tick=at
                journal.location(android.location.Location("gps").apply {
                    latitude=49.0;longitude=8.0;accuracy=3f;this.speed=speed
                    time=((wall+tick)*1000).toLong();elapsedRealtimeNanos=(tick+1)*1_000_000_000L
                });journal.snapshot()
            }
            feed(10f,0)
            for(t in 1L..16L)feed(0f,t)
            val prompt=requireNotNull(journal.stoppedTripSnapshot())
            assertFalse(prompt.estimated);journal.saveStoppedTrip(prompt.tripID,123456)
            assertNull(journal.stoppedTripSnapshot())
            val ended=journal.snapshot().first.single()
            assertEquals("ended",ended.getString("state"));assertEquals(123456,ended.getInt("odo_end"))
            feed(0f,17);assertEquals(1,journal.snapshot().first.size)
            journal.lifecycle(false);journal.lifecycle(true);assertEquals(1,journal.snapshot().first.size)
            feed(10f,18);assertEquals(2,journal.snapshot().first.size)
            for(t in 19L..34L)feed(0f,t)
            val next=requireNotNull(journal.stoppedTripSnapshot())
            assertEquals(123456,next.reading);assertTrue(next.estimated)
            journal.continueStoppedTrip(next.tripID);assertNull(journal.stoppedTripSnapshot())
            feed(1f,35);assertTrue(runCatching {journal.saveStoppedTrip(next.tripID,123457)}.isFailure)
        }
    }

    @Test fun explicitStopFreezesMetadataAndAllowsOdometerAfterGPSChanges() = withJournalRoot {context,_ ->
        var tick=0L
        val wall=System.currentTimeMillis()/1000.0
        TripJournal(context,heartbeat=false,wallClock={wall+tick},elapsedClock={tick*1000}).use {journal ->
            journal.setEnabled(true);journal.start()
            val id=journal.snapshot().first.single().getString("id")
            fun feed(speed:Float,t:Long,lat:Double) {tick=t;journal.location(android.location.Location("gps").apply {
                latitude=lat;longitude=8.0;accuracy=3f;this.speed=speed;time=((wall+tick)*1000).toLong();elapsedRealtimeNanos=(tick+1)*1_000_000_000L
            });journal.snapshot()}
            feed(10f,0,49.0)
            journal.matchedPlace(wall,"Startstraße","Karlsruhe",49.0,8.0,3.0)
            feed(10f,1,49.0001)
            journal.matchedPlace(wall+1,"Zielstraße","Karlsruhe",49.0001,8.0,3.0)
            feed(0f,2,49.0001)
            assertNotNull(journal.stoppedTripSnapshot())
            journal.endStoppedTrip(id)
            val saved=journal.history().single()
            assertEquals("ended",saved.getString("state"));assertFalse(saved.has("odo_end"))
            assertEquals("Startstraße\nKarlsruhe",saved.getString("start_place"))
            assertEquals("Zielstraße\nKarlsruhe",saved.getString("end_place"))
            feed(0f,3,49.01)
            journal.lifecycle(false);journal.lifecycle(true)
            journal.saveEndedTripOdometer(id,123456)
            val after=journal.history().single()
            assertEquals(123456,after.getInt("odo_end"))
            listOf("start","end","distance","duration","start_place","end_place").forEach {assertEquals(it,saved.opt(it),after.opt(it))}
            val canonical=org.json.JSONObject(File(journal.export(id),"journal.json").readText()).getJSONObject("trip")
            assertEquals("Startstraße\nKarlsruhe",canonical.getString("start_place"))
            java.util.zip.ZipFile(journal.archive(id,TripExportOptions(masked=true))).use {zip ->
                val masked=org.json.JSONObject(zip.getInputStream(zip.getEntry("journal.json")).bufferedReader().readText()).getJSONObject("trip")
                assertFalse(masked.has("start_place"));assertFalse(masked.has("end_place"))
            }

        }
        SQLiteDatabase.openDatabase(File(context.filesDir,"trip-journal/trips.sqlite").path,null,SQLiteDatabase.OPEN_READWRITE).use {db ->db.execSQL("DELETE FROM events")}
        TripJournal(context,heartbeat=false).use {reopened ->
            val saved=reopened.history().single()
            assertEquals("Startstraße\nKarlsruhe",saved.getString("start_place"))
            assertEquals(1,saved.getInt("history_version"))
        }
    }

}
