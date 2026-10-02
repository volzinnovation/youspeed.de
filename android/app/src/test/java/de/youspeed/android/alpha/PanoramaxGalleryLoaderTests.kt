package de.youspeed.android.alpha

import java.time.Instant
import java.util.ArrayDeque
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import org.junit.Assert.*
import org.junit.Test

class PanoramaxGalleryLoaderTests {
    @Test fun callerRemainsResponsiveWhileLargeGalleryLoadIsBlocked() {
        val executor = Executors.newSingleThreadExecutor()
        val loading = CountDownLatch(1)
        val release = CountDownLatch(1)
        val published = CountDownLatch(1)
        val caller = Thread.currentThread()
        var worker: Thread? = null
        var photoCount = 0
        val instant = Instant.parse("2026-09-25T12:00:00Z")
        val item = PanoramaxItemRecord("item", "original.jpg", "thumbnail.jpg",
            PanoramaxCaptureMetadata("item", "session", instant,
                PanoramaxLocationSample(49.0, 8.0, instant, 2.0), "0".repeat(64), 4, "test"),
            PanoramaxItemState.CAPTURED)
        val batch = PanoramaxBatchRecord("batch", "session", instant,
            PanoramaxBatchState.AWAITING_REVIEW, List(10_000) { item.copy(itemId = "item-$it") })
        val loader = PanoramaxGalleryLoader(
            execute = { task -> executor.execute(task); true },
            load = {
                worker = Thread.currentThread()
                loading.countDown()
                check(release.await(5, TimeUnit.SECONDS))
                listOf(batch)
            },
            publish = { batches, count ->
                assertSame(batch, batches.single())
                photoCount = count
                published.countDown()
            },
            onFailure = { throw it },
        )
        try {
            loader.refresh()
            assertTrue(loading.await(2, TimeUnit.SECONDS))
            assertNotSame("Disk work must run outside the requesting/UI thread", caller, worker)
            assertEquals("A blocked scan does not publish an empty gallery", 1L, published.count)
            release.countDown()
            assertTrue(published.await(2, TimeUnit.SECONDS))
            assertEquals(10_000, photoCount)
        } finally {
            release.countDown()
            executor.shutdownNow()
        }
    }

    @Test fun refreshBurstsKeepAtMostOneQueuedScanAndRetainChangesDuringLoading() {
        val tasks = ArrayDeque<() -> Unit>()
        var reads = 0
        var publications = 0
        lateinit var loader: PanoramaxGalleryLoader
        loader = PanoramaxGalleryLoader(
            execute = { tasks.add(it); true },
            load = {
                reads++
                if (reads == 1) repeat(1_000) { loader.refresh() }
                emptyList()
            },
            publish = { _, _ -> publications++ },
            onFailure = { throw it },
        )
        repeat(1_000) { loader.refresh() }
        assertEquals(1, tasks.size)
        tasks.removeFirst().invoke()
        assertEquals("A change during the scan must trigger one follow-up", 1, tasks.size)
        tasks.removeFirst().invoke()
        assertTrue(tasks.isEmpty())
        assertEquals(2, reads)
        assertEquals(2, publications)
    }

    @Test fun failedOrRejectedLoadsCanBeRetriedWithoutClearingTheCurrentGallery() {
        val tasks = ArrayDeque<() -> Unit>()
        var accept = false
        var fail = true
        var failures = 0
        var publications = 0
        val loader = PanoramaxGalleryLoader(
            execute = { if (accept) { tasks.add(it); true } else false },
            load = { if (fail) error("Unreadable queue") else emptyList() },
            publish = { _, _ -> publications++ },
            onFailure = { failures++ },
        )
        loader.refresh()
        assertTrue(tasks.isEmpty())
        accept = true
        loader.refresh()
        tasks.removeFirst().invoke()
        assertEquals(1, failures)
        assertEquals(0, publications)
        fail = false
        loader.refresh()
        tasks.removeFirst().invoke()
        assertEquals(1, publications)
    }
}
