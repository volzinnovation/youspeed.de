package de.youspeed.android.alpha

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class V3SpeedLimitLookupTests {
    @Test
    fun combinedPolylineMetricsPreserveDistanceHeadingAndProgressThroughBends() {
        val points = listOf(LatLonPoint(0.0, 0.0), LatLonPoint(0.01, 0.0), LatLonPoint(0.01, 0.01))
        // Frozen outputs of the previous independent distance/heading/progress traversals.
        val cases = listOf(
            Triple(LatLonPoint(0.005, 0.003), "first segment",
                PolylineMetrics(333.9599987283746, 555.9754011676646, 1667.9261865670146, 0.0)),
            Triple(LatLonPoint(0.009, 0.007), "second segment",
                PolylineMetrics(111.1320000000001, 1890.316352114874, 333.5852356198052, 89.9999991273354)),
            Triple(LatLonPoint(0.01, 0.0), "equal-distance bend keeps first segment heading",
                PolylineMetrics(0.0, 1111.9508023353292, 1111.95078539935, 0.0)),
            Triple(LatLonPoint(-0.002, 0.0), "before start",
                PolylineMetrics(222.264, 0.0, 2223.901587734679, 0.0)),
            Triple(LatLonPoint(0.01, 0.012), "after end",
                PolylineMetrics(222.6399966089989, 2223.901587734679, 0.0, 89.9999991273354)),
        )
        for ((query, label, expected) in cases) {
            val actual = requireNotNull(V3SpeedLimitLookup.polylineMetrics(query.lat, query.lon, points))
            assertEquals("$label distance", requireNotNull(expected.distanceM), requireNotNull(actual.distanceM), 1e-9)
            assertEquals("$label start progress", expected.distanceToStartM, actual.distanceToStartM, 1e-9)
            assertEquals("$label end progress", expected.distanceToEndM, actual.distanceToEndM, 1e-9)
            assertEquals("$label heading", requireNotNull(expected.localHeadingDeg), requireNotNull(actual.localHeadingDeg), 1e-9)
        }
    }

    @Test
    fun combinedPolylineMetricsKeepEmptySinglePointAndDegenerateGeometryBehavior() {
        assertNull(V3SpeedLimitLookup.polylineMetrics(0.0, 0.0, emptyList()))
        val single = requireNotNull(V3SpeedLimitLookup.polylineMetrics(48.801, 8.4, listOf(LatLonPoint(48.8, 8.4))))
        assertEquals(111.19508023406384, requireNotNull(single.distanceM), 1e-9)
        assertEquals(0.0, single.distanceToStartM, 0.0)
        assertEquals(0.0, single.distanceToEndM, 0.0)
        assertNull(single.localHeadingDeg)

        val repeatedStart = requireNotNull(V3SpeedLimitLookup.polylineMetrics(0.0, 0.0,
            listOf(LatLonPoint(0.0, 0.0), LatLonPoint(0.0, 0.0), LatLonPoint(0.01, 0.0))))
        assertEquals(0.0, requireNotNull(repeatedStart.distanceM), 0.0)
        assertEquals(0.0, repeatedStart.distanceToStartM, 0.0)
        assertEquals(1111.9508023353292, repeatedStart.distanceToEndM, 1e-9)
        assertNull("A tied later segment must not replace the degenerate first segment's heading", repeatedStart.localHeadingDeg)

        val invalid = requireNotNull(V3SpeedLimitLookup.polylineMetrics(0.0, 0.0,
            listOf(LatLonPoint(Double.NaN, 0.0), LatLonPoint(0.0, 0.0))))
        assertNull("Unavailable geometry must still use the bounding-box distance fallback", invalid.distanceM)
        assertEquals(0.0, invalid.distanceToStartM, 0.0)
        assertTrue(invalid.distanceToEndM.isNaN())
        assertNull(invalid.localHeadingDeg)
    }

    @Test
    fun computesAxisHeadingWithoutRecursing() {
        val northbound = V3SpeedLimitLookup.computeAxisHeadingDegOrNull(
            lat1 = 48.7990507,
            lon1 = 8.4382557,
            lat2 = 48.8090507,
            lon2 = 8.4382557,
        )
        val eastbound = V3SpeedLimitLookup.computeAxisHeadingDegOrNull(
            lat1 = 48.7990507,
            lon1 = 8.4382557,
            lat2 = 48.7990507,
            lon2 = 8.4482557,
        )

        assertEquals(0.0, northbound ?: Double.NaN, 0.5)
        assertEquals(90.0, eastbound ?: Double.NaN, 0.5)
        assertNull(
            V3SpeedLimitLookup.computeAxisHeadingDegOrNull(
                lat1 = 48.7990507,
                lon1 = 8.4382557,
                lat2 = 48.7990507,
                lon2 = 8.4382557,
            ),
        )
    }

    @Test
    fun derivesUnlimitedMotorwayFromExplicitNoneTag() {
        val derived = V3SpeedLimitLookup.deriveSpeedLimitWithSource(
            maxspeed = "none",
            maxspeedType = null,
            sourceMaxspeed = null,
            highway = "motorway",
        )

        assertNull(derived.speed)
        assertTrue(derived.isUnlimited)
        assertEquals(DerivedSpeedSource.EXPLICIT_UNLIMITED_TAG, derived.source)
    }

    @Test
    fun derivesInheritedGermanUrbanAndRuralDefaults() {
        val urban = V3SpeedLimitLookup.deriveSpeedLimitWithSource(
            maxspeed = null,
            maxspeedType = "DE:urban",
            sourceMaxspeed = null,
            highway = "secondary",
        )
        val rural = V3SpeedLimitLookup.deriveSpeedLimitWithSource(
            maxspeed = null,
            maxspeedType = null,
            sourceMaxspeed = "DE:rural",
            highway = "secondary",
        )

        assertEquals(50, urban.speed)
        assertEquals(DerivedSpeedSource.INHERITED_TAG, urban.source)
        assertEquals(100, rural.speed)
        assertEquals(DerivedSpeedSource.INHERITED_TAG, rural.source)
    }

    @Test
    fun derivesFallbackHighwayClassValuesLikeIphone() {
        assertEquals(10, V3SpeedLimitLookup.deriveSpeedLimitKmh(null, null, null, "living_street"))
        assertEquals(50, V3SpeedLimitLookup.deriveSpeedLimitKmh(null, null, null, "residential"))
        assertEquals(50, V3SpeedLimitLookup.deriveSpeedLimitKmh(null, null, null, "service"))
        assertEquals(100, V3SpeedLimitLookup.deriveSpeedLimitKmh(null, null, null, "trunk"))
        assertNull(V3SpeedLimitLookup.deriveSpeedLimitKmh(null, null, null, "motorway"))
    }
}
