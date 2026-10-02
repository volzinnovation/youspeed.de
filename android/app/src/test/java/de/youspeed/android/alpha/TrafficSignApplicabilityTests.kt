package de.youspeed.android.alpha

import java.io.File
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class TrafficSignApplicabilityTests {
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
