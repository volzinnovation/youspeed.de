package de.youspeed.android.alpha

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.content.ContextWrapper
import androidx.exifinterface.media.ExifInterface
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.time.Instant
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PanoramaxMetadataInstrumentedTest {
    private val capturedAt = Instant.parse("2026-09-11T12:34:56Z")
    private val sample = PanoramaxLocationSample(-33.123456, -70.654321, capturedAt, 3.0, -12.5, 359.5)

    @Test fun credentialsRoundTripThroughKeystoreCiphertextWithoutPlaintextAtRest() = withDirectory { directory ->
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val isolatedContext = object : ContextWrapper(context) {
            override fun getNoBackupFilesDir(): File = directory
        }
        val storage = PanoramaxCredentialStore(isolatedContext)
        val credentials = PanoramaxCredentials("instrumented-secret-value", "instrumented-device-id")
        storage.save(credentials)
        assertEquals(credentials, storage.read())
        val saved = File(directory, "panoramax-credentials.json").readText()
        assertFalse(saved.contains(credentials.token))
        assertFalse(saved.contains(credentials.tokenId))
        storage.delete()
        assertNull(storage.read())
    }

    @Test fun jpegEmbedsGpsHeadingCaptureTimeAndTrafficSignAnnotation() = withDirectory { directory ->
        val jpeg = createJpeg(File(directory, "photo.jpg"))
        val annotation = annotation()
        PanoramaxJpegMetadata.write(jpeg, sample, listOf(annotation))
        val exif = ExifInterface(jpeg.absolutePath)
        assertArrayEquals(doubleArrayOf(sample.latitude, sample.longitude), requireNotNull(exif.latLong), 0.000001)
        assertEquals(-12.5, exif.getAltitude(0.0), 0.01)
        assertEquals(359.5, exif.getAttributeDouble(ExifInterface.TAG_GPS_IMG_DIRECTION, -1.0), 0.001)
        assertEquals("T", exif.getAttribute(ExifInterface.TAG_GPS_IMG_DIRECTION_REF))
        assertEquals("2026:09:11", exif.getAttribute(ExifInterface.TAG_GPS_DATESTAMP))
        assertEquals("12:34:56", exif.getAttribute(ExifInterface.TAG_GPS_TIMESTAMP))
        assertEquals("2026:09:11 12:34:56", exif.getAttribute(ExifInterface.TAG_DATETIME_ORIGINAL))
        assertEquals("+00:00", exif.getAttribute(ExifInterface.TAG_OFFSET_TIME_ORIGINAL))
        assertEquals(listOf(annotation), PanoramaxExifUserCommentCodec.decode(exif.getAttribute(ExifInterface.TAG_USER_COMMENT)))
    }

    @Test fun preparingLegacyOriginalRepairsExifAndUpdatesDurableHash() = withDirectory { directory ->
        val jpeg = createJpeg(File(directory, "legacy.jpg"))
        val thumb = createJpeg(File(directory, "thumb.jpg"))
        val store = PanoramaxQueueStore(File(directory, "queue"))
        val batch = store.createBatch("legacy-session", capturedAt)
        val originalHash = PanoramaxQueueStore.sha256(jpeg)
        val item = store.addJpeg(batch.batchId, jpeg, thumb, PanoramaxCaptureMetadata(
            "legacy-image", batch.captureSessionId, capturedAt, sample, originalHash, jpeg.length(), "test",
            imageWidthPixels = 64, imageHeightPixels = 48, trafficSignAnnotations = listOf(annotation()),
        ))
        store.transitionBatch(batch.batchId, PanoramaxBatchState.AWAITING_REVIEW)
        val prepared = store.prepareOriginalForUpload(batch.batchId, item.itemId)
        val current = requireNotNull(store.getBatch(batch.batchId)).items.single()
        assertNotEquals(originalHash, current.metadata.sha256)
        assertEquals(PanoramaxQueueStore.sha256(prepared), current.metadata.sha256)
        assertEquals(prepared.length(), current.metadata.byteSize)
        val exif = ExifInterface(prepared.absolutePath)
        assertArrayEquals(doubleArrayOf(sample.latitude, sample.longitude), requireNotNull(exif.latLong), 0.000001)
        assertEquals(listOf(annotation()), PanoramaxExifUserCommentCodec.decode(exif.getAttribute(ExifInterface.TAG_USER_COMMENT)))
        assertTrue(prepared.parentFile?.listFiles().orEmpty().none { it.name.endsWith(".tmp") })
    }

    @Test fun lateRecognitionAnnotatesExistingStillAndDeduplicatesPhysicalTrack() = withDirectory { directory ->
        val jpeg = createJpeg(File(directory, "late.jpg"))
        val thumb = createJpeg(File(directory, "late-thumb.jpg"))
        val store = PanoramaxQueueStore(File(directory, "late-queue"))
        val batch = store.createBatch("late-session", capturedAt)
        val item = store.addJpeg(batch.batchId, jpeg, thumb, PanoramaxCaptureMetadata(
            "late-image", batch.captureSessionId, capturedAt, sample, PanoramaxQueueStore.sha256(jpeg), jpeg.length(), "test",
        ))
        val draft = PanoramaxTrafficSignAnnotationDraft(
            "late-annotation", "late-event", capturedAt.plusSeconds(2), NormalizedTrafficSignBoundingBox(0.1, 0.1, 0.3, 0.5),
            listOf(PanoramaxSemanticTag("osm|traffic_sign", "DE:274-50")), 50, "track-1", 0.9, 0.95,
            TrafficSignDetectionContext("way-1", sample.latitude, sample.longitude, 359.5, TrafficSignTravelDirection.UNKNOWN,
                TrafficSignRuntimeSourceSignature("test", null)),
        )
        assertEquals(item.itemId, store.attachTrafficSignAnnotation(batch.batchId, draft))
        assertEquals(item.itemId, store.attachTrafficSignAnnotation(batch.batchId, draft.copy(sourceEventId = "weaker", classificationConfidence = 0.9)))
        val current = requireNotNull(store.getBatch(batch.batchId)).items.single()
        assertEquals(1, current.metadata.trafficSignAnnotations?.size)
        assertEquals("late-event", current.metadata.trafficSignAnnotations?.single()?.sourceEventId)
        assertEquals(PanoramaxQueueStore.sha256(store.originalFile(current)), current.metadata.sha256)
        assertEquals(current.metadata.trafficSignAnnotations, PanoramaxExifUserCommentCodec.decode(
            ExifInterface(store.originalFile(current).absolutePath).getAttribute(ExifInterface.TAG_USER_COMMENT)))
        assertNull(store.attachTrafficSignAnnotation(batch.batchId, draft.copy(frameTimestampUtc = capturedAt.plusSeconds(6))))
        store.transitionBatch(batch.batchId, PanoramaxBatchState.AWAITING_REVIEW)
        assertNull(store.attachTrafficSignAnnotation(batch.batchId, draft.copy(sourceEventId = "stopped")))
    }

    @Test fun jpegDimensionsRespectCaptureOrientation() = withDirectory { directory ->
        // Distinct quadrants prove that pixels, not just reported dimensions, are upright.
        val expectedQuadrants = mapOf(
            1 to listOf("red", "green", "blue", "yellow"),
            2 to listOf("green", "red", "yellow", "blue"),
            3 to listOf("yellow", "blue", "green", "red"),
            4 to listOf("blue", "yellow", "red", "green"),
            5 to listOf("red", "blue", "green", "yellow"),
            6 to listOf("blue", "red", "yellow", "green"),
            7 to listOf("yellow", "green", "blue", "red"),
            8 to listOf("green", "yellow", "red", "blue"),
        )
        for ((orientation, expected) in expectedQuadrants) {
            val jpeg = createJpeg(File(directory, "oriented-$orientation.jpg"), coloredQuadrants = true)
            ExifInterface(jpeg.absolutePath).apply {
                setAttribute(ExifInterface.TAG_ORIENTATION, orientation.toString())
                saveAttributes()
            }
            val dimensions = if (orientation in 5..8) 48 to 64 else 64 to 48
            assertEquals(dimensions, PanoramaxJpegMetadata.pixelDimensions(jpeg))
            val thumbnail = File(directory, "upright-$orientation.thumb.jpg")
            PanoramaxJpegMetadata.createThumbnail(jpeg, thumbnail)
            assertEquals(dimensions, PanoramaxJpegMetadata.pixelDimensions(thumbnail))
            val thumbnailOrientation = ExifInterface(thumbnail.absolutePath)
                .getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_UNDEFINED)
            // Bitmap JPEG output may omit EXIF; unspecified and normal both mean no transform.
            assertTrue(thumbnailOrientation in setOf(ExifInterface.ORIENTATION_UNDEFINED, ExifInterface.ORIENTATION_NORMAL))
            val decoded = requireNotNull(BitmapFactory.decodeFile(thumbnail.absolutePath))
            try {
                val actual = listOf(
                    decoded.width / 4 to decoded.height / 4,
                    decoded.width * 3 / 4 to decoded.height / 4,
                    decoded.width / 4 to decoded.height * 3 / 4,
                    decoded.width * 3 / 4 to decoded.height * 3 / 4,
                ).map { (x, y) -> quadrantColor(decoded.getPixel(x, y)) }
                assertEquals("Wrong pixel orientation for EXIF $orientation", expected, actual)
            } finally { decoded.recycle() }
        }
    }

    @Test fun missingThumbnailIsRebuiltFromTheRetainedOriginal() = withDirectory { directory ->
        val original = createJpeg(File(directory, "retained.jpg"))
        val thumbnail = createJpeg(File(directory, "missing-thumb.jpg"))
        val store = PanoramaxQueueStore(File(directory, "thumbnail-queue"))
        val batch = store.createBatch("thumbnail-session", capturedAt)
        val item = store.addJpeg(batch.batchId, original, thumbnail, PanoramaxCaptureMetadata(
            "thumbnail-image", batch.captureSessionId, capturedAt, sample, PanoramaxQueueStore.sha256(original), original.length(), "test",
        ))
        assertTrue(store.thumbnailFile(item).delete())
        assertEquals(1, store.repairMissingThumbnails())
        assertEquals(64 to 48, PanoramaxJpegMetadata.pixelDimensions(store.thumbnailFile(item)))
        assertEquals(0, store.repairMissingThumbnails())
        assertTrue(store.originalFile(item).exists())
    }

    private fun annotation() = PanoramaxTrafficSignAnnotation(
        "annotation-1", "event-1", capturedAt, listOf(2, 3, 30, 40),
        listOf(PanoramaxSemanticTag("osm|traffic_sign", "DE:274-50")), 50, "track-1",
        0.95, 0.97, "way-1", sample.latitude, sample.longitude, 359.5, TrafficSignTravelDirection.UNKNOWN,
    )

    private fun quadrantColor(pixel: Int): String = when {
        Color.red(pixel) > 180 && Color.green(pixel) > 180 && Color.blue(pixel) < 80 -> "yellow"
        Color.red(pixel) > 180 && Color.green(pixel) < 80 && Color.blue(pixel) < 80 -> "red"
        Color.green(pixel) > 180 && Color.red(pixel) < 80 && Color.blue(pixel) < 80 -> "green"
        Color.blue(pixel) > 180 && Color.red(pixel) < 80 && Color.green(pixel) < 80 -> "blue"
        else -> "unexpected($pixel)"
    }

    private fun createJpeg(file: File, coloredQuadrants: Boolean = false): File {
        val bitmap = Bitmap.createBitmap(64, 48, Bitmap.Config.ARGB_8888)
        if (coloredQuadrants) {
            bitmap.setPixels(IntArray(64 * 48) { index ->
                val x = index % 64
                val y = index / 64
                when { x < 32 && y < 24 -> Color.RED; y < 24 -> Color.GREEN; x < 32 -> Color.BLUE; else -> Color.YELLOW }
            }, 0, 64, 0, 0, 64, 48)
        } else bitmap.eraseColor(Color.GREEN)
        try { file.outputStream().use { assertTrue(bitmap.compress(Bitmap.CompressFormat.JPEG, 90, it)) } }
        finally { bitmap.recycle() }
        return file
    }

    private fun withDirectory(block: (File) -> Unit) {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val directory = File(context.cacheDir, "panoramax-test-${System.nanoTime()}").apply { mkdirs() }
        try { block(directory) } finally { directory.deleteRecursively() }
    }
}
