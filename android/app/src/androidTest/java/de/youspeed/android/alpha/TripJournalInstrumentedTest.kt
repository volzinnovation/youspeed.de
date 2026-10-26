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
    @Test fun endpointSeparationUsesStrictHundredMetreBoundary() {
        for(metres in listOf(99.999,100.001,1000.0)) {
            val latitude=metres/6_371_008.8*180/Math.PI
            assertEquals(metres,TripJournal.endpointSeparationMeters(0.0,0.0,latitude,0.0),0.000001)
        }
    }
    @Test fun shortLoopIsDiscardedWithoutEditorAndCountersOrMediaAreNotDeleted() = withJournalRoot {context,_ ->
        var tick=0L
        val wall=System.currentTimeMillis()/1000.0
        TripJournal(context,heartbeat=false,wallClock={wall+tick},elapsedClock={tick*1000}).use {journal ->
            journal.setEnabled(true);journal.start()
            val id=journal.snapshot().first.single().getString("id")
            fun feed(latitude:Double,speed:Float=10f) {
                journal.location(android.location.Location("gps").apply {
                    this.latitude=latitude;longitude=8.0;accuracy=3f;this.speed=speed
                    time=((wall+tick)*1000).toLong();elapsedRealtimeNanos=(tick+1)*1_000_000_000L
                });journal.snapshot();tick++
            }
            for(latitude in listOf(49.0,49.0005,49.001,49.0005,49.0)) feed(latitude)
            journal.bind("short-loop")
            val before=journal.snapshot()
            assertTrue(before.first.single().getDouble("distance")>200)
            val exported=journal.export(id)
            val media=File(context.filesDir,"independent.jpg").apply {writeText("retained media")}
            feed(49.0,0f)
            assertNull(journal.stoppedTripSnapshot())
            assertTrue(runCatching {journal.endStoppedTrip(id)}.isFailure)
            journal.stop();journal.completeFinalizerForTesting()
            assertTrue(journal.history().isEmpty())
            assertEquals(before.second.getDouble("distance"),journal.snapshot().second.getDouble("distance"),0.0)
            assertFalse(exported.exists());assertTrue(media.exists())
            journal.media("short-loop","late",media.path,"photo");journal.tsr("late",emptyMap())
            assertTrue(journal.events(id).isEmpty())
            journal.newTrip();feed(49.0001)
            assertTrue(journal.history().isEmpty());assertNotEquals(id,journal.snapshot().first.single().getString("id"))
        }
    }
    @Test fun finalizerDropsShortTripAndRecoveryDropsEmptySession() = withJournalRoot {context,_ ->
        TripJournal(context,heartbeat=false).use {journal ->
            journal.setEnabled(true);journal.start()
            val id=journal.snapshot().first.single().getString("id")
            journal.stop();assertEquals("finalizing",journal.snapshot().first.single().getString("state"))
            assertTrue(journal.history().isEmpty())
            journal.completeFinalizerForTesting()
            assertTrue(journal.history().isEmpty());assertTrue(journal.events(id).isEmpty())
            journal.newTrip();assertEquals(1,journal.snapshot().first.size);assertTrue(journal.history().isEmpty())
        }
        TripJournal(context,heartbeat=false).use {journal -> assertTrue(journal.history().isEmpty())}
    }
    @Test fun stopAndVisibleHistoryRequireCurrentEndpointSeparationOfHundredMetres() = withJournalRoot {context,_ ->
        var tick=0L
        val wall=System.currentTimeMillis()/1000.0
        TripJournal(context,heartbeat=false,wallClock={wall+tick},elapsedClock={tick*1000}).use {journal ->
            journal.setEnabled(true);journal.start()
            val id=journal.snapshot().first.single().getString("id")
            fun feed(metres:Double,accuracyMetres:Float=3f) {
                journal.location(android.location.Location("gps").apply {
                    latitude=49+metres/6_371_008.8*180/Math.PI;longitude=8.0;accuracy=accuracyMetres;speed=0f
                    time=((wall+tick)*1000).toLong();elapsedRealtimeNanos=(tick+1)*1_000_000_000L
                });journal.snapshot();tick++
            }
            assertTrue(journal.history().isEmpty())
            feed(0.0);feed(50.0);feed(99.999)
            assertNull(journal.stoppedTripSnapshot());assertTrue(journal.history().isEmpty())
            assertEquals("Keep evidence buffered before the threshold",1,journal.snapshot().first.size)
            feed(100.001)
            assertNotNull(journal.stoppedTripSnapshot());assertEquals(1,journal.history().size)
            feed(0.0,100f);assertEquals(1,journal.history().size)
            feed(10.0)
            assertNull(journal.stoppedTripSnapshot());assertTrue(journal.history().isEmpty())
            assertTrue(runCatching {journal.endStoppedTrip(id)}.isFailure)
            assertEquals("Returning near the start hides the active trip without deleting it",1,journal.snapshot().first.size)
            feed(150.0)
            assertNotNull(journal.stoppedTripSnapshot());assertEquals(1,journal.history().size)
        }
    }
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
            val at=System.currentTimeMillis()
            for((index,lat) in listOf(49.0,49.001).withIndex()) journal.location(android.location.Location("gps").apply {
                latitude=lat;longitude=8.0;accuracy=3f;speed=10f;time=at+index*2000;elapsedRealtimeNanos=(index+1)*2_000_000_000L
            })
            journal.snapshot()
            assertNull(journal.error)
        }
        TripJournal(context,heartbeat=false).use { reopened ->
            val saved=reopened.snapshot().first.single()
            assertEquals(tripID,saved.getString("id"))
            assertEquals("interrupted",saved.getString("state"))
            assertEquals(4,reopened.events(tripID).size)
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
                    latitude=if(at==0L) 49.0 else if(at<=18L) 49.001 else 49.002;longitude=8.0;accuracy=3f;this.speed=speed
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
            feed(10f,2,49.001)
            journal.matchedPlace(wall+2,"Zielstraße","Karlsruhe",49.001,8.0,3.0)
            feed(0f,3,49.001)
            assertNotNull(journal.stoppedTripSnapshot())
            journal.endStoppedTrip(id)
            val saved=journal.history().single()
            assertEquals("ended",saved.getString("state"));assertFalse(saved.has("odo_end"))
            assertEquals("Startstraße\nKarlsruhe",saved.getString("start_place"))
            assertEquals("Zielstraße\nKarlsruhe",saved.getString("end_place"))
            feed(0f,4,49.01)
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
            assertEquals(2,saved.getInt("history_version"))
        }
    }

    @Test fun delayedPlaceCallbacksAreIncludedBeforeHistoryIsFrozen() = withJournalRoot {context,_ ->
        var wall=System.currentTimeMillis()/1000.0
        var elapsed=10000L
        TripJournal(context,heartbeat=false,wallClock={wall},elapsedClock={elapsed}).use {journal ->
            journal.setEnabled(true);journal.start()
            val id=journal.snapshot().first.single().getString("id")
            val at=wall
            fun feed(lat:Double) {journal.location(android.location.Location("gps").apply {
                latitude=lat;longitude=8.0;accuracy=3f;speed=10f;time=(wall*1000).toLong();elapsedRealtimeNanos=elapsed*1_000_000
            });journal.snapshot()}
            feed(49.0);wall+=2;elapsed+=2000;feed(49.001)
            journal.stop()
            val pending=journal.history().single()
            assertEquals(0,pending.getInt("history_version"))
            journal.matchedPlace(at,"Startstraße","Karlsruhe",49.0,8.0,3.0)
            journal.matchedPlace(at+2,"Zielstraße","Karlsruhe",49.001,8.0,3.0)
            assertEquals(2,journal.events(id).count {it.optString("kind")=="place"})
            journal.setEnabled(false)
            journal.matchedPlace(at,"Declined",null,49.0,8.0,3.0)
            assertEquals(2,journal.events(id).count {it.optString("kind")=="place"})
            journal.setEnabled(true);journal.lifecycle(false)
            journal.matchedPlace(at,"Background",null,49.0,8.0,3.0)
            assertEquals(2,journal.events(id).count {it.optString("kind")=="place"})
            journal.lifecycle(true)
            journal.completeFinalizerForTesting()
            val saved=journal.history().single()
            assertEquals("Startstraße\nKarlsruhe",saved.getString("start_place"))
            assertEquals("Zielstraße\nKarlsruhe",saved.getString("end_place"))
            assertEquals(2,saved.getInt("history_version"))
            listOf("distance","end","duration").forEach {assertEquals(it,pending.opt(it),saved.opt(it))}
            journal.matchedPlace(at,"Too late",null,49.0,8.0,3.0)
            assertEquals(2,journal.events(id).count {it.optString("kind")=="place"})
        }
    }

    @Test fun missingVersionOneNamesAreRepairedOnceWithoutReplacingSavedNames() = withJournalRoot {context,_ ->
        var wall=System.currentTimeMillis()/1000.0
        var before=org.json.JSONObject()
        TripJournal(context,heartbeat=false,wallClock={wall}).use {journal ->
            journal.setEnabled(true);journal.start();journal.snapshot()
            journal.location(android.location.Location("gps").apply {
                latitude=49.0;longitude=8.0;accuracy=3f;speed=10f;time=(wall*1000).toLong();elapsedRealtimeNanos=1_000_000_000
            })
            journal.matchedPlace(wall,"Captured",null,49.0,8.0,3.0)
            wall+=2
            journal.location(android.location.Location("gps").apply {
                latitude=49.001;longitude=8.0;accuracy=3f;speed=10f;time=(wall*1000).toLong();elapsedRealtimeNanos=3_000_000_000
            })
            journal.matchedPlace(wall,"Captured",null,49.001,8.0,3.0)
            journal.stop();journal.completeFinalizerForTesting()
            before=journal.history().single()
        }
        val database=File(context.filesDir,"trip-journal/trips.sqlite")
        SQLiteDatabase.openDatabase(database.path,null,SQLiteDatabase.OPEN_READWRITE).use {db ->
            db.execSQL("UPDATE trips SET start_place='Preserved',end_place=NULL,history_version=1")
        }
        TripJournal(context,heartbeat=false).use {repaired ->
            val after=repaired.history().single()
            assertEquals("Preserved",after.getString("start_place"))
            assertEquals("Captured",after.getString("end_place"))
            assertEquals(2,after.getInt("history_version"))
            listOf("distance","end","duration").forEach {assertEquals(it,before.opt(it),after.opt(it))}
        }
        SQLiteDatabase.openDatabase(database.path,null,SQLiteDatabase.OPEN_READWRITE).use {db ->
            db.execSQL("DELETE FROM events");db.execSQL("UPDATE trips SET end_place=NULL")
        }
        TripJournal(context,heartbeat=false).use {reopened ->
            val stable=reopened.history().single()
            assertEquals("Preserved",stable.getString("start_place"));assertFalse(stable.has("end_place"))
            assertEquals(2,stable.getInt("history_version"))
        }
    }
}
