package de.youspeed.android.alpha

import java.time.Instant
import java.time.OffsetDateTime
import org.junit.Assert.*
import org.junit.Test

class SolarDaylightTests {
    @Test fun numericalElevationsMatchIPhoneReference() {
        // Computed by the unchanged Swift SolarDaylight implementation.
        assertEquals(-0.306899070365, SolarDaylight.elevationDegrees(48.76, 8.34, Instant.parse("2026-10-18T16:30:00Z"))!!, 1e-9)
        assertEquals(12.425937130402, SolarDaylight.elevationDegrees(48.76, 8.34, Instant.parse("2026-06-21T18:00:00Z"))!!, 1e-9)
        assertEquals(63.255541280433, SolarDaylight.elevationDegrees(-33.87, 151.21, Instant.parse("2026-12-21T00:00:00Z"))!!, 1e-9)
        // Dropping the higher harmonics pauses the camera too early here.
        assertTrue(SolarDaylight.permitsCameraTSR(48.76, 8.34, Instant.parse("2026-10-18T16:32:00Z")))
    }
    @Test fun seasonsPolarRegionsLeapYearAndDateline() {
        assertEquals("2026-10-18T17:05:00Z", false, SolarDaylight.permitsCameraTSR(48.76, 8.34, Instant.parse("2026-10-18T17:05:00Z")))
        assertEquals("2026-06-21T18:00:00Z", true, SolarDaylight.permitsCameraTSR(48.76, 8.34, Instant.parse("2026-06-21T18:00:00Z")))
        assertEquals("2026-12-21T18:00:00Z", false, SolarDaylight.permitsCameraTSR(48.76, 8.34, Instant.parse("2026-12-21T18:00:00Z")))
        assertEquals("2026-06-21T00:00:00Z", true, SolarDaylight.permitsCameraTSR(78.22, 15.65, Instant.parse("2026-06-21T00:00:00Z")))
        assertEquals("2026-12-21T12:00:00Z", false, SolarDaylight.permitsCameraTSR(78.22, 15.65, Instant.parse("2026-12-21T12:00:00Z")))
        assertEquals("2026-12-21T00:00:00Z", true, SolarDaylight.permitsCameraTSR(-33.87, 151.21, Instant.parse("2026-12-21T00:00:00Z")))
        assertEquals("2026-12-21T12:00:00Z", false, SolarDaylight.permitsCameraTSR(-33.87, 151.21, Instant.parse("2026-12-21T12:00:00Z")))
        assertEquals("2024-02-29T12:00:00Z", true, SolarDaylight.permitsCameraTSR(0.0, 0.0, Instant.parse("2024-02-29T12:00:00Z")))
        assertEquals("2026-03-20T00:00:00Z", true, SolarDaylight.permitsCameraTSR(0.0, 180.0, Instant.parse("2026-03-20T00:00:00Z")))
        assertEquals("2026-03-20T12:00:00Z", false, SolarDaylight.permitsCameraTSR(0.0, -180.0, Instant.parse("2026-03-20T12:00:00Z")))
    }
    @Test fun dstAndTimezoneOffsetsDescribeAbsoluteInstants() {
        assertEquals(SolarDaylight.elevationDegrees(48.76, 8.34, OffsetDateTime.parse("2026-10-25T02:30:00+02:00").toInstant()), SolarDaylight.elevationDegrees(48.76, 8.34, Instant.parse("2026-10-25T00:30:00Z")))
        assertEquals(SolarDaylight.elevationDegrees(48.76, 8.34, OffsetDateTime.parse("2026-10-25T02:30:00+01:00").toInstant()), SolarDaylight.elevationDegrees(48.76, 8.34, Instant.parse("2026-10-25T01:30:00Z")))
        assertEquals(SolarDaylight.elevationDegrees(48.76, 8.34, OffsetDateTime.parse("2026-03-29T03:30:00+02:00").toInstant()), SolarDaylight.elevationDegrees(48.76, 8.34, Instant.parse("2026-03-29T01:30:00Z")))
        assertEquals(SolarDaylight.elevationDegrees(48.76, 8.34, OffsetDateTime.parse("2026-07-01T12:00:00+05:30").toInstant()), SolarDaylight.elevationDegrees(48.76, 8.34, Instant.parse("2026-07-01T06:30:00Z")))
    }
    @Test fun missingAndInvalidLocationPausesCamera() {
        for ((lat, lon) in listOf(null to 8.0, 49.0 to null, Double.NaN to 8.0, 91.0 to 8.0, 49.0 to 181.0, 49.0 to Double.POSITIVE_INFINITY)) {
            assertFalse(SolarDaylight.permitsCameraTSR(lat, lon, Instant.parse("2026-10-18T12:00:00Z")))
        }
    }
}
