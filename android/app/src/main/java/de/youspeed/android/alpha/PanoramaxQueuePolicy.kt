package de.youspeed.android.alpha

data class PanoramaxQueueCleanupReport(
    val recoveredBatchIds: List<String> = emptyList(),
    val removedOrphanFileCount: Int = 0,
    val removedOrphanByteCount: Long = 0,
    val removedEmptyBatchCount: Int = 0,
    val failedRelativePaths: List<String> = emptyList(),
) { val hasFailures: Boolean get() = failedRelativePaths.isNotEmpty() }

data class PanoramaxDeletionReport(
    val deletedItemIds: List<String> = emptyList(),
    val failedRelativePaths: List<String> = emptyList(),
) { val hasFailures: Boolean get() = failedRelativePaths.isNotEmpty() }

object PanoramaxQueuePolicy {
    fun isUploaded(state: PanoramaxItemState): Boolean = state in setOf(
        PanoramaxItemState.UPLOADED, PanoramaxItemState.ACCEPTED, PanoramaxItemState.DUPLICATE,
    )
    fun canSelectItem(state: PanoramaxItemState): Boolean = state in setOf(
        PanoramaxItemState.CAPTURED, PanoramaxItemState.INCLUDED, PanoramaxItemState.EXCLUDED,
        PanoramaxItemState.QUEUED, PanoramaxItemState.RETRYABLE_ERROR,
    )
    fun canEditSelection(state: PanoramaxBatchState): Boolean = state in setOf(
        PanoramaxBatchState.AWAITING_REVIEW, PanoramaxBatchState.APPROVED,
        PanoramaxBatchState.PARTIAL, PanoramaxBatchState.BLOCKED,
    )
    fun canStartUpload(state: PanoramaxBatchState): Boolean = state in setOf(
        PanoramaxBatchState.APPROVED, PanoramaxBatchState.PARTIAL, PanoramaxBatchState.PROCESSING,
    )
    fun canResumeRemoteSet(batch: PanoramaxBatchRecord): Boolean = !batch.remoteUploadSetId.isNullOrBlank() &&
        (batch.state == PanoramaxBatchState.PROCESSING ||
            (batch.state == PanoramaxBatchState.PARTIAL && (batch.items.isEmpty() || batch.items.any { isUploaded(it.state) })))
    fun canEvictItem(batchState: PanoramaxBatchState, itemState: PanoramaxItemState): Boolean = when (batchState) {
        PanoramaxBatchState.CAPTURING, PanoramaxBatchState.CREATING_UPLOAD_SET,
        PanoramaxBatchState.UPLOADING, PanoramaxBatchState.PROCESSING -> false
        PanoramaxBatchState.PARTIAL -> !isUploaded(itemState)
        else -> true
    }
}

/** Matches the iPhone gallery: local selection also serves deletion, while
 * upload sends only eligible originals and resumes existing remote work. */
data class PanoramaxGalleryUploadPlan(
    val selections: Map<String, Set<String>>,
    val resumableBatchIds: Set<String>,
) {
    val selectedItemCount: Int get() = selections.values.sumOf { it.size }
    val hasWork: Boolean get() = selections.isNotEmpty() || resumableBatchIds.isNotEmpty()

    companion object {
        fun create(
            batches: List<PanoramaxBatchRecord>,
            selectedItemIds: Map<String, Set<String>>,
            activeBatchIds: Set<String> = emptySet(),
        ): PanoramaxGalleryUploadPlan {
            val available = batches.filter { it.batchId !in activeBatchIds }
            val selections = available.filter { PanoramaxQueuePolicy.canEditSelection(it.state) }
                .mapNotNull { batch ->
                    val selected = selectedItemIds[batch.batchId].orEmpty()
                    batch.items.filter { it.itemId in selected && PanoramaxQueuePolicy.canSelectItem(it.state) }
                        .mapTo(mutableSetOf()) { it.itemId }
                        .takeIf { it.isNotEmpty() }?.let { batch.batchId to it }
                }.toMap()
            val resumable = available.filter { it.batchId !in selections && PanoramaxQueuePolicy.canResumeRemoteSet(it) }
                .mapTo(mutableSetOf()) { it.batchId }
            return PanoramaxGalleryUploadPlan(selections, resumable)
        }
    }
}
