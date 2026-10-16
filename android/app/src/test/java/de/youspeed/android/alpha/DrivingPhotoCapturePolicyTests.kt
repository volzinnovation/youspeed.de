package de.youspeed.android.alpha

import java.time.Instant
import org.junit.Assert.*
import org.junit.Test

class DrivingPhotoCapturePolicyTests {
    private val now = Instant.parse("2026-10-10T12:00:00Z")
    private val sample = PanoramaxLocationSample(48.0, 8.0, now, 5.0)
    private fun ready(speed: Double = 30.0, session: Boolean = true, camera: Boolean = true,
        output: Boolean = true, batch: Boolean = true, storage: Boolean = true, inFlight: Boolean = false,
        location: PanoramaxLocationSample? = sample, previous: Instant? = null) = DrivingPhotoCapturePolicy.isReady(
        speed, session, camera, output, batch, storage, inFlight, location, now, previous)

    @Test fun strictOneKmhThresholdDoesNotChangeOrdinaryFourKmhSafetyPolicy() {
        for (speed in listOf(-1.0, 0.0, 0.99, 1.0, Double.NaN, Double.POSITIVE_INFINITY)) {
            assertFalse("Hidden at $speed", DrivingPhotoCapturePolicy.isVisible(speed))
            assertFalse(ready(speed = speed))
        }
        for (speed in listOf(1.001, 1.5, 3.99, 4.0, 100.0)) {
            assertTrue(DrivingPhotoCapturePolicy.isVisible(speed))
            assertTrue(ready(speed = speed))
        }
        assertEquals(4.0, DrivingInteractionMotionPolicy.CONTROLS_SPEED_THRESHOLD_KMH, 0.0)
        assertFalse("Automatic minimum speed stays unchanged", PanoramaxCapturePolicy.isMoving(1.5 / 3.6))
    }

    @Test fun readinessRequiresEveryCaptureResourceAndNoConcurrentPhoto() {
        assertTrue(ready())
        assertFalse(ready(session = false))
        assertFalse(ready(camera = false))
        assertFalse(ready(output = false))
        assertFalse(ready(batch = false))
        assertFalse(ready(storage = false))
        assertFalse(ready(inFlight = true))
        assertFalse(ready(location = null))
    }

    @Test fun locationMustBeFreshAccurateAndGeographicallyValid() {
        assertTrue(ready(location = sample.copy(capturedAt = now.minusSeconds(10))))
        assertFalse(ready(location = sample.copy(capturedAt = now.minusMillis(10_001))))
        assertFalse(ready(location = sample.copy(capturedAt = now.plusSeconds(61))))
        for (accuracy in listOf(-1.0, 50.01, Double.NaN, Double.POSITIVE_INFINITY))
            assertFalse(ready(location = sample.copy(accuracyMeters = accuracy)))
        assertTrue(ready(location = sample.copy(accuracyMeters = 50.0)))
        for (latitude in listOf(-90.01, 90.01, Double.NaN))
            assertFalse(ready(location = sample.copy(latitude = latitude)))
        for (longitude in listOf(-180.01, 180.01, Double.POSITIVE_INFINITY))
            assertFalse(ready(location = sample.copy(longitude = longitude)))
    }

    @Test fun completedOrFailedFastCapturesStillDebounceRepeatedTaps() {
        assertFalse(ready(previous = now))
        assertFalse(ready(previous = now.minusMillis(499)))
        assertTrue(ready(previous = now.minusMillis(500)))
        assertFalse(ready(previous = now.plusMillis(1)))
    }

    @Test fun manualRequestIgnoresAutomaticCadenceButNotReadiness() {
        assertFalse(PanoramaxCapturePolicy.shouldCapture(sample, sample, now))
        assertTrue(ready(location = sample))
        assertFalse(ready(location = sample, inFlight = true))
    }
}
