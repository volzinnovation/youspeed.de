package de.youspeed.android.alpha

import java.io.File
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class TrafficSignApplicabilityTests {
    @Test fun zoneTextRequiresBothTheWordAndTheExactNumber() {
        for (text in listOf("30 ZONE", "ZONE\n30", "30 zona")) assertTrue(text, TSRLiveSignAdmission.verifiesZoneText(text, 30))
        for (text in listOf("40 Kurort", "70 GEFAHR", "20 ZONE", "ZONE", "30", "30 ZONE 70", "30 OZONEN"))
            assertFalse(text, TSRLiveSignAdmission.verifiesZoneText(text, 30))
    }
    private fun zoneBatches(x: Double = .45, calibrated: Boolean = false): List<TSRFrameCandidateBatch> =
        scenarios().first { it.getValue("id").jsonPrimitive.content == "ego_right" }
            .getValue("batches").jsonArray.map { TSRApplicabilityJson.decodeBatch(it.jsonObject) }.map { batch ->
                batch.copy(candidates = batch.candidates.map { it.copy(semanticKey = "zone_start:30:km/h", box = it.box.copy(x = x)) },
                    road = batch.road!!.let { if (calibrated) it else it.copy(cameraHorizontalFovDeg = null, cameraYawDeg = null) })
            }
    @Test fun verifiedZoneNeedsAnEgoApproachButInformationPanelsNeverGainAuthority() {
        for (calibrated in listOf(false, true)) {
            val session = TSRApplicabilitySession()
            val unverified = TSRApplicabilitySession()
            for ((index, batch) in zoneBatches(calibrated = calibrated).withIndex()) {
                val rejected = unverified.evaluate(batch)
                assertEquals(setOf(batch.candidates.single().candidateId), unverified.liveWithheldCandidateIDs)
                for (sink in listOf("display", "immediate", "passage"))
                    assertFalse(TSRApplicabilityAuthority.allows(rejected.decisions.single(), batch.scope, batch.frameId,
                        rejected.decisions.single().trackId, sink, "shadow"))
                val admitted = session.evaluate(batch, batch.candidates.map { it.candidateId }.toSet())
                assertEquals(index == 0, session.liveWithheldCandidateIDs.isNotEmpty())
                assertEquals(batch.candidates, admitted.batch.candidates) // Raw evidence is preserved.
            }
        }
    }
    @Test fun farLeftZoneAndStaleRoadAreWithheldWhileLeftEndSignsRemainEligible() {
        val session = TSRApplicabilitySession()
        for (batch in zoneBatches(x = .015)) {
            session.evaluate(batch, batch.candidates.map { it.candidateId }.toSet())
            assertTrue(session.liveWithheldCandidateIDs.isNotEmpty())
        }
        for (variant in listOf("stale", "missing", "truncated", "unstable", "turning")) {
            val guarded = TSRApplicabilitySession()
            for (original in zoneBatches()) {
                val batch = when (variant) {
                    "stale" -> original.copy(road = original.road!!.copy(capturedAtMs = original.capturedAtMs - 2000))
                    "missing" -> original.copy(road = null)
                    "truncated" -> original.copy(truncated = true)
                    "unstable" -> original.copy(road = original.road!!.copy(matchedStable = false))
                    else -> original.copy(road = original.road!!.copy(courseDeg = 90.0))
                }
                guarded.evaluate(batch, batch.candidates.map { it.candidateId }.toSet())
                assertTrue(variant, guarded.liveWithheldCandidateIDs.isNotEmpty())
            }
        }
        val ends = TSRApplicabilitySession()
        for (zone in zoneBatches(x = .015)) {
            ends.evaluate(zone.copy(candidates = zone.candidates.map { it.copy(semanticKey = "speed_limit_end:70:km/h") }))
            assertTrue(ends.liveWithheldCandidateIDs.isEmpty())
        }
    }
    @Test fun uncalibratedPeripheralSpeedNeedsNoAuthorityOverTheLinkedSideRoad() {
        for (center in listOf(.015, .85, .45)) {
            val session = TSRApplicabilitySession()
            for (zone in zoneBatches(x = center)) {
                val heading = if (center < .2) 270.0 else 90.0
                val batch = zone.copy(candidates = zone.candidates.map { it.copy(semanticKey = "maximum_speed:30:km/h") },
                    road = zone.road!!.copy(branches = listOf(TSRApplicabilityCorridor("side", heading, 15.0, "residential", true, heading))))
                session.evaluate(batch)
                assertEquals(center != .45, session.liveWithheldCandidateIDs.isNotEmpty())
            }
        }
        // Once the vehicle actually follows that road, its heading is the new
        // ego tangent and a central, growing zone can be admitted normally.
        val turned = TSRApplicabilitySession()
        for ((index, zone) in zoneBatches().withIndex()) {
            val scope = zone.scope.copy(traversalEpoch = 2)
            val batch = zone.copy(scope = scope, road = zone.road!!.copy(scope = scope,
                wayId = "side", courseDeg = 90.0, localTangentDeg = 90.0))
            turned.evaluate(batch, batch.candidates.map { it.candidateId }.toSet())
            assertEquals(index == 0, turned.liveWithheldCandidateIDs.isNotEmpty())
        }
    }
    @Test fun lateUntrackedZoneCannotBypassAdmission() {
        val batches = zoneBatches()
        val session = TSRApplicabilitySession()
        for (batch in batches) session.evaluate(batch, batch.candidates.map { it.candidateId }.toSet())
        val old = batches.first().copy(frameId = "late-frame", candidates = batches.first().candidates.map { it.copy(candidateId = "late-frame:0") })
        session.evaluate(old, setOf("late-frame:0"))
        assertEquals(setOf("late-frame:0"), session.liveWithheldCandidateIDs)
    }
    @Test fun knownSideRoadIsVetoedEvenInShadow() {
        val output = outputs(scenarios().first { it.getValue("id").jsonPrimitive.content == "weak_ego_strong_branch" }).second.last()
        val branch = output.decisions.first { it.classification == "LIKELY_BRANCH" }
        assertTrue(TSRLiveSignAdmission.blocks(branch))
        for (sink in listOf("display", "immediate", "passage"))
            assertFalse(TSRApplicabilityAuthority.allows(branch, output.batch.scope, output.batch.frameId, branch.trackId, sink, "shadow"))
        val ego = output.decisions.first { it.classification == "LIKELY_EGO_CORRIDOR" }
        assertTrue(TSRApplicabilityAuthority.allows(ego, output.batch.scope, output.batch.frameId, ego.trackId, "immediate", "shadow"))
    }
    @Test fun secondarySignLogMetadataRoundTripAndLegacyDecode() {
        val legacy = TSRApplicabilityJson.decodeBatch(scenarios().first().getValue("batches").jsonArray.first().jsonObject)
        assertNull(legacy.country)
        assertNull(legacy.candidates.first().rawClassId)
        val batch = legacy.copy(country = "FR", candidates = legacy.candidates.map {
            it.copy(rawClassId = "AB4", semanticKey = "unknown::", detectorRawScore = 0.3, classifierRawScore = 0.99)
        })
        val diagnostic = TSRApplicabilitySession().evaluate(batch)
        val decoded = TSRApplicabilityJson.decodeDiagnostic(TSRApplicabilityJson.encodeDiagnostic(diagnostic))
        assertEquals("FR", decoded.batch.country)
        assertEquals(0.3, decoded.batch.candidates.first().detectorRawScore)
        assertEquals(0.99, decoded.batch.candidates.first().classifierRawScore)
        assertEquals("AB4", decoded.batch.candidates.first().rawClassId)
        assertEquals("unknown::", decoded.batch.candidates.first().semanticKey)
        assertEquals("AB4", decoded.tracks.first().samples.first().candidate.rawClassId)
    }

    @Test fun accessRoadConflictAndLegitimateMainlineChanges() {
        for (scenario in scenarios()) {
            val counts = scenario["expectedAccessWithheldCounts"]?.jsonArray ?: continue
            val session = TSRApplicabilitySession()
            val batches = scenario.getValue("batches").jsonArray.map { TSRApplicabilityJson.decodeBatch(it.jsonObject) }
            for ((index, batch) in batches.withIndex()) {
                val output = session.evaluate(batch)
                assertEquals(scenario.getValue("id").toString() + " frame " + index, counts[index].jsonPrimitive.int, session.accessRoadWithheldCandidateIDs.size)
                if (counts[index].jsonPrimitive.int > 0) assertTrue(session.canConsumePassage("previous-main-road-sign", null, "shadow"))
                for (decision in output.decisions.filter { TSRAccessRoadPolicy.reason in it.reasons })
                    for (sink in listOf("display", "immediate", "passage"))
                        assertFalse(TSRApplicabilityAuthority.allows(decision, batch.scope, batch.frameId, decision.trackId, sink, "shadow"))
            }
            session.reset()
            session.evaluate(batches[2])
            assertTrue(session.accessRoadWithheldCandidateIDs.isEmpty())
        }
    }
    @Test fun activeExitGuardKeepsRampAndRepeatedMainlineSigns() {
        for (scenario in scenarios()) {
            val count = scenario["expectedWithheldCount"]?.jsonPrimitive?.int ?: continue
            val session = TSRApplicabilitySession()
            for (raw in scenario.getValue("batches").jsonArray) {
                val batch = TSRApplicabilityJson.decodeBatch(raw.jsonObject)
                assertEquals(scenario.getValue("id").toString(), count, TSRMotorwayExitPolicy.withheldCandidates(batch).size)
                val output = session.evaluate(batch)
                for (decision in output.decisions.filter { TSRMotorwayExitPolicy.reason in it.reasons }) {
                    for (sink in listOf("display", "immediate", "passage")) {
                        assertFalse(TSRApplicabilityAuthority.allows(decision, batch.scope, batch.frameId, decision.trackId, sink, "shadow"))
                    }
                    assertFalse(session.canConsumePassage(decision.trackId, null, "shadow"))
                }
            }
        }
    }
    private fun scenarios(): List<JsonObject> {
        val file = listOf(File("../../shared/tsr/applicability/golden-vectors-v1.json"), File("../shared/tsr/applicability/golden-vectors-v1.json"))
            .first { it.exists() }
        return Json.parseToJsonElement(file.readText()).jsonObject.getValue("scenarios").jsonArray.map { it.jsonObject }
    }
    private fun outputs(scenario: JsonObject): Pair<TSRApplicabilitySession, List<TSRApplicabilityDiagnostic>> {
        val session = TSRApplicabilitySession()
        return session to scenario.getValue("batches").jsonArray.map { session.evaluate(TSRApplicabilityJson.decodeBatch(it.jsonObject)) }
    }
    @Test fun exportNativeParityEvidenceWhenRequested() {
        val destination = System.getenv("TSR_APPLICABILITY_PARITY_OUTPUT") ?: return
        val result = JsonArray(scenarios().map { scenario ->
            val (_, frames) = outputs(scenario)
            buildJsonObject {
                put("id", scenario.getValue("id"))
                put("frames", JsonArray(frames.map { TSRApplicabilityJson.encodeDiagnostic(it) }))
            }
        })
        File(destination).apply { parentFile?.mkdirs(); writeText(result.toString()) }
    }
    @Test fun sharedGoldenDecisionsAndNonEgoAuthority() {
        for (scenario in scenarios()) {
            val (_, frames) = outputs(scenario)
            val expected = scenario["expectedFinalClass"]?.jsonPrimitive?.contentOrNull
            if (expected != null) assertTrue(scenario.getValue("id").toString(), frames.last().decisions.any { it.classification == expected })
            for (frame in frames) {
                assertTrue(frame.tracks.size <= 24)
                for (decision in frame.decisions) for (sink in listOf("display", "immediate", "passage")) {
                    assertEquals(decision.classification == "LIKELY_EGO_CORRIDOR", TSRApplicabilityAuthority.allows(decision, frame.batch.scope, frame.batch.frameId, decision.trackId, sink, "enforce"))
                }
                assertEquals(frame, TSRApplicabilityJson.decodeDiagnostic(TSRApplicabilityJson.encodeDiagnostic(frame)))
            }
        }
    }
    @Test fun independentPhysicalSignsAndCachedFrames() {
        val frames = outputs(scenarios().first { it.getValue("id").jsonPrimitive.content == "simultaneous_equal_signs" }).second
        assertEquals(2, frames.last().tracks.size)
        assertEquals(listOf(3,3), frames.last().tracks.map { it.samples.size })
        val duplicate = outputs(scenarios().first { it.getValue("id").jsonPrimitive.content == "duplicate_frame" }).second
        assertEquals(3, duplicate.last().tracks.first().samples.size)
        val weak = outputs(scenarios().first { it.getValue("id").jsonPrimitive.content == "weak_ego_strong_branch" }).second.last()
        assertEquals(setOf("LIKELY_EGO_CORRIDOR", "LIKELY_BRANCH"), weak.decisions.map { it.classification }.toSet())
    }
    @Test fun withheldAndFailedFramesNeverBecomePassageLoss() {
        for (name in listOf("failed_frame", "proposal_cap", "parallel_road", "camera_remount")) {
            val (session, _) = outputs(scenarios().first { it.getValue("id").jsonPrimitive.content == name })
            assertFalse(name, session.canConsumePassage("track-1", null, "enforce"))
        }
        val (session, _) = outputs(scenarios().first { it.getValue("id").jsonPrimitive.content == "detector_dropout" })
        assertTrue(session.canConsumePassage("track-1", null, "enforce"))
    }
    @Test fun legacyAndStaleDecisionFailClosed() {
        val (_, frames) = outputs(scenarios().first { it.getValue("id").jsonPrimitive.content == "ego_right" })
        val frame=frames.last();val decision=frame.decisions.first()
        assertFalse(TSRApplicabilityAuthority.allows(decision.copy(schemaVersion=2),frame.batch.scope,frame.batch.frameId,decision.trackId,"immediate","enforce"))
        assertFalse(TSRApplicabilityAuthority.allows(null,frame.batch.scope,frame.batch.frameId,decision.trackId,"immediate","enforce"))
        assertFalse(TSRApplicabilityAuthority.allows(decision,frame.batch.scope,"later-frame",decision.trackId,"immediate","enforce"))
        assertFalse(TSRApplicabilityAuthority.allows(decision,frame.batch.scope,frame.batch.frameId,"other-sign","immediate","disabled"))
    }
}
