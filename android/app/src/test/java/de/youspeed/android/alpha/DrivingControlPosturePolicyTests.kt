package de.youspeed.android.alpha

import kotlin.math.*
import org.junit.Assert.*
import org.junit.Test
import java.time.Instant

class DrivingControlPosturePolicyTests {
    @Test fun slowSpeedAndMissingSignalAllowEveryPosture() {
        for (angle in listOf(null, 0.0, 10.0, 11.0, 90.0, 180.0)) {
            for (speed in listOf(0.0, 0.5, 3.999))
                assertTrue(DrivingControlPosturePolicy.controlsAllowed(false, angle, speed, true))
            assertTrue(DrivingControlPosturePolicy.controlsAllowed(false, angle, 70.0, false))
        }
        assertFalse(DrivingControlPosturePolicy.controlsAllowed(true, 90.0, 4.0, true))
        assertFalse(DrivingPhotoCapturePolicy.replacesSettings(3.999, true))
        assertFalse(DrivingPhotoCapturePolicy.replacesSettings(70.0, false))
        assertTrue(DrivingPhotoCapturePolicy.replacesSettings(4.0, true))
        val now = Instant.parse("2026-10-19T08:00:00Z")
        assertFalse(DrivingControlPosturePolicy.hasSignal(null, null, now))
        assertFalse(DrivingControlPosturePolicy.hasSignal(now.minusMillis(3_001), 5.0, now))
        assertFalse(DrivingControlPosturePolicy.hasSignal(now, 60.0, now))
        assertTrue(DrivingControlPosturePolicy.hasSignal(now.minusSeconds(3), 5.0, now))
    }
    @Test fun onlyFaceUpWithinTenDegreesCanShowControlsInEveryRotation() {
        for (angle in listOf(0.0, 5.0, 10.0, 10.001, 30.0, 79.0, 90.0, 101.0, 180.0)) {
            for (landscape in listOf(false, true)) {
                val radians = Math.toRadians(angle)
                val measured = DrivingControlPosturePolicy.screenAngleDegrees(
                    if (landscape) sin(radians) else 0.0,
                    if (landscape) 0.0 else sin(radians), -cos(radians))!!
                assertEquals(angle, measured, 1e-9)
                assertEquals(angle <= 10.0, DrivingControlPosturePolicy.controlsAllowed(true, measured))
                assertEquals(angle <= 10.0, DrivingControlPosturePolicy.controlsAllowed(false, measured))
            }
        }
    }

    @Test fun flatDeskKeepsControlsAndSettingsAtEveryReportedSpeed() {
        for(angle in listOf(0.0,5.0,10.0)) for(speed in listOf(21.0,70.0,180.0,Double.NaN,Double.POSITIVE_INFINITY)) {
            assertTrue(DrivingControlPosturePolicy.controlsAllowed(false,angle,speed,true))
            assertFalse(DrivingPhotoCapturePolicy.replacesSettings(speed,true,phoneIsFlat=true))
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
