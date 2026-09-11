package de.youspeed.android.alpha

import androidx.exifinterface.media.ExifInterface
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import java.io.File
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

/** Embeds the same durable location and sign evidence as the iPhone original. */
object PanoramaxJpegMetadata {
    fun decodeUpright(file: File, maximumDimension: Int = 1600): Bitmap? {
        require(maximumDimension > 0)
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(file.absolutePath, bounds)
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null
        var sample = 1
        while (maxOf(bounds.outWidth, bounds.outHeight) / (sample * 2) >= maximumDimension) sample *= 2
        val decoded = BitmapFactory.decodeFile(file.absolutePath, BitmapFactory.Options().apply { inSampleSize = sample }) ?: return null
        val matrix = Matrix()
        when (ExifInterface(file.absolutePath).getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL)) {
            ExifInterface.ORIENTATION_FLIP_HORIZONTAL -> matrix.setScale(-1f, 1f)
            ExifInterface.ORIENTATION_ROTATE_180 -> matrix.setRotate(180f)
            ExifInterface.ORIENTATION_FLIP_VERTICAL -> matrix.setScale(1f, -1f)
            ExifInterface.ORIENTATION_TRANSPOSE -> { matrix.setRotate(90f); matrix.postScale(-1f, 1f) }
            ExifInterface.ORIENTATION_ROTATE_90 -> matrix.setRotate(90f)
            ExifInterface.ORIENTATION_TRANSVERSE -> { matrix.setRotate(-90f); matrix.postScale(-1f, 1f) }
            ExifInterface.ORIENTATION_ROTATE_270 -> matrix.setRotate(-90f)
        }
        val upright = if (matrix.isIdentity) decoded else Bitmap.createBitmap(decoded, 0, 0, decoded.width, decoded.height, matrix, true)
        if (upright !== decoded) decoded.recycle()
        val scale = minOf(1.0, maximumDimension.toDouble() / maxOf(upright.width, upright.height))
        if (scale >= 1.0) return upright
        return Bitmap.createScaledBitmap(upright, (upright.width * scale).toInt().coerceAtLeast(1),
            (upright.height * scale).toInt().coerceAtLeast(1), true).also { if (it !== upright) upright.recycle() }
    }

    fun createThumbnail(original: File, thumbnail: File, maximumDimension: Int = 640) {
        val bitmap = requireNotNull(decodeUpright(original, maximumDimension)) { "Could not decode Panoramax original" }
        try {
            thumbnail.parentFile?.mkdirs()
            thumbnail.outputStream().use { check(bitmap.compress(Bitmap.CompressFormat.JPEG, 72, it)) { "Could not write Panoramax thumbnail" } }
        } finally { bitmap.recycle() }
    }

    /** Pixel coordinates in the upright image, matching iPhone's EXIF orientation handling. */
    fun pixelDimensions(file: File): Pair<Int, Int>? {
        val exif = ExifInterface(file.absolutePath)
        val width = exif.getAttributeInt(ExifInterface.TAG_IMAGE_WIDTH, 0)
        val height = exif.getAttributeInt(ExifInterface.TAG_IMAGE_LENGTH, 0)
        if (width <= 0 || height <= 0) return null
        return if (exif.getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL) in 5..8)
            height to width else width to height
    }

    fun write(
        file: File,
        sample: PanoramaxLocationSample,
        annotations: List<PanoramaxTrafficSignAnnotation> = emptyList(),
    ) {
        require(sample.latitude.isFinite() && sample.latitude in -90.0..90.0)
        require(sample.longitude.isFinite() && sample.longitude in -180.0..180.0)
        val exif = ExifInterface(file.absolutePath)
        exif.setLatLong(sample.latitude, sample.longitude)
        sample.altitudeMeters?.takeIf(Double::isFinite)?.let(exif::setAltitude)
        val utc = sample.capturedAt.atOffset(ZoneOffset.UTC)
        exif.setAttribute(ExifInterface.TAG_GPS_DATESTAMP, utc.format(DateTimeFormatter.ofPattern("yyyy:MM:dd")))
        exif.setAttribute(ExifInterface.TAG_GPS_TIMESTAMP, utc.format(DateTimeFormatter.ofPattern("HH:mm:ss")))
        exif.setAttribute(ExifInterface.TAG_DATETIME_ORIGINAL, utc.format(DateTimeFormatter.ofPattern("yyyy:MM:dd HH:mm:ss")))
        exif.setAttribute(ExifInterface.TAG_OFFSET_TIME_ORIGINAL, "+00:00")
        sample.headingDegrees?.takeIf { it.isFinite() && it in 0.0..360.0 }?.let { heading ->
            exif.setAttribute(ExifInterface.TAG_GPS_IMG_DIRECTION, "${(heading * 1000).toLong()}/1000")
            exif.setAttribute(ExifInterface.TAG_GPS_IMG_DIRECTION_REF, "T")
        }
        if (annotations.isNotEmpty()) {
            exif.setAttribute(ExifInterface.TAG_USER_COMMENT, requireNotNull(PanoramaxExifUserCommentCodec.encode(annotations)))
        }
        exif.saveAttributes()
        val verified = ExifInterface(file.absolutePath)
        val coordinates = requireNotNull(verified.latLong) { "Could not verify JPEG GPS metadata" }
        check(kotlin.math.abs(coordinates[0] - sample.latitude) < 0.000001 &&
            kotlin.math.abs(coordinates[1] - sample.longitude) < 0.000001) { "JPEG GPS metadata differs from capture" }
        if (annotations.isNotEmpty()) {
            check(PanoramaxExifUserCommentCodec.decode(verified.getAttribute(ExifInterface.TAG_USER_COMMENT)) == annotations) {
                "Could not verify JPEG traffic-sign annotations"
            }
        }
    }
}
