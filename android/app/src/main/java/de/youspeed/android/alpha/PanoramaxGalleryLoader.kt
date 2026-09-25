package de.youspeed.android.alpha

import java.util.concurrent.atomic.AtomicBoolean

/** Coalesces progress/capture refreshes on the controller's serial background executor. */
internal class PanoramaxGalleryLoader(
    private val execute: (() -> Unit) -> Boolean,
    private val load: () -> List<PanoramaxBatchRecord>,
    private val publish: (List<PanoramaxBatchRecord>, Int) -> Unit,
    private val onFailure: (Exception) -> Unit,
) {
    private val queued = AtomicBoolean(false)

    fun refresh() {
        if (!queued.compareAndSet(false, true)) return
        if (!execute {
            // Allow one follow-up scan while this one is running. A burst of
            // upload notifications cannot enqueue a full scan for every photo.
            queued.set(false)
            try {
                val batches = load()
                publish(batches, batches.sumOf { it.items.size })
            } catch (error: Exception) {
                onFailure(error)
            }
        }) queued.set(false)
    }
}
