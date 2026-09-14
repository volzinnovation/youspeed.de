package de.youspeed.android.alpha

import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.RejectedExecutionException

/** One running lookup and one replaceable pending fix, independent of capture and file work. */
internal class LatestPendingLookupWorker(
    private val executor: ExecutorService = Executors.newSingleThreadExecutor(),
    private val onFailure: (Exception) -> Unit = {},
) : AutoCloseable {
    private val lock = Any()
    private var pending: (() -> Unit)? = null
    private var draining = false
    private var closed = false

    fun submit(task: () -> Unit): Boolean = synchronized(lock) {
        if (closed) return false
        pending = task
        if (!draining) {
            draining = true
            try {
                executor.execute(::drain)
            } catch (_: RejectedExecutionException) {
                draining = false
                pending = null
                return false
            }
        }
        true
    }

    fun clearPending() = synchronized(lock) { pending = null }

    private fun drain() {
        while (true) {
            val task = synchronized(lock) {
                val next = pending
                pending = null
                if (closed || next == null) {
                    draining = false
                    return
                }
                next
            }
            // Lookup failures are reported by the controller. A failed lookup
            // must not leave the newest pending GPS fix permanently undrained.
            try {
                task()
            } catch (failure: Exception) {
                onFailure(failure)
            }
        }
    }

    override fun close() {
        synchronized(lock) {
            closed = true
            pending = null
        }
        executor.shutdownNow()
    }
}

/** Arrival of a newer GPS fix does not invalidate useful work already in flight. */
internal class TrafficSignLookupMutationGate {
    private val lock = Any()
    private var token = 0L
    private var committedSequence = Long.MIN_VALUE

    fun snapshot(): Long = synchronized(lock) { token }

    fun advance(): Long = synchronized(lock) {
        committedSequence = Long.MIN_VALUE
        ++token
    }

    fun isCurrent(expected: Long): Boolean = synchronized(lock) { token == expected }

    fun isLatestCommitted(expected: Long, sequence: Long): Boolean = synchronized(lock) {
        token == expected && committedSequence == sequence
    }

    fun <T> mutateIfCurrent(expected: Long, block: () -> T): T? = synchronized(lock) {
        if (token != expected) null else block()
    }

    fun <T> commitIfCurrent(expected: Long, sequence: Long, block: () -> T?): T? = synchronized(lock) {
        if (token != expected || sequence <= committedSequence) return null
        block()?.also { committedSequence = sequence }
    }
}
