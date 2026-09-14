package de.youspeed.android.alpha

/**
 * Defers one button action until its current movie has finalized successfully.
 * Call from the controller's serial execution context. Capture the button's
 * intended action before submitting; finalization must not toggle a stopped
 * recorder back on. This gate never starts recording itself.
 */
class DashcamButtonActionGate {
    private data class PendingAction(val path: String, val action: () -> Unit)

    private var pending: PendingAction? = null

    val isWaiting: Boolean
        get() = pending != null

    fun submit(
        requiredFinalizationPath: String?,
        stopVideo: () -> Unit,
        action: () -> Unit,
    ) {
        if (pending != null) return
        if (requiredFinalizationPath == null) {
            action()
            return
        }

        val submitted = PendingAction(requiredFinalizationPath, action)
        pending = submitted
        try {
            stopVideo()
        } catch (error: Throwable) {
            // Preserve any subsequent action installed by a synchronous callback.
            if (pending === submitted) pending = null
            throw error
        }
    }

    fun onFinalized(path: String, success: Boolean) {
        val finalized = pending ?: return
        if (finalized.path != path) return
        pending = null
        if (success) finalized.action()
    }

    fun cancel() {
        pending = null
    }
}
