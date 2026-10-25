package de.youspeed.android.alpha

import java.io.File
import org.junit.Assert.*
import org.junit.Test

class SpeedLimitReferenceModelTests {
    private val root = File("../../shared/speed-limit-reference")
    private fun bytes(name: String) = root.resolve(name).readBytes()
    private fun model() = SpeedLimitReferenceModel.load(::bytes)
    private fun normalized(value: Any?): Any? = when(value) {
        is Number -> value.toDouble()
        is Map<*, *> -> value.mapValues { normalized(it.value) }
        is List<*> -> value.map(::normalized)
        else -> value
    }
    @Test fun packagedPolicyIsTheSharedRuntimePolicy() {
        val model = model()
        assertEquals("1.2.0", model.version)
        assertEquals(listOf("voice", "camera", "bundle"), model.policy["priority"])
    }
    @Test fun frozenScenariosThroughNativeInterpreter() {
        val corpus = SpeedLimitReferenceModel.decode(bytes("scenarios-v1.2.0.json"))
        for (scenario in corpus["scenarios"] as List<Map<String, Any?>>) {
            val machine = SpeedReferenceMachine(model())
            for ((index, row) in (scenario["steps"] as List<Map<String, Any?>>).withIndex()) {
                val result = machine.step(row["event"] as Map<String, Any?>)
                val actual = mapOf("state" to result.state, "value" to result.value?.json,
                    "violation_reference_kmh" to result.baselineKmh, "penalty_reference_kmh" to result.baselineKmh,
                    "display_stale" to (result.state == "LAST_KNOWN"), "current" to result.current,
                    "generation" to result.generation, "applicability_revision" to result.applicabilityRevision,
                    "transition_id" to result.transition, "expiry_reasons" to result.expiryReasons, "rejection" to result.rejection)
                for ((key, expected) in row["expect"] as Map<String, Any?>) assertEquals("${scenario["id"]} step $index $key", normalized(expected), normalized(actual[key]))
            }
        }
    }
    @Test fun runtimePreservesBriefRampExcursionButExpiresSustainedDeparture() {
        var now = 0.0
        val runtime = SpeedReferenceRuntime(model()) { now }
        runtime.context("a8", "ref:A8", setOf("A8"), "forward", true)
        runtime.bundle("map", SpeedReferenceValue("numeric", 130))
        runtime.voice("speech", SpeedReferenceValue("numeric", 130))
        now = 137.302
        runtime.context("ramp", "ref:A57:ramp", emptySet(), "forward", true)
        runtime.tick(250.0)
        now = 143.751
        runtime.context("a8-next", "ref:A8", setOf("A8"), "forward", true)
        assertEquals("VOICE", runtime.output()?.state)
        now = 150.0
        runtime.context("ramp", "ref:A57:ramp", emptySet(), "forward", true)
        now = 158.0
        runtime.context("ramp", "ref:A57:ramp", emptySet(), "forward", true)
        assertEquals("LAST_KNOWN", runtime.output()?.state)
        assertNull(runtime.output()?.baselineKmh)
    }
    @Test fun repeatedCameraWithdrawalDoesNotEraseFreshRoadEvidence() {
        val runtime = SpeedReferenceRuntime(model()) { 0.0 }
        runtime.bundle("map", SpeedReferenceValue("numeric", 80))
        runtime.camera("sign", SpeedReferenceValue("numeric", 30))
        runtime.pipelineAuthorityWithdrawn("end-sign")
        assertEquals("LAST_KNOWN", runtime.output()?.state)
        runtime.bundle("fresh-map", SpeedReferenceValue("numeric", 80))
        repeat(100) { runtime.pipelineAuthorityWithdrawn("end-sign") }
        assertEquals("BUNDLE", runtime.output()?.state)
        assertEquals(80, runtime.output()?.baselineKmh)
        runtime.pipelineAuthorityWithdrawn("different-end-sign")
        assertEquals("LAST_KNOWN", runtime.output()?.state)
        assertNull(runtime.output()?.baselineKmh)
    }

    @Test fun pendingRoadConfirmsAfterEightSecondsAcrossOppositeWayOrientations() {
        for (relationOnly in listOf(false, true)) {
            var now = 0.0
            val runtime = SpeedReferenceRuntime(model()) { now }
            runtime.context("old", "ref:old", emptySet(), "forward", true)
            runtime.bundle("old-map", SpeedReferenceValue("numeric", 70))
            val road = if (relationOnly) null else "ref:L562"
            val relations = if (relationOnly) setOf("562") else emptySet()
            // Recorded L562 traversal: adjacent OSM ways have opposite digitization.
            for ((at, way, direction) in listOf(Triple(1.0, "242667444", "forward"), Triple(3.0, "242667445", "reverse"),
                Triple(4.0, "242667443", "forward"), Triple(7.0, "31266734", "reverse"), Triple(8.999, "733915457", "forward"))) {
                now = at
                runtime.context(way, road, relations, direction, true)
                runtime.bundle("new-map", SpeedReferenceValue("numeric", 50))
                assertEquals("LAST_KNOWN", runtime.output()?.state)
                assertEquals(0, runtime.output()?.generation)
                assertNull(runtime.output()?.baselineKmh)
            }
            assertTrue(requireNotNull(runtime.camera("pending-sign", SpeedReferenceValue("numeric", 30))).pendingContextAfter)
            now = 9.0
            runtime.context("733915457", road, relations, "forward", true)
            assertEquals(1, runtime.output()?.generation)
            runtime.bundle("current-map", SpeedReferenceValue("numeric", 50))
            assertEquals("BUNDLE", runtime.output()?.state)
            assertEquals(50, runtime.output()?.baselineKmh)
            assertEquals("CAMERA", runtime.camera("fresh-sign", SpeedReferenceValue("numeric", 30))?.after?.state)
        }
    }

    @Test fun pendingSameWayReversalRestartsAndUnknownDoesNotEraseDirection() {
        var now = 0.0
        val runtime = SpeedReferenceRuntime(model()) { now }
        runtime.context("old", "ref:old", emptySet(), "forward", true)
        runtime.bundle("old-map", SpeedReferenceValue("numeric", 70))
        for ((at, direction) in listOf(1.0 to "forward", 3.0 to "unknown", 4.0 to "reverse", 9.0 to "reverse", 11.999 to "unknown")) {
            now = at
            runtime.context("new", "ref:new", emptySet(), direction, true)
            assertEquals(0, runtime.output()?.generation)
        }
        now = 12.0
        runtime.context("new", "ref:new", emptySet(), "unknown", true)
        assertEquals(1, runtime.output()?.generation)
        runtime.bundle("new-map", SpeedReferenceValue("numeric", 50))
        now = 13.0
        runtime.context("new", "ref:new", emptySet(), "forward", true)
        assertEquals("LAST_KNOWN", runtime.output()?.state)
        now = 21.0
        runtime.context("new", "ref:new", emptySet(), "forward", true)
        assertEquals(2, runtime.output()?.generation)
    }

    @Test fun unrelatedPendingRoadRestartsConfirmation() {
        var now = 0.0
        val runtime = SpeedReferenceRuntime(model()) { now }
        runtime.context("old", "ref:old", setOf("old"), "forward", true)
        runtime.bundle("old-map", SpeedReferenceValue("numeric", 70))
        now = 1.0
        runtime.context("b", "ref:B", setOf("B"), "forward", true)
        now = 4.0
        runtime.context("c", "ref:C", setOf("C"), "forward", true)
        now = 9.0
        runtime.context("c", "ref:C", setOf("C"), "forward", true)
        assertEquals(0, runtime.output()?.generation)
        now = 12.0
        runtime.context("c", "ref:C", setOf("C"), "forward", false)
        assertEquals(0, runtime.output()?.generation)
        runtime.context("c", "ref:C", setOf("C"), "forward", true)
        assertEquals(1, runtime.output()?.generation)
    }

    @Test fun acceptedDirectionSurvivesUnknownButRealReversalStillWaitsEightSeconds() {
        var now = 0.0
        val runtime = SpeedReferenceRuntime(model()) { now }
        runtime.context("road", "ref:A", emptySet(), "forward", true)
        runtime.bundle("map", SpeedReferenceValue("numeric", 70))
        now = 1.0
        runtime.context("road", "ref:A", emptySet(), "unknown", true)
        assertEquals("BUNDLE", runtime.output()?.state)
        now = 2.0
        runtime.context("road", "ref:A", emptySet(), "reverse", true)
        assertEquals("LAST_KNOWN", runtime.output()?.state)
        now = 9.999
        runtime.context("road", "ref:A", emptySet(), "unknown", true)
        assertEquals(0, runtime.output()?.generation)
        now = 10.0
        runtime.context("road", "ref:A", emptySet(), "reverse", true)
        assertEquals(1, runtime.output()?.generation)
    }
    @Test fun dismissalRejectsDelayedEvidenceButAllowsNewSigns() {
        val gate = VisionDismissalGate()
        val now = java.time.Instant.ofEpochSecond(100)
        gate.dismiss(now, listOf("active"))
        assertFalse(gate.permits("active", now.plusSeconds(1)))
        assertFalse(gate.permits("queued", now.minusSeconds(1)))
        assertFalse(gate.permits("queued", now.plusSeconds(2)))
        assertTrue(gate.permits("new-sign", now.plusSeconds(3)))
    }
    @Test fun rejectsChangedPolicyAndApprovalLock() {
        for (changed in listOf("policy-v1.2.0.json", "approval-lock.json")) {
            assertTrue(runCatching { SpeedLimitReferenceModel.load { name -> if (name == changed) bytes(name) + byteArrayOf(32) else bytes(name) } }.isFailure)
        }
        assertTrue(runCatching { SpeedLimitReferenceModel.load { error("missing resource") } }.isFailure)
    }
    @Test fun distanceExpiryRemovesViolationAndPenaltyBaselineAtPresentationBoundary() {
        var now = 0.0
        val runtime = SpeedReferenceRuntime(model()) { now }
        runtime.camera("accepted-pipeline-passage", SpeedReferenceValue("numeric", 30))
        val current = runtime.output()!!.effective()
        val state = ConsumerUiState(speedLimitKmh = current.resolution?.speedKmh,
            currentSpeedKmh = 80.0, effectiveSpeedLimitSource = current.source)
        assertEquals(50, ConsumerMainScreenLogic.currentOverspeedKmh(state))
        now = 100.0
        runtime.tick(5_000.0)
        val stale = runtime.output()!!.effective()
        val after = state.copy(speedLimitKmh = stale.resolution?.speedKmh, effectiveSpeedLimitSource = stale.source)
        assertEquals(30, after.speedLimitKmh)
        assertEquals(EffectiveSpeedLimitSource.LAST_KNOWN, after.effectiveSpeedLimitSource)
        assertEquals(0, ConsumerMainScreenLogic.currentOverspeedKmh(after))
        assertNull(ConsumerMainScreenLogic.currentPenaltyNotice(after))
    }

    @Test fun cameraReceiptReportsAcceptedAndDuplicateOffersWithoutChangingDeduplication() {
        val runtime = SpeedReferenceRuntime(model()) { 0.0 }
        runtime.camera("old", SpeedReferenceValue("numeric", 70))
        val accepted = requireNotNull(runtime.camera("new", SpeedReferenceValue("numeric", 80)))
        assertEquals("new", accepted.offeredId)
        assertEquals("camera", accepted.offeredKind)
        assertEquals(70, accepted.before.value?.kmh)
        assertEquals("T03", accepted.after.transition)
        assertEquals(80, accepted.after.value?.kmh)
        assertEquals("new", accepted.after.evidenceId)
        val repeated = requireNotNull(runtime.camera("new", SpeedReferenceValue("numeric", 30)))
        assertEquals(30, repeated.offeredValue.kmh)
        assertEquals("T11", repeated.after.transition)
        assertEquals(80, repeated.after.value?.kmh)
        assertEquals(80, runtime.output()?.baselineKmh)
    }

    @Test fun cameraReceiptExposesPendingGateAndPreservesWithheldEvidenceBehavior() {
        var now = 0.0
        val runtime = SpeedReferenceRuntime(model()) { now }
        runtime.context("road", "ref:A", emptySet(), "forward", true)
        runtime.camera("old", SpeedReferenceValue("numeric", 70))
        now = 1.0
        runtime.context("ramp", "ref:B", emptySet(), "forward", false)
        val withheld = requireNotNull(runtime.camera("new", SpeedReferenceValue("numeric", 80)))
        assertTrue(withheld.pendingContextBefore)
        assertTrue(withheld.pendingContextAfter)
        assertEquals("T11", withheld.after.transition)
        assertEquals(70, withheld.after.value?.kmh)
        now = 2.0
        runtime.context("road", "ref:A", emptySet(), "forward", true)
        val repeated = requireNotNull(runtime.camera("new", SpeedReferenceValue("numeric", 80)))
        assertFalse(repeated.pendingContextBefore)
        assertEquals("T11", repeated.after.transition)
        assertEquals(70, repeated.after.value?.kmh)
        assertNull(repeated.diagnosticFields["gapBefore"])
        assertNull(repeated.diagnosticFields["seenBefore"])
        assertEquals("pending_context_only", repeated.diagnosticFields["gateDiagnosticAvailability"])
    }

    @Test fun cameraReceiptDistinguishesAcceptedEnclosingOfferFromSelectedOrdinaryValue() {
        val runtime = SpeedReferenceRuntime(model()) { 0.0 }
        runtime.camera("posted", SpeedReferenceValue("numeric", 70))
        val receipt = requireNotNull(runtime.camera("zone", SpeedReferenceValue("numeric", 30), true))
        assertEquals("camera_context", receipt.offeredKind)
        assertEquals("T12", receipt.after.transition)
        assertEquals("posted", receipt.after.evidenceId)
        assertEquals(70, receipt.after.value?.kmh)
    }

    @Test fun cameraReceiptKeepsExpiryOriginsAndReportsActualRejection() {
        var now = 0.0
        val runtime = SpeedReferenceRuntime(model()) { now }
        runtime.camera("sign", SpeedReferenceValue("numeric", 70))
        now = 300.0
        val expired = requireNotNull(runtime.camera("sign", SpeedReferenceValue("numeric", 70)))
        assertEquals("LAST_KNOWN", expired.before.state)
        assertEquals("T11", expired.after.transition)
        assertFalse(expired.after.current)
        val rejected = requireNotNull(runtime.camera("invalid", SpeedReferenceValue("numeric", 0)))
        assertEquals("REJECT", rejected.after.transition)
        assertEquals("invalid_value", rejected.after.rejection)
        assertEquals("sign", rejected.after.evidenceId)
        val fields = rejected.diagnosticFields["after"] as Map<*, *>
        assertEquals("invalid_value", fields["rejection"])
        assertNull(SpeedReferenceRuntime(null) { 0.0 }.camera("sign", SpeedReferenceValue("numeric", 70)))
    }
    @Test fun returnAcrossWaysClearsOutboundCamera() {
        var now=0.0
        val runtime=SpeedReferenceRuntime(model()){now}
        runtime.context("723493085","ref:L340",setOf("144648"),"forward",true)
        runtime.bundle("map100",SpeedReferenceValue("numeric",100))
        runtime.camera("outbound-sign",SpeedReferenceValue("numeric",100))
        val steps=listOf(Triple(1.0,"178845215","reverse"),Triple(2.0,"935939126","forward"),Triple(3.0,"178845215","forward"),Triple(4.0,"723493085","reverse"))
        for((at,way,direction) in steps) {
            now=at;runtime.context(way,if(way=="935939126") "service" else "ref:L340",if(way=="935939126") emptySet() else setOf("144648"),direction,true)
        }
        assertTrue(runtime.contextPending())
        now=11.0;runtime.context("723493085","ref:L340",setOf("144648"),"reverse",true)
        assertEquals(1,runtime.output()?.generation)
        runtime.bundle("map60",SpeedReferenceValue("numeric",60))
        assertEquals("BUNDLE",runtime.output()?.state);assertEquals(60,runtime.output()?.baselineKmh)
        runtime.camera("outbound-sign",SpeedReferenceValue("numeric",100))
        assertEquals(60,runtime.output()?.baselineKmh)
    }

    @Test fun versionedVerifiedBundleRoadChangeCases() {
        val corpus=SpeedLimitReferenceModel.decode(bytes("road-context-scenarios-v1.2.0.json"))
        for(scenario in corpus["scenarios"] as List<Map<String,Any?>>) {
            var now=0.0
            val runtime=SpeedReferenceRuntime(model()){now}
            runtime.context("old","name:old",emptySet(),"forward",true)
            runtime.bundle("old-map",SpeedReferenceValue("numeric",70))
            when(scenario["initial_source"]) {
                "camera" -> runtime.camera("old-camera",SpeedReferenceValue("numeric",70))
                "voice" -> runtime.voice("old-voice",SpeedReferenceValue("numeric",70))
            }
            for(fix in scenario["fixes"] as List<Map<String,Any?>>) {
                fun n(key:String)=(fix[key] as Number).toDouble()
                now=n("time")
                runtime.context(fix["way"] as? String,fix["road"] as? String,emptySet(),fix["direction"] as String,fix["stable"] as Boolean,
                    SpeedReferenceBundleFix(n("source_time"),n("age_s"),n("accuracy_m"),n("match_distance_m"),fix["applicable"] as Boolean))
                runtime.bundle("new-map",if(fix["applicable"]==true) SpeedReferenceValue("numeric",50) else null)
            }
            val expected=scenario["expect"] as Map<String,Any?>;val id=scenario["id"] as String
            assertEquals(id,(expected["generation"] as Number).toInt(),runtime.output()?.generation)
            assertEquals(id,expected["state"],runtime.output()?.state)
            assertEquals(id,(expected["baseline"] as? Number)?.toInt(),runtime.output()?.baselineKmh)
        }
    }

}
