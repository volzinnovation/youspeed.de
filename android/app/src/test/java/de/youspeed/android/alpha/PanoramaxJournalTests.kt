package de.youspeed.android.alpha

import java.io.File
import java.time.Instant
import java.util.concurrent.Callable
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import kotlin.io.path.createTempDirectory
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.*
import org.junit.Test

class PanoramaxJournalTests {
    private val instant = Instant.parse("2026-09-01T12:00:00Z")

    @Test fun growingCaptureAndIndividualStatusWritesHaveLinearMetadataIO() = withQueue { root, store ->
        val batch = store.createBatch("linear", instant)
        // Invoke the existing encoder only in this test to calculate the exact
        // former full-JSON rewrite cost for these same mutations.
        val legacyEncoder = PanoramaxQueueStore::class.java.getDeclaredMethod("encode", PanoramaxBatchRecord::class.java).apply { isAccessible = true }
        fun legacyBytes(snapshot: PanoramaxBatchRecord) = requireNotNull(legacyEncoder.invoke(store, snapshot)).toString().toByteArray().size.toLong()
        var legacyTotal = legacyBytes(batch)
        repeat(512) {
            add(root, store, batch, "photo-$it")
            legacyTotal += legacyBytes(requireNotNull(store.getBatch(batch.batchId)))
        }
        val capture = store.persistenceStatistics
        val loaded = requireNotNull(store.getBatch(batch.batchId))
        loaded.items.forEach { legacyTotal += legacyBytes(store.updateItem(batch.batchId, it.itemId, PanoramaxItemState.UPLOADED)) }
        val complete = store.persistenceStatistics
        // A full-record rewrite costs over 80 MB for this fixture. Small item
        // records plus geometric checkpoints stay below 4 MB for both phases.
        assertTrue("$complete", complete.metadataBytesWritten < 4_000_000L)
        assertTrue(complete.metadataBytesWritten * 20 < legacyTotal)
        assertEquals(1024, complete.journalWrites)
        assertTrue("$complete", complete.checkpointWrites < 20)
        assertEquals(0, complete.snapshotReads)
        val reopened = PanoramaxQueueStore(root)
        assertEquals(512, reopened.getBatch(batch.batchId)?.items?.size)
        assertTrue(reopened.getBatch(batch.batchId)!!.items.all { it.state == PanoramaxItemState.UPLOADED })
        println("Panoramax journal IO: capture512=$capture; capture512+status512=$complete; legacyFullRewrites=$legacyTotal")
    }

    @Test fun galleryScanDoesNotEvictTheHotCaptureBatch() = withQueue { root, store ->
        repeat(6) { store.createBatch("archived-$it", instant) }
        val hot = store.createBatch("hot", instant)
        add(root, store, hot, "first")
        assertEquals(7, store.listBatches().size)
        val reads = store.persistenceStatistics.snapshotReads
        add(root, store, hot, "second")
        assertEquals(reads, store.persistenceStatistics.snapshotReads)
        assertEquals(2, store.getBatch(hot.batchId)?.items?.size)
    }

    @Test fun checkpointWatermarkMakesInterruptedJournalPruningIdempotent() = withQueue { root, store ->
        val batch = store.createBatch("watermark", instant)
        val item = add(root, store, batch, "original")
        store.updateItem(batch.batchId, item.itemId, PanoramaxItemState.UPLOADING)
        val journal = File(root, "panoramax/batches/${batch.batchId}.journal")
        val obsolete = journal.listFiles()!!.filter { it.extension == "json" }.associate { it.name to it.readBytes() }
        store.updateItem(batch.batchId, item.itemId, PanoramaxItemState.UPLOADED)
        store.checkpoint(batch.batchId)
        // Reproduce a process exit after the checkpoint replacement and before
        // obsolete-record cleanup. Older pending/in-flight states must not win.
        obsolete.forEach { (name, bytes) -> File(journal, name).writeBytes(bytes) }
        File(journal, ".00000000000000099999.json.tmp").writeText("unfinished")
        val reopened = PanoramaxQueueStore(root)
        assertEquals(PanoramaxItemState.UPLOADED, reopened.getBatch(batch.batchId)?.items?.single()?.state)
        reopened.updateItemFavorite(batch.batchId, item.itemId, true)
        assertTrue(PanoramaxQueueStore(root).getBatch(batch.batchId)!!.items.single().isFavorite)
    }

    @Test fun legacyCheckpointUpgradesAndCorruptCommittedJournalNeverScavengesAssets() = withQueue { root, store ->
        val batch = store.createBatch("legacy", instant)
        val item = add(root, store, batch, "original")
        store.checkpoint(batch.batchId)
        val file = File(root, "panoramax/batches/${batch.batchId}.json")
        val objectValue = Json.parseToJsonElement(file.readText()).jsonObject
        file.writeText(JsonObject(objectValue - "_queue_checkpoint").toString())
        val legacy = PanoramaxQueueStore(root)
        assertEquals(item, legacy.getBatch(batch.batchId)?.items?.single())
        legacy.updateItem(batch.batchId, item.itemId, PanoramaxItemState.ACCEPTED)
        val journal = File(root, "panoramax/batches/${batch.batchId}.journal")
        journal.listFiles()!!.single { it.extension == "json" }.writeText("{broken")
        val reopened = PanoramaxQueueStore(root)
        assertTrue(runCatching { reopened.getBatch(batch.batchId) }.isFailure)
        val cleanup = reopened.performStartupMaintenanceNow()
        assertTrue(cleanup.hasFailures)
        assertTrue(store.originalFile(item).exists())
        assertTrue(store.thumbnailFile(item).exists())
    }

    @Test fun peerInstancesSerializeMutationsAndNeverResurrectDeletedItems() = withQueue { root, store ->
        val batch = store.createBatch("concurrent", instant)
        repeat(64) { add(root, store, batch, "photo-$it") }
        val stale = requireNotNull(store.getBatch(batch.batchId))
        val peer = PanoramaxQueueStore(root)
        peer.getBatch(batch.batchId) // Warm the peer cache before all mutations.
        val workers = Executors.newFixedThreadPool(8)
        try {
            val futures = (0 until 64).map { index -> workers.submit(Callable {
                if (index % 2 == 0) store.updateItem(batch.batchId, "photo-$index", PanoramaxItemState.ACCEPTED)
                else peer.updateItemFavorite(batch.batchId, "photo-$index", true)
            }) }
            futures.forEach { it.get(10, TimeUnit.SECONDS) }
        } finally { workers.shutdownNow() }
        val result = requireNotNull(store.getBatch(batch.batchId))
        result.items.forEachIndexed { index, item ->
            if (index % 2 == 0) assertEquals(PanoramaxItemState.ACCEPTED, item.state) else assertTrue(item.isFavorite)
        }
        assertEquals(result, peer.getBatch(batch.batchId))
        peer.deleteItems(batch.batchId, setOf("photo-1"))
        store.updateBatch(stale)
        assertFalse(PanoramaxQueueStore(root).getBatch(batch.batchId)!!.items.any { it.itemId == "photo-1" })
    }

    @Test fun failedCheckpointDoesNotUndoAnAlreadyDurableAcceptedItem() = withQueue { root, store ->
        val batch = store.createBatch("checkpoint-failure", instant)
        val item = add(root, store, batch, "original")
        val blocked = File(root, "panoramax/batches/.${batch.batchId}.json.tmp").apply { mkdir() }
        File(blocked, "blocked").writeText("blocked")
        repeat(128) { store.updateItemFavorite(batch.batchId, item.itemId, it % 2 == 0) }
        store.updateItem(batch.batchId, item.itemId, PanoramaxItemState.ACCEPTED)
        assertEquals(PanoramaxItemState.ACCEPTED, PanoramaxQueueStore(root).getBatch(batch.batchId)?.items?.single()?.state)
    }

    private fun add(root: File, store: PanoramaxQueueStore, batch: PanoramaxBatchRecord, id: String): PanoramaxItemRecord {
        val original = File(root, "fixture.jpg").apply { writeBytes(byteArrayOf(-1, -40, 1, 2, -1, -39)) }
        val thumbnail = File(root, "fixture.thumb.jpg").apply { writeBytes(byteArrayOf(-1, -40, 5, -1, -39)) }
        val sample = PanoramaxLocationSample(49.0, 8.0, instant, 5.0)
        return store.addJpeg(batch.batchId, original, thumbnail, PanoramaxCaptureMetadata(id, batch.captureSessionId,
            instant, sample, PanoramaxQueueStore.sha256(original), original.length(), "test"))
    }

    private fun withQueue(block: (File, PanoramaxQueueStore) -> Unit) {
        val root = createTempDirectory("panoramax-journal").toFile()
        try { block(root, PanoramaxQueueStore(root)) } finally { root.deleteRecursively() }
    }
}
