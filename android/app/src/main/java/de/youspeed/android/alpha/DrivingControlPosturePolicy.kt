package de.youspeed.android.alpha

import kotlin.math.acos
import kotlin.math.sqrt
import java.time.Duration
import java.time.Instant

/** Below 4 km/h or without GPS, controls remain available in every mounting position. */
internal object DrivingControlPosturePolicy {
    /** Core Motion convention: a downward gravity vector in units of g; face-up is zero degrees. */
    fun screenAngleDegrees(x: Double, y: Double, z: Double): Double? {
        if (!x.isFinite() || !y.isFinite() || !z.isFinite()) return null
        val length = sqrt(x * x + y * y + z * z)
        if (length !in 0.5..1.5) return null
        return Math.toDegrees(acos((-z / length).coerceIn(-1.0, 1.0)))
    }

    fun isFlat(screenAngleDegrees: Double?): Boolean =
        screenAngleDegrees != null && screenAngleDegrees.isFinite() &&
            screenAngleDegrees >= 0.0 && screenAngleDegrees <= 10.0 + 1e-9

    /** At 4 km/h or above with GPS, unknown posture cannot establish a flat phone. */
    fun controlsAllowed(speedControlsAllowed: Boolean, screenAngleDegrees: Double?,
        speedKmh: Double = 20.0, hasSignal: Boolean = true): Boolean =
        !hasSignal || (speedKmh.isFinite() && speedKmh >= 0.0 && speedKmh < 4.0) ||
            (speedControlsAllowed && isFlat(screenAngleDegrees))

    fun hasSignal(observedAt: Instant?, accuracy: Double?, now: Instant): Boolean =
        observedAt != null && accuracy != null && accuracy.isFinite() && accuracy >= 0.0 && accuracy < 60.0 &&
            Duration.between(observedAt, now).let { !it.isNegative && it <= Duration.ofSeconds(3) }
}
