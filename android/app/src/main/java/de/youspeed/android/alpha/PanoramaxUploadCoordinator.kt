package de.youspeed.android.alpha

import java.io.File
import java.io.InterruptedIOException
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors

/** Explicit post-drive jobs. Neither restoration, account changes nor connectivity starts a job. */
class PanoramaxUploadCoordinator(
    private val store: PanoramaxQueueStore,
    private val account: PanoramaxAccountAccess,
    private val canProcessUploads: () -> Boolean,
    private val deleteUploadedImages: () -> Boolean,
    private val onChange: () -> Unit,
    private val transport: PanoramaxUploadTransport = HttpPanoramaxUploadTransport(),
    private val prepareOriginal: (String, String) -> File = store::prepareOriginalForUpload,
    private val pollingIntervalMillis: Long = 2000,
    private val pollingAttempts: Int = 12,
) : AutoCloseable {
    private class Job {
        val cancellation = PanoramaxRequestCancellation()
        @Volatile var thread: Thread? = null
    }
    private val executor = Executors.newCachedThreadPool { runnable -> Thread(runnable, "Panoramax-upload").apply { isDaemon = true } }
    private val jobs = ConcurrentHashMap<String, Job>()
    private val progress = ConcurrentHashMap<String, PanoramaxUploadProgress>()
    private val statuses = ConcurrentHashMap<String, String>()
    @Volatile private var closed = false

    val activeBatchIds: Set<String> get() = jobs.keys.toSet()
    val progressByBatch: Map<String, PanoramaxUploadProgress> get() = progress.toMap()
    val statusByBatch: Map<String, String> get() = statuses.toMap()
    val aggregateProgress: PanoramaxUploadProgress? get() {
        val active = progress.values.toList()
        if (active.isEmpty()) return null
        val phase = listOf(PanoramaxUploadPhase.STOPPING, PanoramaxUploadPhase.UPLOADING, PanoramaxUploadPhase.PROCESSING, PanoramaxUploadPhase.PREPARING)
            .first { value -> active.any { it.phase == value } }
        return PanoramaxUploadProgress(active.sumOf { it.completedItems }, active.sumOf { it.totalItems }, phase)
    }

    fun uploadSelections(selections: Map<String, Set<String>>) {
        selections.forEach { (batchId, itemIds) -> if (itemIds.isNotEmpty()) launch(batchId, itemIds) }
    }

    fun uploadBatch(batchId: String) { launch(batchId, null) }

    private fun launch(batchId: String, selection: Set<String>?) {
        if (closed) return
        if (!canProcessUploads()) { statuses[batchId] = "Finish recording before uploading"; changed(); return }
        val job = Job()
        if (jobs.putIfAbsent(batchId, job) != null) return
        progress[batchId] = PanoramaxUploadProgress(0, selection?.size ?: 0, PanoramaxUploadPhase.PREPARING)
        statuses[batchId] = "Preparing upload"
        changed()
        executor.execute {
            job.thread = Thread.currentThread()
            try {
                requireAllowed(job)
                check(account.validateConnection()) { "Connect and validate your Panoramax account" }
                requireAllowed(job)
                val token = requireNotNull(account.tokenForUpload()) { "Connect and validate your Panoramax account" }
                if (selection != null) store.approveSelection(batchId, selection)
                val batch = requireNotNull(store.getBatch(batchId)) { "Unknown Panoramax batch" }
                require(PanoramaxQueuePolicy.canStartUpload(batch.state)) { "Review and approve this batch first" }
                val origin = account.origin
                require(batch.instanceOrigin == null || batch.instanceOrigin.trimEnd('/') == origin) { "Select the Panoramax server used for this batch" }
                perform(batch, token, origin, job)
            } catch (error: Exception) {
                // File/HTTP errors and cancellation always quarantine any request with an unknown response.
                val recovery = runCatching { if (store.getBatch(batchId) != null) store.abandonInFlightItems(batchId) }
                statuses[batchId] = if (recovery.isFailure) "Upload stopped — queue recovery failed; restart before retrying" else
                    if (job.cancellation.isCancelled || error is InterruptedException || error is InterruptedIOException) "Upload stopped" else
                        if (error is IllegalArgumentException || error is IllegalStateException) error.message ?: "Upload could not start" else
                            PanoramaxUploadClient.userMessage(error)
            } finally {
                progress.remove(batchId)
                jobs.remove(batchId, job)
                job.thread = null
                Thread.interrupted()
                changed()
            }
        }
    }

    private fun perform(initial: PanoramaxBatchRecord, token: String, origin: String, job: Job) {
        val batchId = initial.batchId
        val selected = initial.items.filter { it.state in transferableStates }
        val previousCount = initial.items.count { PanoramaxQueuePolicy.isUploaded(it.state) }
        require(selected.isNotEmpty() || PanoramaxQueuePolicy.canResumeRemoteSet(initial) || initial.state == PanoramaxBatchState.PROCESSING) { "No images selected" }
        val client = PanoramaxUploadClient(token, store.uploadTemporaryDirectory(), transport, job.cancellation, { requireAllowed(job) }, origin = origin)
        var remoteId = initial.remoteUploadSetId
        if (initial.state == PanoramaxBatchState.PROCESSING) {
            require(!remoteId.isNullOrBlank()) { "Missing remote upload set" }
            progress[batchId] = PanoramaxUploadProgress(previousCount, previousCount, PanoramaxUploadPhase.PROCESSING)
            pollAndFinish(batchId, remoteId, client)
            return
        }

        store.updateBatch(initial.copy(
            state = if (remoteId == null) PanoramaxBatchState.CREATING_UPLOAD_SET else PanoramaxBatchState.UPLOADING,
            instanceOrigin = origin,
        ))
        changed()
        if (remoteId == null) {
            val response = client.createUploadSet("YouSpeed ${initial.createdAt}", selected.size)
            remoteId = response.id
            // Keep the server ID even if cancellation arrived with the response.
            val current = store.getBatch(batchId) ?: return
            store.updateBatch(current.copy(remoteUploadSetId = remoteId, state = PanoramaxBatchState.UPLOADING))
            changed()
            requireAllowed(job)
        }
        val uploadSetId = remoteId
        var uploaded = previousCount
        var total = previousCount + selected.size
        publishProgress(batchId, uploaded, total, PanoramaxUploadPhase.UPLOADING)
        for (item in selected) {
            requireAllowed(job)
            val durable = store.getBatch(batchId)?.items?.firstOrNull { it.itemId == item.itemId }
            if (durable == null || durable.state !in transferableStates) {
                total = (total - 1).coerceAtLeast(uploaded)
                publishProgress(batchId, uploaded, total, PanoramaxUploadPhase.UPLOADING)
                continue
            }
            val original = prepareOriginal(batchId, durable.itemId)
            try {
                client.upload(original, uploadSetId, "${durable.itemId}.jpg") {
                    requireAllowed(job)
                    // updateItem cannot resurrect a local deletion; mark immediately before transport.
                    store.updateItem(batchId, durable.itemId, PanoramaxItemState.UPLOADING)
                    changed()
                }
            } catch (error: Exception) {
                val latest = store.getBatch(batchId)?.items?.firstOrNull { it.itemId == item.itemId }
                if (latest == null) {
                    total = (total - 1).coerceAtLeast(uploaded)
                    publishProgress(batchId, uploaded, total, PanoramaxUploadPhase.UPLOADING)
                    continue
                }
                if (latest.state == PanoramaxItemState.UPLOADING) {
                    store.updateItem(batchId, item.itemId, PanoramaxUploadClient.durableItemStateAfterUploadFailure(error, job.cancellation.isCancelled))
                }
                throw error
            }
            if (store.getBatch(batchId)?.items?.any { it.itemId == item.itemId } == true) {
                // A returned success outranks simultaneous cancellation and is never resent.
                store.updateItem(batchId, item.itemId, PanoramaxItemState.UPLOADED)
                uploaded++
            } else total = (total - 1).coerceAtLeast(uploaded)
            publishProgress(batchId, uploaded, total, PanoramaxUploadPhase.UPLOADING)
            requireAllowed(job)
        }
        val current = store.getBatch(batchId) ?: return
        if (current.items.any { it.state in transferableStates }) {
            store.transitionBatch(batchId, PanoramaxBatchState.PARTIAL)
            statuses[batchId] = "$uploaded/$total transferred — retry remaining images"
            changed()
            return
        }
        client.complete(uploadSetId)
        // Completion is durable before the next cancellation-sensitive poll.
        if (store.getBatch(batchId) == null) return
        store.transitionBatch(batchId, PanoramaxBatchState.PROCESSING)
        publishProgress(batchId, uploaded, total, PanoramaxUploadPhase.PROCESSING)
        requireAllowed(job)
        pollAndFinish(batchId, uploadSetId, client)
    }

    private fun pollAndFinish(batchId: String, remoteId: String, client: PanoramaxUploadClient) {
        try {
            client.pollUntilReady(remoteId, pollingAttempts, pollingIntervalMillis)
            if (store.getBatch(batchId) == null) return
            store.transitionBatch(batchId, PanoramaxBatchState.COMPLETE)
            val deletion = if (deleteUploadedImages()) store.deleteUploadedItems(batchId) else PanoramaxDeletionReport()
            statuses[batchId] = if (deletion.hasFailures) "Upload complete — some local files could not be removed" else "Upload complete"
        } catch (_: PanoramaxProcessingTimeout) {
            statuses[batchId] = "Images transferred — processing continues; resume later"
        }
        changed()
    }

    private fun publishProgress(batchId: String, completed: Int, total: Int, phase: PanoramaxUploadPhase) {
        progress[batchId] = PanoramaxUploadProgress(completed, total, phase)
        statuses[batchId] = if (phase == PanoramaxUploadPhase.PROCESSING) "Panoramax is processing the batch" else "$completed/$total images transferred"
        changed()
    }

    private fun requireAllowed(job: Job) {
        job.cancellation.check()
        if (closed || !canProcessUploads()) throw InterruptedIOException("Finish recording before uploading")
    }

    fun stopAll() { jobs.keys.toList().forEach(::stopBatch) }

    fun stopBatch(batchId: String) {
        val job = jobs[batchId] ?: return
        progress[batchId]?.let { progress[batchId] = it.copy(phase = PanoramaxUploadPhase.STOPPING) }
        job.cancellation.cancel()
        job.thread?.interrupt()
        val recovery = runCatching { if (store.getBatch(batchId) != null) store.abandonInFlightItems(batchId) }
        statuses[batchId] = if (recovery.isSuccess) "Stopping upload" else "Upload stopped — queue recovery failed"
        changed()
    }

    private fun changed() { runCatching(onChange) }
    override fun close() { closed = true; stopAll(); executor.shutdown() }

    private companion object {
        val transferableStates = setOf(PanoramaxItemState.QUEUED, PanoramaxItemState.INCLUDED, PanoramaxItemState.RETRYABLE_ERROR)
    }
}
