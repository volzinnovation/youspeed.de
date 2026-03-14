package de.youspeed.android.alpha

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class V3SpeedLimitLookupTests {
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
    fun germanBelow50SpeedLimitImpliesInsideCity() {
        assertTrue(V3SpeedLimitLookup.germanLowSpeedLimitImpliesInsideCity(countryCode = "DEU", speedKmh = 30))
        assertFalse(V3SpeedLimitLookup.germanLowSpeedLimitImpliesInsideCity(countryCode = "DEU", speedKmh = 50))
        assertFalse(V3SpeedLimitLookup.germanLowSpeedLimitImpliesInsideCity(countryCode = "NLD", speedKmh = 30))
    }

    @Test
    fun derivesFallbackHighwayClassValuesLikeIphone() {
        assertEquals(10, V3SpeedLimitLookup.deriveSpeedLimitKmh(null, null, null, "living_street"))
        assertEquals(50, V3SpeedLimitLookup.deriveSpeedLimitKmh(null, null, null, "residential"))
        assertEquals(100, V3SpeedLimitLookup.deriveSpeedLimitKmh(null, null, null, "trunk"))
        assertNull(V3SpeedLimitLookup.deriveSpeedLimitKmh(null, null, null, "motorway"))
    }
}
