package de.youspeed.android.alpha

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.ColorSpace
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.time.Clock
import java.time.Instant
import java.time.ZoneId
import java.time.ZoneOffset
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class SignCollectionStoreInstrumentedTest {
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private class TestClock(var time: Instant = Instant.parse("2026-10-02T09:55:00Z")) : Clock() {
        override fun getZone() = ZoneOffset.UTC
        override fun withZone(zone: ZoneId): Clock = this
        override fun instant() = time
    }
    @Test fun sqliteRestartSharingAndDeletionBarrier() {
        val gate = SignCollectionContractGate { path -> context.assets.open("tsr/collection-contract-v1/$path").use { it.readBytes() } }
        val root = File(context.noBackupFilesDir, "collection-test-${SignCollectionJson.uuid()}")
        val clock = TestClock()
        var store = SignCollectionStore(root, gate, clock)
        try {
            val installation = store.installationId; val session = SignCollectionJson.uuid()
            store.beginSession(session); assertTrue(store.shouldPrompt("sign_metadata", "example-camera-use-1"))
            store.beginSession(session); assertFalse(store.shouldPrompt("sign_metadata", "example-camera-use-1"))
            store.decide("sign_metadata", "example-camera-use-1", true, false)
            val event = SignCollectionJson.parse(context.assets.open("tsr/collection-contract-v1/fixtures/sighting-batch-v1.json").bufferedReader().use { it.readText() }).jsonObject.getValue("events").jsonArray[0].jsonObject
            store.enqueue("sighting", event, "example-camera-use-1"); val batch = store.prepareBatch()!!
            store.close(); store = SignCollectionStore(root, gate, clock)
            assertEquals(installation, store.installationId); assertEquals(batch.body, store.prepareBatch()!!.body)
            assertThrows(Exception::class.java) { store.enqueue("sighting", event, "example-camera-use-1") }
            store.finishBestEffortBatch(batch.id); assertEquals(0,store.pendingCount())
            store.beginSession(SignCollectionJson.uuid()); assertTrue(store.shouldPrompt("sign_metadata", "example-camera-use-1"))
            store.decide("sign_metadata", "example-camera-use-1", false, true); store.endSession(); store.beginSession(SignCollectionJson.uuid())
            assertFalse(store.shouldPrompt("sign_metadata", "material-change"))
            val deletion = store.requestDeletion(); assertEquals(deletion, store.requestDeletion())
            assertThrows(Exception::class.java) { store.prepareBatch() }
            val pending = buildJsonObject { put("operation_receipt", "delete-receipt"); put("state", "deletion_pending"); put("next_collection_epoch", 1); put("active_data_removed", false) }
            store.applyControlReceipt(deletion, pending); store.close(); store = SignCollectionStore(root, gate, clock)
            assertEquals("delete-receipt", store.nextControl()!!.receipt); assertEquals(0, store.collectionEpoch)
            store.applyControlReceipt(deletion, JsonObject(pending + mapOf("active_data_removed" to JsonPrimitive(true), "state" to JsonPrimitive("active_data_removed"))))
            assertEquals(installation, store.installationId); assertEquals(1, store.collectionEpoch)
            store.beginSession(SignCollectionJson.uuid()); store.decide("sign_metadata", "example-camera-use-1", true, false)
            val peer = SignCollectionStore(root, gate, clock)
            try { peer.withdraw("sign_metadata", "example-camera-use-1") } finally { peer.close() }
            val fresh = JsonObject(event + ("event_id" to JsonPrimitive(SignCollectionJson.uuid())))
            assertThrows(Exception::class.java) { store.enqueue("sighting", fresh, "example-camera-use-1") }
            store.decide("sign_metadata", "example-camera-use-1", true, false); store.enqueue("sighting", fresh, "example-camera-use-1")
            store.prepareBatch(); clock.time = clock.time.plusSeconds(31L * 86400)
            assertNull(store.prepareBatch()); assertEquals(0, store.pendingCount()); assertEquals(1, store.expiredEventCount())
        } finally { store.close(); root.deleteRecursively() }
    }
    @Test fun automaticCropsUseOneRequestAndBoundedRetries() {
        val gate = SignCollectionContractGate { path -> context.assets.open("tsr/collection-contract-v1/$path").use { it.readBytes() } }
        val root = File(context.noBackupFilesDir,"fast-crops-${SignCollectionJson.uuid()}")
        val clock = TestClock(); var store = SignCollectionStore(root,gate,clock)
        val bitmap = Bitmap.createBitmap(1,1,Bitmap.Config.ARGB_8888)
        try {
            bitmap.eraseColor(0xff00aabb.toInt())
            val crop = SignCollectionCrop.generate(bitmap,mapOf("x" to 0.0,"y" to 0.0,"width" to 1.0,"height" to 1.0),hashSource=false)
            store.beginSession(SignCollectionJson.uuid()); store.decide("sign_metadata",SignCollectionCapabilities.metadataDisclosure,true,false)
            store.authorizeAutomaticCrops()
            var claim = store.claim("crop_storage",SignCollectionCapabilities.cropDisclosure)
            val observation = SignCollectionJson.uuid()
            fun metadata(review: Boolean = false) = crop.metadata(SignCollectionJson.uuid(),observation,store.installationId,0,"detector",clock.instant(),"device-frame",if (review) "user_reviewed" else "passed","metadata-strip-1",claim)
            store.stageCrop(metadata(true),crop.bytes)
            store.endSession(); store.close(); store = SignCollectionStore(root,gate,clock)
            store.migrateAutomaticCrops(); assertEquals(0,store.cropReviewCount()); assertArrayEquals(crop.bytes,store.nextCrop()!!.bytes)
            store.beginSession(SignCollectionJson.uuid()); store.decide("sign_metadata",SignCollectionCapabilities.metadataDisclosure,true,false); store.authorizeAutomaticCrops()
            claim = store.claim("crop_storage",SignCollectionCapabilities.cropDisclosure)
            repeat(9) { store.enqueueAutomaticCrop(metadata(),crop.bytes) }
            val caps = buildJsonObject {
                put("limits",buildJsonObject { put("metadata_bytes",524288); put("event_bytes",16384); put("media_bytes",5242880) })
                put("disclosure_versions",buildJsonObject { put("sign_metadata",JsonArray(listOf(JsonPrimitive(SignCollectionCapabilities.metadataDisclosure)))); put("crop_storage",JsonArray(listOf(JsonPrimitive(SignCollectionCapabilities.cropDisclosure)))) })
            }
            var captures = 0; var capabilities = 0; var cropStatus = 204; var metadataRequests = 0
            val http = object : SignCollectionRequesting {
                override fun request(path: String,body: String?): SignCollectionHTTPResponse {
                    if (path=="capabilities") { capabilities++; return SignCollectionHTTPResponse(200,caps) }
                    val value = SignCollectionJson.parse(body!!).jsonObject
                    if (path=="consent-events") return SignCollectionHTTPResponse(200,buildJsonObject { put("state","recorded"); put("operation_receipt","grant-"+value.getValue("event_id").jsonPrimitive.content) })
                    assertEquals("capture-sightings",path); metadataRequests++
                    return SignCollectionHTTPResponse(204,JsonObject(emptyMap()))
                }
                override fun captureCrop(metadata: String,bytes: ByteArray): SignCollectionHTTPResponse {
                    captures++; assertArrayEquals(crop.bytes,bytes)
                    return SignCollectionHTTPResponse(cropStatus,JsonObject(emptyMap()),if(cropStatus==429) "60" else null)
                }
            }
            val worker = SignCollectionUploadWorker(store,http,clock) { 0.0 }
            assertEquals("offline",worker.runOnce(false,true)); assertEquals(0,captures)
            assertEquals("contribution_paused",worker.runOnce(true,false)); assertEquals(0,captures)
            assertEquals("crop_sent",worker.runOnce(true,true)); assertEquals(8,captures); assertEquals(0,store.pendingCount())
            worker.runOnce(true,true); assertEquals(10,captures); assertNull(store.nextCrop()); assertEquals(1,capabilities)
            store.enqueueAutomaticCrop(metadata(),crop.bytes); cropStatus=429
            assertEquals("backoff",worker.runOnce(true,true)); assertEquals(60_000L,worker.retryDelayMillis())
            clock.time=clock.time.plusSeconds(59); assertEquals("backoff",worker.runOnce(true,true)); assertEquals(11,captures)
            clock.time=clock.time.plusSeconds(1); cropStatus=204; worker.runOnce(true,true); assertEquals(12,captures); assertNull(store.nextCrop())
            store.enqueueAutomaticCrop(metadata(),crop.bytes); cropStatus=503
            repeat(3) { worker.runOnce(true,true); clock.time=clock.time.plusSeconds(65) }
            assertEquals(15,captures); assertNull(store.nextCrop()); assertEquals(0,store.pendingCount())
            val fixture = SignCollectionJson.parse(context.assets.open("tsr/collection-contract-v1/fixtures/sighting-batch-v1.json").bufferedReader().use { it.readText() }).jsonObject.getValue("events").jsonArray[0].jsonObject
            store.enqueue("sighting",JsonObject(fixture+("event_id" to JsonPrimitive(SignCollectionJson.uuid()))),SignCollectionCapabilities.metadataDisclosure)
            worker.runOnce(true,true); assertEquals(1,metadataRequests); assertEquals(0,store.pendingCount())
        } finally { bitmap.recycle(); store.close(); root.deleteRecursively() }
    }

    @Test fun cropGeometryAndAutomaticSharingWithdrawal() {
        val gate = SignCollectionContractGate { path -> context.assets.open("tsr/collection-contract-v1/$path").use { it.readBytes() } }
        val root = File(context.noBackupFilesDir,"crop-geometry-${SignCollectionJson.uuid()}")
        val clock = TestClock(); val store = SignCollectionStore(root,gate,clock)
        val bitmap = Bitmap.createBitmap(1,1,Bitmap.Config.ARGB_8888,false,ColorSpace.get(ColorSpace.Named.SRGB))
        try {
            bitmap.eraseColor(0xff00aabb.toInt())
            val crop = SignCollectionCrop.generate(bitmap,mapOf("x" to 0.0,"y" to 0.0,"width" to 1.0,"height" to 1.0))
            assertEquals("12cc7f777c6213cec843bd1056ed1e2e1677c8f728e0b1d28d84000f53882d7e",crop.sourceHash)
            assertEquals(1,BitmapFactory.decodeByteArray(crop.bytes,0,crop.bytes.size).height)
            store.beginSession(SignCollectionJson.uuid()); store.decide("sign_metadata",SignCollectionCapabilities.metadataDisclosure,true,false); store.authorizeAutomaticCrops()
            val claim=store.claim("crop_storage",SignCollectionCapabilities.cropDisclosure)
            store.enqueueAutomaticCrop(crop.metadata(SignCollectionJson.uuid(),SignCollectionJson.uuid(),store.installationId,0,"detector",clock.instant(),"frame","passed","metadata-strip-1",claim),crop.bytes)
            store.endSession(); assertNotNull(store.nextCrop()); store.withdraw("sign_metadata",SignCollectionCapabilities.metadataDisclosure)
            assertNull(store.nextCrop()); assertEquals(0,store.cropReviewCount())
        } finally { bitmap.recycle(); store.close(); root.deleteRecursively() }
    }
}
