package de.youspeed.android.alpha

import java.time.Instant
import org.junit.Assert.*
import org.junit.Test

class DrivingInteractionMotionPolicyTests {
    private val now = Instant.parse("2026-09-29T12:00:00Z")
    private fun observe(previous: Boolean = false, raw: Double? = 0.0, filtered: Double = 0.0,
        accuracy: Double? = 5.0, observed: Instant = now) = DrivingInteractionMotionPolicy.observe(
        previous, raw, filtered, accuracy, observed, now)

    @Test fun freshMeasuredZeroUnlocksAndProvidesTheAlignmentTimestamp() {
        assertEquals(DrivingInteractionMotion(true, now), observe())
        assertTrue(observe(observed = now.minusMillis(3_000)).controlsAllowed)
        assertEquals(DrivingInteractionMotion(false, null), observe(observed = now.minusMillis(3_001)))
        assertEquals(DrivingInteractionMotion(false, null), observe(observed = now.plusMillis(1)))
    }

    @Test fun freshSpeedsBelowFourUnlockControlsWithoutClaimingStandstill() {
        for (speed in listOf(0.001, 0.5, 1.0, 3.0, 3.99)) {
            assertEquals(DrivingInteractionMotion(true, null), observe(raw = speed / 3.6, filtered = speed))
        }
        assertEquals(DrivingInteractionMotion(true, null), observe(raw = 0.01))
        assertEquals(DrivingInteractionMotion(true, null), observe(filtered = 3.99))
    }

    @Test fun fourOrFasterLocksForRawAndDisplayedSpeed() {
        for (speed in listOf(4.0, 4.01, 30.0)) {
            assertEquals(DrivingInteractionMotion(false, null), observe(previous = true, raw = speed / 3.6))
            assertEquals(DrivingInteractionMotion(false, null), observe(previous = true, filtered = speed))
            assertEquals(DrivingInteractionMotion(false, null), observe(previous = true, raw = null, filtered = speed))
        }
    }

    @Test fun deceleratingBelowFourRestoresControlsAndAcceleratingLocksAgain() {
        val moving = observe(previous = true, raw = 10.0, filtered = 36.0)
        val slow = observe(previous = moving.controlsAllowed, raw = 3 / 3.6, filtered = 3.0)
        val movingAgain = observe(previous = slow.controlsAllowed, raw = 4 / 3.6, filtered = 4.0)
        assertFalse(moving.controlsAllowed)
        assertTrue(slow.controlsAllowed)
        assertFalse(movingAgain.controlsAllowed)
    }

    @Test fun staleLowSpeedCannotUnlockControls() {
        assertTrue(observe(raw = 1 / 3.6, filtered = 1.0, observed = now.minusMillis(3_000)).controlsAllowed)
        assertFalse(observe(raw = 1 / 3.6, filtered = 1.0, observed = now.minusMillis(3_001)).controlsAllowed)
        assertFalse(observe(raw = 1 / 3.6, filtered = 1.0, observed = now.plusMillis(1)).controlsAllowed)
        assertFalse(observe(raw = null, filtered = 1.0).controlsAllowed)
        assertTrue(observe(previous = true, raw = null, filtered = 1.0).controlsAllowed)
    }

    @Test fun MissingOrInvalidSpeedCannotUnlockAfterMovement() {
        for (raw in listOf(null, -1.0, Double.NaN, Double.POSITIVE_INFINITY)) {
            assertEquals(DrivingInteractionMotion(false, null), observe(raw = raw))
        }
        for (accuracy in listOf(null, -1.0, Double.NaN, Double.POSITIVE_INFINITY)) {
            assertEquals(DrivingInteractionMotion(false, null), observe(accuracy = accuracy))
        }
        assertEquals(DrivingInteractionMotion(false, null), observe(filtered = Double.NaN))
        assertEquals(DrivingInteractionMotion(false, null), observe(filtered = -1.0))
    }

    @Test fun InitialSetupStaysAccessibleWithoutInventingStationaryEvidence() {
        assertEquals(DrivingInteractionMotion(true, null), observe(previous = true, raw = null))
        assertEquals(DrivingInteractionMotion(true, null), observe(previous = true, observed = now.minusSeconds(10)))
    }
}
