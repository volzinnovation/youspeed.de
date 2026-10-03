package de.youspeed.android.alpha

import org.junit.Assert.*
import org.junit.Test

class BundleMatcherHistoryTests {
    private val france = BundleRouteIdentity("alsace.sqlite", "v1", "FRA", "a".repeat(64))
    private val germany = BundleRouteIdentity("baden-wuerttemberg.sqlite", "v1", "DEU", "b".repeat(64))

    @Test
    fun crossingEitherDirectionStartsTheNewMapWithoutRoadRefOrTunnelHistory() {
        val tracker = WayMatchSessionTracker()
        tracker.selectBundle(france)
        record(tracker, "fr-road", "A 35")
        record(tracker, "fr-road", "A 35")
        val frenchContext = requireNotNull(tracker.snapshotOrNull())
        assertEquals(2, frenchContext.matchedFixCount)
        assertEquals("A 35", frenchContext.activeStreetRef)
        assertTrue(frenchContext.isInMotorwayMode)
        assertTrue(frenchContext.recentTunnelCandidateWayIds.isNotEmpty())
        assertTrue(frenchContext.recentFixes.isNotEmpty())

        tracker.selectBundle(germany)
        assertNull("First German query must receive no French continuity", tracker.snapshotOrNull())
        record(tracker, "de-road", "B 500")
        val germanContext = requireNotNull(tracker.snapshotOrNull())
        assertEquals(1, germanContext.matchedFixCount)
        assertEquals(listOf("de-road"), germanContext.recentWayHistory)
        assertEquals(listOf("B 500"), germanContext.recentStreetRefs)

        tracker.selectBundle(france)
        assertNull("Returning to France must not restore either map's prior history", tracker.snapshotOrNull())
    }

    @Test
    fun repeatedFixesKeepContinuityButSameCountryRegionAndDatabaseRevisionChangesResetIt() {
        val tracker = WayMatchSessionTracker()
        tracker.selectBundle(germany)
        record(tracker, "de-road", "B 500")
        val previous = tracker.snapshotOrNull()
        tracker.selectBundle(germany.copy(dbSha256 = null))
        assertEquals("Unknown digest is not a different bundle", previous, tracker.snapshotOrNull())
        tracker.selectBundle(germany)
        assertEquals(previous, tracker.snapshotOrNull())

        for (next in listOf(germany.copy(dbPath = "rheinland-pfalz.sqlite"),
            germany.copy(bundleVersion = "v2"), germany.copy(dbSha256 = "c".repeat(64)))) {
            tracker.selectBundle(next)
            assertNull(tracker.snapshotOrNull())
            record(tracker, "new-road", "B 1")
            tracker.selectBundle(germany)
            assertNull(tracker.snapshotOrNull())
            record(tracker, "de-road", "B 500")
        }
        tracker.reset()
        tracker.selectBundle(germany)
        assertNull("Start/stop or no coverage clears the current bundle's history", tracker.snapshotOrNull())
    }

    private fun record(tracker: WayMatchSessionTracker, way: String, ref: String) {
        tracker.record(result(way, ref), 48.8, 8.1, 5.0, 4, 90.0, 60.0)
    }

    private fun result(way: String, ref: String) = SpeedLookupResult(
        wayId = way, highway = "motorway", streetName = ref, streetBaseName = ref, streetRef = ref,
        speedLimitKmh = 100, isUnlimitedSpeedLimit = false, cityName = null, cityPlaceName = null,
        cityDistrictName = null, insideCity = false, citySource = null, queryTimeMs = 1.0,
        candidateCount = 1, speedCandidateCount = 1, candidateTraces = emptyList(),
        nearestCandidateDistanceM = 1.0, nearestSpeedCandidateDistanceM = 1.0, isTunnelSegment = false,
        matchedEndpointProximityM = 5.0, streetRefTokens = listOf(ref),
        nearbyTunnelCandidateWayIds = setOf("$way-tunnel"), nearbyTunnelCandidateRefs = setOf(ref),
        portalEligibleTunnelWayIds = setOf("$way-tunnel"), portalEligibleTunnelRefs = setOf(ref),
        activeCorridorState = null, approachCorridorStateCandidate = null, usedWalkingTurnSwitch = false,
        usedMiniHMM = false, miniHMMCandidateCount = 0, matchHypotheses = emptyList(), selectionTrace = emptyList(),
    )
}
