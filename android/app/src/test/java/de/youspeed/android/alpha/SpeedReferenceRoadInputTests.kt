package de.youspeed.android.alpha

import org.junit.Assert.*
import org.junit.Test

class SpeedReferenceRoadInputTests {
    private fun direction(speed: Double? = 10.0, bearing: Double? = 90.0,
        bearingAccuracy: Double? = 5.0, accuracy: Double? = 5.0, age: Long = 0) =
        SpeedReferenceRoadInput.direction(TrafficSignTravelDirection.REVERSE,
            speed, bearing, bearingAccuracy, accuracy, 10_000, 10_000 + age)

    @Test fun stoppedDisplacementAndUnreliableCoursesCannotClaimAReversal() {
        for (speed in listOf(null, 0.0, 0.99, Double.NaN)) assertEquals(TrafficSignTravelDirection.UNKNOWN, direction(speed = speed))
        for (bearing in listOf(null, -1.0, 360.0, Double.NaN)) assertEquals(TrafficSignTravelDirection.UNKNOWN, direction(bearing = bearing))
        for (uncertainty in listOf(null, -1.0, 25.01, Double.POSITIVE_INFINITY)) assertEquals(TrafficSignTravelDirection.UNKNOWN, direction(bearingAccuracy = uncertainty))
        for (accuracy in listOf(null, -1.0, 20.01, Double.NaN)) assertEquals(TrafficSignTravelDirection.UNKNOWN, direction(accuracy = accuracy))
        for (age in listOf(-1L, 1501L)) assertEquals(TrafficSignTravelDirection.UNKNOWN, direction(age = age))
    }

    @Test fun freshMeasuredMovingCourseRetainsDirectionIncludingExistingReliabilityBounds() {
        assertEquals(TrafficSignTravelDirection.REVERSE, direction())
        assertEquals(TrafficSignTravelDirection.REVERSE, direction(speed = 1.0, bearing = 0.0,
            bearingAccuracy = 25.0, accuracy = 20.0, age = 1500))
    }

    @Test fun matchStatusUsesAuthoritativeReferenceRatherThanRawMapValue() {
        val old = EffectiveSpeedLimit(TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.NUMERIC, 50),
            EffectiveSpeedLimitSource.LAST_KNOWN, "reference_last_known_T06")
        assertEquals("matched_last_known", SpeedReferenceRoadInput.lookupStatus("current-road", old))
        assertEquals("matched_unlimited", SpeedReferenceRoadInput.lookupStatus("current-road",
            EffectiveSpeedLimit(TrafficSignResolvedLimit(TrafficSignResolvedLimitKind.UNLIMITED), EffectiveSpeedLimitSource.BUNDLE, "reference_bundle_T04")))
        assertEquals("matched_no_speed", SpeedReferenceRoadInput.lookupStatus("current-road", EffectiveSpeedLimit(null, EffectiveSpeedLimitSource.NONE, "unknown")))
        assertEquals("no_match", SpeedReferenceRoadInput.lookupStatus(null, EffectiveSpeedLimit(null, EffectiveSpeedLimitSource.NONE, "unknown")))
    }
}
