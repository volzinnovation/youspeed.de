package de.youspeed.android.alpha

import kotlin.math.acos
import kotlin.math.sqrt

/** The speed lock applies only to an upright phone, independent of the selected screen rotation. */
internal object DrivingControlPosturePolicy {
    /** Core Motion convention: a downward gravity vector in units of g; face-up is zero degrees. */
    fun screenAngleDegrees(x: Double, y: Double, z: Double): Double? {
        if (!x.isFinite() || !y.isFinite() || !z.isFinite()) return null
        val length = sqrt(x * x + y * y + z * z)
        if (length !in 0.5..1.5) return null
        return Math.toDegrees(acos((-z / length).coerceIn(-1.0, 1.0)))
    }

    fun isUpright(screenAngleDegrees: Double?): Boolean =
        screenAngleDegrees != null && screenAngleDegrees.isFinite() &&
            screenAngleDegrees >= 80.0 - 1e-9 && screenAngleDegrees <= 100.0 + 1e-9

    /** Missing or invalid posture evidence must not hide buttons or dismiss an open dialog. */
    fun controlsAllowed(speedControlsAllowed: Boolean, screenAngleDegrees: Double?): Boolean =
        speedControlsAllowed || !isUpright(screenAngleDegrees)
}
