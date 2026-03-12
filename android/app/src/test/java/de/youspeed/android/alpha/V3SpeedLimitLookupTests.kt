package de.youspeed.android.alpha

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class V3SpeedLimitLookupTests {
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
        assertEquals(100, V3SpeedLimitLookup.deriveSpeedLimitKmh(null, null, null, "trunk"))
        assertNull(V3SpeedLimitLookup.deriveSpeedLimitKmh(null, null, null, "motorway"))
    }
}
