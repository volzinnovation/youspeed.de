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
            override fun getNoBackupFilesDir()=File(root,"no-backup").apply {mkdirs()}
            override fun getSharedPreferences(name:String,mode:Int):SharedPreferences=base.getSharedPreferences(preferenceName,mode)
        }
        val clock=Clock()
        try {TripJournal(context,false,{clock.wall},{clock.elapsed}).use {test(context,clock,it)}} finally {base.deleteSharedPreferences(preferenceName);root.deleteRecursively()}
    }

    private fun libraryPhoto(context:Context,id:String,jpeg:File):File {
        val store=PanoramaxQueueStore(context)
        val batch=store.createBatch("photo-session")
        val at=java.time.Instant.now()
        val metadata=PanoramaxCaptureMetadata(id,batch.captureSessionId,at,PanoramaxLocationSample(48.0,8.0,at,3.0),PanoramaxQueueStore.sha256(jpeg),jpeg.length(),"YouSpeed/test")
        return store.originalFile(store.addJpeg(batch.batchId,jpeg,jpeg,metadata))
    }

    private fun libraryVideo(context:Context,id:String,bytes:ByteArray):File = File(context.filesDir,"dashcam/$id").apply {
        parentFile!!.mkdirs();writeBytes(bytes)
    }

    @Test fun restoredMediaUsesLibraryIdentityAndNeverImportedPathOrLocalPath()=isolated {context,clock,journal ->
        journal.setEnabled(true);journal.start();val trip=journal.snapshot().first.single().getString("id")
        journal.location(clock.fix(48.0));journal.snapshot();clock.advance(2.0);journal.location(clock.fix(48.001));journal.snapshot()
        val privateBytes="PRIVATE SENTINEL".toByteArray()
        val privateFile=File(context.filesDir,"private.sqlite").apply {writeBytes(privateBytes)}
        val originalBytes="LIBRARY ORIGINAL".toByteArray()
        val original=libraryVideo(context,"owned.mp4",originalBytes)
        journal.bind("capture")
        journal.media("capture","fake.mp4",privateFile.path,"video",clock.wall,metadata=mapOf("started_at" to clock.wall,"duration_s" to 10.0))
        journal.media("capture","wrong-photo",original.path,"photo",clock.wall)
        journal.media("capture","owned.mp4","/old-container/owned.mp4","video",clock.wall)
        val payload=journal.backupPayload()
        val entries=payload.getJSONArray("events")
        for(index in 0 until entries.length()) {
            val entry=entries.getJSONObject(index)
            if(entry.getString("kind")=="media") entry.put("payload",TripJournalProjection.payload(entry).put("local_path",privateFile.path).toString())
        }
        val backup=TripJournalFiles.backup(context,payload,"synthetic-password")
        journal.restore(backup,"synthetic-password")
        val projected=TripJournalProjection.media(journal.events(trip),journal.mediaLibrary)
        assertEquals("local_missing",projected.single {it.optString("id")=="fake.mp4"}.getString("availability"))
        assertEquals("local_missing",projected.single {it.optString("id")=="wrong-photo"}.getString("availability"))
        assertEquals(original.canonicalFile,File(projected.single {it.optString("id")=="owned.mp4"}.getString("path")).canonicalFile)
        assertNull(TripJournalProjection.seek(journal.events(trip),clock.wall+1,journal.mediaLibrary))
        listOf("../private.sqlite","nested/owned.mp4","","private.sqlite").forEach {assertNull(journal.mediaLibrary.open(it,"video"))}
        ZipFile(journal.archive(trip,TripExportOptions(selectedMedia=projected.map {it.getString("id")}.toSet()))).use {zip ->
            val copies=zip.entries().asSequence().filter {it.name.startsWith("media/")}.toList()
            assertEquals(1,copies.size);assertArrayEquals(originalBytes,zip.getInputStream(copies.single()).readBytes())
        }
        assertArrayEquals(privateBytes,privateFile.readBytes())
        original.delete()
        assertNull(journal.mediaLibrary.file("owned.mp4","video"))
    }

    @Test fun localMediaRejectsFinalAndParentSymlinksAndPinsOpenedOriginal()=isolated {context,clock,journal ->
        journal.setEnabled(true);journal.start();val trip=journal.snapshot().first.single().getString("id")
        val privateFile=File(context.filesDir,"private.mp4").apply {writeText("PRIVATE")}
        assertNull(journal.mediaLibrary.open("private.mp4","video"))
        val originalBytes="ORIGINAL".toByteArray()
        val original=libraryVideo(context,"owned.mp4",originalBytes)
        journal.bind("capture");journal.media("capture","owned.mp4",original.path,"video",clock.wall)
        val projected=TripJournalProjection.media(journal.events(trip),journal.mediaLibrary)
        assertEquals("local_original",projected.single().getString("availability"))
        journal.mediaLibrary.open("owned.mp4","video")!!.use {input ->
            assertTrue(original.delete());android.system.Os.symlink(privateFile.path,original.path)
            assertNull(journal.mediaLibrary.file("owned.mp4","video"));assertNull(journal.mediaLibrary.open("owned.mp4","video"))
            assertArrayEquals(originalBytes,input.readBytes())
            ZipFile(journal.archive(trip,TripExportOptions(selectedMedia=setOf("owned.mp4")))).use {zip ->
                assertFalse(zip.entries().asSequence().any {it.name.startsWith("media/")})
            }
        }
        assertTrue(original.delete());original.writeBytes(originalBytes)
        val outside=File(context.filesDir,"outside-library")
        assertTrue(original.parentFile!!.renameTo(outside));android.system.Os.symlink(outside.path,original.parentFile!!.path)
        assertNull(journal.mediaLibrary.open("owned.mp4","video"));assertTrue(original.parentFile!!.delete())
        val staged=File(context.cacheDir,"photo.jpg")
        val bitmap=android.graphics.Bitmap.createBitmap(2,2,android.graphics.Bitmap.Config.ARGB_8888)
        staged.outputStream().use {bitmap.compress(android.graphics.Bitmap.CompressFormat.JPEG,95,it)};bitmap.recycle()
        val photo=libraryPhoto(context,"photo",staged)
        assertNotNull(journal.mediaLibrary.file("photo","photo"))
        journal.media("capture","unknown-photo",photo.path,"photo",clock.wall)
        val forgedPhoto=TripJournalProjection.media(journal.events(trip),journal.mediaLibrary).single {it.optString("id")=="unknown-photo"}
        assertEquals("local_missing",forgedPhoto.getString("availability"));assertNull(journal.mediaLibrary.open("unknown-photo","photo"))
        val moved=File(context.filesDir,"outside-capture")
        assertTrue(photo.parentFile!!.renameTo(moved));android.system.Os.symlink(moved.path,photo.parentFile!!.path)
        assertNull(journal.mediaLibrary.file("photo","photo"));assertNull(journal.mediaLibrary.open("photo","photo"))
    }

    @Test fun remoteAndMissingPhotoMetadataRemainAvailableWithoutTrustingTheirLocators()=isolated {context,clock,journal ->
        val staged=File(context.cacheDir,"photo.jpg")
        val bitmap=android.graphics.Bitmap.createBitmap(2,2,android.graphics.Bitmap.Config.ARGB_8888)
        staged.outputStream().use {bitmap.compress(android.graphics.Bitmap.CompressFormat.JPEG,95,it)};bitmap.recycle()
        val original=libraryPhoto(context,"photo",staged)
        journal.setEnabled(true);journal.start();val trip=journal.snapshot().first.single().getString("id")
        journal.bind("capture");journal.media("capture","photo","/old-container/photo.jpg","photo",clock.wall)
        journal.media("capture","photo","https://example.invalid/?pic=photo","photo_remote",clock.wall)
        val projected=TripJournalProjection.media(journal.events(trip),journal.mediaLibrary)
        assertEquals(setOf("local_original","remote_reference"),projected.map {it.getString("availability")}.toSet())
        assertEquals("The trip library filter uses the queue's trusted path alias",original.absolutePath,
            projected.single {it.getString("availability")=="local_original"}.getString("path"))
        assertTrue(original.delete())
        val missing=TripJournalProjection.media(journal.events(trip),journal.mediaLibrary)
        assertEquals(setOf("local_missing","remote_reference"),missing.map {it.getString("availability")}.toSet())
        assertEquals(2,missing.size)
    }
    @Test fun gpsRetriesAndStorageOptOutDoNotDuplicateOrRetainPrivateTrack()=isolated { _,clock,journal ->
        journal.setEnabled(true);journal.start();val id=journal.snapshot().first.single().getString("id")
        journal.location(clock.fix(48.0));journal.snapshot();clock.advance(2.0)
        val second=clock.fix(48.001);journal.location(second)
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
        journal.location(clock.fix(48.0));journal.snapshot();clock.advance(2.0);journal.location(clock.fix(48.001));journal.snapshot()
        clock.advance(8.0);journal.lifecycle(false);val checkpoint=journal.snapshot().first.single().getDouble("end")
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
        journal.odometer(id,12000.0,null);journal.snapshot();journal.location(clock.fix(48.0));journal.snapshot();clock.advance(2.0);journal.location(clock.fix(48.001));journal.stop();journal.snapshot();clock.advance(6.0);journal.completeFinalizerForTesting();journal.snapshot()
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
        // Active rows have no frozen endpoint metadata; check the captured evidence.
        assertEquals("Street\nTown",TripJournalProjection.endpointPlaces(JSONObject(),journal.events(id)).first)
        journal.lifecycle(false);journal.matchedPlace(clock.wall,"Background","Town",48.0,8.0,3.0);journal.lifecycle(true);journal.snapshot()
        journal.stop();journal.matchedPlace(clock.wall,"Late","Town",48.0,8.0,3.0);journal.snapshot();journal.setEnabled(false);journal.matchedPlace(clock.wall,"Disabled","Town",48.0,8.0,3.0)
        journal.snapshot()
        assertEquals(listOf("Street","Late"),journal.events(id).filter {it.optString("kind")=="place"}.map {TripJournalProjection.payload(it).getString("street_name")})
    }
    @Test fun canonicalArchiveIncludesLosslessLogsAndMaskedCopyCannotLeakRawEvidence()=isolated { _,clock,journal ->
        journal.setEnabled(true);journal.start();val id=journal.snapshot().first.single().getString("id")
        for(i in 0..6) {journal.location(clock.fix(48.0+i*0.0005));journal.snapshot();clock.advance(1.0)}
        journal.tsr("recognition",mapOf("private_road" to "SECRET-HOME-ROAD"))
        journal.signEvent(mapOf("class_code" to "DE:274-50","source" to "camera","evidence_id" to "endpoint-sign","latitude" to 48.0,"longitude" to 8.0))
        journal.snapshot()
        val full=journal.archive(id,TripExportOptions(includeRawLogs=true))
        ZipFile(full).use { zip ->
            listOf("journal.json","trip.json","track.gpx","track.geojson","media.json","overview.pdf","manifest.json").forEach {assertNotNull(it,zip.getEntry(it))}
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
            assertNull(zip.getEntry("gps.ndjson"))
            val manifest=JSONObject(zip.getInputStream(zip.getEntry("manifest.json")).bufferedReader().readText())
            assertTrue(manifest.getBoolean("masked"));assertFalse(manifest.getBoolean("raw_logs_included"))
            File(InstrumentationRegistry.getInstrumentation().targetContext.filesDir,"journal-validation-masked.json").writeText(zip.getInputStream(zip.getEntry("journal.json")).bufferedReader().readText())
        }
        journal.delete(id);assertTrue(journal.snapshot().first.isEmpty());assertFalse(full.exists());assertFalse(masked.exists())
    }
    @Test fun compactArchiveKeepsTypedEvidenceOnceAndVerboseDiagnosticsRequireOptIn()=isolated { context,clock,_ ->
        fun event(seq:Long,kind:String,p:JSONObject)=JSONObject().put("seq",seq).put("time",clock.wall+seq).put("kind",kind).put("payload",p.toString())
        val trip=JSONObject().put("id",UUID.randomUUID().toString()).put("start",clock.wall).put("end",clock.wall+20).put("distance",200.0).put("duration",20.0).put("state","ended")
        val camera=JSONObject().put("class_code","DE:274-30").put("source","camera").put("evidence_id","camera-sign").put("ocr", "22–6 h").put("parent_annotation","main-sign").put("latitude",48.001).put("longitude",8.0)
        val frame=JSONObject().put("event","traffic_sign_inference").put("details",JSONObject().put("frame_id","frame-7").put("supplementary_ocr_only",true).put("ocr","22–6 h").put("parent_annotation","main-sign"))
        val diagnostic=JSONObject().put("message","verbose diagnostic ".repeat(20000)).put("received_at",clock.wall)
        val evidenceWithMessage=JSONObject().put("message","OCR crop details").put("frame_id","frame-8")
        val events=listOf(
            event(1,"gps",JSONObject().put("latitude",48.001).put("longitude",8.0).put("valid",true).put("track_eligible",true).put("reason","accepted")),
            event(2,"tsr",diagnostic),event(3,"tsr",frame),event(4,"tsr",evidenceWithMessage),event(5,"sign",camera),
            event(6,"gap",JSONObject().put("reason","sampling_gap")),event(7,"media",JSONObject().put("id","photo-7").put("type","photo").put("path","/not-selected.jpg")),
            event(8,"place",JSONObject().put("street_name","Public sample street")))
        val original=events.map {it.toString()};val counters=JSONObject().put("origin",0.0).put("distance",200.0).put("usage",20.0)
        assertFalse(TripExportOptions().includeRawLogs)
        val compact=TripJournalFiles.archive(context,trip,events,counters,TripExportOptions())
        ZipFile(compact).use {zip ->
            val journal=JSONObject(zip.getInputStream(zip.getEntry("journal.json")).bufferedReader().readText())
            val saved=journal.getJSONArray("events");val byId=(0 until saved.length()).associate {saved.getJSONObject(it).getLong("seq") to saved.getJSONObject(it)}
            assertEquals(original.size-1,saved.length());assertFalse(byId.containsKey(2));assertEquals(setOf(1L,3L,4L,5L,6L,7L,8L),byId.keys)
            assertEquals("frame-7",byId.getValue(3).getJSONObject("payload").getJSONObject("details").getString("frame_id"))
            assertTrue(byId.getValue(3).getJSONObject("payload").getJSONObject("details").getBoolean("supplementary_ocr_only"))
            assertEquals("22–6 h",byId.getValue(5).getJSONObject("payload").getString("ocr"));assertEquals("main-sign",byId.getValue(5).getJSONObject("payload").getString("parent_annotation"))
            assertEquals("frame-8",byId.getValue(4).getJSONObject("payload").getString("frame_id"))
            assertEquals("compact",journal.getString("export_profile"));assertEquals(1,journal.getInt("omitted_verbose_message_events"));assertFalse(journal.getJSONObject("privacy").getBoolean("raw_logs_included"))
            listOf("gps","tsr","sign","gap").forEach {kind ->listOf("json","csv","ndjson").forEach {ext ->assertNull("Redundant $kind.$ext",zip.getEntry("$kind.$ext"))}}
            listOf("sign_events.ndjson","media.ndjson","media-index.json").forEach {assertNull(zip.getEntry(it))}
            val manifest=JSONObject(zip.getInputStream(zip.getEntry("manifest.json")).bufferedReader().readText());assertEquals("compact",manifest.getString("export_profile"));assertEquals(1,manifest.getInt("omitted_verbose_message_events"))
        }
        val full=TripJournalFiles.archive(context,trip,events,counters,TripExportOptions(includeRawLogs=true))
        ZipFile(full).use {zip ->
            val entry=zip.getEntry("journal.json");assertEquals(java.util.zip.ZipEntry.DEFLATED,entry.method);assertTrue(entry.compressedSize<entry.size/2)
            val journal=JSONObject(zip.getInputStream(entry).bufferedReader().readText());val saved=journal.getJSONArray("events")
            assertEquals(original.size,saved.length());assertEquals(diagnostic.getString("message"),saved.getJSONObject(1).getJSONObject("payload").getString("message"))
            assertEquals("diagnostic",journal.getString("export_profile"));assertEquals(0,journal.getInt("omitted_verbose_message_events"));assertTrue(journal.getJSONObject("privacy").getBoolean("raw_logs_included"))
            assertNull(zip.getEntry("tsr.ndjson"))
        }
        assertEquals(original,events.map {it.toString()})
    }
    @Test fun maskedSelectedPhotoStripsGpsAndPreservesOriginalAndUnknownPositionIsExcluded()=isolated { context,clock,journal ->
        journal.setEnabled(true);journal.start();val id=journal.snapshot().first.single().getString("id")
        for(i in 0..6) {journal.location(clock.fix(48.0+i*0.0005));journal.snapshot();clock.advance(1.0)}
        val staged=File(context.filesDir,"sample.jpg")
        val bitmap=android.graphics.Bitmap.createBitmap(16,8,android.graphics.Bitmap.Config.ARGB_8888)
        staged.outputStream().use {bitmap.compress(android.graphics.Bitmap.CompressFormat.JPEG,95,it)};bitmap.recycle()
        androidx.exifinterface.media.ExifInterface(staged).apply {setLatLong(48.0015,8.0);setAttribute(androidx.exifinterface.media.ExifInterface.TAG_ORIENTATION,androidx.exifinterface.media.ExifInterface.ORIENTATION_ROTATE_90.toString());saveAttributes()}
        val original=libraryPhoto(context,"visible",staged)
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
        journal.location(clock.fix(48.0));journal.snapshot();clock.advance(2.0);journal.location(clock.fix(48.001));journal.snapshot()
        clock.advance(8.0);val intent=clock.wall;journal.stop();journal.snapshot()
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
