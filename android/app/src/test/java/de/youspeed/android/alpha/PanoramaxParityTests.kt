package de.youspeed.android.alpha

import java.io.File
import java.io.IOException
import java.time.Duration
import java.time.Instant
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger
import kotlin.io.path.createTempDirectory
import org.junit.Assert.*
import org.junit.Test

class PanoramaxParityTests {
    private val instant = Instant.parse("2026-09-01T12:00:00Z")

    @Test fun timeCadenceUsesIntervalAndGpsMovementWithoutTheDistanceThreshold() {
        val previous = PanoramaxLocationSample(49.0, 8.0, instant, 2.0)
        val movedTenMeters = previous.copy(longitude = 8.00014, capturedAt = instant.plusSeconds(5))
        val time = PanoramaxCadenceConfig(distanceMeters = 25.0, triggerMode = PanoramaxCaptureTriggerMode.TIME)
        assertTrue(PanoramaxCapturePolicy.shouldCapture(previous, movedTenMeters, config = time))
        assertFalse(PanoramaxCapturePolicy.shouldCapture(previous, movedTenMeters, config = time.copy(triggerMode = PanoramaxCaptureTriggerMode.DISTANCE)))
        assertFalse(PanoramaxCapturePolicy.shouldCapture(previous, movedTenMeters.copy(capturedAt = instant.plusSeconds(4)), config = time))
        assertFalse(PanoramaxCapturePolicy.shouldCapture(previous, previous.copy(capturedAt = instant.plusSeconds(60)), config = time))
    }

    @Test fun startupRecoversInterruptedWorkAndNeverScavengesReferencedOrUnreadableImages() = withQueue { root, store ->
        val captured = addBatch(root, store, "capture", 1)
        val uploading = addBatch(root, store, "upload", 3)
        store.updateBatch(uploading.copy(state = PanoramaxBatchState.UPLOADING, remoteUploadSetId = "remote", items = uploading.items.mapIndexed { index, item ->
            item.copy(state = listOf(PanoramaxItemState.UPLOADED, PanoramaxItemState.UPLOADING, PanoramaxItemState.QUEUED)[index])
        }))
        val orphan = File(store.originalFile(captured.items.single()).parentFile, "orphan.jpg").apply { writeText("orphan") }
        val corruptDirectory = File(root, "private/panoramax/batches/broken").apply { mkdirs() }
        val corruptOriginal = File(corruptDirectory, "keep.jpg").apply { writeText("precious") }
        File(root, "private/panoramax/batches/broken.json").writeText("not-json")

        val report = store.performStartupMaintenanceNow()

        assertEquals(PanoramaxBatchState.AWAITING_REVIEW, store.getBatch(captured.batchId)?.state)
        assertEquals(PanoramaxBatchState.PARTIAL, store.getBatch(uploading.batchId)?.state)
        assertEquals(listOf(PanoramaxItemState.UPLOADED, PanoramaxItemState.ABANDONED, PanoramaxItemState.QUEUED), store.getBatch(uploading.batchId)?.items?.map { it.state })
        assertFalse(orphan.exists())
        assertTrue(store.originalFile(captured.items.single()).exists())
        assertTrue(corruptOriginal.exists())
        assertEquals(listOf("batches/broken.json"), report.failedRelativePaths)
    }

    @Test fun localDeletionCannotBeUndoneByAnUploadSnapshotAndPreservesRemoteResume() = withQueue { root, store ->
        val initial = addBatch(root, store, "deletion", 1)
        val partial = initial.copy(state = PanoramaxBatchState.PARTIAL, remoteUploadSetId = "remote",
            items = initial.items.map { it.copy(state = PanoramaxItemState.UPLOADED) })
        store.updateBatch(partial)
        store.deleteItems(partial.batchId, setOf(partial.items.single().itemId))
        store.updateBatch(partial)
        val current = requireNotNull(store.getBatch(partial.batchId))
        assertTrue(current.items.isEmpty())
        assertTrue(PanoramaxQueuePolicy.canResumeRemoteSet(current))
        assertFalse(store.originalFile(initial.items.single()).exists())
        assertThrows(IllegalArgumentException::class.java) { store.updateItem(current.batchId, initial.items.single().itemId, PanoramaxItemState.UPLOADED) }
    }

    @Test fun quotaKeepsFavoritesLiveCapturesAndAcceptedPartialItems() = withQueue { root, store ->
        val removable = addBatch(root, store, "remove", 1)
        store.transitionBatch(removable.batchId, PanoramaxBatchState.AWAITING_REVIEW)
        val favorite = addBatch(root, store, "favorite", 1)
        store.transitionBatch(favorite.batchId, PanoramaxBatchState.AWAITING_REVIEW)
        store.updateItemFavorite(favorite.batchId, favorite.items.single().itemId, true)
        val live = addBatch(root, store, "live", 1)
        val partial = addBatch(root, store, "partial", 1)
        store.updateBatch(partial.copy(state = PanoramaxBatchState.PARTIAL, remoteUploadSetId = "remote", items = partial.items.map { it.copy(state = PanoramaxItemState.UPLOADED) }))
        val report = store.enforceStorageLimit(1)
        assertEquals(listOf(removable.items.single().itemId), report.deletedItemIds)
        assertTrue(store.originalFile(favorite.items.single()).exists())
        assertTrue(store.getBatch(favorite.batchId)?.items?.single()?.isFavorite == true)
        assertTrue(store.originalFile(live.items.single()).exists())
        assertTrue(store.originalFile(partial.items.single()).exists())
    }

    @Test fun accountConnectionUsesYouSpeedByDefaultAndNeverOptsIntoCapture() {
        val memory = MemoryCredentials()
        val requests = mutableListOf<PanoramaxHttpRequest>()
        val account = PanoramaxAccount(memory, PanoramaxUploadTransport { request, _ ->
            requests += request
            when (request.path) {
                "/api/auth/tokens/generate" -> response("""{"id":"device","jwt_token":"secret","links":[{"rel":"claim","href":"https://panoramax.youspeed.de/claim/device"}]}""")
                else -> PanoramaxHttpResponse(200)
            }
        })
        assertEquals("https://panoramax.youspeed.de/claim/device", account.connect())
        assertFalse(account.state.isConnected)
        assertEquals("secret", account.tokenForUpload())
        assertTrue(account.validateConnection())
        account.disconnect()
        assertNull(account.tokenForUpload())
        assertEquals(listOf("/api/auth/tokens/generate", "/api/users/me", "/api/users/me/tokens/device"), requests.map { it.path })
        assertFalse(requests.joinToString().contains("secret"))
    }

    @Test fun accountCanSelectOpenStreetMapFranceAndRoutesEveryAccountRequestThere() {
        val memory = MemoryCredentials()
        val requests = mutableListOf<PanoramaxHttpRequest>()
        val account = PanoramaxAccount(memory, PanoramaxUploadTransport { request, _ ->
            requests += request
            when (request.path) {
                "/api/auth/tokens/generate" -> response("""{"id":"osm-device","jwt_token":"osm-secret","links":[{"rel":"claim","href":"https://panoramax.openstreetmap.fr/claim/osm-device"}]}""")
                else -> PanoramaxHttpResponse(200)
            }
        })

        account.selectServer("openstreetmap-france")

        assertEquals("https://panoramax.openstreetmap.fr", account.origin)
        assertEquals("https://panoramax.openstreetmap.fr/claim/osm-device", account.connect())
        assertTrue(account.validateConnection())
        account.disconnect()
        assertTrue(requests.all { it.origin == "https://panoramax.openstreetmap.fr" })
    }

    @Test fun explicitUploadSkipsAcceptedItemsCompletesBeforeDeletingAndCleansMultipart() = withQueue { root, store ->
        val batch = addBatch(root, store, "resume", 2)
        store.updateBatch(batch.copy(state = PanoramaxBatchState.PARTIAL, remoteUploadSetId = "existing", items = batch.items.mapIndexed { index, item ->
            item.copy(state = if (index == 0) PanoramaxItemState.UPLOADED else PanoramaxItemState.QUEUED)
        }))
        val paths = mutableListOf<String>()
        val transport = PanoramaxUploadTransport { request, _ ->
            paths += request.path
            assertTrue(store.originalFile(batch.items.first()).exists())
            if (request.path.endsWith("/files")) {
                val body = requireNotNull(request.bodyFile).readText(Charsets.ISO_8859_1)
                assertTrue(body.contains("name=\"file\""))
                assertTrue(body.contains(batch.items.last().itemId + ".jpg"))
            }
            when {
                request.path.endsWith("/files") -> PanoramaxHttpResponse(201)
                request.path.endsWith("/complete") -> response("""{"id":"existing","status":"processing"}""")
                else -> response("""{"id":"existing","ready":true}""")
            }
        }
        coordinator(store, transport, deleteUploaded = true).use { coordinator ->
            coordinator.uploadBatch(batch.batchId)
            awaitIdle(coordinator)
            assertEquals("Upload complete", coordinator.statusByBatch[batch.batchId])
        }
        assertEquals(listOf("/api/upload_sets/existing/files", "/api/upload_sets/existing/complete", "/api/upload_sets/existing"), paths)
        assertNull(store.getBatch(batch.batchId))
        assertFalse(store.originalFile(batch.items.first()).exists())
        assertTrue(store.uploadTemporaryDirectory().listFiles().orEmpty().isEmpty())
    }

    @Test fun stopAbandonsOnlyInFlightImageAndKeepsAcceptedAndQueuedEvidence() = withQueue { root, store ->
        val batch = addBatch(root, store, "stop", 3)
        store.approveSelectionAfterClosing(batch)
        val started = CountDownLatch(1)
        val fileCalls = AtomicInteger()
        val transport = PanoramaxUploadTransport { request, cancellation ->
            when {
                request.path == "/api/upload_sets" -> response("""{"id":"remote"}""")
                request.path.endsWith("/files") -> {
                    if (fileCalls.incrementAndGet() == 2) {
                        started.countDown()
                        try { CountDownLatch(1).await(5, TimeUnit.SECONDS) } catch (_: InterruptedException) { }
                        cancellation.check()
                    }
                    PanoramaxHttpResponse(201)
                }
                else -> error("Cancellation must prevent completion/polling")
            }
        }
        coordinator(store, transport).use { coordinator ->
            coordinator.uploadBatch(batch.batchId)
            assertTrue(started.await(5, TimeUnit.SECONDS))
            coordinator.stopAll()
            awaitIdle(coordinator)
        }
        val current = requireNotNull(store.getBatch(batch.batchId))
        assertEquals(PanoramaxBatchState.PARTIAL, current.state)
        assertEquals(listOf(PanoramaxItemState.UPLOADED, PanoramaxItemState.ABANDONED, PanoramaxItemState.QUEUED), current.items.map { it.state })
        assertTrue(current.items.all { store.originalFile(it).exists() })
    }

    @Test fun startingCaptureBlocksTheNextNetworkBoundaryAndPreservesSuccessfulResponse() = withQueue { root, store ->
        val batch = addBatch(root, store, "gate", 2)
        store.approveSelectionAfterClosing(batch)
        val allowed = AtomicBoolean(true)
        val requests = mutableListOf<String>()
        val transport = PanoramaxUploadTransport { request, _ ->
            requests += request.path
            if (request.path.endsWith("/files")) { allowed.set(false); PanoramaxHttpResponse(201) }
            else response("""{"id":"remote"}""")
        }
        coordinator(store, transport, allowed = allowed::get).use { coordinator ->
            coordinator.uploadBatch(batch.batchId)
            awaitIdle(coordinator)
        }
        assertEquals(listOf("/api/upload_sets", "/api/upload_sets/remote/files"), requests)
        assertEquals(listOf(PanoramaxItemState.UPLOADED, PanoramaxItemState.QUEUED), store.getBatch(batch.batchId)?.items?.map { it.state })
    }

    @Test fun activeCaptureAndUnreviewedBatchNeverReachUploadTransport() = withQueue { root, store ->
        val batch = addBatch(root, store, "blocked", 1)
        val calls = AtomicInteger()
        val transport = PanoramaxUploadTransport { _, _ -> calls.incrementAndGet(); error("Must not upload") }
        coordinator(store, transport, allowed = { false }).use { coordinator -> coordinator.uploadBatch(batch.batchId); awaitIdle(coordinator) }
        coordinator(store, transport).use { coordinator -> coordinator.uploadBatch(batch.batchId); awaitIdle(coordinator) }
        assertEquals(0, calls.get())
        assertEquals(PanoramaxBatchState.CAPTURING, store.getBatch(batch.batchId)?.state)
    }

    @Test fun processingTimeoutRetainsLocalEvidenceAndResumeOnlyPolls() = withQueue { root, store ->
        val batch = addBatch(root, store, "processing", 1)
        store.updateBatch(batch.copy(state = PanoramaxBatchState.PROCESSING, remoteUploadSetId = "remote", items = batch.items.map { it.copy(state = PanoramaxItemState.UPLOADED) }))
        val paths = mutableListOf<String>()
        coordinator(store, PanoramaxUploadTransport { request, _ -> paths += request.path; response("""{"id":"remote","ready":false}""") }, deleteUploaded = true).use { coordinator ->
            coordinator.uploadBatch(batch.batchId)
            awaitIdle(coordinator)
        }
        assertEquals(listOf("/api/upload_sets/remote"), paths)
        assertEquals(PanoramaxBatchState.PROCESSING, store.getBatch(batch.batchId)?.state)
        assertTrue(store.originalFile(batch.items.single()).exists())
    }

    @Test fun failureClassificationOnlyRetriesKnownResponses() {
        assertEquals(PanoramaxItemState.ABANDONED, PanoramaxUploadClient.durableItemStateAfterUploadFailure(IOException(), false))
        assertEquals(PanoramaxItemState.RETRYABLE_ERROR, PanoramaxUploadClient.durableItemStateAfterUploadFailure(PanoramaxHttpException(503), false))
        assertEquals(PanoramaxItemState.ABANDONED, PanoramaxUploadClient.durableItemStateAfterUploadFailure(PanoramaxHttpException(503), true))
    }

    @Test fun retryAfterDefinitiveHttpFailureReusesSetAndSkipsAcceptedOriginal() = withQueue { root, store ->
        val batch = addBatch(root, store, "http-retry", 2)
        store.approveSelectionAfterClosing(batch)
        val creates = AtomicInteger()
        val files = mutableListOf<String>()
        val failSecond = AtomicBoolean(true)
        val transport = PanoramaxUploadTransport { request, _ ->
            when {
                request.path == "/api/upload_sets" -> { creates.incrementAndGet(); response("""{"id":"same-set"}""") }
                request.path.endsWith("/files") -> {
                    val body = requireNotNull(request.bodyFile).readText(Charsets.ISO_8859_1)
                    val item = batch.items.first { body.contains(it.itemId + ".jpg") }.itemId
                    files += item
                    PanoramaxHttpResponse(if (item == batch.items.last().itemId && failSecond.getAndSet(false)) 503 else 201)
                }
                else -> response("""{"id":"same-set","ready":true}""")
            }
        }
        coordinator(store, transport).use { coordinator ->
            coordinator.uploadBatch(batch.batchId)
            awaitIdle(coordinator)
            assertEquals(listOf(PanoramaxItemState.UPLOADED, PanoramaxItemState.RETRYABLE_ERROR), store.getBatch(batch.batchId)?.items?.map { it.state })
            coordinator.uploadBatch(batch.batchId)
            awaitIdle(coordinator)
        }
        assertEquals(1, creates.get())
        assertEquals(listOf(batch.items.first().itemId, batch.items.last().itemId, batch.items.last().itemId), files)
        assertEquals(PanoramaxBatchState.COMPLETE, store.getBatch(batch.batchId)?.state)
    }

    @Test fun deletingAnInFlightItemCannotBeUndoneByItsLateSuccess() = withQueue { root, store ->
        val batch = addBatch(root, store, "late-delete", 2)
        store.approveSelectionAfterClosing(batch)
        val reachedUpload = CountDownLatch(1)
        val respond = CountDownLatch(1)
        val transport = PanoramaxUploadTransport { request, _ ->
            if (request.path.endsWith("/files")) {
                reachedUpload.countDown()
                while (respond.count > 0) {
                    try { respond.await(50, TimeUnit.MILLISECONDS) } catch (_: InterruptedException) { }
                }
                PanoramaxHttpResponse(201)
            } else response("""{"id":"remote"}""")
        }
        coordinator(store, transport).use { coordinator ->
            coordinator.uploadBatch(batch.batchId)
            assertTrue(reachedUpload.await(5, TimeUnit.SECONDS))
            coordinator.stopBatch(batch.batchId)
            store.deleteItems(batch.batchId, setOf(batch.items.first().itemId))
            respond.countDown()
            awaitIdle(coordinator)
        }
        val current = requireNotNull(store.getBatch(batch.batchId))
        assertEquals(listOf(batch.items.last().itemId), current.items.map { it.itemId })
        assertEquals(PanoramaxItemState.QUEUED, current.items.single().state)
        assertFalse(store.originalFile(batch.items.first()).exists())
    }

    private fun coordinator(store: PanoramaxQueueStore, transport: PanoramaxUploadTransport, deleteUploaded: Boolean = false, allowed: () -> Boolean = { true }) =
        PanoramaxUploadCoordinator(store, object : PanoramaxAccountAccess {
            override fun validateConnection() = true
            override fun tokenForUpload() = "test-token"
        }, allowed, { deleteUploaded }, {}, transport, { batchId, itemId ->
            store.originalFile(requireNotNull(store.getBatch(batchId)).items.first { it.itemId == itemId })
        }, pollingIntervalMillis = 0, pollingAttempts = 1)

    private fun awaitIdle(coordinator: PanoramaxUploadCoordinator) {
        val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(5)
        while (coordinator.activeBatchIds.isNotEmpty() && System.nanoTime() < deadline) Thread.sleep(5)
        assertTrue("Upload worker did not finish: ${coordinator.statusByBatch}", coordinator.activeBatchIds.isEmpty())
    }

    private fun PanoramaxQueueStore.approveSelectionAfterClosing(batch: PanoramaxBatchRecord) {
        transitionBatch(batch.batchId, PanoramaxBatchState.AWAITING_REVIEW)
        approveSelection(batch.batchId, batch.items.map { it.itemId }.toSet())
    }

    private fun addBatch(root: File, store: PanoramaxQueueStore, name: String, count: Int): PanoramaxBatchRecord {
        val batch = store.createBatch(name, instant)
        repeat(count) { index ->
            val file = File(root, "$name-$index.jpg").apply { writeBytes(byteArrayOf(-1, -40, 1, 2, -1, -39)) }
            val thumb = File(root, "$name-$index.thumb.jpg").apply { writeBytes(byteArrayOf(-1, -40, 5, -1, -39)) }
            val sample = PanoramaxLocationSample(49.0, 8.0, instant.plusSeconds(index.toLong()), 5.0)
            store.addJpeg(batch.batchId, file, thumb, PanoramaxCaptureMetadata("$name-$index", name, sample.capturedAt, sample,
                PanoramaxQueueStore.sha256(file), file.length(), "test"))
        }
        return requireNotNull(store.getBatch(batch.batchId))
    }

    private fun response(json: String) = PanoramaxHttpResponse(200, json.toByteArray())
    private fun withQueue(block: (File, PanoramaxQueueStore) -> Unit) {
        val root = createTempDirectory("panoramax-parity").toFile()
        try { block(root, PanoramaxQueueStore(File(root, "private"))) } finally { root.deleteRecursively() }
    }
    private class MemoryCredentials : PanoramaxOriginCredentialStorage {
        var value: PanoramaxCredentials? = null
        override fun read() = value
        override fun save(credentials: PanoramaxCredentials) { value = credentials }
        override fun delete() { value = null }
        private val values = mutableMapOf<String, PanoramaxCredentials>()
        override fun read(origin: String) = values[origin]
        override fun save(origin: String, credentials: PanoramaxCredentials) { values[origin] = credentials }
        override fun delete(origin: String) { values.remove(origin) }
    }
}
