package de.youspeed.android.alpha

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class TrafficSignTraversalTrackerTests {
    @Test
    fun sameWayKeepsTraversalEpoch() {
        val tracker = TrafficSignTraversalTracker()

        val first = tracker.update("123.0", TrafficSignTravelDirection.FORWARD, false, emptySet())
        val second = tracker.update("123", TrafficSignTravelDirection.FORWARD, false, emptySet())

        assertEquals(1L, first.epoch)
        assertTrue(first.continuouslyRelated)
        assertEquals(1L, second.epoch)
        assertTrue(second.continuouslyRelated)
    }

    @Test
    fun relatedWaysKeepEpochButUnrelatedWayStartsOne() {
        val tracker = TrafficSignTraversalTracker()
        tracker.update("100", TrafficSignTravelDirection.FORWARD, true, setOf(7L))

        val related = tracker.update("101", TrafficSignTravelDirection.FORWARD, true, setOf(7L))
        val unrelated = tracker.update("102", TrafficSignTravelDirection.FORWARD, true, setOf(8L))

        assertEquals(1L, related.epoch)
        assertTrue(related.continuouslyRelated)
        assertEquals(2L, unrelated.epoch)
        assertFalse(unrelated.continuouslyRelated)
    }

    @Test
    fun reversingOnSameWayStartsNewEpoch() {
        val tracker = TrafficSignTraversalTracker()
        tracker.update("100", TrafficSignTravelDirection.FORWARD, false, emptySet())

        val reversed = tracker.update("100", TrafficSignTravelDirection.REVERSE, false, emptySet())

        assertEquals(2L, reversed.epoch)
        assertFalse(reversed.continuouslyRelated)
    }
}
