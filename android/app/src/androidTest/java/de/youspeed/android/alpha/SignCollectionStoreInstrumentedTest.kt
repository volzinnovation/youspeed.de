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
    @Test fun sqliteRestartConsentReceiptsAndDeletionBarrier() {
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
            fun receipt(status: String, id: String = event.getValue("event_id").jsonPrimitive.content, batchId: String = batch.id) = buildJsonObject {
                put("schema_version", 1); put("batch_id", batchId); put("collection_epoch", 0); put("durability", "live_eu_committed"); put("operation_receipt", "test-private-receipt")
                put("results", JsonArray(listOf(buildJsonObject { put("event_id", id); put("status", status); put("retryable", status == "retry_later") })))
            }
            assertThrows(Exception::class.java) { store.applyBatchReceipt(receipt("accepted", SignCollectionJson.uuid())) }; assertEquals(1, store.pendingCount())
            store.applyBatchReceipt(receipt("retry_later")); assertNull(store.prepareBatch()); clock.time = clock.time.plusSeconds(61)
            val retry = store.prepareBatch()!!; assertNotEquals(batch.id, retry.id)
            store.applyBatchReceipt(receipt("duplicate", batchId = retry.id)); assertEquals(0, store.pendingCount())
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
    @Test fun automaticCropsRecoverLostAckAndAppendStatusWithoutSessionConsent() {
        val gate = SignCollectionContractGate { path -> context.assets.open("tsr/collection-contract-v1/$path").use { it.readBytes() } }
        val root = File(context.noBackupFilesDir, "crop-test-${SignCollectionJson.uuid()}")
        val clock = TestClock(); var store = SignCollectionStore(root, gate, clock)
        val bitmap = Bitmap.createBitmap(1, 1, Bitmap.Config.ARGB_8888, false, ColorSpace.get(ColorSpace.Named.SRGB))
        try {
            bitmap.setPixel(0,0,0xff00aabb.toInt()); val crop = SignCollectionCrop.generate(bitmap, mapOf("x" to 0.0,"y" to 0.0,"width" to 1.0,"height" to 1.0))
            store.beginSession(SignCollectionJson.uuid())
            store.decide("sign_metadata", SignCollectionCapabilities.metadataDisclosure, true, false)
            store.authorizeAutomaticCrops()
            val claim = store.claim("crop_storage", SignCollectionCapabilities.cropDisclosure)
            val id = SignCollectionJson.uuid(); val observation = SignCollectionJson.uuid()
            val metadata = crop.metadata(id, observation, store.installationId, 0, "detector", clock.instant(), "test-frame", "user_reviewed", "user-review-1", claim)
            store.stageCrop(metadata, crop.bytes); assertEquals(1,store.cropReviewCount()); assertNull(store.nextCrop())
            store.endSession(); store.close(); store = SignCollectionStore(root, gate, clock)
            store.migrateAutomaticCrops(); assertArrayEquals(crop.bytes, store.nextCrop()!!.bytes)
            val caps = buildJsonObject {
                put("contract_manifest_sha256", SignCollectionContractGate.MANIFEST_SHA256); put("schema_versions", JsonArray(listOf(JsonPrimitive(1))))
                put("one_way_uploads", true); put("durability", "live_eu_committed")
                put("limits", buildJsonObject { put("metadata_bytes", 524288); put("event_bytes", 16384); put("media_bytes", 5242880) })
                put("disclosure_versions", buildJsonObject { put("sign_metadata", JsonArray(listOf(JsonPrimitive(SignCollectionCapabilities.metadataDisclosure)))); put("crop_storage", JsonArray(listOf(JsonPrimitive(SignCollectionCapabilities.cropDisclosure)))) })
            }
            var reservedBody: String? = null; var durable = false; var puts = 0; var linked = false
            val http = object : SignCollectionRequesting {
                override fun request(path: String, body: String?): SignCollectionHTTPResponse {
                    if (path == "capabilities") return SignCollectionHTTPResponse(200,caps)
                    val value = SignCollectionJson.parse(body!!).jsonObject
                    if (path == "consent-events") return SignCollectionHTTPResponse(200, buildJsonObject { put("state","recorded"); put("operation_receipt", "grant-"+value.getValue("event_id").jsonPrimitive.content) })
                    if (path == "media-uploads") {
                        if (reservedBody != null) assertEquals(reservedBody,body); reservedBody = body
                        assertEquals(JsonPrimitive("passed"), value["privacy_preflight"])
                        return SignCollectionHTTPResponse(200, buildJsonObject { put("state",if (durable) "media_durable" else "reserved"); put("sha256",crop.encodedHash); put("operation_receipt","crop-receipt"); if (durable) put("durability","live_eu_committed") else put("handle","safe_handle") })
                    }
                    assertEquals("media-status-batches",path)
                    val events = value.getValue("events").jsonArray
                    assertEquals(JsonPrimitive("linked"), events[0].jsonObject["status"]); assertEquals(JsonPrimitive(observation),events[0].jsonObject["observation_id"]); linked = true
                    return SignCollectionHTTPResponse(200,buildJsonObject { put("schema_version",1); put("batch_id",value.getValue("batch_id")); put("collection_epoch",0); put("durability","live_eu_committed"); put("operation_receipt","status-receipt"); put("results",JsonArray(events.map { buildJsonObject { put("event_id",it.jsonObject.getValue("event_id")); put("status","accepted"); put("retryable",false) } })) })
                }
                override fun upload(handle: String, bytes: ByteArray): SignCollectionHTTPResponse {
                    assertEquals("safe_handle",handle); assertArrayEquals(crop.bytes,bytes); puts++; durable = true; throw java.io.IOException("lost_ack")
                }
            }
            var worker = SignCollectionUploadWorker(store,http,clock) { 0.0 }
            assertEquals("offline",worker.runOnce(false,true)); assertEquals(0,puts)
            assertEquals("contribution_paused",worker.runOnce(true,false)); assertEquals(0,puts)
            assertEquals("crop_delivery_unavailable",worker.runOnce(true,true)); assertTrue(store.transportRetryMillis() <= clock.millis())
            assertArrayEquals(crop.bytes,store.nextCrop()!!.bytes); assertEquals("crop-receipt",store.nextCrop()!!.receipt)
            store.close(); clock.time = clock.time.plusSeconds(10); store = SignCollectionStore(root,gate,clock)
            worker = SignCollectionUploadWorker(store,http,clock) { 0.0 }; worker.runOnce(true,true)
            assertNull(store.nextCrop()); assertEquals(1,puts); assertEquals(1,store.pendingCount())
            worker.runOnce(true,true); assertTrue(linked); assertEquals(0,store.pendingCount())
            store.beginSession(SignCollectionJson.uuid()); store.decide("sign_metadata",SignCollectionCapabilities.metadataDisclosure,true,false)
            val renewed = store.decide("crop_storage",SignCollectionCapabilities.cropDisclosure,true,false)
            fun stage(): String {
                val cropId = SignCollectionJson.uuid()
                store.stageCrop(crop.metadata(cropId,observation,store.installationId,0,"detector",clock.instant(),null,"user_reviewed","user-review-1",renewed),crop.bytes)
                return cropId
            }
            stage(); store.migrateAutomaticCrops(); stage(); clock.time = clock.time.plusSeconds(8L*86400); store.expireCrops()
            assertNull(store.nextCrop()); assertEquals(0,store.cropReviewCount()); assertEquals(2,store.expiredCropCount())
            val expired = SignCollectionJson.parse(store.prepareBatch()!!.body).jsonObject.getValue("events").jsonArray[0].jsonObject
            assertEquals(JsonPrimitive("expired"),expired["status"])
            val automatic = SignCollectionCrop.generate(bitmap, mapOf("x" to 0.0,"y" to 0.0,"width" to 1.0,"height" to 1.0), hashSource = false)
            assertNull(automatic.sourceHash); assertArrayEquals(crop.bytes, automatic.bytes)
            store.enqueueAutomaticCrop(automatic.metadata(SignCollectionJson.uuid(),observation,store.installationId,0,"detector",clock.instant(),"automatic-device-frame","passed","metadata-strip-1",renewed),automatic.bytes)
            store.endSession(); assertArrayEquals(automatic.bytes, store.nextCrop()!!.bytes); assertEquals(0,store.cropReviewCount())
            store.withdraw("sign_metadata",SignCollectionCapabilities.metadataDisclosure); assertNull(store.nextCrop())
        } finally { bitmap.recycle(); store.close(); root.deleteRecursively() }
    }

    @Test fun cropPixelsMetadataAndDurableBytes() {
        val gate = SignCollectionContractGate { path -> context.assets.open("tsr/collection-contract-v1/$path").use { it.readBytes() } }
        val root = File(context.noBackupFilesDir, "collection-test-${SignCollectionJson.uuid()}")
        val clock = TestClock(); var store = SignCollectionStore(root, gate, clock)
        val bitmap = Bitmap.createBitmap(1, 1, Bitmap.Config.ARGB_8888, false, ColorSpace.get(ColorSpace.Named.SRGB))
        try {
            bitmap.setPixel(0, 0, 0xff00aabb.toInt())
            val crop = SignCollectionCrop.generate(bitmap, mapOf("x" to 0.0, "y" to 0.0, "width" to 1.0, "height" to 1.0))
            assertEquals("12cc7f777c6213cec843bd1056ed1e2e1677c8f728e0b1d28d84000f53882d7e", crop.sourceHash)
            assertEquals(1, BitmapFactory.decodeByteArray(crop.bytes, 0, crop.bytes.size).height)
            val rows = Bitmap.createBitmap(2, 4, Bitmap.Config.ARGB_8888, false, ColorSpace.get(ColorSpace.Named.SRGB))
            try {
                val colors = intArrayOf(0xffff0000.toInt(), 0xff00ff00.toInt(), 0xff0000ff.toInt(), 0xffffff00.toInt())
                rows.setPixels(colors.flatMap { listOf(it, it) }.toIntArray(), 0, 2, 0, 0, 2, 4)
                val rowCrop = SignCollectionCrop.generate(rows, mapOf("x" to 0.0, "y" to .25, "width" to 1.0, "height" to .25))
                val decoded = BitmapFactory.decodeByteArray(rowCrop.bytes, 0, rowCrop.bytes.size)
                try { assertEquals(colors[1], decoded.getPixel(0,0)); assertEquals(colors[2], decoded.getPixel(0,1)) } finally { decoded.recycle() }
                val rgb = byteArrayOf(-1,0,0,-1,0,0,0,-1,0,0,-1,0,0,0,-1,0,0,-1,-1,-1,0,-1,-1,0)
                assertEquals(SignCollectionJson.sha256(rgb), rowCrop.sourceHash)
            } finally { rows.recycle() }
            store.beginSession(SignCollectionJson.uuid()); val claim = store.decide("crop_storage", "crop-1", true, false)
            val id = SignCollectionJson.uuid()
            val metadata = crop.metadata(id, SignCollectionJson.uuid(), store.installationId, 0, "manual_capture", clock.instant(), "synthetic-frame", "user_reviewed", "review-1", claim)
            store.enqueueCrop(metadata, crop.bytes, "crop-1"); store.close(); store = SignCollectionStore(root, gate, clock)
            assertArrayEquals(crop.bytes, store.nextCrop()!!.bytes)
            val reserved = buildJsonObject { put("state", "reserved"); put("handle", "upload-handle"); put("operation_receipt", "crop-receipt"); put("sha256", crop.encodedHash) }
            store.applyCropReceipt(id, reserved); assertEquals("upload-handle", store.nextCrop()!!.handle)
            val durable = buildJsonObject { put("state", "media_durable"); put("durability", "live_eu_committed"); put("operation_receipt", "crop-receipt"); put("sha256", crop.encodedHash) }
            store.applyCropReceipt(id, durable); assertNull(store.nextCrop())
        } finally { bitmap.recycle(); store.close(); root.deleteRecursively() }
    }

    @Test fun privacyOperationsRecoverAcrossRestartAndLaterDeletions() {
        val gate = SignCollectionContractGate { path -> context.assets.open("tsr/collection-contract-v1/$path").use { it.readBytes() } }
        val root = File(context.noBackupFilesDir, "collection-privacy-test-${SignCollectionJson.uuid()}")
        var store = SignCollectionStore(root, gate)
        try {
            store.beginSession(SignCollectionJson.uuid())
            store.decide("processor:test", "processor-1", true, false)
            val grant = store.nextControl()!!.id
            store.applyControlReceipt(grant, buildJsonObject { put("operation_receipt", "grant-receipt"); put("state", "recorded") })
            store.withdraw("processor:test", "processor-1")
            val withdrawal = store.nextControl()!!.id
            val stopping = buildJsonObject { put("operation_receipt", "withdrawal-receipt"); put("state", "processing_stop_pending") }
            store.applyControlReceipt(withdrawal, stopping)
            store.close(); store = SignCollectionStore(root, gate)
            assertEquals("withdrawal-receipt", store.nextControl()!!.receipt)
            assertThrows(Exception::class.java) { store.applyControlReceipt(withdrawal, JsonObject(stopping + ("state" to JsonPrimitive("processing_stopped")))) }
            assertThrows(Exception::class.java) { store.applyControlReceipt(withdrawal, JsonObject(stopping + mapOf("operation_receipt" to JsonPrimitive("changed-receipt"), "state" to JsonPrimitive("processing_stop_applied")))) }
            fun deletionReceipt(epoch: Int, token: String, removed: Boolean, archives: Boolean = false, backups: Boolean = false) = buildJsonObject {
                put("operation_receipt", token); put("state", if (removed) "active_data_removed" else "deletion_pending")
                put("next_collection_epoch", epoch + 1); put("active_data_removed", removed)
                put("archives_purged", archives); put("backup_expiry_complete", backups)
            }
            val first = store.requestDeletion()
            store.applyControlReceipt(first, deletionReceipt(0, "first-delete", false))
            assertEquals(listOf(first, withdrawal), store.pendingControls().map { it.id })
            val active = deletionReceipt(0, "first-delete", true)
            store.applyControlReceipt(first, active)
            store.close(); store = SignCollectionStore(root, gate)
            assertEquals(1, store.collectionEpoch); assertFalse(store.controlStatus(first)!!.isComplete)
            assertTrue(store.pendingControls().any { it.id == first && it.receipt == "first-delete" })
            assertTrue(store.controlStatus(grant)!!.isComplete)
            store.beginSession(SignCollectionJson.uuid()); store.decide("sign_metadata", "example-camera-use-1", true, false)
            val currentGrant = store.nextControl()!!.id
            assertNotEquals(first, currentGrant); assertNotEquals(withdrawal, currentGrant)
            store.applyControlReceipt(currentGrant, buildJsonObject { put("operation_receipt", "current-grant"); put("state", "recorded") })
            store.applyControlReceipt(first, active)
            assertEquals(1, store.collectionEpoch)
            val event = SignCollectionJson.parse(context.assets.open("tsr/collection-contract-v1/fixtures/sighting-batch-v1.json").bufferedReader().use { it.readText() }).jsonObject.getValue("events").jsonArray[0].jsonObject
            store.enqueue("sighting", JsonObject(event + ("event_id" to JsonPrimitive(SignCollectionJson.uuid()))), "example-camera-use-1")
            val second = store.requestDeletion()
            store.applyControlReceipt(first, deletionReceipt(0, "first-delete", true, archives = true))
            assertEquals(JsonPrimitive(true), store.controlStatus(first)!!.response!!["archives_purged"])
            assertFalse(store.controlStatus(first)!!.isComplete); assertEquals(second, store.nextControl()!!.id)
            store.applyControlReceipt(first, deletionReceipt(0, "first-delete", true, archives = true, backups = true))
            assertEquals(1, store.collectionEpoch)
            assertThrows(Exception::class.java) { store.prepareBatch() }
            assertThrows(Exception::class.java) { store.applyControlReceipt(first, active) }
            store.applyControlReceipt(second, deletionReceipt(1, "second-delete", true))
            assertEquals(2, store.collectionEpoch)
            store.applyControlReceipt(withdrawal, JsonObject(stopping + ("state" to JsonPrimitive("processing_stop_applied"))))
            assertThrows(Exception::class.java) { store.applyControlReceipt(withdrawal, stopping) }
            store.clearPendingForDeveloper()
            store.close(); store = SignCollectionStore(root, gate)
            assertTrue(store.controlStatus(first)!!.isComplete); assertTrue(store.controlStatus(withdrawal)!!.isComplete)
            assertEquals(listOf(second), store.pendingControls().map { it.id })
            store.applyControlReceipt(second, deletionReceipt(1, "second-delete", true, archives = true, backups = true))
            assertNull(store.nextControl()); assertEquals(2, store.collectionEpoch)
        } finally { store.close(); root.deleteRecursively() }
    }

    @Test fun eventLimitCountsCanonicalBytesAndRejectsOverflowAtomically() {
        val gate = SignCollectionContractGate { path -> context.assets.open("tsr/collection-contract-v1/$path").use { it.readBytes() } }
        val root = File(context.noBackupFilesDir, "collection-size-test-${SignCollectionJson.uuid()}")
        val store = SignCollectionStore(root, gate)
        try {
            store.beginSession(SignCollectionJson.uuid()); store.decide("sign_metadata", "example-camera-use-1", true, false)
            val limit = SignCollectionStore.maximumEventBytes; assertEquals(16_384, limit)
            var event = SignCollectionJson.parse(context.assets.open("tsr/collection-contract-v1/fixtures/sighting-batch-v1.json").bufferedReader().use { it.readText() }).jsonObject.getValue("events").jsonArray[0].jsonObject
            val marker = "\u0001".repeat(160)
            val flags = MutableList(32) { JsonPrimitive(marker) }
            event = JsonObject(event + ("evidence" to JsonObject(event.getValue("evidence").jsonObject + ("quality_flags" to JsonArray(flags)))))
            var trim = (SignCollectionJson.canonical(event).toByteArray(Charsets.UTF_8).size - limit + 5) / 6
            flags.indices.forEach { index -> val count = minOf(trim, 159); flags[index] = JsonPrimitive("\u0001".repeat(160 - count)); trim -= count }
            event = JsonObject(event + ("evidence" to JsonObject(event.getValue("evidence").jsonObject + ("quality_flags" to JsonArray(flags)))))
            val padding = limit - SignCollectionJson.canonical(event).toByteArray(Charsets.UTF_8).size
            var app = event.getValue("app").jsonObject
            app = JsonObject(app + ("build" to JsonPrimitive(app.getValue("build").jsonPrimitive.content + "x".repeat(padding))))
            event = JsonObject(event + ("app" to app))
            assertEquals(limit, SignCollectionJson.canonical(event).toByteArray(Charsets.UTF_8).size)
            gate.validate(event, "sighting"); store.enqueue("sighting", event, "example-camera-use-1")
            app = JsonObject(app + ("build" to JsonPrimitive(app.getValue("build").jsonPrimitive.content + "x")))
            val overflow = JsonObject(event + mapOf("app" to app, "event_id" to JsonPrimitive(SignCollectionJson.uuid())))
            gate.validate(overflow, "sighting")
            val error = assertThrows(IllegalArgumentException::class.java) { store.enqueue("sighting", overflow, "example-camera-use-1") }
            assertEquals("capacity", error.message); assertEquals(1, store.pendingCount())
        } finally { store.close(); root.deleteRecursively() }
    }
}
