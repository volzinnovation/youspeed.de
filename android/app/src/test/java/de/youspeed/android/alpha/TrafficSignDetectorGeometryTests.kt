package de.youspeed.android.alpha

import org.junit.Assert.assertEquals
import org.junit.Test

class TrafficSignDetectorGeometryTests {
    @Test fun landscapeResolutionsRetainTheSameRightmostSquare() {
        for ((width, height) in listOf(3840 to 2160, 1920 to 1080, 1280 to 720, 640 to 360)) {
            val geometry = TrafficSignDetectorGeometry(width, height)
            assertEquals(1024.0, height * geometry.scale, 1e-9)
            assertEquals(16384.0 / 9, geometry.scaledWidth, 1e-9)
            assertEquals(7168.0 / 9, geometry.left, 1e-9)
        }
    }

    @Test fun squareAndPortraitRemainUndistortedWithRightAlignment() {
        assertEquals(0.0, TrafficSignDetectorGeometry(1024, 1024).left, 0.0)
        val portrait = TrafficSignDetectorGeometry(640, 1280)
        assertEquals(0.8, portrait.scale, 0.0)
        assertEquals(512.0, portrait.scaledWidth, 0.0)
        assertEquals(-512.0, portrait.left, 0.0)
    }

    @Test(expected = IllegalArgumentException::class)
    fun invalidDimensionsAreRejected() { TrafficSignDetectorGeometry(0, 1080) }
}
