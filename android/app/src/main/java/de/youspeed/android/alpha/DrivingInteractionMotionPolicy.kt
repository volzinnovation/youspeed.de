package de.youspeed.android.alpha

import java.time.Duration
import java.time.Instant

internal data class DrivingInteractionMotion(val controlsAllowed: Boolean, val stationaryObservedAt: Instant?)

/** Fresh speeds below 4 km/h unlock controls; only a measured zero establishes standstill. */
internal object DrivingInteractionMotionPolicy {
    const val CONTROLS_SPEED_THRESHOLD_KMH = 4.0
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
        if (filteredSpeedKmh >= CONTROLS_SPEED_THRESHOLD_KMH ||
            (rawSpeedMetersPerSecond?.let { it.isFinite() && it >= CONTROLS_SPEED_THRESHOLD_KMH / 3.6 } == true)) {
            return DrivingInteractionMotion(false, null)
        }
        val ageMs = Duration.between(observedAt, now).toMillis()
        if (validRaw && filteredSpeedKmh.isFinite() && filteredSpeedKmh >= 0.0 && ageMs in 0..3_000) {
            val stopped = rawSpeedMetersPerSecond == 0.0 && filteredSpeedKmh == 0.0
            return DrivingInteractionMotion(true, observedAt.takeIf { stopped })
        }
        return DrivingInteractionMotion(previouslyAllowed, null)
    }
}
