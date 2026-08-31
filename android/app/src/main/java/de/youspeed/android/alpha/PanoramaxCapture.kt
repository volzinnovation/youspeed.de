package de.youspeed.android.alpha

import java.time.Duration
import java.time.Instant
import kotlin.math.max

/** The durable lifecycle of a reviewed Panoramax contribution. */
enum class PanoramaxBatchState {
    CAPTURING,
    AWAITING_REVIEW,
    APPROVED,
    CREATING_UPLOAD_SET,
    UPLOADING,
    PROCESSING,
    COMPLETE,
    PARTIAL,
    BLOCKED,
}

enum class PanoramaxItemState {
    CAPTURED,
    INCLUDED,
    EXCLUDED,
    QUEUED,
    UPLOADING,
    UPLOADED,
    ACCEPTED,
    DUPLICATE,
    REJECTED,
    RETRYABLE_ERROR,
    PERMANENT_ERROR,
}

data class PanoramaxLocationSample(
    val latitude: Double,
    val longitude: Double,
    val capturedAt: Instant,
    val accuracyMeters: Double,
    val altitudeMeters: Double? = null,
    val headingDegrees: Double? = null,
)

data class PanoramaxCaptureMetadata(
    val captureId: String,
    val captureSessionId: String,
    val capturedAt: Instant,
    val location: PanoramaxLocationSample,
    val sha256: String,
    val byteSize: Long,
    val software: String,
) {
    fun validate(now: Instant = capturedAt): List<String> = buildList {
        if (captureId.isBlank()) add("captureId is missing")
        if (captureSessionId.isBlank()) add("captureSessionId is missing")
        if (capturedAt.isAfter(now.plusSeconds(60))) add("capture time is in the future")
        if (!location.latitude.isFinite() || location.latitude !in -90.0..90.0) add("latitude is invalid")
        if (!location.longitude.isFinite() || location.longitude !in -180.0..180.0) add("longitude is invalid")
        if (!location.accuracyMeters.isFinite() || location.accuracyMeters < 0.0) add("location accuracy is invalid")
        if (location.capturedAt.isAfter(now.plusSeconds(60))) add("location time is in the future")
        if (kotlin.math.abs(Duration.between(location.capturedAt, capturedAt).seconds) > 120) add("location is not associated with shutter time")
        if (location.headingDegrees != null && (!location.headingDegrees.isFinite() || location.headingDegrees !in 0.0..360.0)) add("heading is invalid")
        if (byteSize <= 0) add("image is empty")
        if (!sha256.matches(Regex("[0-9a-fA-F]{64}"))) add("sha256 is invalid")
        if (software.isBlank()) add("software provenance is missing")
    }
}

data class PanoramaxCadenceConfig(
    val distanceMeters: Double = 25.0,
    val fallbackInterval: Duration = Duration.ofSeconds(5),
    val maxLocationAge: Duration = Duration.ofSeconds(10),
    val maxAccuracyMeters: Double = 50.0,
) {
    init {
        require(distanceMeters > 0.0)
        require(!fallbackInterval.isNegative && !fallbackInterval.isZero)
        require(!maxLocationAge.isNegative && !maxLocationAge.isZero)
        require(maxAccuracyMeters > 0.0)
    }
}

/** Pure policy: cadence is independent from TSR frames or sign detections. */
object PanoramaxCapturePolicy {
    fun shouldCapture(
        lastCapture: PanoramaxLocationSample?,
        current: PanoramaxLocationSample,
        now: Instant = current.capturedAt,
        config: PanoramaxCadenceConfig = PanoramaxCadenceConfig(),
    ): Boolean {
        if (current.capturedAt.isAfter(now.plusSeconds(60))) return false
        if (Duration.between(current.capturedAt, now) > config.maxLocationAge) return false
        if (!current.accuracyMeters.isFinite() || current.accuracyMeters < 0.0 || current.accuracyMeters > config.maxAccuracyMeters) return false
        val previous = lastCapture ?: return true
        if (!current.capturedAt.isAfter(previous.capturedAt)) return false
        val distance = haversineMeters(previous.latitude, previous.longitude, current.latitude, current.longitude)
        // A time fallback is only useful while moving; it must not produce stationary duplicates.
        return distance >= config.distanceMeters ||
            (Duration.between(previous.capturedAt, current.capturedAt) >= config.fallbackInterval && distance >= max(3.0, config.distanceMeters / 5.0))
    }

    private fun haversineMeters(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
        val earthRadius = 6_371_000.0
        val dLat = Math.toRadians(lat2 - lat1)
        val dLon = Math.toRadians(lon2 - lon1)
        val a = kotlin.math.sin(dLat / 2) * kotlin.math.sin(dLat / 2) +
            kotlin.math.cos(Math.toRadians(lat1)) * kotlin.math.cos(Math.toRadians(lat2)) *
            kotlin.math.sin(dLon / 2) * kotlin.math.sin(dLon / 2)
        return earthRadius * 2 * kotlin.math.atan2(kotlin.math.sqrt(a), kotlin.math.sqrt(1 - a))
    }
}
