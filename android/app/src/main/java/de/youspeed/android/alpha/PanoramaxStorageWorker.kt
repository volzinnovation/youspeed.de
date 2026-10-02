package de.youspeed.android.alpha

import java.util.concurrent.Executors

/**
 * Orders capture batch creation, JPEG persistence and session finalization
 * independently of map downloads. Closing drains accepted work so a finalizer
 * can seal its session after the last in-flight write without blocking the UI.
 */
internal class PanoramaxStorageWorker : AutoCloseable {
    private val executor = Executors.newSingleThreadExecutor { task ->
        Thread(task, "panoramax-storage")
    }

    fun execute(task: () -> Unit) = executor.execute(task)

    override fun close() = executor.shutdown()
}
