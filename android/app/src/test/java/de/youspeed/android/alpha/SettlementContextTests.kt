package de.youspeed.android.alpha

import org.junit.Assert.*
import org.junit.Test

class SettlementContextTests {
    private val point = SettlementPoint(49.0, 8.0)
    private val east = listOf(SettlementPoint(49.0, 7.999), SettlementPoint(49.0, 8.001))
    private fun segment(inside: Boolean?, direction: Int = 0, confidence: String = "high", points: List<SettlementPoint> = east) =
        SettlementSegment(direction, SettlementContext(inside, "zone_traffic", confidence), points)

    @Test fun directionalContextRequiresReliableHeadingOrAgreement() {
        val segments = listOf(segment(true, 1), segment(false, -1))
        assertEquals(true, SettlementContextPolicy.resolve(segments, point, 90.0).insideCity)
        assertEquals(false, SettlementContextPolicy.resolve(segments, point, 270.0).insideCity)
        assertEquals("settlement:conflict:unknown", SettlementContextPolicy.resolve(segments, point, null).citySource)
        assertNull(SettlementContextPolicy.resolve(segments, point, 0.0).insideCity)
        assertNull(SettlementContextPolicy.resolve(listOf(segment(true, 1)), point, null).insideCity)
        assertEquals(true, SettlementContextPolicy.resolve(listOf(segment(true, 1), segment(true, -1)), point, null).insideCity)
        assertNull(SettlementContextPolicy.reliableHeading(90.0, 30.0, null))
        assertNull(SettlementContextPolicy.reliableHeading(90.0, 3.0, 5.0))
        assertNull(SettlementContextPolicy.reliableHeading(90.0, null, 5.0))
        assertNull(SettlementContextPolicy.reliableHeading(90.0, 30.0, 46.0))
        assertEquals(90.0, SettlementContextPolicy.reliableHeading(90.0, 30.0, 5.0))
    }

    @Test fun sharedEndpointConflictAndMissingDirectionNeverSelectDistantEvidence() {
        val before = listOf(east.first(), point)
        val after = listOf(point, east.last())
        assertNull(SettlementContextPolicy.resolve(listOf(segment(false, points = before), segment(true, points = after)), point, 90.0).insideCity)
        val distant = listOf(SettlementPoint(49.001, 7.999), SettlementPoint(49.001, 8.001))
        assertNull(SettlementContextPolicy.resolve(listOf(segment(true, 1), segment(false, -1, points = distant)), point, 270.0).insideCity)
    }

    @Test fun curvedGeometryUsesLocalDirectionAndDegenerateEdgesDoNotOverrideIt() {
        val bent = listOf(SettlementPoint(48.999, 8.0), point, point, SettlementPoint(49.0, 8.001))
        val eastPoint = SettlementPoint(49.0, 8.0005)
        assertEquals(true, SettlementContextPolicy.resolve(listOf(segment(true, 1, points = bent), segment(false, -1, points = bent)), eastPoint, 90.0).insideCity)
        assertNull(SettlementContextPolicy.resolve(listOf(segment(true, points = listOf(point, point))), point, 90.0).insideCity)
    }

    @Test fun explicitSemanticsRemainIndependentOfNumericSpeed() {
        assertEquals(false, SettlementContextPolicy.legacy(listOf("maxspeed" to "30", "source_maxspeed" to "DE:rural"))?.insideCity)
        assertEquals(true, SettlementContextPolicy.legacy(listOf("maxspeed" to "70", "maxspeed_type" to "DE:urban"))?.insideCity)
        assertNull(SettlementContextPolicy.legacy(listOf("maxspeed" to "30", "maxspeed_type" to "DE:zone30")))
        assertEquals("conflict", SettlementContextPolicy.legacy(listOf("maxspeed_type" to "DE:rural", "source_maxspeed" to "DE:urban"))?.source)
        assertNull(SettlementContextPolicy.resolve(listOf(segment(null, confidence = "unknown")), point, 90.0).insideCity)
        assertNull(SettlementContextPolicy.resolve(listOf(segment(true).copy(context = SettlementContext(true, "unsupported", "high"))), point, 90.0).insideCity)
    }

    @Test fun cityEntryInvalidatesOnFirstHighConfirmationIncludingConfidenceUpgrade() {
        val high = "settlement:traffic_sign:high"
        val low = "settlement:landuse:low"
        assertFalse(TrafficSignBundleContextPolicy.enteredCity(false, true, high, low))
        assertTrue(TrafficSignBundleContextPolicy.enteredCity(true, true, low, high))
        assertTrue(TrafficSignBundleContextPolicy.enteredCity(null, true, null, high))
        assertTrue(TrafficSignBundleContextPolicy.enteredCity(false, true, high, high))
        assertFalse(TrafficSignBundleContextPolicy.enteredCity(true, true, high, high))
        assertFalse(TrafficSignBundleContextPolicy.enteredCity(false, true, high, "admin_polygon"))
        assertEquals(
            TrafficSignBundleContextTransition.EXITED_CITY,
            TrafficSignBundleContextPolicy.transition(true, false, high, high),
        )
        assertEquals(
            TrafficSignBundleContextTransition.NONE,
            TrafficSignBundleContextPolicy.transition(true, false, high, "settlement:landuse:low"),
        )
    }

    @Test fun appVersionComparisonAndManifestSchemaAreEnforced() {
        assertTrue(BundleAppVersion.isAtLeast("1.1", "1.1.0"))
        assertTrue(BundleAppVersion.isAtLeast("1.10", "1.2"))
        assertFalse(BundleAppVersion.isAtLeast("1.1", "1.2"))
        assertFalse(BundleAppVersion.isAtLeast("1.1.0-beta.2", "1.1.0"))
        assertTrue(BundleAppVersion.isAtLeast("1.1.0-beta.10", "1.1.0-beta.2"))
        assertTrue(BundleAppVersion.isAtLeast("1.1.0+build.1", "1.1"))
        assertFalse(BundleAppVersion.isAtLeast("1.1", "invalid"))
        assertFalse(BundleAppVersion.isAtLeast("invalid", "1.1"))
        val manifest = V3BundleManifest("youspeed.v3.bundle.manifest", 1, "v3", "test", "DEU", "test", "", "1.1",
            BundleArtifact("test.sqlite", 1, "", null), null, null, null, null)
        manifest.validateLaunchContract("1.1")
        assertTrue(runCatching { manifest.copy(schemaVersion = 2).validateLaunchContract("1.1") }.isFailure)
        assertTrue(runCatching { manifest.copy(minAppVersion = "1.2").validateLaunchContract("1.1") }.isFailure)
    }
}
