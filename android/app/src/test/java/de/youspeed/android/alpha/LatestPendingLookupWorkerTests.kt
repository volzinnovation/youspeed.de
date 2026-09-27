package de.youspeed.android.alpha

import java.util.concurrent.AbstractExecutorService
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import org.junit.Assert.*
import org.junit.Test

class LatestPendingLookupWorkerTests {
    @Test
    fun settingsRejectsRunningAndPausedFixesThenAcceptsFreshFixAfterDismissal() {
        val worker = LatestPendingLookupWorker()
        val gate = TrafficSignLookupMutationGate()
        val started = CountDownLatch(1)
        val release = CountDownLatch(1)
        val drainedDuringBootstrap = CountDownLatch(1)
        val replacementPublished = CountDownLatch(1)
        val published = java.util.concurrent.CopyOnWriteArrayList<String>()
        val oldToken = gate.snapshot()
        try {
            worker.submit {
                started.countDown()
                assertTrue(release.await(5, TimeUnit.SECONDS))
                gate.commitIfCurrent(oldToken, 1) { published += "deleted/context/path" }
            }
            assertTrue(started.await(5, TimeUnit.SECONDS))
            assertTrue(gate.setSettingsVisible(true))
            worker.clearPending()
            val duringBootstrap = gate.snapshot()
            assertFalse(gate.isCurrent(oldToken))
            assertNull(gate.mutateIfCurrent<Unit>(duringBootstrap) { error("Read a revoked bundle") })
            worker.submit {
                gate.commitIfCurrent(duringBootstrap, 2) { published += "bootstrap/old/path" }
                drainedDuringBootstrap.countDown()
            }
            release.countDown()
            assertTrue(drainedDuringBootstrap.await(5, TimeUnit.SECONDS))
            assertTrue(published.isEmpty())

            assertTrue(gate.setSettingsVisible(false))
            assertFalse(gate.isCurrent(duringBootstrap))
            assertFalse(gate.isLatestCommitted(oldToken, 1))
            val fresh = gate.snapshot()
            worker.submit {
                gate.commitIfCurrent(fresh, 3) { published += "replacement/context/path" }
                replacementPublished.countDown()
            }
            assertTrue(replacementPublished.await(5, TimeUnit.SECONDS))
            assertEquals(listOf("replacement/context/path"), published)
        } finally { release.countDown(); worker.close() }
    }

    @Test
    fun settingsDismissalWaitsForAllQueuedRemovalsAndRepeatedVisibilityIsIdempotent() {
        val gate = TrafficSignLookupMutationGate()
        assertTrue(gate.setSettingsVisible(true))
        val paused = gate.snapshot()
        assertFalse(gate.setSettingsVisible(true))
        assertEquals(paused, gate.snapshot())
        assertFalse(gate.beginBundleRemoval())
        assertFalse(gate.beginBundleRemoval())
        assertFalse(gate.setSettingsVisible(false))
        assertTrue(gate.isPaused())
        assertFalse(gate.endBundleRemoval())
        assertFalse(gate.isCurrent(paused))
        assertTrue(gate.endBundleRemoval())
        assertFalse(gate.isPaused())
        assertFalse(gate.isCurrent(paused))
        assertTrue(gate.isCurrent(gate.snapshot()))
        assertFalse(gate.setSettingsVisible(false))
    }

    @Test
    fun removalFailureOrRejectedSubmissionCanReleaseItsPauseWhileSettingsIsClosed() {
        val gate = TrafficSignLookupMutationGate()
        val previous = gate.snapshot()
        assertTrue(gate.beginBundleRemoval())
        assertFalse(gate.isCurrent(previous))
        // Completion uses the same balancing operation on success, failure and rejection.
        assertTrue(gate.endBundleRemoval())
        assertFalse(gate.isPaused())
        assertTrue(gate.isCurrent(gate.snapshot()))
    }

    @Test
    fun newerGpsFixesDoNotStarveRunningResultAndOnlyNewestPendingFixRuns() {
        val executor = ManualExecutor()
        val worker = LatestPendingLookupWorker(executor)
        val gate = TrafficSignLookupMutationGate()
        val epoch = gate.snapshot()
        val processed = mutableListOf<Int>()
        worker.submit {
            processed += 1
            worker.submit { processed += 2 }
            worker.submit {
                // Starting newer work does not suppress an already ready UI update.
                assertTrue(gate.isLatestCommitted(epoch, 1))
                processed += 3
                assertEquals("new", gate.commitIfCurrent(epoch, 3) { "new" })
            }
            assertEquals("slow", gate.commitIfCurrent(epoch, 1) { "slow" })
            assertTrue(gate.isLatestCommitted(epoch, 1))
        }
        executor.runNext()
        assertEquals(listOf(1, 3), processed)
        assertTrue(gate.isLatestCommitted(epoch, 3))
        assertFalse(gate.isLatestCommitted(epoch, 1))
        worker.close()
    }

    @Test
    fun stoppingDiscardsPendingWorkAndRejectsInFlightResultAcrossRestart() {
        val executor = ManualExecutor()
        val worker = LatestPendingLookupWorker(executor)
        val gate = TrafficSignLookupMutationGate()
        val stoppedEpoch = gate.snapshot()
        val processed = mutableListOf<String>()
        worker.submit {
            processed += "running"
            worker.submit { processed += "stopped pending" }
            gate.advance()
            worker.clearPending()
            assertNull(gate.commitIfCurrent(stoppedEpoch, 1) { "stopped" })
        }
        executor.runNext()
        val restartedEpoch = gate.snapshot()
        worker.submit {
            processed += "restarted"
            assertEquals("fresh", gate.commitIfCurrent(restartedEpoch, 1) { "fresh" })
        }
        executor.runNext()
        assertEquals(listOf("running", "restarted"), processed)
        worker.close()
    }

    @Test
    fun lateOrDuplicateResultCannotOverwriteNewerCommittedFix() {
        val gate = TrafficSignLookupMutationGate()
        val epoch = gate.snapshot()
        assertEquals(4, gate.commitIfCurrent(epoch, 4) { 4 })
        assertNull(gate.commitIfCurrent(epoch, 3) { error("old result mutated state") })
        assertNull(gate.commitIfCurrent(epoch, 4) { error("duplicate mutated state") })
        assertNull(gate.commitIfCurrent(epoch, 5) { null })
        assertTrue(gate.isLatestCommitted(epoch, 4))
        assertEquals(5, gate.commitIfCurrent(epoch, 5) { 5 })
    }

    @Test
    fun pendingSlotIsBoundedBeforeStartAndCloseRejectsFurtherWork() {
        val executor = ManualExecutor()
        val worker = LatestPendingLookupWorker(executor)
        val processed = mutableListOf<Int>()
        repeat(100) { value -> worker.submit { processed += value } }
        assertEquals(1, executor.queuedCount)
        executor.runNext()
        assertEquals(listOf(99), processed)
        worker.submit { processed += 100 }
        worker.close()
        assertFalse(worker.submit { processed += 101 })
        assertEquals(listOf(99), processed)
    }

    @Test
    fun lookupFailureIsReportedAndNewestPendingFixStillRuns() {
        val executor = ManualExecutor()
        val failures = mutableListOf<Exception>()
        val worker = LatestPendingLookupWorker(executor, failures::add)
        var recovered = false
        worker.submit {
            worker.submit { recovered = true }
            throw IllegalStateException("lookup failed")
        }
        executor.runNext()
        assertTrue(recovered)
        assertEquals("lookup failed", failures.single().message)
        worker.close()
    }

    private class ManualExecutor : AbstractExecutorService() {
        private val queued = ArrayDeque<Runnable>()
        private var stopped = false
        val queuedCount: Int get() = queued.size
        fun runNext() = queued.removeFirst().run()
        override fun execute(command: Runnable) { queued += command }
        override fun shutdown() { stopped = true }
        override fun shutdownNow(): MutableList<Runnable> {
            stopped = true
            return queued.toMutableList().also { queued.clear() }
        }
        override fun isShutdown(): Boolean = stopped
        override fun isTerminated(): Boolean = stopped && queued.isEmpty()
        override fun awaitTermination(timeout: Long, unit: TimeUnit): Boolean = isTerminated
    }
}
