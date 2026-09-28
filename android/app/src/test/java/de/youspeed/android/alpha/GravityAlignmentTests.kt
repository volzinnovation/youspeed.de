package de.youspeed.android.alpha

import java.time.Instant
import kotlin.math.cos
import kotlin.math.sin
import org.junit.Assert.*
import org.junit.Test

class GravityAlignmentTests {
    @Test fun bothManualLandscapeMountsRemapAndroidGravityToUprightScreen() {
        val lower = GravityAlignmentGeometry.fromAndroidGravity(-9.80665, 0.0, 0.0,
            ManualOrientation.LANDSCAPE_CAMERA_LOWER_RIGHT)!!
        val upper = GravityAlignmentGeometry.fromAndroidGravity(9.80665, 0.0, 0.0,
            ManualOrientation.LANDSCAPE_CAMERA_UPPER_LEFT)!!
        assertEquals(0.0, lower.rollDegrees, 0.0001)
        assertEquals(0.0, upper.rollDegrees, 0.0001)
        assertTrue(lower.isLevel)
        assertEquals(lower.rollDegrees, upper.rollDegrees, 0.0001)
        assertEquals(lower.tiltDegrees, upper.tiltDegrees, 0.0001)
    }

    @Test fun rollAndTiltAreEquivalentAcrossChosenMounts() {
        val roll = Math.toRadians(12.0)
        val tilt = Math.toRadians(-8.0)
        val sx = sin(roll) * cos(tilt)
        val sy = -cos(roll) * cos(tilt)
        val z = sin(tilt)
        for ((orientation, xy) in listOf(
            ManualOrientation.PORTRAIT to (sx to sy),
            ManualOrientation.LANDSCAPE_CAMERA_LOWER_RIGHT to (-sy to sx),
            ManualOrientation.LANDSCAPE_CAMERA_UPPER_LEFT to (sy to -sx),
        )) {
            val reading = GravityAlignmentGeometry.fromDownwardGravity(xy.first, xy.second, z, orientation)!!
            assertEquals(12.0, reading.rollDegrees, 0.0001)
            assertEquals(-8.0, reading.tiltDegrees, 0.0001)
            assertFalse(reading.isLevel)
        }
    }

    @Test fun unavailableOrFlatGravityNeverAppearsLevel() {
        for (v in listOf(doubleArrayOf(0.0, 0.0, 0.0), doubleArrayOf(0.0, 0.0, 1.0),
            doubleArrayOf(Double.NaN, -1.0, 0.0), doubleArrayOf(0.0, -3.0, 0.0))) {
            assertNull(GravityAlignmentGeometry.fromDownwardGravity(v[0], v[1], v[2], ManualOrientation.PORTRAIT))
        }
        val upsideDown = GravityAlignmentGeometry.fromDownwardGravity(0.0, 1.0, 0.0, ManualOrientation.PORTRAIT)!!
        assertEquals(180.0, upsideDown.rollDegrees, 0.0001)
        assertFalse(upsideDown.isLevel)
    }

    @Test fun levelRequiresBothAnglesWithinThreeDegrees() {
        assertTrue(GravityAlignmentReading(3.0, -3.0).isLevel)
        assertFalse(GravityAlignmentReading(3.01, 0.0).isLevel)
        assertFalse(GravityAlignmentReading(0.0, -3.01).isLevel)
    }

    @Test fun overlayRequiresFreshVerifiedZeroSpeedInLandscape() {
        val now = Instant.parse("2026-09-29T12:00:00Z")
        assertTrue(GravityAlignmentVisibility.isVisible(true, true, 0.0, now, now, false))
        assertTrue(GravityAlignmentVisibility.isFreshStationary(0.0, now.minusSeconds(3), now, false))
        assertFalse(GravityAlignmentVisibility.isVisible(false, true, 0.0, now, now, false))
        assertFalse(GravityAlignmentVisibility.isVisible(true, false, 0.0, now, now, false))
        assertFalse(GravityAlignmentVisibility.isVisible(true, true, 0.0, now, now, true))
        assertFalse(GravityAlignmentVisibility.isFreshStationary(0.0, now.minusSeconds(3).minusNanos(1), now, false))
        assertFalse(GravityAlignmentVisibility.isFreshStationary(0.0, now.plusNanos(1), now, false))
        assertFalse(GravityAlignmentVisibility.isFreshStationary(0.0, null, now, false))
        for (speed in listOf(null, Double.NaN, Double.POSITIVE_INFINITY, -1.0, 0.001)) {
            assertFalse(GravityAlignmentVisibility.isFreshStationary(speed, now, now, false))
        }
    }
}
