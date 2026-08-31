package de.youspeed.android.alpha

import java.io.File
import java.time.Duration
import java.time.Instant
import kotlin.io.path.createTempDirectory
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PanoramaxCaptureTests {
    private val t0 = Instant.parse("2026-08-31T10:00:00Z")

    private fun fix(seconds: Long, latitude: Double = 49.0, longitude: Double = 8.0, accuracy: Double = 5.0) =
        PanoramaxLocationSample(latitude, longitude, t0.plusSeconds(seconds), accuracy)

    @Test
    fun cadenceUsesDistanceAndRejectsStationaryFallback() {
        val config = PanoramaxCadenceConfig(distanceMeters = 25.0, fallbackInterval = Duration.ofSeconds(5))
        assertTrue(PanoramaxCapturePolicy.shouldCapture(null, fix(0), config = config))
        assertFalse(PanoramaxCapturePolicy.shouldCapture(fix(0), fix(5), config = config))
        assertTrue(PanoramaxCapturePolicy.shouldCapture(fix(0), fix(5, longitude = 8.0004), config = config))
    }

    @Test
    fun staleAndInaccurateLocationsPauseCapture() {
        val config = PanoramaxCadenceConfig(maxLocationAge = Duration.ofSeconds(10), maxAccuracyMeters = 30.0)
        assertFalse(PanoramaxCapturePolicy.shouldCapture(fix(0), fix(20, longitude = 8.001), now = t0.plusSeconds(40), config = config))
        assertFalse(PanoramaxCapturePolicy.shouldCapture(fix(0), fix(5, longitude = 8.001, accuracy = 31.0), config = config))
    }

    @Test
    fun metadataRequiresValidGpsTimeAndHash() {
        val metadata = PanoramaxCaptureMetadata(
            captureId = "capture-1",
            captureSessionId = "session-1",
            capturedAt = t0,
            location = PanoramaxLocationSample(91.0, 8.0, t0, 5.0),
            sha256 = "not-a-hash",
            byteSize = 0,
            software = "YouSpeed/test",
        )
        assertTrue(metadata.validate().isNotEmpty())
    }

    @Test
    fun queuePersistsMetadataAndSeparatesOriginalsFromThumbnails() {
        val root = createTempDirectory("panoramax-queue").toFile()
        try {
            val store = PanoramaxQueueStore(File(root, "no-backup"))
            val batch = store.createBatch("session-1", t0)
            val jpeg = File(root, "scene.jpg").apply { writeBytes(byteArrayOf(0xFF.toByte(), 0xD8.toByte(), 1, 2, 0xFF.toByte(), 0xD9.toByte())) }
            val thumbnail = File(root, "thumb.jpg").apply { writeBytes(byteArrayOf(0xFF.toByte(), 0xD8.toByte(), 5, 0xFF.toByte(), 0xD9.toByte())) }
            val itemId = "capture-1"
            val metadata = PanoramaxCaptureMetadata(
                captureId = itemId,
                captureSessionId = "session-1",
                capturedAt = t0,
                location = PanoramaxLocationSample(49.0, 8.0, t0, 5.0),
                sha256 = PanoramaxQueueStore.sha256(jpeg),
                byteSize = jpeg.length(),
                software = "YouSpeed/test",
            )
            store.addJpeg(batch.batchId, jpeg, thumbnail, metadata)
            val restored = requireNotNull(store.getBatch(batch.batchId))
            assertEquals(1, restored.items.size)
            val queueRoot = File(root, "no-backup/panoramax")
            assertTrue(File(queueRoot, restored.items.single().originalPath).exists())
            assertTrue(File(queueRoot, restored.items.single().thumbnailPath).exists())
        } finally {
            root.deleteRecursively()
        }
    }

}
