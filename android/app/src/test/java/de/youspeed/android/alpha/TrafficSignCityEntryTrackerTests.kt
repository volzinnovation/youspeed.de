package de.youspeed.android.alpha

import org.junit.Assert.*
import org.junit.Test

class TrafficSignCityEntryTrackerTests {
    private val high = "settlement:zone_traffic:high"
    private val low = "settlement:landuse:low"
    private fun position(time: Long, latitude: Double = 49.0) =
        TrafficSignPositionSample(time, latitude, 8.0, 90.0, 20.0)

    @Test fun weakOrMissingEvidenceWithinTownDoesNotCreateAnotherCameraEntry() {
        val tracker = TrafficSignCityEntryTracker()
        assertTrue(tracker.observe(true, high, position(10_000), "bundle-a"))
        assertFalse(tracker.observe(true, low, position(12_000), "bundle-a"))
        assertFalse(tracker.observe(null, "settlement:missing:unknown", position(14_000), "bundle-a"))
        assertFalse(tracker.observe(true, high, position(18_000, 49.001), "bundle-a"))
        assertFalse(tracker.observe(true, high, position(19_000, 49.0011), "bundle-a"))
    }

    @Test fun outsideConfirmationStillProducesOneEntryAfterAWeakInsideFix() {
        val tracker = TrafficSignCityEntryTracker()
        assertFalse(tracker.observe(false, high, position(10_000), "bundle-a"))
        assertFalse(tracker.observe(true, low, position(12_000), "bundle-a"))
        assertTrue(tracker.observe(true, high, position(14_000), "bundle-a"))
        assertFalse(tracker.observe(true, high, position(15_000), "bundle-a"))
    }

    @Test fun weakFixesDoNotExtendTheTimeOrDistanceBound() {
        val elapsedTracker = TrafficSignCityEntryTracker()
        assertTrue(elapsedTracker.observe(true, high, position(10_000), "bundle-a"))
        assertFalse(elapsedTracker.observe(true, low, position(17_999), "bundle-a"))
        assertTrue(elapsedTracker.observe(true, high, position(18_001), "bundle-a"))
        val distanceTracker = TrafficSignCityEntryTracker()
        assertTrue(distanceTracker.observe(true, high, position(10_000), "bundle-a"))
        assertFalse(distanceTracker.observe(true, low, position(11_000, 49.001), "bundle-a"))
        assertTrue(distanceTracker.observe(true, high, position(12_000, 49.002), "bundle-a"))
    }

    @Test fun explicitExitLifecycleAndBundleChangeEndTheOldConfirmation() {
        val tracker = TrafficSignCityEntryTracker()
        assertTrue(tracker.observe(true, high, position(10_000), "bundle-a"))
        assertFalse(tracker.observe(false, high, position(11_000), "bundle-a"))
        assertTrue(tracker.observe(true, high, position(12_000), "bundle-a"))
        tracker.reset()
        assertTrue(tracker.observe(true, high, position(13_000), "bundle-a"))
        assertTrue(tracker.observe(true, high, position(14_000), "bundle-b"))
    }

    @Test fun invalidAndOutOfOrderFixesCannotConfirmAnEntry() {
        val tracker = TrafficSignCityEntryTracker()
        assertFalse(tracker.observe(true, high, position(10_000, Double.NaN), "bundle-a"))
        assertTrue(tracker.observe(true, high, position(12_000), "bundle-a"))
        assertFalse(tracker.observe(null, "settlement:missing:unknown", position(13_000), "bundle-a"))
        assertFalse(tracker.observe(true, high, position(12_500), "bundle-a"))
        assertFalse(tracker.observe(null, high, position(13_000), "bundle-a"))
        assertTrue(tracker.observe(true, high, position(14_000), "bundle-a"))
    }
}
