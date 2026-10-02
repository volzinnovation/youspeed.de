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
        assertEquals("1.1.0", model.version)
        assertEquals(listOf("voice", "camera", "bundle"), model.policy["priority"])
    }
    @Test fun frozenScenariosThroughNativeInterpreter() {
        val corpus = SpeedLimitReferenceModel.decode(bytes("scenarios-v1.1.0.json"))
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
        for (changed in listOf("policy-v1.1.0.json", "approval-lock.json")) {
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
}
