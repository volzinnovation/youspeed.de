package de.youspeed.android.alpha

import java.time.Duration
import java.time.Instant

/** The driving shutter is the sole dashboard action that does not stop the movie. */
internal object DrivingPhotoCapturePolicy {
    const val SPEED_THRESHOLD_KMH = 1.0
    const val MINIMUM_FREE_BYTES = 20_000_000L
    const val TAP_INTERVAL_MILLIS = 500L

    fun isVisible(speedKmh: Double): Boolean = speedKmh.isFinite() && speedKmh > SPEED_THRESHOLD_KMH

    fun isLocationUsable(sample: PanoramaxLocationSample?, now: Instant): Boolean = sample != null &&
        sample.latitude.isFinite() && sample.latitude in -90.0..90.0 &&
        sample.longitude.isFinite() && sample.longitude in -180.0..180.0 &&
        sample.accuracyMeters.isFinite() && sample.accuracyMeters in 0.0..50.0 &&
        !sample.capturedAt.isAfter(now.plusSeconds(60)) &&
        Duration.between(sample.capturedAt, now) <= Duration.ofSeconds(10)

    fun isReady(speedKmh: Double, sessionActive: Boolean, cameraReady: Boolean, photoOutputReady: Boolean,
        batchReady: Boolean, storageReady: Boolean, captureInFlight: Boolean,
        sample: PanoramaxLocationSample?, now: Instant, lastManualRequestAt: Instant?): Boolean =
        isVisible(speedKmh) && sessionActive && cameraReady && photoOutputReady && batchReady &&
            storageReady && !captureInFlight && isLocationUsable(sample, now) &&
            (lastManualRequestAt == null || Duration.between(lastManualRequestAt, now).toMillis() >= TAP_INTERVAL_MILLIS)
}
