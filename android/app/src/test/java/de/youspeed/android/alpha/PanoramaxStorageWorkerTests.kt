package de.youspeed.android.alpha

import java.io.File
import java.time.Instant
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.RejectedExecutionException
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import kotlin.io.path.createTempDirectory
import org.junit.Assert.*
import org.junit.Test

class PanoramaxStorageWorkerTests {
    @Test fun capturePersistsAndFinalizesWhileDownloadIsBlockedAndShutdownDrainsWrites() {
        val root = createTempDirectory("panoramax-storage-worker").toFile()
        val store = PanoramaxQueueStore(File(root, "private"))
        val downloads = Executors.newSingleThreadExecutor()
        val storage = PanoramaxStorageWorker()
        val downloadStarted = CountDownLatch(1)
        val releaseDownload = CountDownLatch(1)
        val captureStarted = CountDownLatch(1)
        val releaseCapture = CountDownLatch(1)
        val finalized = CountDownLatch(1)
        val failure = AtomicReference<Throwable?>()
        val batchId = AtomicReference<String>()
        try {
            downloads.execute {
                downloadStarted.countDown()
                releaseDownload.await(10, TimeUnit.SECONDS)
            }
            assertTrue(downloadStarted.await(5, TimeUnit.SECONDS))
            storage.execute {
                try {
                    val instant = Instant.parse("2026-09-01T12:00:00Z")
                    val batch = store.createBatch("capture-session", instant)
                    batchId.set(batch.batchId)
                    captureStarted.countDown()
                    check(releaseCapture.await(5, TimeUnit.SECONDS))
                    val jpeg = File(root, "capture.jpg").apply { writeBytes(byteArrayOf(-1, -40, 1, 2, -1, -39)) }
                    val thumbnail = File(root, "thumbnail.jpg").apply { writeBytes(byteArrayOf(-1, -40, 5, -1, -39)) }
                    val sample = PanoramaxLocationSample(49.0, 8.0, instant, 5.0)
                    store.addJpeg(batch.batchId, jpeg, thumbnail, PanoramaxCaptureMetadata(
                        "capture", "capture-session", instant, sample,
                        PanoramaxQueueStore.sha256(jpeg), jpeg.length(), "test",
                    ))
                } catch (error: Throwable) { failure.compareAndSet(null, error) }
            }
            storage.execute {
                try {
                    val batch = requireNotNull(store.getBatch(batchId.get()))
                    check(batch.items.size == 1) { "Finalizer ran before the accepted JPEG write" }
                    store.transitionBatch(batch.batchId, PanoramaxBatchState.AWAITING_REVIEW)
                } catch (error: Throwable) { failure.compareAndSet(null, error) }
                finally { finalized.countDown() }
            }
            assertTrue("Photo storage must not wait for the download", captureStarted.await(5, TimeUnit.SECONDS))
            storage.close() // Must return while the accepted JPEG is still in flight.
            assertThrows(RejectedExecutionException::class.java) { storage.execute {} }
            assertEquals(1L, finalized.count)
            releaseCapture.countDown()
            assertTrue(finalized.await(5, TimeUnit.SECONDS))
            failure.get()?.let { throw AssertionError("Photo storage failed", it) }
            assertEquals("Download is still blocked", 1L, releaseDownload.count)
            val reopened = PanoramaxQueueStore(File(root, "private"))
            val durable = requireNotNull(reopened.getBatch(batchId.get()))
            assertEquals(PanoramaxBatchState.AWAITING_REVIEW, durable.state)
            assertTrue(reopened.originalFile(durable.items.single()).isFile)
            assertEquals(durable.items.single().metadata.sha256, PanoramaxQueueStore.sha256(reopened.originalFile(durable.items.single())))
        } finally {
            releaseCapture.countDown()
            releaseDownload.countDown()
            storage.close()
            downloads.shutdownNow()
            finalized.await(5, TimeUnit.SECONDS)
            downloads.awaitTermination(5, TimeUnit.SECONDS)
            root.deleteRecursively()
        }
    }
}
