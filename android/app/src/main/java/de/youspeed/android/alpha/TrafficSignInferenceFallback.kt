package de.youspeed.android.alpha

/** Keeps native inference resources on their owning thread and retries a failed accelerator once on CPU. */
internal class TrafficSignInferenceFallback<T : AutoCloseable>(
    private val createCpu: () -> T,
    createAccelerated: (() -> T)?,
    unavailableReason: String?,
    private val onCpuFallback: (String) -> Unit = {},
) : AutoCloseable {
    private val ownerThread = Thread.currentThread()
    private var closed = false
    var executionBackend: String = if (createAccelerated == null) "cpu" else "gpu"
        private set
    var accelerationFallbackReason: String? = null
        private set
    private var resource: T? = if (createAccelerated == null) {
        unavailableReason?.let(::recordFallback)
        createCpu()
    } else {
        try {
            createAccelerated()
        } catch (failure: RuntimeException) {
            recordFallback("GPU initialization failed: ${failureDescription(failure)}")
            createCpu()
        } catch (failure: LinkageError) {
            recordFallback("GPU runtime unavailable: ${failureDescription(failure)}")
            createCpu()
        }
    }

    fun <R> run(action: (T) -> R): R {
        checkOwner()
        check(!closed) { "Traffic-sign inference runtime is closed" }
        return try {
            action(checkNotNull(resource) { "Traffic-sign inference runtime is unavailable" })
        } catch (failure: RuntimeException) {
            retryOnCpu(failure, action)
        } catch (failure: LinkageError) {
            retryOnCpu(failure, action)
        }
    }

    private fun <R> retryOnCpu(failure: Throwable, action: (T) -> R): R {
        if (executionBackend != "gpu") throw failure
        // GPU delegates and their interpreters must be disposed on this same thread.
        val acceleratedResource = resource
        resource = null
        val cleanupFailure = try {
            acceleratedResource?.close()
            null
        } catch (cleanup: RuntimeException) {
            cleanup
        } catch (cleanup: LinkageError) {
            cleanup
        }
        recordFallback("GPU inference failed: ${failureDescription(failure)}" +
            (cleanupFailure?.let { "; GPU cleanup failed: ${failureDescription(it)}" } ?: ""))
        resource = createCpu()
        return action(checkNotNull(resource))
    }

    private fun recordFallback(reason: String) {
        executionBackend = "cpu"
        accelerationFallbackReason = reason
        onCpuFallback(reason)
    }

    override fun close() {
        checkOwner()
        if (closed) return
        closed = true
        val closingResource = resource
        resource = null
        closingResource?.close()
    }

    private fun checkOwner() {
        check(Thread.currentThread() === ownerThread) {
            "Traffic-sign inference must run and close on the thread that initialized it"
        }
    }

    private fun failureDescription(failure: Throwable): String =
        failure.message?.takeIf(String::isNotBlank) ?: failure.javaClass.simpleName
}
