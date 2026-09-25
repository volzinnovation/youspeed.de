package de.youspeed.android.alpha

import java.io.File
import java.time.Instant
import kotlin.io.path.createTempDirectory
import org.junit.Assert.*
import org.junit.Test

class PanoramaxRetentionTests {
    private val instant = Instant.parse("2026-09-01T12:00:00Z")
    private val imageBytes = 11L

    @Test fun quotaEvictsOldestAcrossBatchesAndStopsAtTheByteBudget() = withQueue { root, store ->
        val first = addBatch(root, store, "first", listOf(0, 2, 4))
        val second = addBatch(root, store, "second", listOf(1, 3, 5))

        val report = store.enforceStorageLimit(imageBytes * 3)

        assertFalse(report.hasFailures)
        assertEquals(listOf("first-0", "second-0", "first-1"), report.deletedItemIds)
        assertEquals(listOf("first-2"), store.getBatch(first.batchId)?.items?.map { it.itemId })
        assertEquals(listOf("second-1", "second-2"), store.getBatch(second.batchId)?.items?.map { it.itemId })
        (first.items + second.items).forEach { item ->
            assertEquals(item.itemId !in report.deletedItemIds, store.originalFile(item).exists())
            assertEquals(item.itemId !in report.deletedItemIds, store.thumbnailFile(item).exists())
        }
    }

    @Test fun failedAssetDeletionStopsBeforeLaterItemsInTheSameOrAnotherBatch() = withQueue { root, store ->
        val first = addBatch(root, store, "first", listOf(0, 1, 3))
        val second = addBatch(root, store, "second", listOf(2))
        val blockedItem = first.items[1]
        val blockedOriginal = store.originalFile(blockedItem)
        assertTrue(blockedOriginal.delete())
        assertTrue(blockedOriginal.mkdir())
        File(blockedOriginal, "cannot-delete").writeText("retained")

        val report = store.enforceStorageLimit(1)

        assertEquals(listOf("first-0", "first-1"), report.deletedItemIds)
        assertEquals(listOf(blockedItem.originalPath), report.failedRelativePaths)
        // A failed asset is orphaned only after its record was durably removed;
        // every later candidate remains in the gallery for a future retry.
        assertEquals(listOf("first-2"), store.getBatch(first.batchId)?.items?.map { it.itemId })
        assertEquals(second.items, store.getBatch(second.batchId)?.items)
        assertTrue(blockedOriginal.exists())
        assertTrue(store.originalFile(first.items.last()).exists())
        assertTrue(store.originalFile(second.items.single()).exists())
        val reopened = PanoramaxQueueStore(File(root, "private"))
        assertEquals(listOf("first-2"), reopened.getBatch(first.batchId)?.items?.map { it.itemId })
    }

    @Test fun failedRecordCommitPreservesAllAssetsAndStopsEviction() = withQueue { root, store ->
        val batch = addBatch(root, store, "blocked", listOf(0, 1))
        val temporary = File(root, "private/panoramax/batches/.${batch.batchId}.json.tmp")
        assertTrue(temporary.mkdir())
        File(temporary, "cannot-replace").writeText("retained")

        val report = store.enforceStorageLimit(1)

        assertTrue(report.deletedItemIds.isEmpty())
        assertEquals(listOf("batches/${batch.batchId}.json"), report.failedRelativePaths)
        assertEquals(batch, store.getBatch(batch.batchId))
        batch.items.forEach {
            assertTrue(store.originalFile(it).exists())
            assertTrue(store.thumbnailFile(it).exists())
        }
    }

    @Test fun quotaProtectsFavoritesAcceptedPartialItemsAndLiveUploadStates() = withQueue { root, store ->
        val batch = addBatch(root, store, "partial", listOf(0, 1, 2, 3))
        val partial = batch.copy(state = PanoramaxBatchState.PARTIAL, remoteUploadSetId = "remote",
            items = batch.items.mapIndexed { index, item ->
                item.copy(isFavorite = index == 1, state = when (index) {
                    0 -> PanoramaxItemState.ACCEPTED
                    2 -> PanoramaxItemState.DUPLICATE
                    else -> PanoramaxItemState.QUEUED
                })
            })
        store.updateBatch(partial)
        val live = listOf(PanoramaxBatchState.CAPTURING, PanoramaxBatchState.CREATING_UPLOAD_SET,
            PanoramaxBatchState.UPLOADING, PanoramaxBatchState.PROCESSING).mapIndexed { index, state ->
            addBatch(root, store, "live-$index", listOf(-index - 1)).copy(state = state).also(store::updateBatch)
        }

        val report = store.enforceStorageLimit(1)

        assertEquals(listOf("partial-3"), report.deletedItemIds)
        assertFalse(report.hasFailures)
        // A late upload snapshot still cannot restore locally evicted items.
        store.updateBatch(partial)
        assertEquals(partial.items.take(3), store.getBatch(partial.batchId)?.items)
        live.forEach { assertEquals(it, store.getBatch(it.batchId)) }
    }

    @Test fun longDriveRetentionPersistsEveryRemainingItemAndPrunesEmptyBatches() = withQueue { root, store ->
        val batch = addBatch(root, store, "long-drive", (0 until 834).toList())

        val report = store.enforceStorageLimit(imageBytes * 134)

        assertFalse(report.hasFailures)
        assertEquals(batch.items.take(700).map { it.itemId }, report.deletedItemIds)
        assertEquals(batch.items.drop(700), store.getBatch(batch.batchId)?.items)
        val finalReport = store.enforceStorageLimit(1)
        assertFalse(finalReport.hasFailures)
        assertEquals(batch.items.drop(700).map { it.itemId }, finalReport.deletedItemIds)
        assertNull(store.getBatch(batch.batchId))
    }

    private fun addBatch(root: File, store: PanoramaxQueueStore, name: String, captureOffsets: List<Int>): PanoramaxBatchRecord {
        val batch = store.createBatch(name, instant)
        val items = captureOffsets.mapIndexed { index, offset ->
            val id = "$name-$index"
            val relativeDirectory = "batches/${batch.batchId}/$id"
            val directory = File(root, "private/panoramax/$relativeDirectory").apply { mkdirs() }
            val original = File(directory, "$id.jpg").apply { writeBytes(byteArrayOf(-1, -40, 1, 2, -1, -39)) }
            File(directory, "$id.thumb.jpg").writeBytes(byteArrayOf(-1, -40, 5, -1, -39))
            val sample = PanoramaxLocationSample(49.0, 8.0, instant.plusSeconds(offset.toLong()), 5.0)
            PanoramaxItemRecord(id, "$relativeDirectory/$id.jpg", "$relativeDirectory/$id.thumb.jpg",
                PanoramaxCaptureMetadata(id, name, sample.capturedAt, sample, PanoramaxQueueStore.sha256(original),
                    original.length(), "test"), PanoramaxItemState.CAPTURED)
        }
        return batch.copy(state = PanoramaxBatchState.AWAITING_REVIEW, items = items).also(store::updateBatch)
    }

    private fun withQueue(block: (File, PanoramaxQueueStore) -> Unit) {
        val root = createTempDirectory("panoramax-retention").toFile()
        try { block(root, PanoramaxQueueStore(File(root, "private"))) } finally { root.deleteRecursively() }
    }
}
