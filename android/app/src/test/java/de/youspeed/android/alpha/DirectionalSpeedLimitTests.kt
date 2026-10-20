package de.youspeed.android.alpha

import org.junit.Assert.*
import org.junit.Test

class DirectionalSpeedLimitTests {
    private fun derive(forward: String?, backward: String?, heading: Double? = 90.0, tangent: Double? = 90.0,
        base: String? = null, speed: Double? = 30.0, accuracy: Double? = 5.0) =
        V3SpeedLimitLookup.deriveDirectionalSpeedLimitWithSource(base, null, null, "secondary", "DE",
            forward, backward, SettlementContextPolicy.reliableHeading(heading, speed, accuracy), tangent)

    @Test fun sourceWaysResolveTheirExplicitLimitsInBothOsmDirections() {
        for ((forward, backward) in listOf("30" to "50", "100" to "70", "70" to "100")) {
            assertEquals(DerivedSpeedResult(forward.toInt(), DerivedSpeedSource.EXPLICIT_TAG, false), derive(forward, backward))
            assertEquals(DerivedSpeedResult(backward.toInt(), DerivedSpeedSource.EXPLICIT_TAG, false), derive(forward, backward, heading = 270.0))
        }
        assertEquals(50, derive("30", "50", heading = 90.0, tangent = 270.0).speed)
        assertEquals(30, derive("30", "50", heading = 270.0, tangent = 270.0).speed)
    }

    @Test fun missingUnreliableOrCrossRoadCourseDoesNotChooseADirectionalLimit() {
        val unavailable = DerivedSpeedSource.DIRECTIONAL_UNRESOLVED
        for (heading in listOf(null, -1.0, 360.0, Double.NaN, 0.0, 180.0)) assertEquals(unavailable, derive("30", "50", heading = heading).source)
        for (speed in listOf(null, 0.0, 7.99, Double.NaN)) assertEquals(unavailable, derive("30", "50", speed = speed).source)
        for (accuracy in listOf(null, -1.0, 45.01, Double.POSITIVE_INFINITY)) assertEquals(unavailable, derive("30", "50", accuracy = accuracy).source)
        assertEquals(unavailable, derive("30", "50", tangent = null).source)
        assertEquals(30, derive("30", "50", heading = 45.0, speed = 8.0, accuracy = 45.0).speed)
        assertEquals(50, derive("30", "50", heading = 225.0).speed)
    }

    @Test fun localTangentAtABendRatherThanWholeWayBearingSelectsTheLimit() {
        val points = listOf(LatLonPoint(0.0, 0.0), LatLonPoint(0.0, .001), LatLonPoint(.001, .001))
        val east = V3SpeedLimitLookup.polylineMetrics(0.0, .0005, points)?.localHeadingDeg
        val north = V3SpeedLimitLookup.polylineMetrics(.0008, .001, points)?.localHeadingDeg
        assertEquals(100, derive("100", "70", heading = 90.0, tangent = east).speed)
        assertEquals(100, derive("100", "70", heading = 0.0, tangent = north).speed)
        assertEquals(70, derive("100", "70", heading = 180.0, tangent = north).speed)
        assertEquals(DerivedSpeedSource.DIRECTIONAL_UNRESOLVED, derive("100", "70", heading = 90.0, tangent = north).source)
    }

    @Test fun equalExplicitOutcomesAreSafeWithoutCourseButOneSidedDefaultsAreNotProof() {
        assertEquals(30, derive("30", "30 km/h", heading = null).speed)
        assertTrue(derive("none", "none", heading = null).isUnlimited)
        assertEquals(DerivedSpeedSource.DIRECTIONAL_UNRESOLVED, derive("30", null, heading = null).source)
        assertEquals(DerivedSpeedSource.DIRECTIONAL_UNRESOLVED, derive("30", null, heading = null, base = "50").source)
        assertEquals(50, derive("30", null, heading = 270.0, base = "50").speed)
        assertEquals(30, derive("30", null, heading = null, base = "30").speed)
    }

    @Test fun explicitUnlimitedAndUnsupportedDirectionalTagsDoNotBecomeDefaults() {
        assertTrue(derive("none", "70").isUnlimited)
        assertEquals(DerivedSpeedSource.EXPLICIT_UNLIMITED_TAG, derive("none", "70").source)
        assertEquals(70, derive("none", "70", heading = 270.0).speed)
        assertEquals(DerivedSpeedSource.DIRECTIONAL_UNRESOLVED, derive("none", "70", heading = null).source)
        assertEquals(DerivedSpeedSource.DIRECTIONAL_UNRESOLVED, derive("30 @ (wet)", "70", base = "50").source)
        assertEquals(70, derive("30 @ (wet)", "70", heading = 270.0, base = "50").speed)
    }

    @Test fun legacyColumnsAndRecognizedSymbolicEvidenceKeepExistingSourceSemantics() {
        assertEquals(V3SpeedLimitLookup.deriveSpeedLimitWithSource("50", null, null, "secondary"), derive(null, null, heading = null, base = "50"))
        assertEquals(V3SpeedLimitLookup.deriveSpeedLimitWithSource(null, null, null, "secondary"), derive(null, null, heading = null))
        assertEquals(DerivedSpeedResult(50, DerivedSpeedSource.INHERITED_TAG, false), derive("DE:urban", "DE:rural"))
        assertEquals(DerivedSpeedResult(100, DerivedSpeedSource.INHERITED_TAG, false), derive("DE:urban", "DE:rural", heading = 270.0))
        assertEquals(DerivedSpeedResult(50, DerivedSpeedSource.INHERITED_TAG, false), derive("DE:urban", "de:urban", heading = null))
    }
}
