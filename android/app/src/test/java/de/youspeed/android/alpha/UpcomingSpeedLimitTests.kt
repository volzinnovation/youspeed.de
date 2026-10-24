package de.youspeed.android.alpha

import java.io.File
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class UpcomingSpeedLimitTests {
    @Test fun sharedSelectionAndLifetimeCorpus() {
        val corpus = Json.parseToJsonElement(File("../../shared/upcoming-speed-limit/scenarios-v1.json").readText()).jsonObject
        assertEquals(1, corpus.getValue("schemaVersion").jsonPrimitive.int)
        for (case in corpus.getValue("cases").jsonArray) {
            val scenario = case.jsonObject
            val tracker = UpcomingSpeedLimitTracker()
            for (raw in scenario.getValue("steps").jsonArray) {
                val step = raw.jsonObject
                val now = (step.getValue("nowS").jsonPrimitive.double * 1000).toLong()
                if ("speedKmh" in step && step["snapshot"] != JsonNull) {
                    val observed = step["speedKmh"]?.takeUnless { it == JsonNull }?.jsonPrimitive?.double
                    val declared = step.getValue("snapshot").jsonObject["lookaheadDistanceM"]?.jsonPrimitive?.double ?: 300.0
                    assertEquals(scenario.getValue("id").jsonPrimitive.content, declared, UpcomingSpeedLimitHorizon.distanceM(observed), 1e-9)
                }
                if (step.getValue("event").jsonPrimitive.content == "fix") tracker.consume(
                    step["snapshot"]?.takeUnless { it == JsonNull }?.jsonObject?.let(::snapshot),
                    step.getValue("bundleID").jsonPrimitive.content,
                    (step.getValue("fixS").jsonPrimitive.double * 1000).toLong(), now)
                val result = tracker.presentation(step["currentLimitKmh"]?.takeUnless { it == JsonNull }?.jsonPrimitive?.int,
                    step.getValue("currentUnlimited").jsonPrimitive.boolean, step.getValue("currentUsable").jsonPrimitive.boolean, now)
                val expected = step.getValue("expected").jsonObject
                val label = scenario.getValue("id").jsonPrimitive.content + " at " + now
                assertEquals(label, expected["signID"]?.takeUnless { it == JsonNull }?.jsonPrimitive?.content, result?.signID)
                assertEquals(label, expected["speedKmh"]?.takeUnless { it == JsonNull }?.jsonPrimitive?.int, result?.speedKmh)
                expected["distanceM"]?.takeUnless { it == JsonNull }?.let { assertEquals(label, it.jsonPrimitive.double, requireNotNull(result).distanceM, 1e-6) }
            }
        }
    }

    @Test fun observedSpeedProvidesThirtySecondsWithoutAnArbitraryDistanceCeiling() {
        for (invalid in listOf(null, -1.0, Double.NaN, Double.POSITIVE_INFINITY, Double.NEGATIVE_INFINITY, Double.MAX_VALUE)) {
            assertEquals(300.0, UpcomingSpeedLimitHorizon.distanceM(invalid), 0.0)
        }
        for (slow in listOf(0.0, 1.0, 30.0, 36.0)) assertEquals(300.0, UpcomingSpeedLimitHorizon.distanceM(slow), 0.0)
        for (speed in listOf(50.0, 100.0, 130.0, 500.0)) assertEquals(speed / 3.6 * 30, UpcomingSpeedLimitHorizon.distanceM(speed), 0.0)
    }

    @Test fun invalidHorizonAndExcessivePathFailClosed() {
        for (horizon in listOf(299.0, Double.NaN, Double.POSITIVE_INFINITY)) {
            val tracker = UpcomingSpeedLimitTracker()
            tracker.consume(fix(100.0).copy(lookaheadDistanceM=horizon), "bundle", 1000, 1000)
            assertNull(tracker.presentation(100, false, true, 1000))
        }
        val maximumPath = List(32) { fix(100.0).path.single() }
        val tracker = UpcomingSpeedLimitTracker()
        tracker.consume(fix(100.0).copy(path=maximumPath), "bundle", 1000, 1000)
        assertEquals("speed", tracker.presentation(100, false, true, 1000)?.signID)
        tracker.consume(fix(100.0).copy(path=maximumPath + maximumPath.first()), "bundle", 2000, 2000)
        assertNull(tracker.presentation(100, false, true, 2000))
    }

    @Test fun hiddenAndPausedPassageCannotReappearAfterJitter() {
        val tracker = UpcomingSpeedLimitTracker()
        tracker.consume(fix(100.0), "bundle", 1000, 1000)
        assertNull(tracker.presentation(50, false, true, 1000))
        tracker.hide()
        tracker.consume(fix(251.0, emptyList()), "bundle", 2000, 2000)
        tracker.consume(fix(249.0), "bundle", 3000, 3000)
        assertNull(tracker.presentation(100, false, true, 3000))
    }

    @Test fun distanceRoundsUpOnlyForDisplay() {
        assertEquals(300, candidate.copy(distanceM=299.1).displayDistanceM)
        assertEquals(10, candidate.copy(distanceM=0.1).displayDistanceM)
    }

    @Test fun unprovenFarJumpOnSameRelationPreservesSuppressionAcrossGapAndJitter() {
        val tracker=UpcomingSpeedLimitTracker()
        tracker.consume(fix(100.0),"bundle",1000,1000)
        tracker.hide()
        val farther=UpcomingSpeedLimitSnapshot("20",1,100.0,setOf(1),
            listOf(UpcomingSpeedLimitPath(null,"20",1,0.0,500.0,-100.0,setOf(1))),emptyList(),"after_gap",topologyAvailable=true)
        tracker.consume(farther,"bundle",2000,2000)
        tracker.consume(fix(249.0),"bundle",3000,3000)
        assertNull(tracker.presentation(100,false,true,3000))
    }
    @Test fun sameWayRawRelationLossLatchesEvenWhenCandidateRemainsInDatabase() {
        val tracker=UpcomingSpeedLimitTracker()
        tracker.consume(fix(100.0),"bundle",1000,1000)
        tracker.consume(fix(110.0).copy(relationGroupIDs=setOf(2)),"bundle",2000,2000)
        assertNull(tracker.presentation(100,false,true,2000))
        tracker.hide()
        tracker.consume(fix(120.0),"bundle",3000,3000)
        assertNull(tracker.presentation(100,false,true,3000))
    }
    @Test fun provisionalContinuationNeverUsesAnOldBundlesCoincidentWayAndGroupIDs() {
        val tracker=UpcomingSpeedLimitTracker()
        val snapshot=fix(100.0).copy(topologyAvailable=true)
        tracker.consume(snapshot,"old-bundle",1000,1000)
        tracker.hide()
        assertTrue(tracker.certifiesContinuation(snapshot,"old-bundle"))
        assertFalse(tracker.certifiesContinuation(snapshot,"new-bundle"))
    }

    private val candidate = UpcomingSpeedLimitCandidate("speed", "source", "snapshot", "rule", "10", 1, 250.0, 70, 150.0)
    private fun fix(chain: Double, candidates: List<UpcomingSpeedLimitCandidate> = listOf(candidate.copy(distanceM=250-chain))) = UpcomingSpeedLimitSnapshot(
        "10", 1, chain, setOf(1), listOf(UpcomingSpeedLimitPath(null,"10",1,0.0,600.0,-chain,setOf(1))), candidates,"test")
    private fun snapshot(o: JsonObject): UpcomingSpeedLimitSnapshot = UpcomingSpeedLimitSnapshot(
        o.str("wayID"), o.num("direction").toInt(), o.num("chainageM"), o.groups(),
        o.getValue("path").jsonArray.map { it.jsonObject.let { p -> UpcomingSpeedLimitPath(p["segmentID"]?.takeUnless { it == JsonNull }?.jsonPrimitive?.content,
            p.str("wayID"),p.num("direction").toInt(),p.num("startM"),p.num("endM"),p.num("entryDistanceM"),p.groups()) } },
        o.getValue("candidates").jsonArray.map { it.jsonObject.let { c -> UpcomingSpeedLimitCandidate(c.str("signID"),c.str("sourceID"),c.str("snapshotSHA256"),c.str("ruleID"),c.str("originWayID"),c.num("direction").toInt(),c.num("stationM"),c.num("speedKmh").toInt(),c.num("distanceM")) } },
        o.str("reason"), o.num("queryTimeMs"), o.getValue("topologyAvailable").jsonPrimitive.boolean,
        o["lookaheadDistanceM"]?.jsonPrimitive?.double ?: 300.0)
    private fun JsonObject.str(key: String)=getValue(key).jsonPrimitive.content
    private fun JsonObject.num(key: String)=getValue(key).jsonPrimitive.double
    private fun JsonObject.groups()=getValue("relationGroupIDs").jsonArray.map { it.jsonPrimitive.long }.toSet()
}
