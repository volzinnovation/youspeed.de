package de.youspeed.android.alpha

import java.time.Duration
import java.time.Instant

internal data class DrivingInteractionMotion(val controlsAllowed: Boolean, val stationaryObservedAt: Instant?)

/** A missing speed is not a stationary measurement and cannot unlock moving controls. */
internal object DrivingInteractionMotionPolicy {
    fun observe(
        previouslyAllowed: Boolean,
        rawSpeedMetersPerSecond: Double?,
        filteredSpeedKmh: Double,
        horizontalAccuracyMeters: Double?,
        observedAt: Instant,
        now: Instant,
    ): DrivingInteractionMotion {
        val validRaw = rawSpeedMetersPerSecond != null && rawSpeedMetersPerSecond.isFinite() &&
            rawSpeedMetersPerSecond >= 0.0 && horizontalAccuracyMeters != null &&
            horizontalAccuracyMeters.isFinite() && horizontalAccuracyMeters >= 0.0
        if ((filteredSpeedKmh.isFinite() && filteredSpeedKmh > 0.0) ||
            (rawSpeedMetersPerSecond?.let { it.isFinite() && it > 0.0 } == true)) {
            return DrivingInteractionMotion(false, null)
        }
        val ageMs = Duration.between(observedAt, now).toMillis()
        if (validRaw && rawSpeedMetersPerSecond == 0.0 && filteredSpeedKmh == 0.0 && ageMs in 0..3_000) {
            return DrivingInteractionMotion(true, observedAt)
        }
        return DrivingInteractionMotion(previouslyAllowed, null)
    }
}
