package de.youspeed.android.alpha

import java.time.Duration
import java.time.Instant
import kotlin.math.abs
import kotlin.math.atan2
import kotlin.math.hypot
import kotlin.math.sqrt

/** Gravity establishes roll and tilt, never the vehicle's heading. */
data class GravityAlignmentReading(val rollDegrees: Double, val tiltDegrees: Double) {
    val isLevel: Boolean get() = abs(rollDegrees) <= 3 && abs(tiltDegrees) <= 3
}

object GravityAlignmentGeometry {
    /** Android's stationary sensor vector has the opposite sign to Core Motion gravity. */
    fun fromAndroidGravity(x: Double, y: Double, z: Double, orientation: ManualOrientation): GravityAlignmentReading? =
        fromDownwardGravity(-x / 9.80665, -y / 9.80665, -z / 9.80665, orientation)

    fun fromDownwardGravity(x: Double, y: Double, z: Double, orientation: ManualOrientation): GravityAlignmentReading? {
        if (!x.isFinite() || !y.isFinite() || !z.isFinite()) return null
        val length = sqrt(x * x + y * y + z * z)
        if (length !in 0.5..1.5) return null
        val (screenX, screenY) = when (orientation) {
            ManualOrientation.PORTRAIT -> x to y
            ManualOrientation.LANDSCAPE_CAMERA_LOWER_RIGHT -> y to -x
            ManualOrientation.LANDSCAPE_CAMERA_UPPER_LEFT -> -y to x
        }
        val inPlane = hypot(screenX, screenY)
        // A flat phone has no stable horizon and must never look successfully aligned.
        if (inPlane / length < 0.1) return null
        return GravityAlignmentReading(
            Math.toDegrees(atan2(screenX, -screenY)),
            Math.toDegrees(atan2(z, inPlane)),
        )
    }
}

object GravityAlignmentVisibility {
    fun isFreshStationary(speedKmh: Double?, stationaryObservedAt: Instant?, now: Instant, inTunnel: Boolean): Boolean {
        if (inTunnel || speedKmh == null || !speedKmh.isFinite() || speedKmh != 0.0 || stationaryObservedAt == null) return false
        val age = Duration.between(stationaryObservedAt, now)
        return !age.isNegative && age <= Duration.ofSeconds(3)
    }

    /** Read-only mounting feedback works before GPS; use the dashboard's rounded zero speed. */
    fun isVisible(landscape: Boolean, speedKmh: Double?, inTunnel: Boolean, searchingForSignal: Boolean = false): Boolean =
        landscape && (searchingForSignal ||
            (!inTunnel && speedKmh != null && speedKmh.isFinite() && speedKmh >= 0.0 && speedKmh < 0.5))
}
