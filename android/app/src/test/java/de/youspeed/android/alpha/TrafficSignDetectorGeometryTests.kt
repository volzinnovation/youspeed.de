package de.youspeed.android.alpha

import org.junit.Assert.assertEquals
import org.junit.Test

class TrafficSignDetectorGeometryTests {
    @Test fun twoEdgeWindowsMapOverlapToOneSourceBox() {
        val windows = TrafficSignDetectorWindow.twoEdges(1920, 1080)
        assertEquals(listOf(0, 840), windows.map { it.left })
        val leftBox = windows[0].sourceBox(NormalizedTrafficSignBoundingBox(900.0 / 1080, .2, .05, .1), 1920)
        val rightBox = windows[1].sourceBox(NormalizedTrafficSignBoundingBox(60.0 / 1080, .2, .05, .1), 1920)
        assertEquals(leftBox.x, rightBox.x, 1e-9)
        val merged = AndroidYoloSignDecoder.merge(listOf(AndroidYoloProposal(.9f, leftBox), AndroidYoloProposal(.85f, rightBox)))
        assertEquals(1, merged.size)
        assertEquals(.9f, merged.single().score)
    }

    @Test fun portraitUsesOnePassAndUltraWideRetainsCenterCoverage() {
        assertEquals(1, TrafficSignDetectorWindow.twoEdges(1080, 1920).size)
        assertEquals(1, TrafficSignDetectorWindow.twoEdges(1080, 1080).size)
        val wide = TrafficSignDetectorWindow.twoEdges(3000, 1000)
        assertEquals(listOf(0, 2000, 0), wide.map { it.left })
        assertEquals(3000, wide.last().width)
    }

    @Test fun landscapeResolutionsFitTheFullFrame() {
        for ((width, height) in listOf(3840 to 2160, 1920 to 1080, 1280 to 720, 640 to 360)) {
            val geometry = TrafficSignDetectorGeometry(width, height)
            assertEquals(1024.0, geometry.scaledWidth, 1e-9)
            assertEquals(576.0, geometry.scaledHeight, 1e-9)
            assertEquals(0.0, geometry.left, 1e-9)
            assertEquals(224.0, geometry.top, 1e-9)
        }
    }

    @Test fun squareAndPortraitRemainUndistortedAndCentered() {
        assertEquals(0.0, TrafficSignDetectorGeometry(1024, 1024).left, 0.0)
        val portrait = TrafficSignDetectorGeometry(640, 1280)
        assertEquals(0.8, portrait.scale, 0.0)
        assertEquals(512.0, portrait.scaledWidth, 0.0)
        assertEquals(256.0, portrait.left, 0.0)
        assertEquals(0.0, portrait.top, 0.0)
    }

    @Test(expected = IllegalArgumentException::class)
    fun invalidDimensionsAreRejected() { TrafficSignDetectorGeometry(0, 1080) }
}
