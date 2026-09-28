package de.youspeed.android.alpha

import java.time.Instant
import org.junit.Assert.*
import org.junit.Test

class DrivingInteractionMotionPolicyTests {
    private val now = Instant.parse("2026-09-29T12:00:00Z")
    private fun observe(previous: Boolean = false, raw: Double? = 0.0, filtered: Double = 0.0,
        accuracy: Double? = 5.0, observed: Instant = now) = DrivingInteractionMotionPolicy.observe(
        previous, raw, filtered, accuracy, observed, now)

    @Test fun onlyFreshMeasuredZeroUnlocksAndProvidesTheAlignmentTimestamp() {
        assertEquals(DrivingInteractionMotion(true, now), observe())
        assertTrue(observe(observed = now.minusMillis(3_000)).controlsAllowed)
        assertEquals(DrivingInteractionMotion(false, null), observe(observed = now.minusMillis(3_001)))
        assertEquals(DrivingInteractionMotion(false, null), observe(observed = now.plusMillis(1)))
    }

    @Test fun rawMovementLocksEvenWhenDisplayedSpeedHasRoundedToZero() {
        assertEquals(DrivingInteractionMotion(false, null), observe(previous = true, raw = 0.001))
        assertEquals(DrivingInteractionMotion(false, null), observe(previous = true, filtered = 0.1))
        assertEquals(DrivingInteractionMotion(false, null), observe(previous = true, raw = null, filtered = 1.0))
    }

    @Test fun MissingOrInvalidSpeedCannotUnlockAfterMovement() {
        for (raw in listOf(null, -1.0, Double.NaN, Double.POSITIVE_INFINITY)) {
            assertEquals(DrivingInteractionMotion(false, null), observe(raw = raw))
        }
        for (accuracy in listOf(null, -1.0, Double.NaN, Double.POSITIVE_INFINITY)) {
            assertEquals(DrivingInteractionMotion(false, null), observe(accuracy = accuracy))
        }
        assertEquals(DrivingInteractionMotion(false, null), observe(filtered = Double.NaN))
    }

    @Test fun InitialSetupStaysAccessibleWithoutInventingStationaryEvidence() {
        assertEquals(DrivingInteractionMotion(true, null), observe(previous = true, raw = null))
        assertEquals(DrivingInteractionMotion(true, null), observe(previous = true, observed = now.minusSeconds(10)))
    }
}
