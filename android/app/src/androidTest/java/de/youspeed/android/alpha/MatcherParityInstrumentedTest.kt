package de.youspeed.android.alpha

import android.database.sqlite.SQLiteDatabase
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.util.UUID
import org.junit.Assert.*
import org.junit.Test

/** These are the same geometry and expected decisions as SpeedConsumerTests on iPhone. */
class MatcherParityInstrumentedTest {
    @Test fun defaultM7RejectsTunnelUnderNearbySurfaceWithoutEntryEvidence() = fixture("crossing-tunnel.sql") { file ->
        V3SpeedLimitLookup(file.path, matchingModel = MatcherDebugProfile.M7.lookupModel).use { lookup ->
            val result = lookup.lookup(52.0, 13.00505, 80.0, 32, 90.0, 20.0, 5.0)
            assertEquals("1002", result.wayId)
            assertEquals(50, result.speedLimitKmh)
            assertFalse(result.isTunnelSegment)
            assertTrue(result.selectionTrace.any { it.step == "simple_tunnel_selectability_gate" })
        }
    }

    @Test fun defaultM7ReleasesSameRefForLinkedLowSpeedTurn() = fixture("straight-linked.sql") { file ->
        val turn = context()
        V3SpeedLimitLookup(file.path, matchingModel = MatcherDebugProfile.M7.lookupModel).use { lookup ->
            val result = lookup.lookup(52.06001, 13.00413, 45.0, 32, null, 23.0, 6.0, matchContext = turn)
            assertEquals(result.selectionTrace.toString(), "12003", result.wayId)
            assertTrue(result.selectionTrace.any { it.step == "simple_low_speed_same_ref_junction_release" })
            val straight = lookup.lookup(52.06001, 13.00413, 45.0, 32, null, 23.0, 6.0,
                matchContext = turn.copy(recentFixes = listOf(WayMatchRecentFix(52.06000, 13.00400))))
            assertEquals("12002", straight.wayId)
        }
    }

    @Test fun m10UsesJunctionHeadingOnCurvedTurn() = fixture("curved-linked.sql") { file ->
        val m9 = lookup(file, MatcherDebugProfile.M9, context())
        val m10 = lookup(file, MatcherDebugProfile.M10, context())
        assertEquals("12002", m9.wayId)
        assertEquals(m10.selectionTrace.toString(), "12003", m10.wayId)
        assertTrue(m10.selectionTrace.any { it.step == "simple_low_speed_same_ref_junction_release" && "12001" in it.detail })
    }

    @Test fun m10ReportsBlockedTurnEvidence() = fixture("curved-linked.sql") { file ->
        V3SpeedLimitLookup(file.path, matchingModel = MatcherDebugProfile.M10.lookupModel).use { service ->
            val result = service.lookup(52.06000, 13.00392, 45.0, 32, 90.0, 23.0, 6.0,
                matchContext = WayMatchContext(preferredWayId = "12001", recentWayIds = listOf("12001"),
                    preferredStreetRef = "B463", activeStreetRef = "B463", recentStreetRefs = listOf("B463")))
            assertEquals("12001", result.wayId)
            val probe = result.selectionTrace.first { it.step == "simple_low_speed_same_ref_probe" }.detail
            assertTrue(probe.contains("candidate=12003"))
            assertTrue(probe.contains("blocked="))
            assertTrue(probe.contains("candidate_geometry_rank="))
            assertTrue(probe.contains("candidate_trace_rank="))
        }
    }

    @Test fun defaultM7UsesPortalEvidenceAndKeepsTunnelAfterGpsRecovery() = fixture("ambiguous-tunnel.sql") { file ->
        val base = WayMatchContext(preferredWayId = "7101", preferredHighway = "primary", preferredEndpointProximityM = 0.0,
            recentWayIds = listOf("7101"), preferredStreetRef = "B 10", recentStreetRefs = listOf("B 10"),
            recentTunnelCandidateWayIds = setOf("7102"), recentTunnelCandidateRefs = setOf("B 10"))
        V3SpeedLimitLookup(file.path, matchingModel = MatcherDebugProfile.M7.lookupModel).use { service ->
            val surface = service.lookup(52.01007, 13.00105, 80.0, 32, 90.0, 30.0, 5.0, 4, base)
            assertEquals("7103", surface.wayId)
            assertFalse(surface.isTunnelSegment)
            val approach = base.copy(recentTunnelApproachWayIds = setOf("7102"), recentTunnelApproachRefs = setOf("B 10"),
                tunnelApproachFixCount = 3, tunnelApproachBaselineAccuracyM = 5.0, tunnelApproachBaselineSignalBars = 4)
            val entry = service.lookup(52.01007, 13.00105, 80.0, 32, 90.0, 30.0, 16.0, 2, approach)
            assertEquals(entry.selectionTrace.toString(), "7102", entry.wayId)
            assertTrue(entry.isTunnelSegment)
            assertTrue(entry.selectionTrace.any { it.step == "tunnel_entry_gate" })
            val recovery = base.copy(preferredWayId = "7102", preferredEndpointProximityM = 18.0,
                recentWayIds = listOf("7102", "7101"), activeStreetRef = "B 10", isInTunnelMode = true)
            val held = service.lookup(52.01007, 13.00105, 80.0, 32, 90.0, 28.0, 5.0, 4, recovery)
            assertEquals(held.selectionTrace.toString(), "7102", held.wayId)
            assertTrue(held.isTunnelSegment)
            assertTrue(held.selectionTrace.any { it.step == "tunnel_exit_gate" })
        }
    }

    @Test fun defaultM7RejectsMiddleTunnelEntryAndKeepsTunnelWithWeakGps() = fixture("tunnel-transition.sql") { file ->
        val approach = WayMatchContext(preferredWayId = "7001", preferredHighway = "primary", preferredEndpointProximityM = 0.0,
            recentWayIds = listOf("7001"), preferredStreetRef = "B 10", recentStreetRefs = listOf("B 10"))
        V3SpeedLimitLookup(file.path, matchingModel = MatcherDebugProfile.M7.lookupModel).use { service ->
            val entry = service.lookup(52.0, 13.0010, 80.0, 32, 90.0, 20.0, 5.0, matchContext = approach)
            assertEquals("7002", entry.wayId)
            val middle = service.lookup(52.0, 13.0015, 80.0, 32, 90.0, 20.0, 5.0, matchContext = approach)
            assertNotEquals("7002", middle.wayId)
            assertFalse(middle.isTunnelSegment)
            val held = service.lookup(52.0, 13.0016, 80.0, 32, 90.0, 20.0, 18.0,
                matchContext = approach.copy(preferredWayId = "7002", preferredEndpointProximityM = 22.0,
                    recentWayIds = listOf("7002"), recentTunnelCandidateWayIds = setOf("7002"),
                    recentTunnelCandidateRefs = setOf("B 10"), isInTunnelMode = true))
            assertEquals("7002", held.wayId)
            assertTrue(held.isTunnelSegment)
        }
    }

    @Test fun m11UsesParticleMotionHeadingWithoutWayLinks() = fixture("curved-unlinked.sql") { file ->
        assertEquals("12002", lookup(file, MatcherDebugProfile.M10, context()).wayId)
        val result = lookup(file, MatcherDebugProfile.M11, context())
        assertEquals(result.selectionTrace.toString(), "12003", result.wayId)
        assertTrue(result.selectionTrace.any { it.step == "simple_sequence_particle_switch" })
        assertTrue(result.matchHypotheses.any { it.wayId == "12003" })
    }

    @Test fun m12UsesNineHistoricalFixesAndGraphWithoutWayLinks() = fixture("curved-unlinked.sql") { file ->
        val history = (0..8).map { i -> WayMatchRecentFix(52.05996 - i * 0.00004, 13.00407 - i * 0.00007,
            38.0 + i, 5.0, 23.0, 6.0, 4) }
        V3SpeedLimitLookup(file.path, matchingModel = MatcherDebugProfile.M12.lookupModel).use { service ->
            val result = service.lookup(52.06006, 13.00412, 45.0, 32, 46.0, 23.0, 6.0, 4, context().copy(recentFixes = history))
            assertEquals(result.selectionTrace.toString(), "12003", result.wayId)
            assertTrue(result.selectionTrace.any { it.step == "simple_sequence_viterbi_seed" && "history_fixes=9" in it.detail && "graph_available=true" in it.detail })
            assertTrue(result.selectionTrace.any { it.step == "simple_sequence_viterbi" && "best_viterbi=12003" in it.detail })
        }
    }

    @Test fun m12UsesRouteRelationAndSameStreetHistoryWithoutDirectLinks() = fixture("continuity-unlinked.sql") { file ->
        V3SpeedLimitLookup(file.path, matchingModel = MatcherDebugProfile.M12.lookupModel).use { service ->
            data class Case(val queryLat: Double, val preferred: String, val expected: String, val nearest: String)
            for ((queryLat, preferred, expected, nearest) in listOf(
                Case(52.00000, "5001", "5002", "5003"), Case(52.01006, "6001", "6002", "6003"))) {
                val route = preferred == "5001"
                val speed = if (route) 38.0 else 34.0
                assertEquals(nearest, service.lookup(queryLat, 13.00480, 40.0, 32, 90.0, speed, 5.0).wayId)
                val history = listOf(13.00360, 13.00320, 13.00280, 13.00240).map {
                    WayMatchRecentFix(if (route) 52.00010 else 52.01000, it, 90.0, 5.0, speed, 5.0, 4)
                }
                val context = WayMatchContext(preferredWayId = preferred, preferredHighway = if (route) "primary" else "secondary",
                    preferredEndpointProximityM = 4.0, recentWayIds = listOf(preferred), recentFixes = history,
                    preferredStreetRef = if (route) "B10" else null, activeStreetRef = if (route) "B10" else null,
                    recentStreetRefs = if (route) listOf("B10") else emptyList(), preferredStreetName = if (route) null else "History Road")
                val result = service.lookup(queryLat, 13.00480, 40.0, 32, 90.0, speed, 5.0, 4, context)
                assertEquals(result.selectionTrace.toString(), expected, result.wayId)
                assertTrue(result.selectionTrace.any { it.step == "simple_sequence_viterbi_seed" && "continuity_available=true" in it.detail })
            }
        }
    }

    private fun context() = WayMatchContext(preferredWayId = "12001", preferredHighway = "primary",
        preferredEndpointProximityM = 3.0, recentWayIds = listOf("12001"), recentFixes = listOf(WayMatchRecentFix(52.05995, 13.00413)),
        preferredStreetRef = "B463", activeStreetRef = "B463", recentStreetRefs = listOf("B463"))

    private fun lookup(file: File, model: MatcherDebugProfile, context: WayMatchContext): SpeedLookupResult =
        V3SpeedLimitLookup(file.path, matchingModel = model.lookupModel).use {
            it.lookup(52.06001, 13.00413, 45.0, 32, null, 23.0, 6.0, matchContext = context)
        }

    private fun fixture(name: String, body: (File) -> Unit) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val file = File(instrumentation.targetContext.cacheDir, "matcher-parity-${UUID.randomUUID()}.sqlite")
        try {
            val sql = instrumentation.context.assets.open("matcher-parity/$name").bufferedReader().use { it.readText() }
            SQLiteDatabase.openOrCreateDatabase(file, null).use { db -> DeltaUpdatePolicy.sqlStatements(sql).forEach(db::execSQL) }
            body(file)
        } finally { SQLiteDatabase.deleteDatabase(file) }
    }
}
