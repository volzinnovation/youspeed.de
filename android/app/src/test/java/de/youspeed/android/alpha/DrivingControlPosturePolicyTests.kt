package de.youspeed.android.alpha

import java.time.Instant
import kotlin.math.cos
import kotlin.math.sin
import org.junit.Assert.*
import org.junit.Test

class DrivingControlPosturePolicyTests {
    private fun angle(degrees: Double, landscape: Boolean = false): Double? {
        val radians = Math.toRadians(degrees)
        val inPlane = -sin(radians)
        return DrivingControlPosturePolicy.screenAngleDegrees(
            if (landscape) inPlane else 0.0,
            if (landscape) 0.0 else inPlane,
            -cos(radians),
        )
    }

    @Test fun flatAndHandheldAnglesAlwaysKeepControlsAvailableAtSpeed() {
        for (degrees in listOf(0.0, 30.0, 60.0, 79.999, 100.001, 120.0, 180.0)) {
            assertTrue("Angle $degrees", DrivingControlPosturePolicy.controlsAllowed(false, angle(degrees)))
        }
    }

    @Test fun inclusiveUprightBandAppliesTheExistingSpeedGateInEveryRotation() {
        for (landscape in listOf(false, true)) {
            for (degrees in listOf(80.0, 80.001, 90.0, 99.999, 100.0)) {
                val posture = angle(degrees, landscape)
                assertEquals(degrees, posture!!, 1e-9)
                assertTrue(DrivingControlPosturePolicy.isUpright(posture))
                assertFalse(DrivingControlPosturePolicy.controlsAllowed(false, posture))
                assertTrue(DrivingControlPosturePolicy.controlsAllowed(true, posture))
            }
        }
    }

    @Test fun gravityNormalizationDoesNotDependOnMagnitudeOrRoll() {
        for (scale in listOf(0.5, 1.0, 1.5)) {
            for (vector in listOf(Triple(scale, 0.0, 0.0), Triple(-scale, 0.0, 0.0),
                Triple(0.0, scale, 0.0), Triple(0.0, -scale, 0.0))) {
                val posture = DrivingControlPosturePolicy.screenAngleDegrees(vector.first, vector.second, vector.third)
                assertEquals(90.0, posture!!, 1e-9)
                assertFalse(DrivingControlPosturePolicy.controlsAllowed(false, posture))
            }
        }
    }

    @Test fun unavailableOrInvalidPostureCannotCloseDialogs() {
        for (posture in listOf(null, Double.NaN, Double.NEGATIVE_INFINITY, Double.POSITIVE_INFINITY, -1.0, 181.0)) {
            assertTrue(DrivingControlPosturePolicy.controlsAllowed(false, posture))
        }
        for (vector in listOf(Triple(0.0, 0.0, 0.0), Triple(0.0, 0.0, 0.49),
            Triple(0.0, 0.0, 1.51), Triple(Double.NaN, -1.0, 0.0),
            Triple(0.0, Double.POSITIVE_INFINITY, 0.0), Triple(0.0, -1.0, Double.NaN))) {
            assertNull(DrivingControlPosturePolicy.screenAngleDegrees(vector.first, vector.second, vector.third))
        }
    }

    @Test fun changingPostureReappliesGpsLatchWithoutWaitingForAnotherFix() {
        val now = Instant.parse("2026-10-17T12:00:00Z")
        val moving = DrivingInteractionMotionPolicy.observe(true, 10.0, 36.0, 5.0, now, now)
        assertFalse(DrivingControlPosturePolicy.controlsAllowed(moving.controlsAllowed, angle(90.0)))
        assertTrue(DrivingControlPosturePolicy.controlsAllowed(moving.controlsAllowed, angle(30.0)))
        // Invalid GPS while handheld retains the speed latch; returning upright restores its lock.
        val missingFix = DrivingInteractionMotionPolicy.observe(moving.controlsAllowed, null, 0.0, 5.0, now, now)
        assertFalse(missingFix.controlsAllowed)
        assertNull(missingFix.stationaryObservedAt)
        assertTrue(DrivingControlPosturePolicy.controlsAllowed(missingFix.controlsAllowed, angle(30.0)))
        assertFalse(DrivingControlPosturePolicy.controlsAllowed(missingFix.controlsAllowed, angle(90.0)))
    }

    @Test fun postureOverrideNeverInventsStationaryEvidence() {
        val now = Instant.parse("2026-10-17T12:00:00Z")
        val moving = DrivingInteractionMotionPolicy.observe(true, 10.0, 36.0, 5.0, now, now)
        assertTrue(DrivingControlPosturePolicy.controlsAllowed(moving.controlsAllowed, angle(0.0)))
        assertNull(moving.stationaryObservedAt)
    }
}
