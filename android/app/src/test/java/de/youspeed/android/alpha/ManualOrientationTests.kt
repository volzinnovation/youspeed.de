package de.youspeed.android.alpha

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ManualOrientationTests {
    @Test
    fun storedMountPositionsRoundTrip() {
        assertEquals("portrait", ManualOrientation.PORTRAIT.storageValue)
        assertEquals("landscape_camera_lower_right", ManualOrientation.LANDSCAPE_CAMERA_LOWER_RIGHT.storageValue)
        assertEquals("landscape_camera_upper_left", ManualOrientation.LANDSCAPE_CAMERA_UPPER_LEFT.storageValue)
        for (orientation in ManualOrientation.entries) {
            assertEquals(orientation, ManualOrientation.fromStorageValue(orientation.storageValue))
        }
    }

    @Test
    fun missingOrUnrecognizedPreferenceUsesPortrait() {
        for (value in listOf(null, "", "unknown", "landscape", "PORTRAIT")) {
            assertEquals(ManualOrientation.PORTRAIT, ManualOrientation.fromStorageValue(value))
        }
    }

    @Test
    fun mountPositionsSelectMatchingWindowAndCameraRotations() {
        // Assert SDK values directly so swapping either mount label is detected.
        assertEquals(1, ManualOrientation.PORTRAIT.requestedOrientation)
        assertEquals(0, ManualOrientation.PORTRAIT.targetRotation)
        assertFalse(ManualOrientation.PORTRAIT.isLandscape)

        val connectorLeft = ManualOrientation.LANDSCAPE_CAMERA_LOWER_RIGHT
        assertEquals(8, connectorLeft.requestedOrientation)
        assertEquals(3, connectorLeft.targetRotation)
        assertTrue(connectorLeft.isLandscape)

        val connectorRight = ManualOrientation.LANDSCAPE_CAMERA_UPPER_LEFT
        assertEquals(0, connectorRight.requestedOrientation)
        assertEquals(1, connectorRight.targetRotation)
        assertTrue(connectorRight.isLandscape)
    }
}
