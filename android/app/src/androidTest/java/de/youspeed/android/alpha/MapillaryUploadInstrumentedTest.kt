package de.youspeed.android.alpha

import android.graphics.Bitmap
import android.graphics.Color
import androidx.exifinterface.media.ExifInterface
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.time.Instant
import java.util.UUID
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class MapillaryUploadInstrumentedTest {
    private class Transport(vararg responses: Pair<Int,String>) : MapillaryUploadTransport {
        private val replies=responses.toMutableList()
        val requests=mutableListOf<MapillaryUploadRequest>()
        override fun execute(request: MapillaryUploadRequest, cancellation: PanoramaxRequestCancellation): PanoramaxHttpResponse {
            requests+=request
            check(replies.isNotEmpty()) { "Unexpected HTTP request" }
            val (code,body)=replies.removeAt(0)
            return PanoramaxHttpResponse(code,body.toByteArray())
        }
    }
    @Test fun resumableOffsetAndOAuthHeaders() {
        val transport=Transport(200 to "{\"offset\":3}",200 to "{\"h\":\"image-handle\"}")
        val handle=MapillaryUploadClient(transport).upload("abcdef".toByteArray(),"photo.jpg","user-token",PanoramaxRequestCancellation())
        assertEquals("image-handle",handle)
        assertEquals("def",transport.requests[1].body!!.toString(Charsets.UTF_8))
        assertEquals("3",transport.requests[1].headers["Offset"])
        assertEquals("photo.jpg",transport.requests[1].headers["X-Entity-Name"])
        assertEquals("user-token",transport.requests[1].token)
        assertFalse(transport.requests[1].toString().contains("user-token"))
    }
    @Test fun invalidOffsetsCannotSendPhotoBytes() {
        for (offset in listOf("-1","4","true","1.5","\"0\"")) {
            val transport=Transport(200 to "{\"offset\":$offset}")
            try {
                MapillaryUploadClient(transport).upload(byteArrayOf(1,2,3),"photo.jpg","user-token",PanoramaxRequestCancellation())
                fail("Invalid offset $offset accepted")
            } catch (e: MapillaryUploadException) { assertEquals("response_error",e.kind) }
            assertEquals(1,transport.requests.size)
        }
    }
    @Test fun authFailureAndCaptureGateStopBeforeTransfer() {
        val transport=Transport(401 to "{}")
        try {
            MapillaryUploadClient(transport).upload(byteArrayOf(1),"photo.jpg","user-token",PanoramaxRequestCancellation())
            fail("Unauthorized upload accepted")
        } catch (e: MapillaryUploadException) { assertEquals(401,e.status) }
        assertEquals(1,transport.requests.size)
        val blocked=Transport()
        try {
            MapillaryUploadClient(blocked).upload(byteArrayOf(1),"photo.jpg","user-token",PanoramaxRequestCancellation()) {false}
            fail("Capture gate bypassed")
        } catch (e: MapillaryUploadException) { assertEquals("paused",e.kind) }
        assertTrue(blocked.requests.isEmpty())
    }
    @Test fun finishUsesImageBundleManifest() {
        val transport=Transport(200 to "{\"cluster_id\":123}")
        val cluster=MapillaryUploadClient(transport).finish("manifest-handle","user-token",PanoramaxRequestCancellation())
        assertEquals("123",cluster)
        val body=JSONObject(transport.requests.single().body!!.toString(Charsets.UTF_8))
        assertEquals("manifest-handle",body.getString("file_handle"))
        assertEquals("mly_bundle_manifest",body.getString("file_type"))
    }
    @Test fun profileUsesEachUsersToken() {
        val transport=Transport(200 to "{\"id\":\"alice\",\"username\":\"Alice\"}")
        assertEquals("alice" to "Alice",MapillaryUploadClient(transport).profile("alice-token"))
        assertEquals("alice-token",transport.requests.single().token)
    }
    @Test fun preparedJpegHasMapillaryMetadataAndPreservesOriginal() = withDirectory { root ->
        val photo=photo(root);val original=photo.file.readBytes();val output=File(root,"mapillary.jpg")
        MapillaryImageMetadata.prepare(photo,output)
        val data=JSONObject(ExifInterface(output).getAttribute(ExifInterface.TAG_IMAGE_DESCRIPTION)!!)
        assertEquals("2026_11_17_06_30_00_123",data.getString("MAPCaptureTime"))
        assertEquals(48.8,data.getDouble("MAPLatitude"),0.0)
        assertEquals(8.4,data.getDouble("MAPLongitude"),0.0)
        assertEquals(MapillaryUploadStore.hash("drive-a".toByteArray()),data.getString("MAPSequenceUUID"))
        assertArrayEquals(original,photo.file.readBytes())
    }
    @Test fun resumeAfterFinishFailureKeepsHandlesAndDoesNotResendImages() = withDirectory { root ->
        val photo=photo(root);val store=MapillaryUploadStore(File(root,"queue"));val job=store.prepare(listOf(photo),"alice")
        val transport=Transport(200 to "{\"offset\":0}",200 to "{\"h\":\"photo-handle\"}",
            200 to "{\"offset\":0}",200 to "{\"h\":\"manifest-handle\"}",503 to "{}")
        try {
            MapillaryUploadWorker(MapillaryUploadClient(transport),store).submit(job,"alice","alice-token",PanoramaxRequestCancellation())
            fail("Expected finish failure")
        } catch (e: MapillaryUploadException) { assertEquals(503,e.status) }
        val reopened=MapillaryUploadStore(File(root,"queue"));val pending=reopened.pending("alice")
        assertEquals(1,pending.size)
        assertEquals("photo-handle",pending[0].images[0].handle)
        assertEquals("manifest-handle",pending[0].manifestHandle)
        assertTrue(reopened.pending("bob").isEmpty())
        val retry=Transport(200 to "{\"cluster_id\":\"cluster\"}")
        MapillaryUploadWorker(MapillaryUploadClient(retry),reopened).submit(pending[0],"alice","alice-token",PanoramaxRequestCancellation())
        assertEquals(1,retry.requests.size)
        assertTrue(retry.requests[0].url.endsWith("/finish_upload"))
        assertTrue(reopened.pending("alice").isEmpty())
        assertTrue(photo.file.isFile)
    }
    @Test fun wrongAccountCannotResumeAnotherUsersJob() = withDirectory { root ->
        val store=MapillaryUploadStore(File(root,"queue"));val job=store.prepare(listOf(photo(root)),"alice")
        val transport=Transport()
        try {
            MapillaryUploadWorker(MapillaryUploadClient(transport),store).submit(job,"bob","bob-token",PanoramaxRequestCancellation())
            fail("Account mismatch accepted")
        } catch (e: MapillaryUploadException) { assertEquals("account_required",e.kind) }
        assertTrue(transport.requests.isEmpty())
    }
    @Test fun overlappingSelectionSkipsPreviouslySubmittedPhotos() = withDirectory { root ->
        val store=MapillaryUploadStore(File(root,"queue"));val first=photo(root)
        val completed=store.prepare(listOf(first),"alice");completed.clusterId="cluster-a";store.save(completed)
        val second=first.copy(itemId="item-b")
        val next=store.prepare(listOf(first,second),"alice")
        assertEquals(listOf("item-b"),next.images.map {it.itemId})
        assertEquals(setOf("item-a"),store.uploadedItemIds("alice"))
        assertTrue(store.uploadedItemIds("bob").isEmpty())
    }
    @Test fun changedOriginalCannotBePreparedForUpload() = withDirectory { root ->
        val photo=photo(root);photo.file.writeBytes(byteArrayOf(1,2,3))
        try {
            MapillaryImageMetadata.prepare(photo,File(root,"output.jpg"));fail("Changed image accepted")
        } catch (e: MapillaryUploadException) {assertEquals("image_error",e.kind)}
    }
    @Test fun malformedSubmissionCannotBeRecordedAsSuccess() {
        for (value in listOf("true","{}","[]","null","1.5","\"\"")) {
            val transport=Transport(200 to "{\"cluster_id\":$value}")
            try {
                MapillaryUploadClient(transport).finish("manifest","user-token",PanoramaxRequestCancellation())
                fail("Accepted invalid submission receipt")
            } catch (e: MapillaryUploadException) {assertEquals("response_error",e.kind)}
        }
    }
    @Test fun changedStagingCopyStopsBeforeAnyTransfer() = withDirectory { root ->
        val queue=File(root,"queue");val store=MapillaryUploadStore(queue);val photo=photo(root)
        val original=photo.file.readBytes();val job=store.prepare(listOf(photo),"alice")
        File(File(queue,job.id),job.images[0].name).writeBytes(byteArrayOf(1,2,3))
        val transport=Transport()
        try {
            MapillaryUploadWorker(MapillaryUploadClient(transport),store).submit(job,"alice","user-token",PanoramaxRequestCancellation())
            fail("Corrupt staging copy was transferred")
        } catch (e: MapillaryUploadException) {assertEquals("image_error",e.kind)}
        assertTrue(transport.requests.isEmpty());assertArrayEquals(original,photo.file.readBytes())
    }
    private fun withDirectory(block: (File)->Unit) {
        val directory=File(InstrumentationRegistry.getInstrumentation().targetContext.cacheDir,"mapillary-test-${UUID.randomUUID()}").apply {mkdirs()}
        try { block(directory) } finally {directory.deleteRecursively()}
    }
    private fun photo(root: File): MapillaryPhoto {
        val file=File(root,"original.jpg")
        Bitmap.createBitmap(16,12,Bitmap.Config.ARGB_8888).apply {
            eraseColor(Color.RED);file.outputStream().use {compress(Bitmap.CompressFormat.JPEG,90,it)};recycle()
        }
        val time=Instant.parse("2026-11-17T06:30:00.123Z")
        val location=PanoramaxLocationSample(48.8,8.4,time,3.0,250.0,15.0)
        return MapillaryPhoto("item-a",file,PanoramaxCaptureMetadata("capture-a","drive-a",time,location,
            MapillaryUploadStore.hash(file.readBytes()),file.length(),"YouSpeed test"))
    }
}
