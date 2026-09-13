package de.youspeed.android.alpha

import kotlin.math.abs
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class LaneDetectionTests {
    private val detector = LaneDetector()

    private fun road(left: Boolean = true, right: Boolean = true, width: Int = 384, height: Int = 216): ByteArray {
        val image = ByteArray(width * height) { 55 }
        for (y in 0 until height) {
            val normalizedY = y.toDouble() / (height - 1)
            if (normalizedY !in 0.52..0.96) continue
            val offset = (normalizedY - 0.52) * 0.30 / 0.44
            for (x in 0 until width) {
                val normalizedX = x.toDouble() / (width - 1)
                if ((left && abs(normalizedX - (0.42 - offset)) < 0.0065) ||
                    (right && abs(normalizedX - (0.58 + offset)) < 0.0065)) {
                    image[y * width + x] = 230.toByte()
                }
            }
        }
        return image
    }

    @Test
    fun pairNeedsTwoFramesAndNeverInventsMissingBoundary() {
        val tracker = LaneTracker()
        val first = detector.detect(road(), 384, 216, 1.0)
        assertTrue(first.hasReliablePair)
        assertEquals(LaneDetectionState.UNCERTAIN, tracker.update(first).state)
        assertTrue(tracker.update(detector.detect(road(), 384, 216, 1.2)).hasReliablePair)
        val single = tracker.update(detector.detect(road(right = false), 384, 216, 1.4))
        assertEquals(LaneDetectionState.UNCERTAIN, single.state)
        assertNotNull(single.left)
        assertNull(single.right)
        val blank = tracker.update(detector.detect(ByteArray(384 * 216) { 55 }, 384, 216, 1.6))
        assertEquals(LaneDetectionState.UNAVAILABLE, blank.state)
        assertNull(blank.left)
        assertNull(blank.right)
    }

    @Test
    fun backwardClockGapsAndExplicitResetRequireFreshConfirmation() {
        val tracker = LaneTracker()
        fun estimate(time: Double) = detector.detect(road(), 384, 216, time)
        tracker.update(estimate(1.0))
        assertTrue(tracker.update(estimate(1.2)).hasReliablePair)
        assertEquals(LaneDetectionState.UNCERTAIN, tracker.update(estimate(2.0)).state)
        assertTrue(tracker.update(estimate(2.2)).hasReliablePair)
        assertEquals(LaneDetectionState.UNCERTAIN, tracker.update(estimate(2.1)).state)
        tracker.reset()
        assertEquals(LaneDetectionState.UNCERTAIN, tracker.update(estimate(2.3)).state)
    }

    @Test
    fun invalidInputAndNonFiniteTimestampAreUnavailable() {
        listOf(Triple(0, 216, ByteArray(0)), Triple(641, 216, ByteArray(0)), Triple(384, 216, byteArrayOf(55))).forEach { (width, height, pixels) ->
            assertEquals(LaneDetectionState.UNAVAILABLE, detector.detect(pixels, width, height, 1.0).state)
        }
        assertEquals(LaneDetectionState.UNAVAILABLE, detector.detect(road(), 384, 216, Double.NaN).state)
        val invalid = LaneDetectionEstimate(null, null, Double.POSITIVE_INFINITY, LaneDetectionState.RELIABLE)
        assertEquals(LaneDetectionState.UNAVAILABLE, LaneTracker().update(invalid).state)
    }

    @Test
    fun fitStaysOnObservedMarkings() {
        val estimate = detector.detect(road(), 384, 216, 1.0)
        listOf(requireNotNull(estimate.left) to true, requireNotNull(estimate.right) to false).forEach { (boundary, isLeft) ->
            assertTrue(boundary.confidence >= 0.62)
            boundary.points.forEach { point ->
                assertTrue(point.y in 0.52..0.96)
                val offset = (point.y - 0.52) * 0.30 / 0.44
                assertEquals(if (isLeft) 0.42 - offset else 0.58 + offset, point.x, 0.008)
            }
        }
    }

    @Test
    fun corridorFillUsesOnlySharedObservedExtent() {
        val left = LaneBoundary(listOf(LanePoint(0.4, 0.5), LanePoint(0.1, 0.9)), 0.9)
        val right = LaneBoundary(listOf(LanePoint(0.6, 0.6), LanePoint(0.8, 0.8)), 0.9)
        val estimate = LaneDetectionEstimate(left, right, 1.0, LaneDetectionState.RELIABLE)
        assertEquals(4, estimate.corridorPoints.size)
        assertTrue(estimate.corridorPoints.all { it.y in 0.6..0.8 })
        assertEquals(0.325, estimate.corridorPoints.first().x, 1e-9)
        assertEquals(0.175, estimate.corridorPoints[1].x, 1e-9)
        assertTrue(estimate.copy(state = LaneDetectionState.UNCERTAIN).corridorPoints.isEmpty())
        assertTrue(estimate.copy(right = null).corridorPoints.isEmpty())
    }
}
