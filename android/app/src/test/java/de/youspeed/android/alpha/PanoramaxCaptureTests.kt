package de.youspeed.android.alpha

import java.io.File
import java.time.Duration
import java.time.Instant
import kotlin.io.path.createTempDirectory
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
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
    fun cadenceRequiresTwiceTheGpsPrecision() {
        val config = PanoramaxCadenceConfig(distanceMeters = 5.0)
        assertFalse(PanoramaxCapturePolicy.shouldCapture(fix(0, accuracy = 12.0), fix(5, longitude = 8.00025, accuracy = 12.0), config = config))
        assertTrue(PanoramaxCapturePolicy.shouldCapture(fix(0, accuracy = 12.0), fix(5, longitude = 8.0005, accuracy = 12.0), config = config))
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
    fun confirmedZoneStartProjectsToGermanExifAnnotation() {
        val event = recognitionEvent(TrafficSignSemanticKind.ZONE_START)

        val draft = PanoramaxTrafficSignAnnotationDraft.from(event)
        val annotation = draft?.projected(1_920, 1_080, t0)

        assertNotNull(annotation)
        assertEquals(listOf(192, 216, 768, 649), annotation?.shape)
        assertEquals("DE:274.1", annotation?.semantics?.first { it.key == "osm|traffic_sign" }?.value)
        assertEquals("track-one", annotation?.physicalSignTrackId)
        assertEquals(TrafficSignTravelDirection.UNKNOWN, annotation?.travelDirection)
    }

    @Test
    fun exifUserCommentRoundTripsWithoutInventingANullTrackId() {
        val annotation = requireNotNull(
            PanoramaxTrafficSignAnnotationDraft.from(
                recognitionEvent(TrafficSignSemanticKind.MAXIMUM_SPEED, trackId = null),
            )?.projected(1_920, 1_080, t0),
        )

        val encoded = requireNotNull(PanoramaxExifUserCommentCodec.encode(listOf(annotation)))
        val decoded = PanoramaxExifUserCommentCodec.decode(encoded)

        assertTrue(encoded.startsWith("YouSpeed.PanoramaxAnnotations/1 "))
        assertEquals(listOf(annotation), decoded)
        assertNull(decoded?.single()?.physicalSignTrackId)
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
                imageWidthPixels = 1_920,
                imageHeightPixels = 1_080,
                trafficSignAnnotations = listOf(annotation()),
            )
            store.addJpeg(batch.batchId, jpeg, thumbnail, metadata)
            val restored = requireNotNull(store.getBatch(batch.batchId))
            assertEquals(1, restored.items.size)
            val queueRoot = File(root, "no-backup/panoramax")
            assertTrue(File(queueRoot, restored.items.single().originalPath).exists())
            assertTrue(File(queueRoot, restored.items.single().thumbnailPath).exists())
            assertEquals(1_920, restored.items.single().metadata.imageWidthPixels)
            assertEquals(listOf(annotation()), restored.items.single().metadata.trafficSignAnnotations)
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun queueRejectsLatePhotoAfterDriveIsClosed() {
        val root = createTempDirectory("panoramax-closed-batch").toFile()
        try {
            val store = PanoramaxQueueStore(File(root, "no-backup"))
            val batch = store.createBatch("session-closed", t0)
            store.updateBatch(batch.copy(state = PanoramaxBatchState.AWAITING_REVIEW))
            val jpeg = File(root, "late-scene.jpg").apply {
                writeBytes(byteArrayOf(0xFF.toByte(), 0xD8.toByte(), 1, 0xFF.toByte(), 0xD9.toByte()))
            }
            val thumbnail = File(root, "late-thumb.jpg").apply {
                writeBytes(byteArrayOf(0xFF.toByte(), 0xD8.toByte(), 2, 0xFF.toByte(), 0xD9.toByte()))
            }
            val metadata = PanoramaxCaptureMetadata(
                captureId = "late-photo",
                captureSessionId = batch.captureSessionId,
                capturedAt = t0,
                location = PanoramaxLocationSample(49.0, 8.0, t0, 5.0),
                sha256 = PanoramaxQueueStore.sha256(jpeg),
                byteSize = jpeg.length(),
                software = "YouSpeed/test",
            )

            assertThrows(IllegalArgumentException::class.java) {
                store.addJpeg(batch.batchId, jpeg, thumbnail, metadata)
            }
        } finally {
            root.deleteRecursively()
        }
    }

    @Test
    fun sealingBatchPreservesItemsAddedAfterCreationSnapshot() {
        val root = createTempDirectory("panoramax-seal").toFile()
        try {
            val store = PanoramaxQueueStore(File(root, "no-backup"))
            val creationSnapshot = store.createBatch("session-seal", t0)
            val jpeg = File(root, "scene-seal.jpg").apply {
                writeBytes(byteArrayOf(0xFF.toByte(), 0xD8.toByte(), 3, 0xFF.toByte(), 0xD9.toByte()))
            }
            val thumbnail = File(root, "thumb-seal.jpg").apply {
                writeBytes(byteArrayOf(0xFF.toByte(), 0xD8.toByte(), 4, 0xFF.toByte(), 0xD9.toByte()))
            }
            val metadata = PanoramaxCaptureMetadata(
                captureId = "captured-before-seal",
                captureSessionId = creationSnapshot.captureSessionId,
                capturedAt = t0,
                location = PanoramaxLocationSample(49.0, 8.0, t0, 5.0),
                sha256 = PanoramaxQueueStore.sha256(jpeg),
                byteSize = jpeg.length(),
                software = "YouSpeed/test",
            )
            store.addJpeg(creationSnapshot.batchId, jpeg, thumbnail, metadata)

            val sealed = store.transitionBatch(creationSnapshot.batchId, PanoramaxBatchState.AWAITING_REVIEW)

            assertEquals(PanoramaxBatchState.AWAITING_REVIEW, sealed.state)
            assertEquals(listOf(metadata.captureId), sealed.items.map { it.itemId })
        } finally {
            root.deleteRecursively()
        }
    }

    private fun recognitionEvent(
        semanticKind: TrafficSignSemanticKind,
        trackId: String? = "track-one",
    ) = TrafficSignRecognitionEvent(
        schemaVersion = 1,
        packId = "de-field-pack",
        artifactSha256 = "a".repeat(64),
        preprocessingVersion = "test-v1",
        source = TrafficSignInputSource.LIVE_FRAME,
        frameTimestampUtc = t0,
        state = TrafficSignRecognitionState.CONFIRMED,
        candidate = TrafficSignCandidate(
            rawClassId = "zone_start_30",
            rawLabel = "Zone 30",
            semantic = TrafficSignSemantic(semanticKind, 30, "km/h"),
            rawScore = 0.91,
            calibratedConfidence = null,
            boundingBox = NormalizedTrafficSignBoundingBox(0.1, 0.2, 0.3, 0.4),
            proposalRawScore = 0.88,
            classifierRawScore = 0.91,
            trackId = trackId,
        ),
        roadContext = TrafficSignDetectionContext(
            wayId = "16620609",
            latitude = 48.77456123700132,
            longitude = 8.276953210799945,
            headingDegrees = 62.0,
            travelDirection = TrafficSignTravelDirection.UNKNOWN,
            sourceSignature = TrafficSignRuntimeSourceSignature("bundle:test", null),
        ),
        latencyMs = 12.0,
        thermalState = null,
    )

    private fun annotation() = requireNotNull(
        PanoramaxTrafficSignAnnotationDraft.from(recognitionEvent(TrafficSignSemanticKind.ZONE_START))
            ?.projected(1_920, 1_080, t0),
    )

}
