package de.youspeed.android.alpha

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class TrafficSignTensorDiagnosticsTests {
    @Test
    fun signChannelKeepsItsOwnMaximumAndInclusiveThresholdCount() {
        val summary = TrafficSignTensorDiagnostics.summarize(
            floatArrayOf(900f, -3f, 0.25f, 0.5f, Float.NaN, Float.POSITIVE_INFINITY, 0.125f, 8f),
            signOffset = 2,
            signCount = 5,
            minimumScore = 0.25,
        )
        assertEquals(0.5, summary.signTopScore)
        assertEquals(900.0, summary.globalTopScore)
        assertEquals(2, summary.signScoresAboveThreshold)
    }

    @Test
    fun nonfiniteOutputHasNoReportedMaximum() {
        val summary = TrafficSignTensorDiagnostics.summarize(
            floatArrayOf(Float.NaN, Float.POSITIVE_INFINITY, Float.NEGATIVE_INFINITY), 0, 3, 0.25,
        )
        assertNull(summary.signTopScore)
        assertNull(summary.globalTopScore)
        assertEquals(0, summary.signScoresAboveThreshold)
    }

    @Test
    fun floatPrecisionAndPositiveZeroArePreservedInNullableDoubleResults() {
        val output = floatArrayOf(-0f, 0f, 0.12345679f, 0.12345678f)
        val summary = TrafficSignTensorDiagnostics.summarize(output, 0, 2, 0.0)
        assertEquals(0.0.toBits(), requireNotNull(summary.signTopScore).toBits())
        assertEquals(output[2].toDouble().toBits(), requireNotNull(summary.globalTopScore).toBits())
        assertEquals(2, summary.signScoresAboveThreshold)
    }

    @Test
    fun emptySignChannelDoesNotTreatOtherOutputsAsSigns() {
        val summary = TrafficSignTensorDiagnostics.summarize(floatArrayOf(0.9f), 1, 0, 0.25)
        assertNull(summary.signTopScore)
        assertEquals(0, summary.signScoresAboveThreshold)
        assertEquals(0.9f.toDouble(), summary.globalTopScore)
    }
}
