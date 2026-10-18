package de.youspeed.android.alpha

import kotlin.math.*
import org.junit.Assert.*
import org.junit.Test

class DrivingControlPosturePolicyTests {
    @Test fun onlyFaceUpWithinTenDegreesCanShowControlsInEveryRotation() {
        for (angle in listOf(0.0, 5.0, 10.0, 10.001, 30.0, 79.0, 90.0, 101.0, 180.0)) {
            for (landscape in listOf(false, true)) {
                val radians = Math.toRadians(angle)
                val measured = DrivingControlPosturePolicy.screenAngleDegrees(
                    if (landscape) sin(radians) else 0.0,
                    if (landscape) 0.0 else sin(radians), -cos(radians))!!
                assertEquals(angle, measured, 1e-9)
                assertEquals(angle <= 10.0, DrivingControlPosturePolicy.controlsAllowed(true, measured))
                assertFalse(DrivingControlPosturePolicy.controlsAllowed(false, measured))
            }
        }
    }

    @Test fun missingOrInvalidPostureCannotUnlockControls() {
        for (angle in listOf(null, Double.NaN, Double.POSITIVE_INFINITY, -1.0, 181.0)) {
            assertFalse(DrivingControlPosturePolicy.controlsAllowed(true, angle))
            assertFalse(DrivingControlPosturePolicy.controlsAllowed(false, angle))
        }
        assertNull(DrivingControlPosturePolicy.screenAngleDegrees(0.0, 0.0, 0.0))
        assertNull(DrivingControlPosturePolicy.screenAngleDegrees(Double.NaN, 0.0, -1.0))
    }
}
