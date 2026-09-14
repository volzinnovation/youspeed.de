package de.youspeed.android.alpha

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class TrafficSignInferenceTimingPolicyTests {
    @Test
    fun verifiedWarmReferenceUsesSlowestInferenceWithSchedulingMargin() {
        val profile = requireNotNull(TrafficSignInferenceTimingPolicy.profile(
            manifestConfirmationWindowMs = 1_500,
            referenceVerified = true,
            warmInferenceTimesMs = listOf(2_300.0, 2_900.0, 2_600.0),
        ))
        assertEquals(2_900.0, profile.measuredWarmMaxMs, 0.0)
        assertEquals(5_800L, profile.confirmationWindowMs)
    }

    @Test
    fun fastDeviceKeepsManifestWindowAndSlowDeviceIsCapped() {
        assertEquals(1_500L, profile(listOf(100.0, 200.0))?.confirmationWindowMs)
        assertEquals(6_000L, profile(listOf(9_000.0))?.confirmationWindowMs)
        assertEquals(6_000L, profile(listOf(Double.MAX_VALUE))?.confirmationWindowMs)
        assertEquals(1_502L, profile(listOf(750.6))?.confirmationWindowMs)
    }

    @Test
    fun failedReferenceOrInvalidMeasurementCannotExtendTiming() {
        assertNull(TrafficSignInferenceTimingPolicy.profile(1_500, false, listOf(2_900.0)))
        assertNull(profile(emptyList()))
        listOf(0.0, -1.0, Double.NaN, Double.POSITIVE_INFINITY, Double.NEGATIVE_INFINITY).forEach { invalid ->
            assertNull(profile(listOf(2_900.0, invalid)))
        }
    }

    @Test
    fun manifestWindowIsNeverReduced() {
        assertEquals(8_000L, TrafficSignInferenceTimingPolicy.profile(8_000, true, listOf(4_000.0))?.confirmationWindowMs)
    }

    private fun profile(timings: List<Double>) = TrafficSignInferenceTimingPolicy.profile(1_500, true, timings)
}
