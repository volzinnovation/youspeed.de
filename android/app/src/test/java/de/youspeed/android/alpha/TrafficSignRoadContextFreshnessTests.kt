package de.youspeed.android.alpha

import org.junit.Assert.*
import org.junit.Test

class TrafficSignRoadContextFreshnessTests {
    @Test
    fun threeSecondLookupRemainsUsableWhenNewerFixArrivesDuringFastTravel() {
        val matched = position(10_000)
        val latest = position(13_000, longitude = 8.0017)
        assertTrue(TrafficSignRoadContextFreshness.accepts(matched, latest, 13_500))
    }

    @Test
    fun oldMatchedRoadCannotRemainCurrentDespiteFreshGpsFixes() {
        val matched = position(10_000)
        assertTrue(TrafficSignRoadContextFreshness.accepts(matched, position(16_000), 16_000))
        assertFalse(TrafficSignRoadContextFreshness.accepts(matched, position(16_001), 16_001))
        assertFalse(TrafficSignRoadContextFreshness.accepts(matched, position(67_000), 67_000))
        assertFalse(TrafficSignRoadContextFreshness.accepts(matched, position(9_999), 13_000))
        assertFalse(TrafficSignRoadContextFreshness.accepts(matched, position(13_001), 13_000))
    }

    @Test
    fun excessiveDisplacementOrTurnRequiresNewRoadMatch() {
        val matched = position(10_000)
        assertFalse(TrafficSignRoadContextFreshness.accepts(matched, position(12_000, longitude = 8.004), 12_000))
        assertFalse(TrafficSignRoadContextFreshness.accepts(matched, position(12_000, heading = 180.0), 12_000))
        assertTrue(TrafficSignRoadContextFreshness.accepts(
            position(10_000, heading = 359.0), position(12_000, heading = 1.0), 12_000,
        ))
    }

    @Test
    fun refreshedCaptureUsesLatestPositionWithoutChangingTrustedRoadScope() {
        val original = context()
        val latest = position(12_000, longitude = 8.001)
        val refreshed = requireNotNull(TrafficSignRoadContextFreshness.refreshedContext(
            original, position(10_000), latest, 13_000,
        ))
        assertEquals(latest.longitude, refreshed.longitude, 0.0)
        assertEquals(original.wayId, refreshed.wayId)
        assertEquals(original.sourceSignature, refreshed.sourceSignature)
        assertEquals(original.bundleSha256, refreshed.bundleSha256)
        assertEquals(original.travelDirection, refreshed.travelDirection)
        assertEquals(original.traversalEpoch, refreshed.traversalEpoch)
        assertEquals(original.routeRelationGroupIds, refreshed.routeRelationGroupIds)
        assertEquals(8.0, original.longitude, 0.0)
        assertNull(TrafficSignRoadContextFreshness.refreshedContext(original, position(10_000), latest, 17_000))
        assertNull(TrafficSignRoadContextFreshness.refreshedContext(original, null, latest, 13_000))
    }

    @Test
    fun absentAndInvalidFixesCannotAuthorizeOldRoadContext() {
        val matched = position(10_000)
        assertFalse(TrafficSignRoadContextFreshness.accepts(matched, null, 12_000))
        assertFalse(TrafficSignRoadContextFreshness.accepts(matched, position(12_000).copy(latitude = Double.NaN), 12_000))
        assertFalse(TrafficSignRoadContextFreshness.accepts(matched, position(12_000).copy(speedMetersPerSecond = -1.0), 12_000))
        assertFalse(TrafficSignRoadContextFreshness.accepts(matched, position(12_000, heading = 360.0), 12_000))
    }

    private fun position(time: Long, longitude: Double = 8.0, heading: Double = 90.0) =
        TrafficSignPositionSample(time, 49.0, longitude, heading, 35.0)

    private fun context() = TrafficSignDetectionContext(
        wayId = "test-way", latitude = 49.0, longitude = 8.0, headingDegrees = 90.0,
        travelDirection = TrafficSignTravelDirection.FORWARD,
        sourceSignature = TrafficSignRuntimeSourceSignature("bundle:test|way:test-way|maxspeed:50", null),
        bundleSha256 = "a".repeat(64), routeRelationGroupIds = setOf(1), traversalEpoch = 7,
    )
}
