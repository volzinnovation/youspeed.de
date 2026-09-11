package de.youspeed.android.alpha

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class TrafficSignFramePolicyTests {
    @Test
    fun adaptiveRateStaysBetweenTwoAndTenFps() {
        assertEquals(2, TrafficSignAdaptiveFramePolicy.decide(TrafficSignAnalysisConditions()).targetFramesPerSecond)
        assertEquals(
            8,
            TrafficSignAdaptiveFramePolicy.decide(
                TrafficSignAnalysisConditions(speedMetersPerSecond = 45.0),
            ).targetFramesPerSecond,
        )
        assertEquals(
            10,
            TrafficSignAdaptiveFramePolicy.decide(
                TrafficSignAnalysisConditions(speedMetersPerSecond = 2.0, hasActiveTrack = true),
            ).targetFramesPerSecond,
        )
    }

    @Test
    fun powerAndThermalPressureDegradePredictably() {
        val active = TrafficSignAnalysisConditions(speedMetersPerSecond = 30.0, hasActiveTrack = true)

        assertEquals(2, TrafficSignAdaptiveFramePolicy.decide(active.copy(powerSaveMode = true)).targetFramesPerSecond)
        assertEquals(
            5,
            TrafficSignAdaptiveFramePolicy.decide(active.copy(thermalPressure = TrafficSignThermalPressure.FAIR)).targetFramesPerSecond,
        )
        assertEquals(
            2,
            TrafficSignAdaptiveFramePolicy.decide(active.copy(thermalPressure = TrafficSignThermalPressure.SERIOUS)).targetFramesPerSecond,
        )
        val critical = TrafficSignAdaptiveFramePolicy.decide(active.copy(thermalPressure = TrafficSignThermalPressure.CRITICAL))
        assertTrue(critical.paused)
        assertEquals(0, critical.targetFramesPerSecond)
        assertNull(critical.minimumIntervalNanos)
        assertTrue(TrafficSignAdaptiveFramePolicy.decide(active.copy(applicationIsActive = false)).paused)
    }

    @Test
    fun speedBandsMatchTheIphoneReference() {
        listOf(0.0 to 2, 20.0 to 2, 30.0 to 4, 45.0 to 4, 60.0 to 6, 75.0 to 6, 100.0 to 8, 120.0 to 8)
            .forEach { (kmh, fps) ->
                assertEquals(fps, TrafficSignAdaptiveFramePolicy.decide(
                    TrafficSignAnalysisConditions(speedMetersPerSecond = kmh / 3.6),
                ).targetFramesPerSecond)
            }
    }

    @Test
    fun slotKeepsOnlyLatestFrameWhileAnalysisIsInFlight() {
        val discarded = mutableListOf<String>()
        val slot = TrafficSignLatestFrameSlot<String>(discarded::add)
        val activeTrack = TrafficSignAnalysisConditions(hasActiveTrack = true)

        slot.offer("first", capturedAtNanos = 0L)
        assertEquals("first", slot.takeIfDue(nowNanos = 0L, conditions = activeTrack)?.value)
        assertTrue(slot.isAnalysisInFlight())

        slot.offer("second", capturedAtNanos = 10L)
        slot.offer("third", capturedAtNanos = 20L)
        assertEquals(listOf("second"), discarded)
        assertNull(slot.takeIfDue(nowNanos = 100_000_000L, conditions = activeTrack))

        slot.markAnalysisComplete()
        assertEquals("third", slot.takeIfDue(nowNanos = 100_000_000L, conditions = activeTrack)?.value)
        assertFalse(slot.hasPendingFrame())
    }

    @Test
    fun slotDiscardsOutOfOrderAndPausedFramesNeverDispatch() {
        val discarded = mutableListOf<Int>()
        val slot = TrafficSignLatestFrameSlot<Int>(discarded::add)
        slot.offer(2, capturedAtNanos = 2L)
        slot.offer(1, capturedAtNanos = 1L)

        val paused = TrafficSignAnalysisConditions(thermalPressure = TrafficSignThermalPressure.CRITICAL)
        assertNull(slot.takeIfDue(nowNanos = 10L, conditions = paused))
        assertEquals(listOf(1), discarded)
        assertTrue(slot.hasPendingFrame())
    }
}
