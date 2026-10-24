package de.youspeed.android.alpha

import android.content.Context
import android.content.ContextWrapper
import android.content.SharedPreferences
import android.location.Location
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.util.UUID
import java.util.zip.ZipFile

@RunWith(AndroidJUnit4::class)
class TripJournalAcceptanceInstrumentedTest {
    private class Clock(var wall:Double=1_800_000_000.0,var elapsed:Long=10000) {
        fun advance(seconds:Double) {wall+=seconds;elapsed+=(seconds*1000).toLong()}
        fun fix(latitude:Double,longitude:Double=8.0)=Location("gps").apply {
            this.latitude=latitude;this.longitude=longitude;accuracy=3f;speed=10f;time=(wall*1000).toLong();elapsedRealtimeNanos=elapsed*1_000_000
        }
    }
    private fun isolated(test:(Context,Clock,TripJournal)->Unit) {
        val base=InstrumentationRegistry.getInstrumentation().targetContext
        val root=File(base.cacheDir,"journal-acceptance-${UUID.randomUUID()}").apply {mkdirs()}
        val preferenceName="journal-acceptance-${UUID.randomUUID()}"
        val context=object:ContextWrapper(base) {
            override fun getFilesDir()=File(root,"files").apply {mkdirs()}
            override fun getCacheDir()=File(root,"cache").apply {mkdirs()}
            override fun getSharedPreferences(name:String,mode:Int):SharedPreferences=base.getSharedPreferences(preferenceName,mode)
        }
        val clock=Clock()
        try {TripJournal(context,false,{clock.wall},{clock.elapsed}).use {test(context,clock,it)}} finally {base.deleteSharedPreferences(preferenceName);root.deleteRecursively()}
    }
    @Test fun gpsRetriesAndStorageOptOutDoNotDuplicateOrRetainPrivateTrack()=isolated { _,clock,journal ->
        journal.setEnabled(true);journal.start();val id=journal.snapshot().first.single().getString("id")
        journal.location(clock.fix(48.0));journal.snapshot();clock.advance(1.0)
        val second=clock.fix(48.0001);journal.location(second)
        val after=journal.snapshot();val measured=after.second.getDouble("distance");assertTrue(measured>10)
        journal.location(second);assertEquals(measured,journal.snapshot().second.getDouble("distance"),0.0)
        assertEquals("duplicate_or_out_of_order",TripJournalProjection.payload(journal.events(id).last()).getString("reason"))
        journal.setEnabled(false);journal.snapshot();val count=journal.events(id).size
        clock.advance(1.0);journal.location(clock.fix(48.0002));journal.snapshot()
        clock.advance(1.0);journal.location(clock.fix(48.0003))
        val disabled=journal.snapshot()
        assertEquals(1,disabled.first.size);assertEquals("ended",disabled.first.single().getString("state"))
        assertEquals(count,journal.events(id).size);assertTrue(disabled.second.getDouble("distance")>measured)
        journal.setEnabled(true);assertEquals(2,journal.snapshot().first.size)
    }
    @Test fun historyCountsRecordedMediaAndDiscoveryIdentitiesWithoutDuplicatingUpdates()=isolated { _,clock,journal ->
        journal.setEnabled(true);journal.start();journal.snapshot();journal.bind("capture");journal.snapshot()
        journal.media("capture","photo-1","/evicted.jpg","photo",clock.wall)
        journal.media("capture","photo-1","https://api.panoramax.xyz/api/pictures/photo-1","photo_remote",clock.wall)
        journal.media("capture","video-1","/evicted.mp4","video",clock.wall)
        journal.media("capture","video-1","/evicted.mp4","video",clock.wall,metadata=mapOf("duration_s" to 12.0))
        repeat(2) {journal.signEvent(mapOf("source" to "government","evidence_id" to "sign-1","class_code" to "DE:274-50"),clock.wall)}
        val trip=journal.snapshot().first.single()
        assertEquals(1,trip.getInt("photo_count"));assertEquals(1,trip.getInt("video_count"));assertEquals(2,trip.getInt("media_count"));assertEquals(1,trip.getInt("sign_count"))
    }
    @Test fun droppedWriterEventsStartANewDistanceSegment()=isolated { _,clock,journal ->
        journal.setEnabled(true);journal.start();val id=journal.snapshot().first.single().getString("id")
        journal.location(clock.fix(48.0));journal.snapshot()
        val backlog=TripJournal::class.java.getDeclaredField("backlog").apply {isAccessible=true}.get(journal) as java.util.concurrent.atomic.AtomicInteger
        backlog.set(4096);clock.advance(1.0);journal.location(clock.fix(48.0001));backlog.set(0)
        clock.advance(1.0);journal.location(clock.fix(48.0002))
        assertEquals(0.0,journal.snapshot().second.getDouble("distance"),0.0)
        val gap=journal.events(id).single {it.optString("kind")=="gap"}
        assertEquals(1,TripJournalProjection.payload(gap).getInt("events_lost"))
        assertEquals("segment_start",TripJournalProjection.payload(journal.events(id).last()).getString("reason"))
    }
    @Test fun nonFiniteOriginalMetricsRemainRejectedLogEvidenceAndDoNotFailTheStore()=isolated { _,clock,journal ->
        journal.setEnabled(true);journal.start();val id=journal.snapshot().first.single().getString("id")
        journal.location(clock.fix(Double.NaN,Double.POSITIVE_INFINITY).apply {accuracy=Float.NaN;speed=Float.NaN;altitude=Double.POSITIVE_INFINITY})
        journal.tsr("non_finite_score",mapOf("score" to Double.NaN));journal.snapshot()
        val gps=TripJournalProjection.payload(journal.events(id).single {it.optString("kind")=="gps"})
        listOf("latitude","longitude","accuracy","speed","altitude","course").forEach {assertTrue(it,gps.isNull(it))}
        assertFalse(gps.getBoolean("valid"));assertEquals(0.0,journal.snapshot().second.getDouble("distance"),0.0);assertNull(journal.error)
        assertTrue(TripJournalProjection.payload(journal.events(id).single {it.optString("kind")=="tsr"}).getJSONObject("details").isNull("score"))
    }
    @Test fun networkOnlyFixCannotBridgeOrInflateGnssDistance()=isolated { _,clock,journal ->
        journal.setEnabled(true);journal.start();val id=journal.snapshot().first.single().getString("id")
        journal.location(clock.fix(48.0));journal.snapshot();clock.advance(1.0)
        journal.location(clock.fix(48.0002).apply {provider=android.location.LocationManager.NETWORK_PROVIDER})
        assertEquals(0.0,journal.snapshot().second.getDouble("distance"),0.0)
        val network=TripJournalProjection.payload(journal.events(id).last());assertEquals("network_only",network.getString("reason"));assertFalse(network.getBoolean("track_eligible"))
        clock.advance(1.0);journal.location(clock.fix(48.0004));assertEquals(0.0,journal.snapshot().second.getDouble("distance"),0.0)
    }
    @Test fun suspensionGracePreservesGapsAndNeverExtendsAbandonedEndpoint()=isolated { _,clock,journal ->
        journal.setEnabled(true);journal.start();val initial=journal.snapshot().first.single().getString("id")
        clock.advance(10.0);journal.lifecycle(false);val checkpoint=journal.snapshot().first.single().getDouble("end")
        clock.advance(120.0);journal.lifecycle(true)
        assertEquals(initial,journal.snapshot().first.single().getString("id"))
        assertEquals(10.0,journal.snapshot().second.getDouble("usage"),0.001)
        assertEquals(1,journal.events(initial).count {it.optString("kind")=="gap"})
        clock.advance(5.0);journal.lifecycle(false);val last=journal.snapshot().first.single().getDouble("end")
        assertTrue(last>checkpoint)
        clock.advance(301.0);journal.lifecycle(true);val resumed=journal.snapshot()
        assertEquals(2,resumed.first.size)
        val old=resumed.first.single {it.getString("id")==initial}
        assertEquals("interrupted",old.getString("state"));assertEquals(last,old.getDouble("end"),0.0)
        assertEquals(15.0,resumed.second.getDouble("usage"),0.001)
    }
    @Test fun encryptedReplacementRestoreKeepsEpochAndCountersOnceAndRejectsDamage()=isolated { _,clock,journal ->
        journal.setEnabled(true);journal.start();val id=journal.snapshot().first.single().getString("id")
        journal.location(clock.fix(48.0));journal.snapshot();clock.advance(1.0);journal.location(clock.fix(48.0001));journal.snapshot()
        val before=journal.snapshot().second
        val backup=journal.backup("test secret passphrase")
        assertFalse(backup.readText().contains(id));assertFalse(backup.readText().contains("48.0001"))
        assertTrue(runCatching {journal.backupPreview(backup,"wrong password")}.isFailure)
        journal.restore(backup,"test secret passphrase");journal.restore(backup,"test secret passphrase")
        val restored=journal.snapshot()
        assertEquals(1,restored.first.size);assertEquals("interrupted",restored.first.single().getString("state"))
        assertEquals(before.getDouble("origin"),restored.second.getDouble("origin"),0.0)
        assertEquals(before.getDouble("distance"),restored.second.getDouble("distance"),0.0)
        assertEquals(before.getDouble("usage"),restored.second.getDouble("usage"),0.0)
        val bad=JSONObject(backup.readText()).put("sha256","invalid");backup.writeText(bad.toString())
        assertTrue(runCatching {journal.restore(backup,"test secret passphrase")}.isFailure)
        assertEquals(before.getDouble("distance"),journal.snapshot().second.getDouble("distance"),0.0)
    }
    @Test fun savedTripEndingOdometerIsOptionalWriteOnceAndNeverChangesActiveTripOrCounters()=isolated { _,clock,journal ->
        journal.setEnabled(true);journal.start();val id=journal.snapshot().first.single().getString("id")
        journal.odometer(id,12000.0,null);journal.snapshot();journal.location(clock.fix(48.0));journal.snapshot();clock.advance(1.0);journal.location(clock.fix(48.0001));journal.stop();journal.snapshot();clock.advance(6.0);journal.completeFinalizerForTesting();journal.snapshot()
        assertEquals("ended",journal.snapshot().first.single().getString("state"))
        journal.newTrip();val current=journal.snapshot().first.first {it.getString("id")!=id}.getString("id");val before=journal.snapshot().second.toString()
        for(value in listOf(Double.NaN,Double.POSITIVE_INFINITY,-1.0,11999.9)) assertTrue(runCatching {journal.setEndingOdometer(id,value)}.isFailure)
        assertTrue(journal.setEndingOdometer(id,12000.5));assertFalse(journal.setEndingOdometer(id,12001.0))
        val saved=journal.snapshot();assertEquals(before,saved.second.toString());assertEquals(12000.5,saved.first.single {it.getString("id")==id}.getDouble("odo_end"),0.0)
        assertEquals("active",saved.first.single {it.getString("id")==current}.getString("state"));assertFalse(saved.first.single {it.getString("id")==current}.has("odo_end"))
        assertEquals(1,journal.events(id).count {it.optString("kind")=="odometer_entry" && TripJournalProjection.payload(it).optString("position")=="end"})
    }
    @Test fun endpointPlaceEvidenceRespectsFixDistanceTimeAndGapBoundaries() {
        fun event(kind:String,time:Double,payload:JSONObject)=JSONObject().put("kind",kind).put("time",time).put("payload",payload.toString())
        fun point(lat:Double=48.0)=JSONObject().put("latitude",lat).put("longitude",8.0).put("accuracy",3.0).put("valid",true).put("track_eligible",true)
        val trip=JSONObject();val fix=event("gps",1000.0,point());val own=event("place",1000.0,point().put("street_name","A long street name").put("city_name","Town"))
        assertEquals("A long street name\nTown",TripJournalProjection.endpointPlaces(trip,listOf(fix,own,event("gap",1000.0,JSONObject()))).first)
        val earlier=event("place",999.0,point().put("street_name","Earlier street"))
        assertNull(TripJournalProjection.endpointPlaces(trip,listOf(earlier,event("gap",1000.0,JSONObject()),fix)).first)
        assertNull(TripJournalProjection.endpointPlaces(trip,listOf(fix,event("place",984.0,point().put("street_name","Old street")))).first)
        assertNull(TripJournalProjection.endpointPlaces(trip,listOf(fix,event("place",1000.0,point(48.001).put("street_name","Distant street")))).first)
        assertEquals("Saved place",TripJournalProjection.endpointPlaces(JSONObject().put("start_place","Saved place"),listOf(fix,own)).first)
    }
    @Test fun matchedPlaceKeepsStorageOptOutForegroundAndEndedLatch()=isolated { _,clock,journal ->
        journal.start();journal.matchedPlace(clock.wall,"Ignored","Town",48.0,8.0,3.0);assertTrue(journal.snapshot().first.isEmpty())
        journal.setEnabled(true);val id=journal.snapshot().first.single().getString("id");journal.location(clock.fix(48.0));journal.matchedPlace(clock.wall,"Street","Town",48.0,8.0,3.0)
        assertEquals("Street\nTown",journal.snapshot().first.single().getString("start_place"))
        journal.lifecycle(false);journal.matchedPlace(clock.wall,"Background","Town",48.0,8.0,3.0);journal.lifecycle(true);journal.snapshot()
        journal.stop();journal.matchedPlace(clock.wall,"Late","Town",48.0,8.0,3.0);journal.snapshot();journal.setEnabled(false);journal.matchedPlace(clock.wall,"Disabled","Town",48.0,8.0,3.0)
        journal.snapshot();assertEquals(1,journal.events(id).count {it.optString("kind")=="place"})
    }
    @Test fun canonicalArchiveIncludesLosslessLogsAndMaskedCopyCannotLeakRawEvidence()=isolated { _,clock,journal ->
        journal.setEnabled(true);journal.start();val id=journal.snapshot().first.single().getString("id")
        for(i in 0..6) {journal.location(clock.fix(48.0+i*0.0005));journal.snapshot();clock.advance(1.0)}
        journal.tsr("recognition",mapOf("private_road" to "SECRET-HOME-ROAD"))
        journal.signEvent(mapOf("class_code" to "DE:274-50","source" to "camera","evidence_id" to "endpoint-sign","latitude" to 48.0,"longitude" to 8.0))
        journal.snapshot()
        val full=journal.archive(id)
        ZipFile(full).use { zip ->
            listOf("journal.json","trip.json","track.gpx","track.geojson","gps.ndjson","tsr.ndjson","sign.json","media.json","overview.pdf","manifest.json").forEach {assertNotNull(it,zip.getEntry(it))}
            val normalized=JSONObject(zip.getInputStream(zip.getEntry("journal.json")).bufferedReader().readText())
            assertEquals("metre",normalized.getJSONObject("units").getString("distance"))
            assertTrue(normalized.getJSONArray("events").length()>6)
            assertTrue(normalized.getJSONArray("events").getJSONObject(0).get("payload") is JSONObject)
            assertEquals(id,normalized.getJSONObject("trip").getString("id"))
            File(InstrumentationRegistry.getInstrumentation().targetContext.filesDir,"journal-validation-canonical.json").writeText(normalized.toString())
        }
        val masked=journal.archive(id,TripExportOptions(masked=true,maskRadiusMetres=70.0,includeRawLogs=true))
        ZipFile(masked).use {zip ->
            zip.entries().asSequence().filter {it.name.endsWith(".json") || it.name.endsWith(".ndjson") || it.name.endsWith(".csv") || it.name.endsWith(".gpx")}.forEach { entry ->
                val text=zip.getInputStream(entry).bufferedReader().readText()
                assertFalse(entry.name,text.contains("SECRET-HOME-ROAD"));assertFalse(entry.name,text.contains("endpoint-sign"))
            }
            assertEquals("",zip.getInputStream(zip.getEntry("gps.ndjson")).bufferedReader().readText())
            val manifest=JSONObject(zip.getInputStream(zip.getEntry("manifest.json")).bufferedReader().readText())
            assertTrue(manifest.getBoolean("masked"));assertFalse(manifest.getBoolean("raw_logs_included"))
            File(InstrumentationRegistry.getInstrumentation().targetContext.filesDir,"journal-validation-masked.json").writeText(zip.getInputStream(zip.getEntry("journal.json")).bufferedReader().readText())
        }
        journal.delete(id);assertTrue(journal.snapshot().first.isEmpty());assertFalse(full.exists());assertFalse(masked.exists())
    }
    @Test fun maskedSelectedPhotoStripsGpsAndPreservesOriginalAndUnknownPositionIsExcluded()=isolated { context,clock,journal ->
        journal.setEnabled(true);journal.start();val id=journal.snapshot().first.single().getString("id")
        for(i in 0..6) {journal.location(clock.fix(48.0+i*0.0005));journal.snapshot();clock.advance(1.0)}
        val original=File(context.filesDir,"sample.jpg")
        val bitmap=android.graphics.Bitmap.createBitmap(16,8,android.graphics.Bitmap.Config.ARGB_8888)
        original.outputStream().use {bitmap.compress(android.graphics.Bitmap.CompressFormat.JPEG,95,it)};bitmap.recycle()
        androidx.exifinterface.media.ExifInterface(original).apply {setLatLong(48.0015,8.0);setAttribute(androidx.exifinterface.media.ExifInterface.TAG_ORIENTATION,androidx.exifinterface.media.ExifInterface.ORIENTATION_ROTATE_90.toString());saveAttributes()}
        val bytes=original.readBytes();val measured=journal.snapshot().second.getDouble("distance")
        journal.bind("photo-session");journal.media("photo-session","visible",original.path,"photo",clock.wall-4,metadata=mapOf("latitude" to 48.0015,"longitude" to 8.0,"accuracy" to 3.0))
        journal.media("photo-session","unknown",original.path,"photo",clock.wall-100)
        journal.snapshot()
        val archive=journal.archive(id,TripExportOptions(masked=true,maskRadiusMetres=70.0,selectedMedia=setOf("visible","unknown")))
        ZipFile(archive).use { zip ->
            val files=zip.entries().asSequence().filter {it.name.startsWith("media/")}.toList();assertEquals(1,files.size)
            val copy=File(context.cacheDir,"redacted.jpg");copy.writeBytes(zip.getInputStream(files.single()).readBytes())
            assertNull(androidx.exifinterface.media.ExifInterface(copy).latLong)
            val upright=android.graphics.BitmapFactory.decodeFile(copy.path)
            try {assertEquals(8,upright.width);assertEquals(16,upright.height)} finally {upright.recycle()}
            val media=JSONObject(zip.getInputStream(zip.getEntry("media.json")).bufferedReader().readText()).getJSONArray("media")
            assertEquals(1,media.length());assertEquals("visible",media.getJSONObject(0).getString("id"));assertFalse(media.getJSONObject(0).has("path"))
        }
        assertArrayEquals(bytes,original.readBytes());assertEquals(measured,journal.snapshot().second.getDouble("distance"),0.0)
    }

    @Test fun installedOfflineRoadContextReadsNamedGeometryWithoutChangingBundle()=isolated { context,clock,journal ->
        journal.setEnabled(true);journal.start();val id=journal.snapshot().first.single().getString("id")
        journal.location(clock.fix(48.0));journal.snapshot();clock.advance(1.0);journal.location(clock.fix(48.0001));journal.snapshot()
        val bundle=File(context.filesDir,"map.sqlite")
        android.database.sqlite.SQLiteDatabase.openOrCreateDatabase(bundle,null).use {db ->
            db.execSQL("CREATE TABLE ways(way_id INTEGER PRIMARY KEY,street_name TEXT,ref TEXT,highway TEXT,min_lon REAL,max_lon REAL,min_lat REAL,max_lat REAL)")
            db.execSQL("CREATE TABLE way_geom(way_id INTEGER PRIMARY KEY,points_json TEXT)")
            db.execSQL("INSERT INTO ways VALUES(1,'Hauptstraße',NULL,'residential',7.99,8.01,47.99,48.01)")
            db.execSQL("INSERT INTO way_geom VALUES(1,'[[47.999,8.0],[48.001,8.0]]')")
        }
        val bytes=bundle.readBytes()
        val result=TripJournalMapContext.load(bundle.path,journal.events(id))
        assertEquals("Hauptstraße",result.roads.single().name)
        assertEquals(47.999,result.roads.single().points.first().first,0.0)
        assertArrayEquals(bytes,bundle.readBytes())
    }

    @Test fun odometerRetainsEnteredMilesAndIsWriteOnceWithDisclosureOptIn()=isolated { _,clock,journal ->
        journal.setEnabled(true);journal.start();val id=journal.snapshot().first.single().getString("id")
        journal.odometer(id,100.0,null,"mi");journal.odometer(id,999.0,null,"km");journal.odometer(id,null,100.0,"km");journal.snapshot()
        assertEquals(160.9344,journal.snapshot().first.single().getDouble("odo_start"),0.000001)
        assertFalse(journal.snapshot().first.single().has("odo_end"))
        journal.odometer(id,null,101.0,"mi");journal.snapshot()
        val entry=journal.events(id).filter {it.optString("kind")=="odometer_entry"}.map(TripJournalProjection::payload)
        assertEquals(2,entry.size);assertEquals("mi",entry.first().getString("entered_unit"));assertEquals(100.0,entry.first().getDouble("entered_value"),0.0)
        ZipFile(journal.archive(id)).use {zip ->
            val normalized=JSONObject(zip.getInputStream(zip.getEntry("journal.json")).bufferedReader().readText())
            assertTrue(normalized.getJSONObject("trip").isNull("odometer_start_km"))
            assertFalse(zip.getInputStream(zip.getEntry("journal.json")).bufferedReader().readText().contains("entered_value"))
        }
        ZipFile(journal.archive(id,TripExportOptions(includeOdometer=true))).use {zip ->
            val normalized=JSONObject(zip.getInputStream(zip.getEntry("journal.json")).bufferedReader().readText())
            assertEquals(160.9344,normalized.getJSONObject("trip").getDouble("odometer_start_km"),0.000001)
        }
    }

    @Test fun stopIntentDrainsOnlyOwnedPreEndSignsAndLatchPreventsRecompositionRestart()=isolated { _,clock,journal ->
        journal.setEnabled(true);journal.start();val id=journal.snapshot().first.single().getString("id")
        clock.advance(10.0);val intent=clock.wall;journal.stop();journal.snapshot()
        assertEquals("finalizing",journal.snapshot().first.single().getString("state"))
        clock.advance(1.0);journal.signEvent(mapOf("evidence_id" to "inside","class_code" to "DE:310","source" to "camera"),intent-0.5)
        journal.signEvent(mapOf("evidence_id" to "outside","class_code" to "DE:311","source" to "camera"),clock.wall)
        journal.start();journal.snapshot();assertEquals(1,journal.snapshot().first.size)
        journal.completeFinalizerForTesting()
        val closed=journal.snapshot().first.single();assertEquals("ended",closed.getString("state"));assertEquals(intent,closed.getDouble("end"),0.0);assertEquals(10.0,closed.getDouble("duration"),0.0)
        val signs=journal.events(id).filter {it.optString("kind")=="sign"};assertEquals(1,signs.size);assertEquals("inside",TripJournalProjection.payload(signs.single()).getString("evidence_id"))
        journal.signEvent(mapOf("evidence_id" to "too-late"),intent-1);journal.snapshot();assertEquals(1,journal.events(id).count {it.optString("kind")=="sign"})
    }

    @Test fun clearAllResetsEpochWhileTripDeletionKeepsLifetimeCountersAndLateMediaCannotResurrect()=isolated { _,clock,journal ->
        journal.setEnabled(true);journal.start();val id=journal.snapshot().first.single().getString("id")
        journal.bind("owned-capture");journal.location(clock.fix(48.0));journal.snapshot();clock.advance(1.0);journal.location(clock.fix(48.0001));journal.snapshot()
        val before=journal.snapshot().second.getDouble("distance")
        journal.delete(id);journal.media("owned-capture","photo-1","/missing.jpg","photo");assertTrue(journal.snapshot().first.isEmpty());assertTrue(journal.events(id).isEmpty())
        assertEquals(before,journal.snapshot().second.getDouble("distance"),0.0)
        clock.advance(10.0);journal.clearAll();val cleared=journal.snapshot()
        assertTrue(cleared.first.isEmpty());assertEquals(0.0,cleared.second.getDouble("distance"),0.0);assertEquals(0.0,cleared.second.getDouble("usage"),0.0);assertEquals(clock.wall,cleared.second.getDouble("origin"),0.0)
    }
}
