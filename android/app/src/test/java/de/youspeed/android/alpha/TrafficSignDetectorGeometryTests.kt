package de.youspeed.android.alpha

import org.junit.Assert.assertEquals
import org.junit.Test

class TrafficSignDetectorGeometryTests {
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
